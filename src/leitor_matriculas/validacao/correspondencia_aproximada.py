"""
correspondencia_aproximada.py

Fuzzy matching CONTROLADO e contextual, usado por `validacao.py` para os
campos MOTIVO e RESPONSÁVEL PELA AUTORIZAÇÃO -- os dois campos manuscritos
mais sujeitos a erro de OCR (letras trocadas, junções erradas) mas cujo
valor correto só pode ser um de uma lista FECHADA e conhecida (Motivos.xlsx
/ Gestores.xlsx).

Isto NÃO é geração livre de texto: o resultado é sempre um dos candidatos
já existentes na base, ou nenhum (REVISAO). Segue o mesmo espírito de
`ocr_engine.normalizar_matricula` -- sugere uma correção plausível, nunca
inventa, e o texto original do OCR continua disponível para quem chamar
(nunca é descartado).

REGRAS (requisito funcional definitivo desta camada):
    1. Só se aplica a um campo de cada vez, contra os candidatos daquele
       campo específico (quem chama passa a lista certa).
    2. Candidatos vêm sempre da base carregada (DataManager) -- nunca são
       inventados aqui.
    3. Normalização (maiúsculo, sem acento) acontece antes de comparar.
    4. Métrica de similaridade: difflib.SequenceMatcher (biblioteca
       padrão -- não introduz nova dependência).
    5. Limiar mínimo de aceitação (LIMIAR_MINIMO_PADRAO).
    6. Compara o 1º e o 2º melhor candidato: se a diferença entre eles for
       pequena demais (MARGEM_AMBIGUIDADE_PADRAO), o resultado é
       AMBIGUA -- nunca escolhe um "no chute".
    7. Base vazia ou texto vazio nunca derruba quem chama -- devolve um
       status explícito (SEM_CANDIDATOS / VAZIO) em vez de lançar exceção.
"""

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

# Separador gestor/auxiliar: hífen com espaço opcional dos dois lados --
# o OCR real produz tanto "GR3 - Eslon" quanto "GR4- Cosecone" (sem espaço
# antes do hífen), então o corte não pode depender de " - " literal.
_RE_SEPARADOR_AUXILIAR = re.compile(r"\s*-\s*")

# Ajustados empiricamente contra os exemplos do requisito funcional
# ("neegadho" -> "NEGADO", "negaoda" -> "NEGADO", "hr negad" -> possível
# "HORÁRIO NEGADO") e contra a base real de Motivos.xlsx (que tem pares
# propositalmente parecidos, como "NEGADA"/"NEGADO"/"H. NEGADO"/"Horário
# negado" -- exatamente o cenário em que a checagem de ambiguidade importa).
LIMIAR_MINIMO_PADRAO = 0.55
MARGEM_AMBIGUIDADE_PADRAO = 0.08


def _normalizar(texto) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto).strip().upper())
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


@dataclass
class ResultadoCorrespondencia:
    """
    Resultado de uma tentativa de correspondência aproximada.

    status:
        "VAZIO"               -- texto_ocr vazio/None (nada a comparar).
        "SEM_CANDIDATOS"      -- lista de candidatos vazia (base indisponível).
        "EXATA"               -- bate exatamente (após normalização) com um candidato.
        "APROXIMADA"          -- não bate exatamente, mas passou no limiar e não é ambíguo.
        "AMBIGUA"             -- dois (ou mais) candidatos disputam de forma parecida demais.
        "SEM_CORRESPONDENCIA" -- nenhum candidato chegou perto o suficiente.

    valor_sugerido: só é preenchido em EXATA/APROXIMADA -- nos outros
    casos é None (nunca "meio-sugerido").
    """
    texto_original: str
    valor_sugerido: Optional[str]
    status: str
    similaridade: Optional[float] = None
    segundo_candidato: Optional[str] = None
    segunda_similaridade: Optional[float] = None

    @property
    def houve_normalizacao(self) -> bool:
        """True quando o valor aceito veio de aproximação, não de igualdade
        exata -- usado por quem chama para registrar isso na Observação."""
        return self.status == "APROXIMADA"


