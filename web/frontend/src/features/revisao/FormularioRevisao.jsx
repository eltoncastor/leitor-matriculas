import { ChevronDown, ChevronUp, Info, TriangleAlert } from "lucide-react";
import clsx from "clsx";
import Button from "../../components/ui/Button";
import StatusBadge from "../../components/ui/StatusBadge";
import { corCampo, rotuloCampo } from "./vocabulario";

const CAMPOS = ["data", "hora", "matricula", "motivo", "gestor"];

function Campo({ nome, valor, onChange, bloqueado, dicas, opcoes }) {
  const cor = corCampo(nome);
  const idCampo = `revisao-campo-${nome}`;
  return (
    <div className="space-y-1">
      <label
        htmlFor={idCampo}
        className={clsx(
          "flex items-center gap-1.5 text-sm",
          bloqueado ? "font-bold text-slate-900" : "font-medium text-slate-600"
        )}
      >
        {bloqueado ? <TriangleAlert className="size-3.5" style={{ color: cor }} /> : null}
        {rotuloCampo(nome)}
      </label>
      <input
        id={idCampo}
        type="text"
        value={valor}
        onChange={(e) => onChange(nome, e.target.value)}
        list={opcoes ? `lista-${nome}` : undefined}
        className={clsx(
          "w-full rounded-xl border bg-white px-3 py-2 text-sm text-slate-800 outline-none transition-colors",
          "focus:ring-2 focus:ring-brand-300",
          bloqueado ? "border-rose-400" : "border-slate-200"
        )}
      />
      {opcoes ? (
        <datalist id={`lista-${nome}`}>
          {opcoes.map((op) => (
            <option key={op} value={op} />
          ))}
        </datalist>
      ) : null}
      {dicas && dicas.length > 0 ? (
        <div className="space-y-0.5 rounded-lg bg-sky-50 px-2.5 py-1.5 text-xs text-sky-700">
          {dicas.map((dica, i) => (
            <p key={i} className="flex items-start gap-1">
              <Info className="mt-0.5 size-3 shrink-0" />
              <span>{dica}</span>
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Área 3 da tela de Revisão: campos editáveis + explicação + ações.
 * Espelha `_mostrar_explicacao_revisao`/`_destacar_campos_revisao` do
 * Tkinter (Fase 18/22c) -- resumo sempre visível, detalhes atrás de "Ver
 * detalhes" (fechado por padrão), campo bloqueante com borda vermelha +
 * ícone no rótulo (nunca a tela inteira em vermelho), sugestões de
 * contexto coladas ao campo a que se referem, NUNCA pré-selecionadas
 * (`valores` só reflete o que já está no registro -- ver `Revisao.jsx`).
 */
export default function FormularioRevisao({
  valores,
  onCampoAlterado,
  explicacao,
  detalhesAbertos,
  onAlternarDetalhes,
  listas,
  nome,
  setorCargo,
  posicaoTexto,
  progressoTexto,
  onAnterior,
  onProximo,
  onConfirmar,
  confirmando,
  ultimoResultado,
}) {
  const camposBloqueantes = explicacao?.explicacao?.campos_bloqueantes || [];
  const detalhes = explicacao?.explicacao?.detalhes || [];
  const sinais = explicacao?.sinais_contexto || [];
  const dicasPorCampo = {};
  for (const sinal of sinais) {
    const texto = sinal.valor_observado ? `${sinal.motivo}: ${sinal.valor_observado}` : sinal.motivo;
    (dicasPorCampo[sinal.campo] ||= []).push(texto);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* Sub-fase 24d: auditoria de consistência -- `StatusBadge` (o
              mesmo vocabulário "Precisa de revisão" da tela de Resultado,
              `ui/estilos.py::STATUS_VOCABULARIO`) existia desde a 24b mas
              nunca tinha sido usado em lugar nenhum. Toda linha aqui É uma
              pendência REVISAO por definição (a lista já filtra isso),
              então o selo reforça o vocabulário compartilhado entre as
              telas em vez de inventar um rótulo novo só para a Revisão. */}
          <StatusBadge status="REVISAO" size="sm" />
          <span className="text-sm font-semibold text-slate-700">{posicaoTexto}</span>
        </div>
        {progressoTexto ? <span className="text-xs text-slate-400">{progressoTexto}</span> : null}
      </div>

      {explicacao?.explicacao?.titulo ? (
        <p className="mb-2 rounded-xl bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">
          {explicacao.explicacao.titulo}
        </p>
      ) : null}

      {detalhes.length > 0 ? (
        <div className="mb-3">
          <button
            type="button"
            onClick={onAlternarDetalhes}
            className="flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-700"
          >
            {detalhesAbertos ? "Ocultar detalhes" : "Ver detalhes"}
            {detalhesAbertos ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
          {detalhesAbertos ? (
            <ul className="mt-1.5 space-y-1 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
              {detalhes.map((linha, i) => (
                <li key={i}>{linha}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="grid flex-1 auto-rows-min gap-3 overflow-y-auto pr-1">
        {CAMPOS.map((nomeCampo) => (
          <Campo
            key={nomeCampo}
            nome={nomeCampo}
            valor={valores[nomeCampo]}
            onChange={onCampoAlterado}
            bloqueado={camposBloqueantes.includes(nomeCampo)}
            dicas={dicasPorCampo[nomeCampo]}
            opcoes={nomeCampo === "motivo" ? listas?.motivos : nomeCampo === "gestor" ? listas?.gestores : null}
          />
        ))}

        <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <p className="font-semibold uppercase tracking-wide text-slate-400">Obtido da base pela matrícula</p>
          <p className="mt-1 text-sm text-slate-700">{nome || "—"}</p>
          {setorCargo ? <p className="text-slate-500">{setorCargo}</p> : null}
        </div>

        {ultimoResultado && !ultimoResultado.confirmou_agora ? (
          <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">
            Ainda não é possível confirmar: {ultimoResultado.observacao_classificacao}
          </p>
        ) : null}
      </div>

      <div className="mt-4 flex items-center justify-between gap-2 border-t border-slate-100 pt-4">
        <div className="flex gap-2">
          <Button variant="secundario" size="sm" onClick={onAnterior}>
            Anterior
          </Button>
          <Button variant="secundario" size="sm" onClick={onProximo}>
            Próximo
          </Button>
        </div>
        <Button variant="primario" onClick={onConfirmar} disabled={confirmando}>
          {confirmando ? "Confirmando..." : "Confirmar e próximo"}
        </Button>
      </div>
    </div>
  );
}
