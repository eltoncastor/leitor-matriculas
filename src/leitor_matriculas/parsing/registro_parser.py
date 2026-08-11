"""
registro_parser.py

Parser espacial: transforma uma lista PLANA de `OCRResult` (texto + confiança
+ bounding box), na ordem em que o OCR encontrou, em uma lista de possíveis
REGISTROS (linhas da tabela da folha), usando somente a posição dos boxes.

Este módulo é intencionalmente independente do PaddleOCR: ele só enxerga a
estrutura `OCRResult` (texto_original, confianca, box), já existente em
`ocr_engine.py`, e não importa nem depende de nada específico do PaddleOCR.
Isso significa que o motor de OCR poderia ser trocado no futuro sem
precisar alterar este arquivo.

O QUE ESTE MÓDULO FAZ:
    1. Ordena os elementos espacialmente (linha a linha, esquerda->direita).
    2. Agrupa os elementos em LINHAS, usando a sobreposição vertical dos
       boxes (não assume que as linhas estão perfeitamente alinhadas).
    3. Tenta localizar a linha de CABEÇALHO da tabela (DATA, HORA, NOME,
       MATRÍCULA, SETOR, MOTIVO, RESPONSÁVEL/GESTOR ou variações), usando
       essa linha para saber a posição x de cada coluna.
    4. Para cada linha de dado (abaixo do cabeçalho), associa cada elemento
       à coluna mais próxima — sem inventar associação quando a distância é
       grande demais para ser confiável (nesse caso, o elemento fica em
       "não associados"). NOME e SETOR são detectados e usados nesta etapa
       só pela geometria (evita que um texto de NOME/SETOR "vaze" para a
       coluna MATRÍCULA/MOTIVO vizinha) — o valor em si é descartado do
       registro logo em seguida (ver requisito funcional definitivo abaixo
       e CAMPOS_IGNORADOS_NA_SAIDA).
    5. Marca cada registro como completo/incompleto (no mínimo a matrícula
       precisa estar presente para ser considerado completo) e informa
       quais campos estão faltando.

REQUISITO FUNCIONAL DEFINITIVO — o que é lido da folha vs. o que é derivado:
    Só DATA, HORA, MATRÍCULA, MOTIVO e RESPONSÁVEL (gestor) são dados
    efetivamente escritos à mão na folha, e por isso são os únicos campos
    que este parser EXPÕE como reconhecidos (`registro.campos`,
    `colunas_detectadas`, `CAMPOS_TODOS`). NOME e SETOR são dados
    DERIVADOS: são obtidos depois, consultando a matrícula na base de
    colaboradores (ver validacao.py / ui.py) — nunca lidos diretamente da
    escrita manuscrita. O parser AINDA localiza a posição das colunas
    "Nome"/"Setor" quando a folha as tiver impressas (só pela geometria,
    para não confundir colunas vizinhas — ver item 4 acima), mas o texto
    capturado ali é sempre descartado de `campos` e preservado em
    `nao_associados` — nunca usado como fonte de nome/setor.

O QUE ESTE MÓDULO NÃO FAZ (fora de escopo desta etapa, de propósito):
    - Não valida a matrícula/gestor/motivo/data/hora contra XLSX ou regras
      de data/hora (isso é `validacao.py` / `tempo_parser.py`).
    - Não normaliza texto (não corrige O->0 etc.) — os textos ficam
      exatamente como o OCR devolveu.
    - Não decide o que fazer com um registro incompleto (isso é revisão
      manual, etapa futura) — só sinaliza.
    - Não lê PDF nem múltiplas páginas — recebe uma lista de OCRResult de
      UMA página/imagem por vez (processar várias páginas é combinar essa
      função com um laço por fora, na etapa de PDF).
"""

import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from leitor_matriculas.ocr.engine import OCRResult


# ---------------------------------------------------------------------------
# Modelo de dados
# ---------------------------------------------------------------------------