def buscar_correspondencia(
    texto_ocr: Optional[str],
    candidatos: List[str],
    limiar_minimo: float = LIMIAR_MINIMO_PADRAO,
    margem_ambiguidade: float = MARGEM_AMBIGUIDADE_PADRAO,
) -> ResultadoCorrespondencia:
    """
    Tenta encontrar, entre `candidatos`, aquele que corresponde a
    `texto_ocr`. Nunca lança exceção; nunca inventa um candidato que não
    esteja na lista.
    """
    if not texto_ocr or not str(texto_ocr).strip():
        return ResultadoCorrespondencia(texto_ocr or "", None, "VAZIO")

    if not candidatos:
        return ResultadoCorrespondencia(texto_ocr, None, "SEM_CANDIDATOS")

    alvo = _normalizar(texto_ocr)

    # As planilhas reais trazem os valores com espaços de preenchimento
    # (" Horário negado         "). Isso é artefato da célula, não parte do
    # valor: sai daqui já aparado, senão iria assim para a planilha final.
    candidatos = [str(c).strip() for c in candidatos]

    pontuacoes = []
    for candidato in candidatos:
        similaridade = difflib.SequenceMatcher(None, alvo, _normalizar(candidato)).ratio()
        pontuacoes.append((similaridade, candidato))
    pontuacoes.sort(key=lambda par: par[0], reverse=True)

    melhor_sim, melhor_candidato = pontuacoes[0]
    segundo_candidato = pontuacoes[1][1] if len(pontuacoes) > 1 else None
    segunda_sim = pontuacoes[1][0] if len(pontuacoes) > 1 else None

    if melhor_sim >= 0.999:
        return ResultadoCorrespondencia(
            texto_ocr, melhor_candidato, "EXATA", melhor_sim, segundo_candidato, segunda_sim
        )

    if melhor_sim < limiar_minimo:
        return ResultadoCorrespondencia(
            texto_ocr, None, "SEM_CORRESPONDENCIA", melhor_sim, segundo_candidato, segunda_sim
        )

    if segunda_sim is not None and (melhor_sim - segunda_sim) < margem_ambiguidade:
        return ResultadoCorrespondencia(
            texto_ocr, None, "AMBIGUA", melhor_sim, segundo_candidato, segunda_sim
        )

    return ResultadoCorrespondencia(
        texto_ocr, melhor_candidato, "APROXIMADA", melhor_sim, segundo_candidato, segunda_sim
    )


# ---------------------------------------------------------------------------
# MOTIVO
#
# "Horário negado" é, de longe, o motivo mais frequente da folha e o mais
# maltratado pelo OCR: manuscrito e abreviado de N formas ("H. negado",
# "Hr. negado", "negado"), ele sai como "Hiv. Nigado", "Negoide",
# "Negade", "NEGAND", "I Wegado", "NoGAAO"... A base reflete isso: além de
# "Horário negado", ela tem "NEGADO", "NEGADA" e "H. NEGADO" cadastrados
# separadamente. Essas entradas são SINÔNIMOS do mesmo motivo real, e é
# justamente por serem quase idênticas entre si que o OCR corrompido cai
# em AMBIGUA na `buscar_correspondencia` -- o registro ia para REVISAO não
# por falta de evidência, mas por excesso de candidatos equivalentes.
#
# `resolver_motivo` trata essa família como uma coisa só:
#   - a família é derivada DA BASE (entradas cujo texto contém "NEGAD"),
#     nunca de uma lista fixa aqui -- se a base mudar, isto acompanha;
#   - o fallback só existe se a base tiver mesmo a entrada canônica
#     "Horário negado" (senão, seria inventar um valor fora da base);
#   - um match EXATO nunca é mexido: se o operador escreveu "NEGADA" e o
#     OCR leu "NEGADA", é isso que vai para a planilha;
#   - um match APROXIMADO que cai na família, e um caso AMBIGUO/sem
#     correspondência com evidência SUFICIENTE de família, viram o valor
#     canônico `HORÁRIO NEGADO`;
#   - a evidência exigida é dupla: passar do limiar contra a família E
#     ganhar dos motivos de FORA da família por uma margem clara. Sem
#     isso, um "ADM"/"ARM" corrompido poderia ser sugado para cá -- é essa
#     segunda checagem que impede o falso positivo.
# ---------------------------------------------------------------------------

MOTIVO_HORARIO_NEGADO = "HORÁRIO NEGADO"

# Marca textual da família na base. Deliberadamente o radical, não a
# palavra inteira: cobre "NEGADO"/"NEGADA"/"H. NEGADO"/"Horário negado".
_MARCA_FAMILIA_NEGADO = "NEGAD"


