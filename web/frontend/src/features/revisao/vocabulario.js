/**
 * src/features/revisao/vocabulario.js
 *
 * Vocabulário de apresentação da Revisão -- rótulos e cores por CAMPO
 * (data/hora/matricula/motivo/gestor). Mesmos valores de `ui/estilos.py`
 * (`CORES_TIPO_PENDENCIA`/Fase 21b) e `validacao/explicacao_revisao.
 * ROTULOS` (Fase 18) -- é o mesmo produto, então a cor e a palavra que o
 * operador associa a "isto é uma pendência de Responsável" não podem
 * divergir entre o Tkinter e a web. Puramente apresentação: nenhuma
 * lógica daqui decide o que é ou não um campo bloqueante -- isso vem do
 * backend (`campos_bloqueantes`, Fase 24c).
 */
export const ROTULOS_CAMPO = {
  data: "Data",
  hora: "Hora",
  matricula: "Matrícula",
  motivo: "Motivo",
  gestor: "Responsável",
};

export const COR_CAMPO = {
  data: "#5C6BC0",
  hora: "#00897B",
  matricula: "#8E24AA",
  motivo: "#EF6C00",
  gestor: "#C2185B",
};

export const COR_CAMPO_PADRAO = "#495057";

export function rotuloCampo(campo) {
  return ROTULOS_CAMPO[campo] || campo;
}

export function corCampo(campo) {
  return COR_CAMPO[campo] || COR_CAMPO_PADRAO;
}

/** Rótulo curto da pendência de uma linha, pro mesmo padrão da lista do
 * Tkinter (`_atualizar_lista_revisao_pendencias`): campos bloqueantes
 * unidos por vírgula, ou "revisão" quando não há nenhum identificado. */
export function rotuloPendencia(camposBloqueantes) {
  if (!camposBloqueantes || camposBloqueantes.length === 0) return "revisão";
  return camposBloqueantes.map(rotuloCampo).join(", ");
}