@dataclass
class CampoOcr:
    """
    Um elemento de OCR já posicionado, preservando exatamente o texto, a
    confiança e o box originais — nada aqui é alterado ou normalizado.
    """
    texto: str
    confianca: Optional[float]
    box: Optional[List[int]]

    @classmethod
    def de_ocr_result(cls, resultado: OCRResult) -> "CampoOcr":
        return cls(texto=resultado.texto_original, confianca=resultado.confianca, box=resultado.box)


# Nomes de campo que o parser tenta identificar via cabeçalho da tabela.
#
# IMPORTANTE (requisito funcional definitivo): esta lista contém SOMENTE os
# dados efetivamente escritos à mão na folha. "nome" e "setor" NÃO estão
# aqui de propósito — são dados derivados (consulta à matrícula na base de
# colaboradores), nunca reconhecidos por OCR. Ver docstring do módulo.
CAMPOS_TODOS = ["matricula", "gestor", "motivo", "data", "hora"]

# Campo mínimo para um registro ser considerado "completo" nesta etapa. A
# matrícula é o dado mais importante (ver conversas anteriores) — sem ela,
# não há como localizar o colaborador depois.
CAMPO_OBRIGATORIO_PARA_COMPLETO = "matricula"


@dataclass
class Registro:
    """
    Um possível registro (linha da tabela) já reconstruído a partir da
    posição espacial dos elementos de OCR.
    """
    indice: int  # ordem de leitura, de cima para baixo (1, 2, 3, ...)
    campos: Dict[str, CampoOcr] = field(default_factory=dict)
    nao_associados: List[CampoOcr] = field(default_factory=list)
    y_min: int = 0
    y_max: int = 0

    @property
    def completo(self) -> bool:
        """
        Um registro é considerado completo quando tem, no mínimo, a
        matrícula. Este é um critério propositalmente mínimo — não exige
        gestor/motivo/data/hora para não marcar como "incompleto" um
        registro que só teve um campo secundário mal lido pelo OCR.
        """
        return CAMPO_OBRIGATORIO_PARA_COMPLETO in self.campos

    def campos_faltando(self) -> List[str]:
        """Quais dos campos conhecidos não foram identificados nesta linha."""
        return [c for c in CAMPOS_TODOS if c not in self.campos]


@dataclass
class ResultadoParser:
    """Resultado completo de rodar o parser espacial sobre uma página/imagem."""
    cabecalho_detectado: bool
    linha_cabecalho: Optional[List[CampoOcr]]
    colunas_detectadas: Dict[str, int]  # nome do campo -> posição x central da coluna
    registros: List[Registro]
    conteudo_antes_cabecalho: List[CampoOcr]  # títulos, "Filial: ...", etc. (linhas acima do cabeçalho)
    elementos_sem_posicao: List[CampoOcr]  # OCRResult sem box (não puderam ser posicionados)
    linhas_ignoradas: List[List[CampoOcr]] = field(default_factory=list)
    # Linhas abaixo do cabeçalho que NÃO renderam nenhum campo associado
    # (ver PROBLEMA 1) — tipicamente rodapé/assinatura/controle de revisão
    # impressos abaixo da tabela. Preservadas aqui (nunca descartadas
    # silenciosamente), mas fora de `registros`: não são liberações.


# ---------------------------------------------------------------------------
# Cabeçalhos conhecidos (para localizar a linha de cabeçalho da tabela)
#
# Estes nomes vêm diretamente da descrição da folha real (DATA, HORA, NOME,
# MATRÍCULA, SETOR, MOTIVO, RESPONSÁVEL pela liberação) — nada aqui foi
# inventado. Se a folha real usar um rótulo diferente, ajuste as listas
# abaixo.
#
# NOME e SETOR continuam aqui DE PROPÓSITO, mesmo não sendo campos que o
# requisito funcional pede para "ler" da folha (são derivados da matrícula
# — ver docstring do módulo). Eles ficam na detecção só pela GEOMETRIA: se
# a folha física tiver essas colunas impressas entre HORA/MATRÍCULA e
# MATRÍCULA/MOTIVO, conhecer a posição x delas é o que impede um texto de
# NOME ou SETOR de "vazar" e ser erroneamente absorvido pela coluna
# MATRÍCULA ou MOTIVO vizinha (a associação é por menor distância — sem
# essa "parede", o vazamento acontece). Por isso, o VALOR de nome/setor é
# sempre descartado de `campos` logo depois da associação (ver
# CAMPOS_IGNORADOS_NA_SAIDA e `parse_registros`) — só a posição é usada.
# ---------------------------------------------------------------------------