@dataclass
class ResultadoMotivo:
    """
    Resultado de resolver o campo MOTIVO.

    status: os mesmos de ResultadoCorrespondencia, mais
        "NORMALIZADA" -- o texto do OCR não bateu de forma confiável com
        nenhum motivo isolado, mas tinha evidência suficiente de ser a
        família "negado", e foi normalizado para MOTIVO_HORARIO_NEGADO.
    """
    texto_original: str
    motivo_confirmado: Optional[str]
    status: str
    similaridade: Optional[float] = None
    segundo_candidato: Optional[str] = None
    houve_fallback: bool = False


def _e_da_familia_negado(texto: Optional[str]) -> bool:
    return _MARCA_FAMILIA_NEGADO in _normalizar(texto)


def _melhor_similaridade(alvo_normalizado: str, candidatos: List[str]) -> float:
    if not candidatos:
        return 0.0
    return max(
        difflib.SequenceMatcher(None, alvo_normalizado, _normalizar(c)).ratio()
        for c in candidatos
    )


def resolver_motivo(
    texto_ocr: Optional[str],
    candidatos_motivos: List[str],
    limiar_minimo: float = LIMIAR_MINIMO_PADRAO,
    margem_ambiguidade: float = MARGEM_AMBIGUIDADE_PADRAO,
) -> ResultadoMotivo:
    """
    Resolve o campo MOTIVO contra a base de motivos, com a canonicalização
    da família "negado" descrita acima. Nunca inventa um motivo fora da
    base; sem evidência suficiente, devolve o status de falha e o registro
    segue para REVISAO como antes.
    """
    candidatos_motivos = [str(c).strip() for c in candidatos_motivos]
    resultado = buscar_correspondencia(texto_ocr, candidatos_motivos, limiar_minimo, margem_ambiguidade)

    if resultado.status in ("VAZIO", "SEM_CANDIDATOS"):
        return ResultadoMotivo(texto_ocr or "", None, resultado.status, resultado.similaridade)

    # Match exato: é exatamente o que está escrito na folha e na base.
    # Não se mexe, nem para canonicalizar a família (requisito: motivo
    # reconhecido com segurança mantém o motivo correto).
    if resultado.status == "EXATA":
        return ResultadoMotivo(
            texto_ocr, resultado.valor_sugerido, "EXATA", resultado.similaridade,
            resultado.segundo_candidato,
        )

    familia = [c for c in candidatos_motivos if _e_da_familia_negado(c)]
    # Só canonicaliza se o próprio valor canônico existir na base -- caso
    # contrário estaríamos escrevendo na planilha um motivo que a empresa
    # não cadastrou.
    canonico_na_base = any(
        _normalizar(c) == _normalizar(MOTIVO_HORARIO_NEGADO) for c in candidatos_motivos
    )

    # Aproximado que caiu na família: o OCR estava corrompido e a correção
    # aponta para um sinônimo. Sai canonicalizado, para a planilha não
    # misturar "H. NEGADO"/"NEGADO"/"HORÁRIO NEGADO" vindos do mesmo erro.
    if resultado.status == "APROXIMADA":
        if canonico_na_base and _e_da_familia_negado(resultado.valor_sugerido):
            return ResultadoMotivo(
                texto_ocr, MOTIVO_HORARIO_NEGADO, "NORMALIZADA", resultado.similaridade,
                resultado.segundo_candidato, houve_fallback=True,
            )
        return ResultadoMotivo(
            texto_ocr, resultado.valor_sugerido, "APROXIMADA", resultado.similaridade,
            resultado.segundo_candidato,
        )

    # AMBIGUA / SEM_CORRESPONDENCIA: última chance, só com evidência dupla.
    if canonico_na_base and familia:
        alvo = _normalizar(texto_ocr)
        sim_familia = _melhor_similaridade(alvo, familia)
        sim_fora = _melhor_similaridade(alvo, [c for c in candidatos_motivos if c not in familia])
        if sim_familia >= limiar_minimo and (sim_familia - sim_fora) >= margem_ambiguidade:
            return ResultadoMotivo(
                texto_ocr, MOTIVO_HORARIO_NEGADO, "NORMALIZADA", sim_familia,
                resultado.segundo_candidato, houve_fallback=True,
            )

    return ResultadoMotivo(
        texto_ocr, None, resultado.status, resultado.similaridade, resultado.segundo_candidato,
    )


