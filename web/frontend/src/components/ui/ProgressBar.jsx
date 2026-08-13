import clsx from "clsx";

/**
 * Barra de progresso do processamento. `percentual === null` (total
 * desconhecido) vira uma barra INDETERMINADA (listra animada), em vez de
 * travar em 0% -- mesmo cuidado que a Fase 7 do Tkinter já tomou ("sem
 * denominador não há percentual honesto a mostrar").
 */
export default function ProgressBar({ percentual, className }) {
  const indeterminada = percentual === null || percentual === undefined;
  return (
    <div
      className={clsx(
        "relative h-3 w-full overflow-hidden rounded-full bg-brand-100/70",
        className
      )}
      role="progressbar"
      aria-valuenow={indeterminada ? undefined : Math.round(percentual)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      {indeterminada ? (
        <div className="absolute inset-y-0 w-1/3 animate-[indeterminado_1.4s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-brand-400 via-brand-600 to-brand-400" />
      ) : (
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-[width] duration-500 ease-out"
          style={{ width: `${Math.min(100, Math.max(0, percentual))}%` }}
        />
      )}
      <style>{`
        @keyframes indeterminado {
          0% { left: -33%; }
          100% { left: 100%; }
        }
      `}</style>
    </div>
  );
}
