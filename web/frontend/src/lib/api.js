/**
 * src/lib/api.js
 *
 * Fase 24b: único ponto do frontend que fala com o backend FastAPI (Fase
 * 24a). Nenhum outro arquivo faz `fetch` direto -- é o que garante que uma
 * mudança de contrato (ver `web/backend/esquemas.py`) só precise ser
 * ajustada aqui. Nenhuma função aqui decide nada de negócio: só formata a
 * chamada HTTP e devolve o JSON (ou lança `ApiError` com o texto que o
 * backend já mandou em `detail`) -- a decisão (CONFIRMADO/REVISAO, o que
 * pode ser exportado, etc.) já veio pronta do backend.
 */

const BASE = "/api";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Erro HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function pedir(caminho, opcoes = {}) {
  const resposta = await fetch(`${BASE}${caminho}`, opcoes);
  if (!resposta.ok) {
    let detalhe = `Erro HTTP ${resposta.status}`;
    try {
      const corpo = await resposta.json();
      detalhe = corpo.detail || detalhe;
    } catch {
      // corpo não era JSON (ex.: erro de rede/proxy) -- mantém a mensagem genérica
    }
    throw new ApiError(resposta.status, detalhe);
  }
  return resposta;
}

/** Cria um lote a partir de um ou mais arquivos (1 PDF, ou 1+ imagens). */
export async function criarLote(arquivos) {
  const forma = new FormData();
  for (const arquivo of arquivos) forma.append("files", arquivo);
  const resposta = await pedir("/lotes", { method: "POST", body: forma });
  return resposta.json();
}

/** Dispara o processamento em background do lote (não espera terminar). */
export async function dispararProcessamento(loteId) {
  const resposta = await pedir(`/lotes/${loteId}/processar`, { method: "POST" });
  return resposta.json();
}

/** Progresso: status/etapa/página atual/total/contagens. */
export async function consultarStatus(loteId) {
  const resposta = await pedir(`/lotes/${loteId}/status`);
  return resposta.json();
}

/** Registros já classificados até agora (ordem física do lote). */
export async function consultarRegistros(loteId) {
  const resposta = await pedir(`/lotes/${loteId}/registros`);
  return resposta.json();
}

/** Confirmação manual de UM registro -- chama confirmar_revisao_manual no
 * backend (Fase 24a); nunca decide nada aqui. `campos` é um subconjunto de
 * {data, hora, matricula, gestor, motivo}. */
export async function confirmarRegistro(loteId, indice, campos) {
  const resposta = await pedir(`/lotes/${loteId}/registros/${indice}/confirmar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(campos),
  });
  return resposta.json();
}

/** URL de download da planilha -- usada direto num `<a href>`, não via
 * fetch (deixa o navegador cuidar do download/nome de arquivo). */
export function urlExportar(loteId) {
  return `${BASE}/lotes/${loteId}/exportar`;
}

/**
 * Fase 24c: "Por que preciso revisar?" -- explicação humana (Fase 17/18)
 * mais os sinais de contexto (Fase 16) de UM registro. Nunca decide nada;
 * só traduz o que o motor de evidências já registrou.
 */
export async function consultarExplicacao(loteId, indice) {
  const resposta = await pedir(`/lotes/${loteId}/registros/${indice}/explicacao`);
  return resposta.json();
}

/** Listas fechadas de Motivo/Responsável, para sugerir no formulário de
 * revisão (nunca restringe -- o operador pode digitar outra coisa, mesma
 * liberdade do Combobox editável do Tkinter). */
export async function consultarListas(loteId) {
  const resposta = await pedir(`/lotes/${loteId}/listas`);
  return resposta.json();
}

/** URL da foto da página de origem -- usada direto num `<img src>` (o
 * navegador trata o 404 "sem foto disponível" via o evento onError do
 * próprio <img>, nunca escondido/inventado aqui). */
export function urlImagemPagina(loteId, numeroPagina) {
  return `${BASE}/lotes/${loteId}/paginas/${numeroPagina}/imagem`;
}
