import clsx from "clsx";

/**
 * O "cartão" central do vocabulário visual desta fase: fundo translúcido
 * + blur (glassmorphism), cantos bem arredondados, sombra suave em vez de
 * borda dura. É o equivalente visual do `Card.TFrame` que a Fase 22b
 * criou para o Tkinter (fundo por CONTRASTE, não por linha) -- só que
 * aqui o teto técnico permite ir além de uma cor sólida.
 */
export default function GlassCard({ as: Componente = "div", className, padding = "p-6", children, ...resto }) {
  return (
    <Componente
      className={clsx(
        "rounded-3xl border border-white/60 bg-white/70 backdrop-blur-xl shadow-glass",
        padding,
        className
      )}
      {...resto}
    >
      {children}
    </Componente>
  );
}
