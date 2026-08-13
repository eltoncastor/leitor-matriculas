import clsx from "clsx";
import { corCampo, rotuloPendencia } from "./vocabulario";

/**
 * Área 1 da tela de Revisão (mesmo modelo mental da Fase 21b no Tkinter):
 * a lista de tudo que falta revisar, navegável, com o tipo de pendência
 * indicado por cor de TEXTO -- nunca de fundo, pelo mesmo motivo do
 * Tkinter ("sem exagerar em cores"). Só apresenta `pendentes` (já
 * calculado por `useRevisao` a partir de `registros`) -- não decide o
 * que é uma pendência.
 */
export default function ListaPendencias({ pendentes, posicaoAtual, onSelecionar }) {
  return (
    <div className="flex h-full flex-col">
      <ul className="flex-1 space-y-1 overflow-y-auto pr-1" role="listbox" aria-label="Pendências">
        {pendentes.map(({ registro, indice }, posicao) => {
          const ativo = posicao === posicaoAtual;
          const campos = registro.campos_bloqueantes || [];
          const corTexto = campos.length > 0 ? corCampo(campos[0]) : "#495057";
          return (
            <li key={indice}>
              <button
                type="button"
                role="option"
                aria-selected={ativo}
                onClick={() => onSelecionar(posicao)}
                className={clsx(
                  "flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors duration-150",
                  ativo ? "bg-brand-50 ring-1 ring-brand-200" : "hover:bg-slate-900/5"
                )}
              >
                <span className="w-9 shrink-0 text-xs font-semibold text-slate-400">
                  p.{registro.pagina_origem}
                </span>
                <span className="w-16 shrink-0 truncate font-mono text-xs text-slate-600">
                  {registro.matricula || "—"}
                </span>
                <span
                  className="min-w-0 flex-1 truncate text-xs font-semibold"
                  style={{ color: corTexto }}
                >
                  {rotuloPendencia(campos)}
                </span>
              </button>
            </li>
          );
        })}
        {pendentes.length === 0 ? (
          <li className="px-3 py-6 text-center text-sm text-slate-400">Nenhuma pendência.</li>
        ) : null}
      </ul>
    </div>
  );
}