CABECALHOS_CONHECIDOS = {
    "data": ["data"],
    "hora": ["hora", "horario", "horário"],
    "nome": ["nome", "colaborador"],
    "matricula": ["matricula", "matrícula"],
    "setor": ["setor", "departamento"],
    "motivo": ["motivo"],
    "gestor": ["responsavel", "responsável", "gestor", "liberado por", "autorizado por"],
}

# Campos que o parser DETECTA geometricamente (para não deixar vazar para
# colunas vizinhas — ver comentário acima) mas NUNCA expõe como campo
# reconhecido: nem em `registro.campos`, nem em `colunas_detectadas`. O
# texto correspondente não é descartado — vai para `nao_associados`, como
# qualquer elemento sem campo reconhecido.
CAMPOS_IGNORADOS_NA_SAIDA = {"nome", "setor"}

# Uma linha só é considerada "cabeçalho" se tiver pelo menos esta
# quantidade de rótulos conhecidos reconhecidos nela — uma única palavra
# batendo por coincidência (ex.: um MOTIVO manuscrito que por acaso é
# "Nome") não deve ser suficiente para confundir a linha com o cabeçalho.
MINIMO_COLUNAS_PARA_CABECALHO = 2

# Campos "estruturados" -- MATRÍCULA/DATA/HORA têm formato reconhecível
# (dígitos, ver _PARECE_DATA/_PARECE_HORA) ou identidade numérica clara,
# ao contrário de MOTIVO/GESTOR, que são texto livre sem filtro de
# formato algum. Uma linha cujo ÚNICO campo associado seja motivo e/ou
# gestor (nenhum campo estruturado) não tem nenhuma evidência real de ser
# uma posição de liberação -- ver verificação em parse_registros (achado
# real: texto de rodapé como "Última Revisão:" caindo, por coincidência de
# posição, dentro da coluna RESPONSÁVEL, sem nenhum outro campo por perto).
CAMPOS_ESTRUTURADOS_MINIMOS = {"matricula", "data", "hora"}

# Quantidade de posições de liberação esperadas por folha (formulário
# impresso padronizado — ver verificar_contagem_posicoes). Usada só como
# RESTRIÇÃO DE VALIDAÇÃO (avisar quando divergir) — nunca para fabricar ou
# descartar registro algum.
POSICOES_ESPERADAS_POR_FOLHA = 8

