/**
 * src/features/lote/regrasArquivo.js
 *
 * Mesma regra de aceitação que `web/backend/rotas/lotes.py` já aplica no
 * servidor (`EXTENSOES_IMAGEM`/`EXTENSAO_PDF`) -- duplicada aqui SÓ para
 * dar feedback imediato no navegador (sem round-trip de rede para dizer
 * "isso não é uma imagem nem PDF"). A decisão que VALE é sempre a do
 * backend: se as duas listas um dia divergirem, o pior caso é o
 * navegador aceitar um arquivo que o backend rejeita com 400 -- nunca o
 * contrário, e nunca uma classificação de negócio sendo decidida aqui.
 */
export const EXTENSOES_IMAGEM = [".jpg", ".jpeg", ".png", ".webp"];
export const EXTENSAO_PDF = ".pdf";

function extensao(nomeArquivo) {
  const ponto = nomeArquivo.lastIndexOf(".");
  return ponto === -1 ? "" : nomeArquivo.slice(ponto).toLowerCase();
}

/**
 * Classifica uma lista de `File` do navegador. Devolve `{ tipo, erro }`:
 * `tipo` é "pdf" | "imagens" | null; `erro` é uma mensagem pronta para
 * mostrar (ou null quando a seleção é válida).
 */
export function classificarSelecao(arquivos) {
  if (!arquivos || arquivos.length === 0) {
    return { tipo: null, erro: null };
  }
  const extensoes = arquivos.map((a) => extensao(a.name));

  if (arquivos.length === 1 && extensoes[0] === EXTENSAO_PDF) {
    return { tipo: "pdf", erro: null };
  }
  if (extensoes.some((e) => e === EXTENSAO_PDF)) {
    return {
      tipo: null,
      erro: "Um PDF precisa ser enviado sozinho -- ou envie 1 PDF, ou envie 1 ou mais imagens, não os dois juntos.",
    };
  }
  const invalidas = arquivos.filter((_, i) => !EXTENSOES_IMAGEM.includes(extensoes[i]));
  if (invalidas.length > 0) {
    return {
      tipo: null,
      erro: `Formato não aceito: ${invalidas.map((a) => a.name).join(", ")}. ` +
        `Use PDF ou imagens (${EXTENSOES_IMAGEM.join(", ")}).`,
    };
  }
  return { tipo: "imagens", erro: null };
}

export function formatarTamanho(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
