import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import clsx from "clsx";

/**
 * Mesmo VOCABULÁRIO da Fase 21c/`ui/estilos.py` (`STATUS_VOCABULARIO`):
 * "Confirmado" / "Precisa de revisão" / "Erro no processamento" -- é o
 * mesmo produto por trás dos dois frontends, então o texto que o operador
 * lê não pode divergir entre o Tkinter e a web só porque a plataforma
 * mudou. Só o ÍCONE trocou de glifo Unicode monocromático para um ícone
 * vetorial (lucide-react) -- consistente com o teto visual mais alto que
 * esta fase busca.
 */
const CONFIG = {
  CONFIRMADO: {
    rotulo: "Confirmado",
    Icone: CheckCircle2,
    classe: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20",
  },
  REVISAO: {
    rotulo: "Precisa de revisão",
    Icone: AlertTriangle,
    classe: "bg-amber-50 text-amber-700 ring-1 ring-amber-600/20",
  },
  ERRO: {
    rotulo: "Erro no processamento",
    Icone: XCircle,
    classe: "bg-rose-50 text-rose-700 ring-1 ring-rose-600/20",
  },
};

export default function StatusBadge({ status, className, size = "md" }) {
  const config = CONFIG[status] ?? CONFIG.REVISAO;
  const { Icone } = config;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full font-semibold",
        size === "md" ? "px-3 py-1 text-sm" : "px-2.5 py-0.5 text-xs",
        config.classe,
        className
      )}
    >
      <Icone className="size-[1.1em]" strokeWidth={2.25} />
      {config.rotulo}
    </span>
  );
}
