import { ScanText } from "lucide-react";

/**
 * Casca visual comum a toda tela do fluxo principal: fundo em gradiente
 * suave com "blobs" desfocados animados (o motivo de existir do
 * glassmorphism -- sem alguma forma colorida por trás, um cartão
 * translúcido só fica cinza) e um cabeçalho fixo simples. Nenhuma lógica
 * de negócio mora aqui -- é puramente apresentação, análogo ao cabeçalho
 * do Tkinter (`_montar_cabecalho`, Fase 22b) que também não decide nada.
 */
export default function AppShell({ children }) {
  return (
    <div className="relative min-h-full overflow-x-hidden bg-slate-50">
      {/* Blobs decorativos -- fixos ao viewport, atrás de tudo, nunca capturam clique */}
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-32 -top-32 size-[32rem] animate-blob rounded-full bg-brand-300/40 blur-3xl" />
        <div className="absolute -right-24 top-1/3 size-[28rem] animate-blob rounded-full bg-violet-300/30 blur-3xl [animation-delay:-6s]" />
        <div className="absolute -bottom-32 left-1/4 size-[30rem] animate-blob rounded-full bg-sky-200/40 blur-3xl [animation-delay:-11s]" />
        <div className="absolute inset-0 bg-gradient-to-b from-white/40 via-transparent to-white/60" />
      </div>

      <header className="sticky top-0 z-20 border-b border-white/60 bg-white/60 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <div className="flex size-10 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glass">
            <ScanText className="size-5" strokeWidth={2.25} />
          </div>
          <div className="leading-tight">
            <p className="text-base font-bold tracking-tight text-slate-900">Leitor de Matrículas</p>
            <p className="text-xs font-medium text-slate-500">Web · by Elton Marques</p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10 sm:py-14">{children}</main>
    </div>
  );
}
