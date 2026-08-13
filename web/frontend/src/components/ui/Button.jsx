import clsx from "clsx";

/**
 * Botão único para todo o frontend -- evita o que o preâmbulo da fase
 * pediu para evitar (o mesmo botão com estilos ligeiramente diferentes
 * espalhado em 5 lugares). `variant` cobre a mesma hierarquia que a
 * Fase 22c já tinha auditado como correta no Tkinter (primário sólido /
 * secundário contornado / terciário discreto).
 */
const VARIANTES = {
  primario:
    "bg-brand-600 text-white shadow-glass hover:bg-brand-700 hover:shadow-glass-lg " +
    "focus-visible:ring-brand-400 disabled:bg-brand-300",
  secundario:
    "bg-white/70 text-brand-700 border border-brand-200 backdrop-blur-sm hover:bg-white hover:border-brand-300 " +
    "focus-visible:ring-brand-300 disabled:text-slate-400 disabled:border-slate-200",
  fantasma:
    "text-slate-600 hover:bg-slate-900/5 focus-visible:ring-slate-300 disabled:text-slate-300",
  perigo:
    "bg-rose-600 text-white shadow-glass hover:bg-rose-700 focus-visible:ring-rose-400 disabled:bg-rose-300",
};

const TAMANHOS = {
  md: "px-5 py-2.5 text-sm gap-2",
  lg: "px-7 py-3.5 text-base gap-2.5",
  sm: "px-3.5 py-1.5 text-xs gap-1.5",
};

export default function Button({
  as: Componente = "button",
  variant = "primario",
  size = "md",
  className,
  icon: Icone,
  iconRight: IconeDireita,
  children,
  ...resto
}) {
  return (
    <Componente
      className={clsx(
        "inline-flex items-center justify-center rounded-2xl font-semibold tracking-tight",
        "transition-all duration-200 ease-out active:scale-[0.97]",
        "focus-visible:outline-none focus-visible:ring-4",
        "disabled:cursor-not-allowed disabled:active:scale-100 disabled:shadow-none",
        VARIANTES[variant],
        TAMANHOS[size],
        className
      )}
      {...resto}
    >
      {Icone ? <Icone className="size-[1.15em] shrink-0" strokeWidth={2.25} /> : null}
      {children}
      {IconeDireita ? <IconeDireita className="size-[1.15em] shrink-0" strokeWidth={2.25} /> : null}
    </Componente>
  );
}
