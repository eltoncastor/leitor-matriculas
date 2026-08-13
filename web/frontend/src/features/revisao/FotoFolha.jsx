import { useEffect, useState } from "react";
import { ImageOff, ZoomIn, ZoomOut } from "lucide-react";
import { urlImagemPagina } from "../../lib/api";

const ZOOM_MIN = 0.4;
const ZOOM_MAX = 3;
const ZOOM_PASSO = 1.25;

/**
 * Área 2 da tela de Revisão: a foto da folha de origem, com zoom básico
 * -- mesmo papel de `canvas_foto`/`_ajustar_zoom` no Tkinter (Fase 10),
 * só que via `<img>` + CSS `transform: scale(...)` em vez de redesenhar
 * um `PhotoImage` a cada zoom. `onError` trata o 404 ("sem foto
 * disponível") mostrando o mesmo aviso que `_mostrar_foto_pagina` já
 * mostrava -- nunca inventa uma imagem.
 */
export default function FotoFolha({ loteId, numeroPagina }) {
  const [zoom, setZoom] = useState(1);
  const [indisponivel, setIndisponivel] = useState(false);

  // Reseta zoom/estado de erro a cada folha nova -- mesma ideia de
  // `_mostrar_foto_pagina` reiniciar o zoom "para caber" numa página nova.
  useEffect(() => {
    setZoom(1);
    setIndisponivel(false);
  }, [loteId, numeroPagina]);

  if (numeroPagina == null) return null;

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex gap-1.5">
          <button
            type="button"
            aria-label="Diminuir zoom"
            onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z / ZOOM_PASSO))}
            className="flex size-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition-colors hover:bg-slate-50"
          >
            <ZoomOut className="size-4" />
          </button>
          <button
            type="button"
            aria-label="Aumentar zoom"
            onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z * ZOOM_PASSO))}
            className="flex size-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition-colors hover:bg-slate-50"
          >
            <ZoomIn className="size-4" />
          </button>
        </div>
        <span className="text-xs font-medium text-slate-400">página {numeroPagina}</span>
      </div>

      <div className="relative flex-1 overflow-auto rounded-xl border border-slate-200 bg-slate-100">
        {indisponivel ? (
          <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 p-6 text-center text-sm text-slate-400">
            <ImageOff className="size-8" strokeWidth={1.5} />
            <p>A foto desta página não está disponível.</p>
          </div>
        ) : (
          <div className="min-w-0 p-4">
            {/*
              Sub-fase 24c, achado real corrigido: `max-w-none` deixava a
              imagem no tamanho INTRÍNSECO (a foto original, ~1500px de
              lado -- ver LARGURA_MAXIMA_MINIATURA em estado.py), o que
              estourava a largura da coluna e empurrava a área do
              formulário pra fora da tela inteira -- só apareciam
              Pendências+Foto no viewport, nunca as três áreas juntas.
              Achado por inspeção visual do screenshot real, não só
              lendo o código. `max-w-full h-auto` faz a imagem caber na
              coluna por padrão (zoom 1 = "ajustar à largura"); o zoom
              em si continua sendo `transform: scale(...)` a partir
              dessa base, com o contêiner pai (`overflow-auto`)
              habilitando rolar para ver além quando amplia.
            */}
            <img
              key={`${loteId}-${numeroPagina}`}
              src={urlImagemPagina(loteId, numeroPagina)}
              alt={`Folha digitalizada -- página ${numeroPagina}`}
              onError={() => setIndisponivel(true)}
              style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
              className="max-w-full rounded-md shadow-sm transition-transform duration-150"
            />
          </div>
        )}
      </div>
    </div>
  );
}
