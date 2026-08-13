import { Link } from "react-router-dom";
import { CheckCircle2, AlertTriangle, XCircle, Download, ClipboardCheck, PartyPopper } from "lucide-react";
import GlassCard from "../../components/ui/GlassCard";
import Button from "../../components/ui/Button";
import { urlExportar } from "../../lib/api";

/**
 * Tela 4 do fluxo: resumo do lote concluído. As CONTAGENS por status são
 * uma agregação simples sobre `registros` (cada `status` já veio DECIDIDO
 * do backend, via `pipeline.montar_registro_exportacao` -- Fase 24a) --
 * o mesmo tipo de soma que a aba "Resumo" da planilha já faz em Python
 * (`xlsx_exporter._aba_resumo`). Nada aqui reclassifica nada.
 */
export default function Resultado({ loteId, status, registros }) {
  const confirmados = registros.filter((r) => r.status === "CONFIRMADO").length;
  const revisao = registros.filter((r) => r.status === "REVISAO").length;
  const erro = registros.filter((r) => r.status === "ERRO").length;
  const total = registros.length;
  const tudoPronto = total > 0 && revisao === 0 && erro === 0;

  return (
    <div className="animate-fade-up space-y-6">
      <GlassCard className="space-y-7">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="flex size-16 items-center justify-center rounded-3xl bg-gradient-to-br from-emerald-400 to-emerald-600 text-white shadow-glass-lg">
            {tudoPronto ? (
              <PartyPopper className="size-8" strokeWidth={1.75} />
            ) : (
              <ClipboardCheck className="size-8" strokeWidth={1.75} />
            )}
          </div>
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
              Processamento concluído
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {total} {total === 1 ? "registro lido" : "registros lidos"} · {status.paginas_processadas}{" "}
              {status.paginas_processadas === 1 ? "folha processada" : "folhas processadas"}
              {status.paginas_com_erro > 0 ? ` · ${status.paginas_com_erro} com falha de leitura` : ""}
            </p>
          </div>
        </div>

        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="flex items-center gap-3 rounded-2xl bg-emerald-50 px-4 py-4 ring-1 ring-emerald-600/10">
            <CheckCircle2 className="size-8 shrink-0 text-emerald-600" strokeWidth={1.75} />
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Confirmados</dt>
              <dd className="text-2xl font-extrabold text-emerald-800">{confirmados}</dd>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-2xl bg-amber-50 px-4 py-4 ring-1 ring-amber-600/10">
            <AlertTriangle className="size-8 shrink-0 text-amber-600" strokeWidth={1.75} />
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-amber-700">Para revisar</dt>
              <dd className="text-2xl font-extrabold text-amber-800">{revisao}</dd>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-2xl bg-rose-50 px-4 py-4 ring-1 ring-rose-600/10">
            <XCircle className="size-8 shrink-0 text-rose-600" strokeWidth={1.75} />
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-rose-700">Com erro</dt>
              <dd className="text-2xl font-extrabold text-rose-800">{erro}</dd>
            </div>
          </div>
        </dl>

        <div className="flex flex-col-reverse gap-3 pt-1 sm:flex-row sm:justify-end">
          <Button
            as="a"
            href={urlExportar(loteId)}
            variant="secundario"
            size="lg"
            icon={Download}
            download
          >
            Baixar planilha
          </Button>
          <Button
            as={Link}
            to={`/lote/${loteId}/revisao`}
            variant="primario"
            size="lg"
            icon={ClipboardCheck}
            disabled={revisao === 0}
          >
            {revisao > 0 ? `Revisar ${revisao} ${revisao === 1 ? "pendência" : "pendências"}` : "Nada para revisar"}
          </Button>
        </div>
      </GlassCard>
    </div>
  );
}
