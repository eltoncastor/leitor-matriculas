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

# ---------------------------------------------------------------------------
# Reconhecimento ESTRUTURAL da família "negado"
#
# A base de motivos é hoje uma lista FECHADA de 7 valores, e o único
# sinônimo da família que sobrou nela é o próprio "HORÁRIO NEGADO". Isso
# quebrou a comparação de texto INTEIRO: o que está escrito na folha é
# quase sempre a abreviação ("Negado", "H.v. Nigado"), curta, contra um
# candidato longo -- a similaridade despenca por diferença de TAMANHO, não
# por falta de evidência ("Negade" x "HORÁRIO NEGADO" = 0.50).
#
# A saída NÃO é baixar o limiar global (isso afrouxaria também RH/ADM/
# ARMÁRIOS/...), e sim olhar a ESTRUTURA do que foi lido:
#
#   1. o texto é quebrado em tokens; procura-se o token que carrega o
#      NÚCLEO da expressão ("NEGADO"/"NEGADA") -- o "H."/"H.V." é só a
#      abreviação de "horário" e vira evidência auxiliar, não o alvo;
#   2. o token é passado por uma tabela FECHADA de confusões reais de OCR
#      manuscrito (dígito lido no lugar de letra, n/v/w/m cursivos, o "d"
#      quebrado em "ol"/"cl") -- nenhuma letra é inventada, só se desfaz
#      uma troca conhecida;
#   3. a decisão exige EVIDÊNCIA COMBINADA (nunca um único critério
#      frouxo): similaridade alta sozinha, OU similaridade média mais um
#      segundo critério independente -- o esqueleto de consoantes N-G-D
#      da palavra, ou a presença da abreviação de "horário" antes dela;
#   4. e, em qualquer caso, a evidência da família tem de ganhar por
#      margem clara da melhor similaridade contra os motivos de FORA da
#      família. É essa checagem que impede "RH", "ADM", "ARMÁRIOS",
#      "FOLGA FIXA", "ESQUECEU CRACHÁ" e "TREINAMENTO" de serem sugados
#      para cá.
#
# Os limiares foram calibrados contra os textos reais de OCR das folhas
# fotografadas E contra um conjunto de controles negativos (os outros 6
# motivos e suas deformações, nomes de gestor, texto impresso do
# formulário): o pior controle negativo pontua 0.615 SEM nenhum critério
# secundário, abaixo de qualquer combinação aceita aqui.
# ---------------------------------------------------------------------------

_NUCLEOS_FAMILIA = ("NEGADO", "NEGADA")

# Dígito lido no lugar de letra (o caso real "NE6400" = "NEGADO" com
# 6->G, 4->A, 0->O).
_DIGITO_LIDO_COMO_LETRA = {
    "0": "O", "1": "I", "3": "E", "4": "A", "5": "S", "6": "G", "8": "B",
}
# Letras cursivas confundidas entre si. Restrito ao que foi de fato
# observado nas folhas ("vigado", "Wegado", "Migado" para "negado").
_LETRAS_EQUIVALENTES = {"V": "N", "W": "N", "M": "N", "L": "I", "J": "I"}
# "d" manuscrito que o OCR quebrou em dois caracteres ("Negaola" = NEGADA,
# "vigaolo" = NEGADO).
_DIGRAFOS_DE_D = (("OL", "D"), ("CL", "D"))

# Abreviação de "horário" antes do núcleo: "H.", "H.V.", "Hiv", "Hev"...
# (uma letra H seguida de no máximo duas letras, tudo num token curto).
_RE_ABREVIACAO_HORARIO = re.compile(r"^H[A-Z]{0,2}$")

# Esqueleto de consoantes de NEGADO/NEGADA, na ordem. Critério secundário
# INDEPENDENTE da similaridade: "NEGOCIO" e "VENDEDOR" (controles
# negativos) não o satisfazem; "NGGAND" e "Negoide" (leituras reais)
# satisfazem.
_ESQUELETO_FAMILIA = ("N", "G", "D")

# Faixa de tamanho plausível para o núcleo lido (NEGADO/NEGADA têm 6).
# Barra tokens curtos demais para carregarem a palavra ("NADA", "NAO").
_TAMANHO_MINIMO_NUCLEO = 5
_TAMANHO_MAXIMO_NUCLEO = 9

# Similaridade que basta SOZINHA como evidência.
LIMIAR_FAMILIA_FORTE = 0.75
# Similaridade que só vale ACOMPANHADA de um segundo critério (esqueleto
# de consoantes ou abreviação de "horário").
LIMIAR_FAMILIA_COMBINADO = 0.60
# Quanto a evidência da família precisa ganhar dos motivos de fora dela.
MARGEM_SOBRE_OUTROS_MOTIVOS = 0.10