# ---------------------------------------------------------------------------
# RESPONSÁVEL (gestor)
#
# O campo RESPONSÁVEL às vezes tem um Auxiliar de Prevenção de Perdas
# anotado junto ao gestor, para registrar quem estava na portaria (ex.:
# "GR3 - DIANA - ESLEANE"). O nome do auxiliar NÃO é usado em lugar
# nenhum do resultado final (não faz parte da planilha) -- por isso este
# módulo não tenta mais reconhecê-lo/corrigi-lo (ver histórico: essa
# tentativa criava risco real de reconhecimento errado em nomes curtos,
# ex. "Eslon" -> "ELTON"). O que importa é só NÃO deixar esse texto extra
# contaminar a identificação do GESTOR -- por isso a lógica de separar um
# possível texto residual depois do gestor continua existindo, só que o
# texto em si é descartado, não devolvido nem processado.
#
# Hífen NÃO significa separação automática: "GR3 - DIANA" e
# "GR4 - ANDRÉ VALENÇA" são identificações ÚNICAS de gestor (existem assim,
# inteiras, na base). Só depois de tentar o texto INTEIRO contra a base é
# que um prefixo (cortado no separador) é tentado -- e a MAIOR sequência
# confiável sempre ganha (prefixo mais longo primeiro). O prefixo pode
# bater EXATO ou APROXIMADO (ex.: "Gkl" -> "GRL", erro de OCR num código
# curto) -- a mesma checagem de limiar/ambiguidade de `buscar_correspondencia`
# já protege contra um chute errado. Quando o prefixo aceito é só um
# código/alias curto (ex.: "GRL") e existe, na base, uma identificação MAIS
# ESPECÍFICA que começa com esse código (ex.: "GRL - FABIANA"), essa versão
# mais específica é usada como gestor_confirmado -- mas só quando não há
# ambiguidade (só uma expansão possível); com duas ou mais, o código
# sozinho não é aceito como confirmação suficiente.
# ---------------------------------------------------------------------------

@dataclass
class ResultadoResponsavel:
    """Resultado de resolver o campo RESPONSÁVEL (só o gestor -- o nome do
    auxiliar de portaria, quando escrito junto, não faz parte do resultado
    final e não é reconhecido/reportado por este módulo)."""
    texto_original: str
    gestor_confirmado: Optional[str]
    status: str  # mesmos status de ResultadoCorrespondencia
    similaridade: Optional[float] = None
    houve_normalizacao: bool = False


def _expandir_para_entrada_mais_especifica(gestor: str, candidatos: List[str]) -> Optional[str]:
    """
    Se `gestor` for um código/alias curto (ex.: "GRL") e existir, entre os
    candidatos, uma identificação MAIS ESPECÍFICA que começa com esse
    código seguido de um separador não-alfanumérico (ex.: "GRL - FABIANA"),
    devolve essa versão mais específica.

    Devolve None (não expande -- mantém o código como está) quando não há
    nenhuma expansão mais específica, OU quando há mais de uma (ambíguo
    demais para escolher sozinho: "ANDERSON" -> "ANDERSON ABREU" /
    "ANDERSON CARLOS" não expande, o código sozinho fica como está). Nunca
    inventa: só escolhe entre o que já existe na base.
    """
    gestor_norm = _normalizar(gestor)
    mais_especificos = []
    for candidato in candidatos:
        candidato_norm = _normalizar(candidato)
        if candidato_norm == gestor_norm:
            continue
        if candidato_norm.startswith(gestor_norm):
            resto = candidato_norm[len(gestor_norm):]
            if resto and not resto[0].isalnum():
                mais_especificos.append(candidato)
    if len(mais_especificos) == 1:
        return mais_especificos[0]
    return None


def _com_expansao(gestor: Optional[str], candidatos: List[str]) -> Optional[str]:
    """`gestor` já expandido para a entrada mais específica, quando existe
    exatamente uma. Aplicado a TODOS os caminhos de aceitação de
    `resolver_responsavel` -- um código de gestor lido sozinho ("GR5", ou
    "6R05" corrigido para "GR5") tem de sair na planilha como a
    identificação completa cadastrada ("GR5 - DIEGO"), venha ele de um
    match exato, aproximado ou de um prefixo."""
    if not gestor:
        return gestor
    return _expandir_para_entrada_mais_especifica(gestor, candidatos) or gestor