# ---------------------------------------------------------------------------
# Filtro de plausibilidade para as colunas DATA/HORA (PROBLEMA 1 — texto
# impresso não pode virar dado).
#
# Evidência real (teste.jpg): texto de rodapé impresso ("Supervisor de
# Prevenção de Perdas", "FOR.PRP.0017") caiu espacialmente perto o
# suficiente das colunas DATA/HORA para ser associado a elas pelo
# algoritmo guloso de menor distância — produzindo registros fantasma.
#
# Este filtro é DELIBERADAMENTE frouxo (não é a validação completa de
# tempo_parser — só uma checagem de FORMATO, não de calendário/hora
# válidos) e se aplica SOMENTE às colunas "data"/"hora": um candidato só é
# aceito nessas colunas se tiver a estrutura mínima de dígito-separador-
# dígito (data) ou dígito-separador-dígito (hora). Texto impresso comum
# (títulos, códigos de formulário, frases) não tem essa estrutura e é
# rejeitado — some para `nao_associados`, nunca cria um dado falso.
# MATRÍCULA/MOTIVO/GESTOR continuam sem filtro de formato nesta fase
# (texto livre; ver PROBLEMA 3/4, que tratam esses campos separadamente).
# O ano é OPCIONAL aqui de propósito: este é só um filtro de FORMATO (dia.
# mês[.ano]), não a validação completa -- uma data sem ano ainda é
# estruturalmente uma data (e será corretamente rejeitada depois, na
# validação de verdade, por tempo_parser.interpretar_data, que exige ano).
# Exigir o ano já neste filtro rejeitaria também esse caso legítimo antes
# mesmo de chegar à validação certa para ele.
# O separador APAGADO pela caneta/OCR ("07 53" no lugar de "07:53") também
# é aceito na coluna HORA, mas com uma exigência extra que o separador
# explícito não precisa ter: nesse caso o texto INTEIRO tem de ser só os
# dois blocos de dígitos (^...$). Sem essa âncora, qualquer frase impressa
# com dois números soltos ("FOR PRP 0017 12 34") voltaria a passar pelo
# filtro — que é exatamente o que ele existe para barrar.
_PARECE_DATA = re.compile(r"\d{1,2}\s*[./\-]\s*\d{1,2}(?:\s*[./\-]\s*\d{2,4})?")
_PARECE_HORA = re.compile(r"\d{1,2}\s*[:hH.]\s*\d{2}|^\s*\d{1,2}\s+\d{2}\s*$")

_FILTROS_DE_FORMATO_POR_COLUNA = {
    "data": _PARECE_DATA,
    "hora": _PARECE_HORA,
}


def _passa_no_filtro_de_formato(nome_campo: str, texto: str) -> bool:
    """
    True se `texto` pode, na estrutura, pertencer à coluna `nome_campo` —
    ou se essa coluna não tem filtro de formato definido (todas exceto
    data/hora, nesta fase).
    """
    padrao = _FILTROS_DE_FORMATO_POR_COLUNA.get(nome_campo)
    if padrao is None:
        return True
    return bool(padrao.search(texto or ""))


# ---------------------------------------------------------------------------
# Helpers geométricos
# ---------------------------------------------------------------------------

def _centro_vertical(box: List[int]) -> float:
    return (box[1] + box[3]) / 2


def _centro_horizontal(box: List[int]) -> float:
    return (box[0] + box[2]) / 2


def _sobreposicao_vertical(y1a: float, y2a: float, y1b: float, y2b: float) -> float:
    """
    Fração de sobreposição vertical entre dois intervalos [y1,y2], relativa
    à altura do MENOR dos dois. 0 = não se sobrepõem; 1 = um está
    inteiramente contido no outro verticalmente.
    """
    intersecao = max(0.0, min(y2a, y2b) - max(y1a, y1b))
    menor_altura = min(y2a - y1a, y2b - y1b)
    if menor_altura <= 0:
        return 0.0
    return intersecao / menor_altura


def _normalizar_texto(texto) -> str:
    """Minúsculo, sem acento, sem espaço nas pontas — só para comparar rótulos de cabeçalho."""
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


# ---------------------------------------------------------------------------
# 1) Ordenação espacial
# ---------------------------------------------------------------------------

def ordenar_elementos(elementos: List[CampoOcr]) -> List[CampoOcr]:
    """
    Devolve os elementos em ordem de leitura (linha a linha, de cima para
    baixo; dentro de cada linha, da esquerda para a direita) — não importa
    a ordem em que o OCR os encontrou originalmente.

    Elementos sem box (posição desconhecida) vão para o final, na ordem em
    que apareceram.
    """
    com_box = [e for e in elementos if e.box is not None]
    sem_box = [e for e in elementos if e.box is None]

    linhas = agrupar_em_linhas(com_box)
    ordenados = [elemento for linha in linhas for elemento in linha]
    return ordenados + sem_box


# ---------------------------------------------------------------------------
# 2) Agrupamento em linhas
# ---------------------------------------------------------------------------

