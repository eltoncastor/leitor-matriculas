import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertOctagon, ArrowLeft, Ban } from "lucide-react";
import GlassCard from "../components/ui/GlassCard";
import Button from "../components/ui/Button";
import Processamento from "../features/lote/Processamento";
import Resultado from "../features/lote/Resultado";
import { consultarStatus, consultarRegistros, ApiError } from "../lib/api";

const INTERVALO_POLLING_MS = 1500;
// Fase 26d: com o processamento podendo depender de um Worker remoto sobre
// uma rede real (Tailscale/túnel), um 502/timeout passageiro deixou de ser
// hipotético. Só desiste depois de falhas CONSECUTIVAS -- um sucesso no
// meio zera a contagem -- com espera crescente a cada tentativa, até um teto.
const LIMITE_FALHAS_CONSECUTIVAS = 6;
const BACKOFF_MAXIMO_MS = 12000;

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
  const [reconectando, setReconectando] = useState(false);
  const timeoutRef = useRef(null);
  const falhasRef = useRef(0);

  useEffect(() => {
    let cancelado = false;

    function agendar(atrasoMs) {
      if (cancelado) return;
      timeoutRef.current = setTimeout(consultar, atrasoMs);
    }

    async function consultar() {
      try {
        const novoStatus = await consultarStatus(loteId);
        if (cancelado) return;
        falhasRef.current = 0;
        setReconectando(false);
        setStatus(novoStatus);

        if (novoStatus.status === "concluido") {
          const dados = await consultarRegistros(loteId);
          if (!cancelado) setRegistros(dados);
          return; // estado final alcançado com sucesso -- para de consultar
        }
        if (novoStatus.status === "erro" || novoStatus.status === "cancelado") {
          return; // estado final -- a tela é derivada direto de `status`
        }

        agendar(INTERVALO_POLLING_MS);
      } catch (erro) {
        if (cancelado) return;
        falhasRef.current += 1;
        if (falhasRef.current >= LIMITE_FALHAS_CONSECUTIVAS) {
          setErroCarregamento(
            erro instanceof ApiError ? erro.detail : "Não foi possível falar com o servidor."
          );
          return;
        }
        setReconectando(true);
        const atraso = Math.min(INTERVALO_POLLING_MS * 2 ** falhasRef.current, BACKOFF_MAXIMO_MS);
        agendar(atraso);
      }
    }

    consultar();
    return () => {
      cancelado = true;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
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

  if (status.status === "cancelado") {
    return <EstadoCancelado />;
  }

  if (status.status === "concluido" && registros) {
    return <Resultado loteId={loteId} status={status} registros={registros} />;
  }

  return <Processamento status={status} reconectando={reconectando} />;
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

function EstadoCancelado() {
  return (
    <div className="animate-fade-up mx-auto max-w-lg">
      <GlassCard className="space-y-4 text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-3xl bg-amber-50 text-amber-600 ring-1 ring-amber-600/10">
          <Ban className="size-7" strokeWidth={1.75} />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">Processamento cancelado</h1>
          <p className="mt-1 text-sm text-slate-500">
            Este lote foi cancelado antes de terminar. Nenhum registro foi gerado.
          </p>
        </div>
        <Button as={Link} to="/" variant="secundario" icon={ArrowLeft}>
          Voltar ao início
        </Button>
      </GlassCard>
    </div>
  );
}