def resolver_responsavel(
    texto_ocr: Optional[str],
    candidatos_gestores: List[str],
    limiar_minimo: float = LIMIAR_MINIMO_PADRAO,
    margem_ambiguidade: float = MARGEM_AMBIGUIDADE_PADRAO,
) -> ResultadoResponsavel:
    """
    Resolve o campo RESPONSÁVEL contra a base de gestores. Nunca inventa
    gestor -- sem correspondência confiável, devolve REVISAO
    (SEM_CORRESPONDENCIA/AMBIGUA), preservando o texto original.

    Se houver texto residual depois do gestor (ex.: um auxiliar de
    portaria anotado junto, "GR3 - DIANA - ESLEANE"), esse texto é usado
    só para NÃO contaminar a identificação do gestor -- é descartado, não
    reconhecido nem devolvido (o resultado final não usa o nome do
    auxiliar).
    """
    candidatos_gestores = [str(c).strip() for c in candidatos_gestores]
    resultado_completo = buscar_correspondencia(texto_ocr, candidatos_gestores, limiar_minimo, margem_ambiguidade)

    if resultado_completo.status in ("VAZIO", "SEM_CANDIDATOS"):
        return ResultadoResponsavel(texto_ocr or "", None, resultado_completo.status)

    # Um match EXATO do texto INTEIRO já é a melhor confirmação possível --
    # nada de mais específico pode existir, então nem tenta separar um
    # texto residual (ex.: "GR3 - DIANA" não deve virar gestor="GR3" nunca).
    if resultado_completo.status == "EXATA":
        gestor_confirmado = _com_expansao(resultado_completo.valor_sugerido, candidatos_gestores)
        return ResultadoResponsavel(
            texto_original=texto_ocr,
            gestor_confirmado=gestor_confirmado,
            status="EXATA",
            similaridade=resultado_completo.similaridade,
            # Expandir "GR5" -> "GR5 - DIEGO" É uma normalização do campo
            # (o texto sai da planilha diferente do que o OCR leu), então
            # a Observação precisa registrar isso.
            houve_normalizacao=_normalizar(gestor_confirmado) != _normalizar(texto_ocr),
        )

    # Para qualquer outro resultado do texto inteiro (APROXIMADA, AMBIGUA
    # ou SEM_CORRESPONDENCIA), tenta separar um possível texto residual
    # (ex.: nome de auxiliar) para não deixar isso atrapalhar a
    # identificação do gestor. Só corta no separador gestor/residual
    # (nunca em espaço simples: nome composto não é gestor+residual).
    partes = [p.strip() for p in _RE_SEPARADOR_AUXILIAR.split(str(texto_ocr)) if p.strip()]
    if len(partes) >= 2:
        # Prefixos do mais longo para o mais curto -- "GR3 - DIANA" (mais
        # específico) sempre tem prioridade sobre "GR3" sozinho. Aceita o
        # PRIMEIRO prefixo que resolver com confiança (exato OU
        # aproximado -- buscar_correspondencia já barra ambiguidade/baixa
        # similaridade); se a resolução for só um código curto com mais de
        # uma expansão possível, essa tentativa não é confiável o
        # suficiente e o laço continua para um prefixo mais curto.
        for tamanho_prefixo in range(len(partes) - 1, 0, -1):
            prefixo = " - ".join(partes[:tamanho_prefixo])
            resultado_prefixo = buscar_correspondencia(prefixo, candidatos_gestores, limiar_minimo, margem_ambiguidade)
            if resultado_prefixo.status not in ("EXATA", "APROXIMADA"):
                continue

            gestor_confirmado = _com_expansao(resultado_prefixo.valor_sugerido, candidatos_gestores)

            return ResultadoResponsavel(
                texto_original=texto_ocr,
                gestor_confirmado=gestor_confirmado,
                status=resultado_prefixo.status,
                similaridade=resultado_prefixo.similaridade,
                houve_normalizacao=True,  # o campo foi reestruturado (texto residual descartado)
            )

    # Nenhum prefixo confiável encontrado: usa o resultado do texto inteiro
    # (aproximado, se houver; senão REVISAO) -- nunca inventa nada.
    if resultado_completo.status == "APROXIMADA":
        return ResultadoResponsavel(
            texto_original=texto_ocr,
            gestor_confirmado=_com_expansao(resultado_completo.valor_sugerido, candidatos_gestores),
            status="APROXIMADA",
            similaridade=resultado_completo.similaridade,
            houve_normalizacao=True,
        )

    return ResultadoResponsavel(
        texto_ocr, None, resultado_completo.status, resultado_completo.similaridade
    )
