import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertOctagon, ArrowLeft } from "lucide-react";
import GlassCard from "../components/ui/GlassCard";
import Button from "../components/ui/Button";
import Processamento from "../features/lote/Processamento";
import Resultado from "../features/lote/Resultado";
import { consultarStatus, consultarRegistros, ApiError } from "../lib/api";

const INTERVALO_POLLING_MS = 1500;

/**
 * Página `/lote/:loteId`: hospeda as telas de Processamento e Resultado
 * (Fase 21a no Tkinter: "Processar -> Resultado"), sempre RE-DERIVANDO o
 * estado do backend via `GET /status` -- nunca guardando "processando"
 * como suposição local. Isso também é o que torna a rota segura a
 * recarregar a página no meio do processamento: reabrir `/lote/<id>`
 * simplesmente retoma o polling de onde o backend realmente está.
 */
export default function PaginaLote() {
  const { loteId } = useParams();
  const [status, setStatus] = useState(null);
  const [registros, setRegistros] = useState(null);
  const [erroCarregamento, setErroCarregamento] = useState(null);
  const intervaloRef = useRef(null);

  useEffect(() => {
    let cancelado = false;

    async function consultar() {
      try {
        const novoStatus = await consultarStatus(loteId);
        if (cancelado) return;
        setStatus(novoStatus);

        if (novoStatus.status === "concluido" || novoStatus.status === "erro") {
          if (intervaloRef.current) {
            clearInterval(intervaloRef.current);
            intervaloRef.current = null;
          }
          if (novoStatus.status === "concluido") {
            const dados = await consultarRegistros(loteId);
            if (!cancelado) setRegistros(dados);
          }
        }
      } catch (erro) {
        if (cancelado) return;
        if (intervaloRef.current) clearInterval(intervaloRef.current);
        setErroCarregamento(
          erro instanceof ApiError ? erro.detail : "Não foi possível falar com o servidor."
        );
      }
    }

    consultar();
    intervaloRef.current = setInterval(consultar, INTERVALO_POLLING_MS);
    return () => {
      cancelado = true;
      if (intervaloRef.current) clearInterval(intervaloRef.current);
    };
  }, [loteId]);

  if (erroCarregamento) {
    return <EstadoErro mensagem={erroCarregamento} />;
  }

  if (!status) {
    return <EstadoCarregando />;
  }

  if (status.status === "erro") {
    return <EstadoErro mensagem={status.erro_fatal || "Falha inesperada processando o lote."} />;
  }

  if (status.status === "concluido" && registros) {
    return <Resultado loteId={loteId} status={status} registros={registros} />;
  }

  return <Processamento status={status} />;
}

function EstadoCarregando() {
  return (
    <div className="animate-fade-in text-center text-sm text-slate-400">Carregando o lote...</div>
  );
}

function EstadoErro({ mensagem }) {
  return (
    <div className="animate-fade-up mx-auto max-w-lg">
      <GlassCard className="space-y-4 text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-3xl bg-rose-50 text-rose-600 ring-1 ring-rose-600/10">
          <AlertOctagon className="size-7" strokeWidth={1.75} />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">Não foi possível continuar</h1>
          <p className="mt-1 text-sm text-slate-500">{mensagem}</p>
        </div>
        <Button as={Link} to="/" variant="secundario" icon={ArrowLeft}>
          Voltar ao início
        </Button>
      </GlassCard>
    </div>
  );
}