# Achado real (entrada/pdf/teste.pdf, página 3): o agrupamento original
# comparava cada candidato só contra a faixa [y_min, y_max] JÁ ACUMULADA da
# linha aberta -- e essa faixa só cresce (nunca encolhe). Numa página com
# células manuscritas altas (boxes de OCR de ~100-135px) e linhas de tabela
# espaçadas por ~90px, isso permite um "encadeamento": um elemento da
# própria linha 1 (alto) empurra a faixa acumulada para baixo o bastante
# para que um elemento da linha 2 tenha >=40% de sobreposição com essa
# faixa JÁ EXPANDIDA — mesmo sem ter absolutamente nenhuma sobreposição
# direta com o primeiro elemento da linha 1. O resultado observado: 4
# linhas reais de liberação (12:32, 12:44, 13:33, 14:07) colapsaram em 1
# única "linha" de 20 elementos, e a página perdeu 3 das 8 posições reais.
#
# Correção: além da sobreposição com a faixa acumulada, exige-se que o topo
# (y1) do candidato não esteja mais longe do que uma TOLERÂNCIA do y1 do
# elemento que ABRIU a linha (esse y1 de abertura nunca muda, ao contrário
# da faixa acumulada) — trava o encadeamentos sem impedir que os vários
# campos de uma mesma linha real (que abrem dentro de uma janela pequena de
# y1, mesmo com célula alta) continuem se agrupando normalmente. A
# tolerância é proporcional à MEDIANA de altura dos elementos da própria
# página (não um pixel fixo), então se adapta à resolução/zoom da foto.
FATOR_TOLERANCIA_ABERTURA_LINHA = 1.0


def agrupar_em_linhas(
    elementos: List[CampoOcr], limiar_sobreposicao_vertical: float = 0.4
) -> List[List[CampoOcr]]:
    """
    Agrupa elementos (que já têm box) em linhas, usando a sobreposição
    vertical dos boxes — não presume que os elementos de uma linha têm
    exatamente o mesmo y (folhas fotografadas raramente estão 100% retas).

    Algoritmo: ordena os elementos por y1 (topo do box) e, sequencialmente,
    decide se cada elemento pertence à última linha aberta OU se abre uma
    linha nova. Um elemento só entra na linha aberta se DUAS condições
    baterem:
        1. sobreposição vertical com a faixa [y_min, y_max] já acumulada
           da linha for >= `limiar_sobreposicao_vertical` (comportamento
           original);
        2. seu y1 não estiver mais longe do que uma tolerância (proporcional
           à altura típica dos elementos da página) do y1 do elemento que
           ABRIU a linha -- trava o "encadeamento" pela faixa acumulada
           (ver comentário acima) sem depender de nenhuma coordenada fixa.

    Dentro de cada linha, os elementos ficam ordenados da esquerda para a
    direita (por x1).

    Elementos sem box são ignorados aqui (ver `ordenar_elementos` /
    `parse_registros`, que os separam antes de chamar esta função).
    """
    elementos_com_box = [e for e in elementos if e.box is not None]
    if not elementos_com_box:
        return []

    altura_mediana_pagina = statistics.median(e.box[3] - e.box[1] for e in elementos_com_box)
    tolerancia_abertura = altura_mediana_pagina * FATOR_TOLERANCIA_ABERTURA_LINHA

    ordenados = sorted(elementos_com_box, key=lambda e: e.box[1])

    linhas: List[List[CampoOcr]] = []
    faixas: List[Tuple[float, float]] = []  # (y_min, y_max) de cada linha aberta
    aberturas: List[float] = []  # y1 do elemento que abriu cada linha (fixo, nunca muda)

    for elemento in ordenados:
        y1, y2 = elemento.box[1], elemento.box[3]

        if linhas:
            y_min_atual, y_max_atual = faixas[-1]
            sobreposicao = _sobreposicao_vertical(y1, y2, y_min_atual, y_max_atual)
            distancia_da_abertura = y1 - aberturas[-1]
        else:
            sobreposicao = 0.0
            distancia_da_abertura = 0.0

        pertence_a_linha_atual = (
            linhas
            and sobreposicao >= limiar_sobreposicao_vertical
            and distancia_da_abertura <= tolerancia_abertura
        )

        if pertence_a_linha_atual:
            linhas[-1].append(elemento)
            y_min_atual, y_max_atual = faixas[-1]
            faixas[-1] = (min(y_min_atual, y1), max(y_max_atual, y2))
        else:
            linhas.append([elemento])
            faixas.append((y1, y2))
            aberturas.append(y1)

    # Ordena cada linha da esquerda para a direita
    for linha in linhas:
        linha.sort(key=lambda e: e.box[0])

    return linhas


