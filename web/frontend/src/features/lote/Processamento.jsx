import { Loader2, FileScan } from "lucide-react";
import GlassCard from "../../components/ui/GlassCard";
import ProgressBar from "../../components/ui/ProgressBar";

/**
 * Tela 3 do fluxo: acompanhamento do processamento. O OCR é lento
 * (~40 s/folha, ver CLAUDE.md) -- esta tela existe para o operador
 * entender que o programa está TRABALHANDO, não travado, exatamente a
 * mesma preocupação que motivou a barra "Folha X/Y" na Fase 7 do
 * Tkinter. Só mostra o que `status` (de `GET /lotes/{id}/status`,
 * consultado por polling em `PaginaLote`) já traz -- nenhuma conta nova
 * é feita aqui.
 */
export default function Processamento({ status }) {
  const total = status.total_paginas;
  const atual = status.pagina_atual;
  const percentual = total ? (atual / total) * 100 : null;

  return (
    <div className="animate-fade-up space-y-6">
      <GlassCard className="space-y-7 text-center">
        <div className="flex justify-center">
          <div className="relative flex size-20 items-center justify-center rounded-3xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glass-lg">
            <FileScan className="size-9" strokeWidth={1.6} />
            <Loader2 className="absolute -bottom-2 -right-2 size-7 animate-spin rounded-full bg-white p-1 text-brand-600 shadow-glass" />
          </div>
        </div>

        <div className="space-y-1.5">
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
            Lendo o texto escrito à mão...
          </h1>
          <p className="text-sm text-slate-500">
            {total
              ? `Folha ${atual} de ${total}`
              : "Preparando o processamento..."}
            {status.etapa_atual ? ` · ${status.etapa_atual}` : ""}
          </p>
        </div>

        <div className="mx-auto max-w-md space-y-2">
          <ProgressBar percentual={percentual} />
          <p className="text-xs font-medium text-slate-400">
            {percentual !== null ? `${Math.round(percentual)}% concluído` : "Calculando o total de folhas..."}
          </p>
        </div>

        <dl className="mx-auto grid max-w-sm grid-cols-3 gap-3 pt-2 text-center">
          <div className="rounded-2xl bg-white/70 px-3 py-3 ring-1 ring-slate-900/5">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Lidas</dt>
            <dd className="text-xl font-bold text-slate-800">{status.paginas_processadas}</dd>
          </div>
          <div className="rounded-2xl bg-white/70 px-3 py-3 ring-1 ring-slate-900/5">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Registros</dt>
            <dd className="text-xl font-bold text-slate-800">{status.total_registros}</dd>
          </div>
          <div className="rounded-2xl bg-white/70 px-3 py-3 ring-1 ring-slate-900/5">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Com erro</dt>
            <dd className={`text-xl font-bold ${status.paginas_com_erro > 0 ? "text-rose-600" : "text-slate-800"}`}>
              {status.paginas_com_erro}
            </dd>
          </div>
        </dl>

        <p className="text-xs text-slate-400">
          O reconhecimento manuscrito é a parte demorada (~40 s por folha) -- pode deixar esta aba
          aberta em segundo plano.
        </p>
      </GlassCard>
    </div>
  );
}
