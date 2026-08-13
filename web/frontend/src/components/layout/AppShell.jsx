import { ScanText } from "lucide-react";
import clsx from "clsx";

/**
 * Casca visual comum a toda tela do fluxo principal: fundo em gradiente
 * suave com "blobs" desfocados animados (o motivo de existir do
 * glassmorphism -- sem alguma forma colorida por trás, um cartão
 * translúcido só fica cinza) e um cabeçalho fixo simples. Nenhuma lógica
 * de negócio mora aqui -- é puramente apresentação, análogo ao cabeçalho
 * do Tkinter (`_montar_cabecalho`, Fase 22b) que também não decide nada.
 */
export default function AppShell({ children, largo = false }) {
  return (
    <div className="relative min-h-full overflow-x-hidden bg-slate-50">
      {/*
        Blobs decorativos -- fixos ao viewport, atrás de tudo, nunca
        capturam clique (pointer-events-none). Sub-fase 24c: media-se
        ~RGB(248-253) em praticamente toda a tela na versão da 24b -- o
        efeito existia no código mas não no pixel, por DOIS problemas
        empilhados, achados por medição (`getComputedStyle` + amostragem
        de pixel via Playwright/PIL, não só "de olho"):

        1) `-z-10` colocava este container ABAIXO do fundo `bg-slate-50`
           do próprio elemento pai (`relative`, mesma stacking context) --
           os blobs literalmente pintavam atrás da cor sólida da tela, não
           só desbotados. Trocado para `z-0`: fica acima do fundo da
           própria tela e dos cartões não-posicionados, mas os cartões
           (`GlassCard`) continuam por cima porque cada um pinta o próprio
           fundo branco translúcido -- é assim que o "vidro" aparece por
           CONTRASTE, sem a decoração invadir onde há conteúdo.
        2) opacidade /30-/40 sobre blur-3xl (64px) espalhava a cor até
           quase não sobrar núcleo nenhum. Opacidade subiu para /80-/95 e
           o blur caiu para 2xl/xl (40/24px); o véu branco por cima
           (`from-white/.. to-white/..`) ficou bem mais leve (/8-/15), só
           o suficiente para não competir com o texto.

        Confirmado com amostragem de pixel antes/depois (ver `saida/
        fase24_screenshots/24c/00_blobs_antes.png`/`00_blobs_depois.png`):
        problema 1 sozinho já produzia a tela quase em branco
        independente da opacidade -- os dois precisavam ser corrigidos
        juntos.
      */}
      <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div className="absolute -left-32 -top-32 size-[32rem] animate-blob rounded-full bg-brand-400/90 blur-2xl" />
        <div className="absolute -right-24 top-1/3 size-[28rem] animate-blob rounded-full bg-violet-400/80 blur-2xl [animation-delay:-6s]" />
        <div className="absolute -bottom-32 left-1/4 size-[30rem] animate-blob rounded-full bg-sky-300/85 blur-xl [animation-delay:-11s]" />
        <div className="absolute inset-0 bg-gradient-to-b from-white/8 via-transparent to-white/15" />
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

      {/* `largo`: a tela de Revisão (24c) precisa de mais espaço que o
          fluxo principal -- três áreas lado a lado, mesmo motivo pelo
          qual o Tkinter usa a janela inteira ali (Fase 21b). */}
      <main className={clsx("mx-auto px-6 py-10 sm:py-14", largo ? "max-w-360" : "max-w-5xl")}>
        {children}
      </main>
    </div>
  );
}