# ---------------------------------------------------------------------------
# 3) Localização da linha de cabeçalho
# ---------------------------------------------------------------------------

def _detectar_linha_cabecalho(
    linhas: List[List[CampoOcr]],
) -> Tuple[Optional[int], Dict[str, int]]:
    """
    Procura, entre as linhas já agrupadas, qual delas é o cabeçalho da
    tabela (a que tem mais rótulos batendo com CABECALHOS_CONHECIDOS).

    Devolve (índice da linha na lista `linhas`, {nome_campo: x_central})
    ou (None, {}) se nenhuma linha parecer um cabeçalho o suficiente
    (ver MINIMO_COLUNAS_PARA_CABECALHO).

    Em caso de mais de uma linha plausível, escolhe a de cima (a primeira),
    e, entre elas, a que tiver mais colunas reconhecidas.
    """
    melhor_indice: Optional[int] = None
    melhor_colunas: Dict[str, int] = {}
    melhor_quantidade = 0

    for indice, linha in enumerate(linhas):
        colunas: Dict[str, int] = {}
        for elemento in linha:
            texto_normalizado = _normalizar_texto(elemento.texto)
            for nome_campo, rotulos in CABECALHOS_CONHECIDOS.items():
                if nome_campo in colunas:
                    continue  # já achou essa coluna nesta linha
                # Comparação por "contém", não por igualdade exata: a folha
                # real usa rótulos em frase completa (ex.: cabeçalho
                # impresso "RESPONSÁVEL PELA AUTORIZAÇÃO", que o OCR ainda
                # pode entregar com pequeno ruído no final, tipo
                # "RESPONSÁVEL PELA AUTORIZAÇT") — uma comparação de
                # igualdade exata contra só "responsavel" nunca bateria, e
                # a coluna do responsável simplesmente não seria detectada.
                # Continua seguro porque MINIMO_COLUNAS_PARA_CABECALHO exige
                # várias colunas batendo na mesma linha antes de aceitar
                # como cabeçalho — um "contém" isolado não basta sozinho.
                if any(rotulo in texto_normalizado for rotulo in rotulos):
                    colunas[nome_campo] = int(_centro_horizontal(elemento.box))
                    break

        if len(colunas) >= MINIMO_COLUNAS_PARA_CABECALHO and len(colunas) > melhor_quantidade:
            melhor_indice = indice
            melhor_colunas = colunas
            melhor_quantidade = len(colunas)
            break  # a primeira linha (mais acima) que atinge o mínimo já basta

    return melhor_indice, melhor_colunas


# ---------------------------------------------------------------------------
# 4) Associação dos campos de uma linha de dados às colunas do cabeçalho
# ---------------------------------------------------------------------------

def _distancia_maxima_padrao(colunas: Dict[str, int]) -> float:
    """
    Calcula uma distância horizontal máxima razoável para considerar um
    elemento pertencente a uma coluna, com base no espaçamento médio entre
    colunas vizinhas do cabeçalho detectado.

    Isso evita "inventar" associação para um elemento que está espacialmente
    longe de qualquer coluna conhecida (por exemplo, um texto solto entre
    registros) — nesses casos, o elemento fica em `nao_associados` em vez
    de ser forçado para a coluna mais próxima, não importa a distância.
    """
    posicoes = sorted(colunas.values())
    if len(posicoes) < 2:
        return float("inf")  # só uma coluna: não há como estimar espaçamento, não filtra por distância

    espacamentos = [b - a for a, b in zip(posicoes, posicoes[1:])]
    media = sum(espacamentos) / len(espacamentos)
    return media * 0.75  # margem: até 75% do espaçamento médio entre colunas


