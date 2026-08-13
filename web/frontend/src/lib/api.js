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

/** Sub-fase 24d, achado da auditoria visual (com o backend derrubado de
 * propósito para testar o estado de erro): quando o backend real está
 * fora do ar, o proxy do Vite (ver vite.config.js) responde com `502` --
 * uma resposta HTTP de verdade, só que sem corpo JSON -- então isto NÃO
 * cai no `catch` de erro de rede do `fetch` (só cairia se o proxy também
 * estivesse fora, ou sem a resposta chegar de jeito nenhum). Sem esta
 * lista, o operador via a mensagem técnica "Erro HTTP 502" em vez de algo
 * acionável. `504`/`503` são o mesmo tipo de sintoma (gateway/upstream
 * inalcançável) e ficam cobertos pelo mesmo motivo. */
const STATUS_SERVIDOR_INALCANCAVEL = new Set([502, 503, 504]);

async function pedir(caminho, opcoes = {}) {
  const resposta = await fetch(`${BASE}${caminho}`, opcoes);
  if (!resposta.ok) {
    let detalhe = `Erro HTTP ${resposta.status}`;
    try {
      const corpo = await resposta.json();
      detalhe = corpo.detail || detalhe;
    } catch {
      // corpo não era JSON -- ou é o backend fora do ar (ver acima) ou uma
      // falha de infraestrutura sem detalhe estruturado nenhum; nos dois
      // casos "Erro HTTP N" sozinho não ajuda o operador a saber o quê
      // fazer.
      if (STATUS_SERVIDOR_INALCANCAVEL.has(resposta.status)) {
        detalhe = "Não foi possível falar com o servidor -- confira se o backend está rodando.";
      }
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