def _desfazer_confusoes_ocr(texto: str) -> str:
    """Aplica a tabela FECHADA de confusões de OCR manuscrito. Nunca
    inventa caractere: só troca um caractere por outro que é sabidamente
    a mesma forma escrita lida de outro jeito."""
    texto = "".join(_DIGITO_LIDO_COMO_LETRA.get(c, c) for c in _normalizar(texto))
    for lido, real in _DIGRAFOS_DE_D:
        texto = texto.replace(lido, real)
    return "".join(_LETRAS_EQUIVALENTES.get(c, c) for c in texto)


def _tem_esqueleto_da_familia(token: str) -> bool:
    """True se as consoantes N, G e D aparecem nessa ordem no token."""
    restante = iter(token)
    return all(consoante in restante for consoante in _ESQUELETO_FAMILIA)


def avaliar_evidencia_familia_negado(texto_ocr: Optional[str]):
    """
    Mede a evidência ESTRUTURAL de que `texto_ocr` é uma leitura
    deformada de "HORÁRIO NEGADO" (ver bloco de comentário acima).

    Devolve `(similaridade, criterio_secundario, token_reconhecido)`:
    `similaridade` é 0.0 quando nenhum token tem sequer a forma de um
    núcleo da família, e `criterio_secundario` diz se algum critério
    independente da similaridade corroborou a leitura. Não decide nada
    sozinha -- quem decide é `resolver_motivo`, que ainda compara isto
    com os motivos de fora da família.
    """
    tokens = [t for t in re.split(r"[^0-9A-Za-zÀ-ÿ]+", _normalizar(texto_ocr)) if t]
    if not tokens:
        return 0.0, False, None

    convertidos = [_desfazer_confusoes_ocr(t) for t in tokens]
    tem_abreviacao_horario = any(
        len(t) <= 3 and _RE_ABREVIACAO_HORARIO.match(t) for t in convertidos
    )

    melhor_similaridade = 0.0
    melhor_token = None
    melhor_esqueleto = False
    for original, convertido in zip(tokens, convertidos):
        if not (_TAMANHO_MINIMO_NUCLEO <= len(convertido) <= _TAMANHO_MAXIMO_NUCLEO):
            continue
        # O núcleo sempre COMEÇA pela consoante N (ou por uma letra que o
        # OCR confunde com ela). Sem isso, qualquer palavra de 5-9 letras
        # entraria na disputa.
        if not convertido.startswith("N"):
            continue
        similaridade = max(
            difflib.SequenceMatcher(None, convertido, nucleo).ratio()
            for nucleo in _NUCLEOS_FAMILIA
        )
        if similaridade > melhor_similaridade:
            melhor_similaridade = similaridade
            melhor_token = original
            melhor_esqueleto = _tem_esqueleto_da_familia(convertido)

    if melhor_token is None:
        return 0.0, False, None
    return melhor_similaridade, (melhor_esqueleto or tem_abreviacao_horario), melhor_token


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
        fora_da_familia = [c for c in candidatos_motivos if c not in familia]
        sim_fora = _melhor_similaridade(alvo, fora_da_familia)

        # (a) Texto INTEIRO parecido com uma entrada da família. Continua
        # sendo o caminho preferencial quando a base ainda tem sinônimos
        # cadastrados (ex.: "NEGADO" como motivo próprio).
        sim_familia = _melhor_similaridade(alvo, familia)
        if sim_familia >= limiar_minimo and (sim_familia - sim_fora) >= margem_ambiguidade:
            return ResultadoMotivo(
                texto_ocr, MOTIVO_HORARIO_NEGADO, "NORMALIZADA", sim_familia,
                resultado.segundo_candidato, houve_fallback=True,
            )

        # (b) Reconhecimento ESTRUTURAL do núcleo "NEGADO"/"NEGADA" dentro
        # do texto (ver bloco de comentário acima). É o que recupera a
        # abreviação manuscrita ("Negade", "H.V. vigaolo", "NE6400"), cujo
        # texto INTEIRO nunca chega perto de "HORÁRIO NEGADO" por pura
        # diferença de tamanho.
        sim_nucleo, criterio_secundario, _token = avaliar_evidencia_familia_negado(texto_ocr)
        evidencia_suficiente = sim_nucleo >= LIMIAR_FAMILIA_FORTE or (
            sim_nucleo >= LIMIAR_FAMILIA_COMBINADO and criterio_secundario
        )
        if evidencia_suficiente and (sim_nucleo - sim_fora) >= MARGEM_SOBRE_OUTROS_MOTIVOS:
            return ResultadoMotivo(
                texto_ocr, MOTIVO_HORARIO_NEGADO, "NORMALIZADA", sim_nucleo,
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


# ---------------------------------------------------------------------------
# Código GR (ex.: "GR3", "GR5", "GRL")
#
# Quando o gestor é anotado pelo CÓDIGO, o código é a informação forte da
# célula -- o que vem depois dele costuma ser o nome de quem estava na
# portaria, escrito por cima/ao lado, e sai do OCR irreconhecível
# ("GRS- Lmone", "GR5 -. Eosee"). Comparar o texto INTEIRO contra a base
# nesses casos afunda a similaridade por causa do lixo, e o registro ia
# para REVISAO mesmo com o código legível.
#
# A leitura do código segue exatamente o padrão de
# `validacao/recuperacao_matricula.py`: gera todas as leituras plausíveis
# do caractere do código por uma tabela FECHADA de confusões de OCR, e
# depois PERGUNTA À BASE quais existem. Exatamente uma existe -> aceita;
# duas ou mais -> ambíguo, ninguém escolhe (-> REVISAO). É essa checagem
# contra a base que faz disto evidência, e não palpite: "GRI" (I lido no
# lugar de 1 ou de L) casa com GR1 E com GRL, os dois cadastrados, e por
# isso continua indo para revisão.
# ---------------------------------------------------------------------------

# Só o que é confusão REAL e observada, e só no caractere do código:
# "S" no lugar de "5" (o mesmo par já tratado em
# `ocr_engine.normalizar_matricula`) e a família I/L/1, que é justamente a
# que produz ambiguidade e tem de continuar produzindo.
_LEITURAS_DO_CODIGO = {
    "S": ("5",),
    "I": ("1", "L"),
    "L": ("L", "1"),
    "1": ("1", "L"),
}
# "G" lido como "6" é recorrente ("6R05"); o "R" não tem confusão aceita
# aqui (as leituras esquisitas dele -- "Ghl", "Gkl", "Ge4" -- já são
# resolvidas pela correspondência aproximada normal, sem precisar de
# regra nova).
_RE_CODIGO_GR = re.compile(r"^[G6]R(.)$")


def _ler_codigo_gestor(texto: Optional[str], candidatos: List[str]) -> Optional[str]:
    """
    Lê um código de gestor ("GR3", "GR5", "GRL") no começo de `texto` e
    devolve o candidato correspondente da base, ou None quando não há
    código legível, quando ele não existe na base, ou quando mais de uma
    leitura plausível existe na base (ambíguo -> REVISAO).
    """
    primeiro_token = _normalizar(texto).split()[0] if _normalizar(texto).split() else ""
    primeiro_token = re.split(r"[^0-9A-Z]", primeiro_token)[0]

    correspondencia = _RE_CODIGO_GR.match(primeiro_token)
    if not correspondencia:
        return None

    caractere = correspondencia.group(1)
    leituras = _LEITURAS_DO_CODIGO.get(caractere, (caractere,))

    na_base = []
    for leitura in leituras:
        codigo = f"GR{leitura}"
        for candidato in candidatos:
            if _normalizar(candidato) == codigo and candidato not in na_base:
                na_base.append(candidato)

    if len(na_base) == 1:
        return na_base[0]
    return None  # nenhum código na base, ou mais de um (ambíguo)


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

    # O CÓDIGO GR PREVALECE sobre o texto secundário do OCR: quando o
    # código está legível, ele identifica o gestor sozinho, e o que vier
    # depois dele (nome de auxiliar de portaria, rabisco, lixo) não muda
    # mais nada. Vem DEPOIS das tentativas acima de propósito -- elas
    # podem achar a identificação MAIS ESPECÍFICA ("GR3 - DIANA" inteira,
    # em vez do código "GR3" sozinho), e a maior sequência confiável
    # sempre ganha -- e ANTES da correspondência aproximada do texto
    # inteiro, que é justamente a que se perde quando o lixo depois do
    # código é grande ("GRS- Lmone").
    gestor_por_codigo = _ler_codigo_gestor(texto_ocr, candidatos_gestores)
    if gestor_por_codigo:
        gestor_confirmado = _com_expansao(gestor_por_codigo, candidatos_gestores)
        return ResultadoResponsavel(
            texto_original=texto_ocr,
            gestor_confirmado=gestor_confirmado,
            status="APROXIMADA",
            similaridade=None,
            houve_normalizacao=_normalizar(gestor_confirmado) != _normalizar(texto_ocr),
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