def _associar_campos_na_linha(
    elementos: List[CampoOcr], colunas: Dict[str, int], distancia_maxima: float
) -> Tuple[Dict[str, CampoOcr], List[CampoOcr]]:
    """
    Associa cada elemento da linha à coluna (campo) mais próxima, com um
    limite de distância para não forçar associações implausíveis.

    Usa um algoritmo guloso simples: monta todos os pares (elemento,
    coluna, distância), ordena pela menor distância, e vai confirmando
    pares enquanto elemento e coluna ainda estiverem livres. Suficiente
    para uma tabela de poucas colunas (não precisa de um algoritmo de
    correspondência ótima mais sofisticado).
    """
    if not colunas:
        return {}, list(elementos)

    candidatos = []
    for elemento in elementos:
        if elemento.box is None:
            continue
        centro_x = _centro_horizontal(elemento.box)
        for nome_campo, x_coluna in colunas.items():
            distancia = abs(centro_x - x_coluna)
            if distancia > distancia_maxima:
                continue
            # PROBLEMA 1: um elemento só é candidato às colunas data/hora se
            # tiver, na estrutura, cara de data/hora — barra texto impresso
            # que por coincidência caiu perto dessas colunas (ver comentário
            # em _PARECE_DATA/_PARECE_HORA). Não afeta as demais colunas.
            if not _passa_no_filtro_de_formato(nome_campo, elemento.texto):
                continue
            candidatos.append((distancia, nome_campo, elemento))

    candidatos.sort(key=lambda c: c[0])

    campos: Dict[str, CampoOcr] = {}
    elementos_usados = set()
    for _, nome_campo, elemento in candidatos:
        if nome_campo in campos:
            continue
        if id(elemento) in elementos_usados:
            continue
        campos[nome_campo] = elemento
        elementos_usados.add(id(elemento))

    nao_associados = [e for e in elementos if id(e) not in elementos_usados]
    return campos, nao_associados


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def parse_registros(
    resultados: List[OCRResult], limiar_sobreposicao_vertical: float = 0.4
) -> ResultadoParser:
    """
    Ponto de entrada do parser espacial.

    Recebe a lista PLANA de `OCRResult` de uma página/imagem (na ordem que
    o OCR encontrou, não importa) e devolve um `ResultadoParser` com os
    possíveis registros já reconstruídos a partir da posição dos boxes.

    Não assume nenhuma quantidade fixa de registros — o número de linhas
    de dados (e, portanto, de registros) é sempre determinado pela
    estrutura espacial real dos elementos recebidos.
    """
    elementos = [CampoOcr.de_ocr_result(r) for r in resultados]

    elementos_sem_posicao = [e for e in elementos if e.box is None]
    elementos_com_posicao = [e for e in elementos if e.box is not None]

    linhas = agrupar_em_linhas(elementos_com_posicao, limiar_sobreposicao_vertical)

    idx_cabecalho, colunas = _detectar_linha_cabecalho(linhas)

    if idx_cabecalho is None:
        # Sem cabeçalho identificado: não há como saber quais linhas são
        # título/rodapé e quais são dados, então cada linha agrupada vira
        # um registro (sem associação de campo nenhuma — tudo em
        # `nao_associados` — em vez de adivinhar).
        conteudo_antes_cabecalho: List[CampoOcr] = []
        linha_cabecalho = None
        linhas_de_dados = linhas
    else:
        conteudo_antes_cabecalho = [
            elemento for linha in linhas[:idx_cabecalho] for elemento in linha
        ]
        linha_cabecalho = linhas[idx_cabecalho]
        linhas_de_dados = linhas[idx_cabecalho + 1 :]

    distancia_maxima = _distancia_maxima_padrao(colunas) if colunas else float("inf")

    registros: List[Registro] = []
    linhas_ignoradas: List[List[CampoOcr]] = []
    indice = 0
    for linha in linhas_de_dados:
        # `colunas` (com nome/setor incluídos) é usado aqui só pela
        # geometria -- ver comentário em CAMPOS_IGNORADOS_NA_SAIDA. Logo
        # depois, nome/setor são retirados de `campos` e preservados em
        # `nao_associados`, nunca expostos como campo reconhecido.
        campos, nao_associados = _associar_campos_na_linha(linha, colunas, distancia_maxima)
        for nome_campo_ignorado in CAMPOS_IGNORADOS_NA_SAIDA:
            elemento_ignorado = campos.pop(nome_campo_ignorado, None)
            if elemento_ignorado is not None:
                nao_associados.append(elemento_ignorado)

        if colunas and not (campos.keys() & CAMPOS_ESTRUTURADOS_MINIMOS):
            # PROBLEMA 1: só entra aqui quando HÁ um cabeçalho detectado
            # (colunas conhecidas) e a linha não tem NENHUM campo
            # estruturado (matrícula/data/hora) associado -- mesmo que
            # motivo e/ou gestor (texto livre, sem filtro de formato)
            # tenham "batido" por coincidência de posição. Isso cobre tanto
            # o caso de zero campos quanto o achado real de uma linha de
            # rodapé onde só o texto caiu dentro da coluna RESPONSÁVEL (ex.:
            # "Última Revisão:" perto da coluna GESTOR): sem nenhum indício
            # estrutural de liberação, não é uma posição de liberação.
            # Preserva o conteúdo (nunca descarta em silêncio), mas NÃO
            # cria um Registro fantasma a partir dele.
            #
            # Sem cabeçalho detectado (colunas vazio), o comportamento
            # continua o de sempre: cada linha vira um Registro incompleto
            # (campos={}) em vez de desaparecer -- sem coordenadas de
            # coluna não há como distinguir "não é liberação" de "é
            # liberação, só não deu pra posicionar campo nenhum", então o
            # mais seguro é mostrar tudo para revisão manual, nunca sumir
            # com a linha.
            linhas_ignoradas.append(linha)
            continue

        indice += 1
        ys = [e.box[1] for e in linha] + [e.box[3] for e in linha]
        registros.append(
            Registro(
                indice=indice,
                campos=campos,
                nao_associados=nao_associados,
                y_min=int(min(ys)),
                y_max=int(max(ys)),
            )
        )

    colunas_detectadas = {
        nome_campo: x for nome_campo, x in colunas.items()
        if nome_campo not in CAMPOS_IGNORADOS_NA_SAIDA
    }

    return ResultadoParser(
        cabecalho_detectado=idx_cabecalho is not None,
        linha_cabecalho=linha_cabecalho,
        colunas_detectadas=colunas_detectadas,
        registros=registros,
        conteudo_antes_cabecalho=conteudo_antes_cabecalho,
        elementos_sem_posicao=elementos_sem_posicao,
        linhas_ignoradas=linhas_ignoradas,
    )


# ---------------------------------------------------------------------------
# PROBLEMA 2 — 8 posições esperadas por folha, como restrição de validação
# ---------------------------------------------------------------------------

def verificar_contagem_posicoes(
    quantidade_encontrada: int, esperado: int = POSICOES_ESPERADAS_POR_FOLHA
) -> Optional[str]:
    """
    Compara a quantidade de posições de liberação reconhecidas nesta
    página contra o esperado (ver POSICOES_ESPERADAS_POR_FOLHA). NÃO
    fabrica nem descarta registro nenhum — só devolve uma mensagem de
    alerta quando a contagem diverge, para quem orquestra (ui.py) decidir
    como mostrar. Devolve None quando a contagem bate exatamente.
    """
    if quantidade_encontrada == esperado:
        return None
    return (
        f"esperava {esperado} posições de liberação nesta página, "
        f"foram reconhecidas {quantidade_encontrada}"
    )
