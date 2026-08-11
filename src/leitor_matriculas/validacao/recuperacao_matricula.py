"""
recuperacao_matricula.py

Recuperação CONTEXTUAL da matrícula quando o OCR entrega caracteres que
não são dígitos.

REQUISITO: a matrícula final só pode conter dígitos (`0-9`). Mas os
caracteres estranhos NÃO devem ser simplesmente apagados -- eles
costumam SER um dígito que o OCR leu errado, e apagá-los mudaria a
matrícula (ex.: "1954+" com o "+" removido viraria "1954", uma matrícula
de 4 dígitos diferente e possivelmente de outra pessoa).

Caso real observado nas folhas: o "7" manuscrito (cortado, à europeia)
sai do OCR como "+".

    "1954+" -> 19547        (existe na base; 19544 não existe)
    "308+4" -> 30874        (existe na base; 30844 não existe)

A EVIDÊNCIA que autoriza a substituição é a base de colaboradores: este
módulo gera todas as leituras plausíveis do texto e pergunta a quem
chamou quais existem na base.

    - exatamente UMA existe  -> recuperação aceita (RECUPERADA)
    - DUAS OU MAIS existem   -> ambíguo, ninguém escolhe (AMBIGUA -> REVISAO)
    - NENHUMA existe         -> devolve a leitura preferida só para o
                               campo sair com dígitos, mas o status
                               (SEM_CORRESPONDENCIA) leva o registro a
                               REVISAO pelo caminho normal ("matrícula
                               não encontrada na base") -- nunca é
                               confirmado com base numa suposição.

Nada aqui inventa dígito: cada substituição testada vem de uma tabela
fechada de confusões conhecidas de OCR manuscrito, e o "." / "-" / espaço
são tratados como ruído de traço (removidos), nunca como dígito.

Este módulo não importa DataManager: recebe a checagem de existência como
uma função (`existe_na_base`), o que o mantém testável sem planilha
nenhuma e sem inverter a direção das dependências.
"""

from dataclasses import dataclass
from itertools import product
from typing import Callable, List, Optional

# Comprimento plausível de uma matrícula (mesma faixa conservadora já
# usada por `ocr_engine.parece_matricula`). Serve só para descartar
# leituras absurdas -- não é usado como evidência de que a matrícula
# está correta.
COMPRIMENTO_MINIMO = 3
COMPRIMENTO_MAXIMO = 8

# Leituras alternativas por caractere. A ORDEM importa: a primeira opção
# é a leitura mais provável, usada como preferida quando a base não
# resolve. Cada dígito é sempre ele mesmo (tratado no código).
#
# "+" -> ("7", "4"): o caso real das folhas é o 7 cortado; o 4 manuscrito
# de traço aberto também pode virar "+", então ele entra como segunda
# leitura para que a base tenha o que desempatar (é justamente essa
# disputa que faz a checagem contra a base ser uma evidência real, e não
# uma confirmação automática do palpite mais provável).
#
# "." / "-" / espaço -> (""): ruído de traço/sujeira do papel, não dígito.
_LEITURAS_POR_CARACTERE = {
    "+": ("7", "4"),
    ".": ("",),
    "-": ("",),
    " ": ("",),
    "O": ("0",), "o": ("0",),
    "I": ("1",), "l": ("1",), "|": ("1",),
    "S": ("5",), "s": ("5",),
    "B": ("8",),
}

# Teto de segurança: um texto com muitos caracteres ambíguos geraria uma
# explosão combinatória de leituras, e "muitas leituras possíveis" já é,
# por si só, sinal de que não há como recuperar com segurança.
MAXIMO_LEITURAS = 16


@dataclass
class ResultadoMatricula:
    """
    status:
        "VAZIO"                -- nada a interpretar (campo ausente).
        "EXATA"                -- o texto já era só dígitos, nada foi mexido.
        "RECUPERADA"           -- houve substituição/limpeza e a leitura foi
                                  confirmada por existir (só ela) na base.
        "AMBIGUA"              -- duas ou mais leituras existem na base;
                                  não dá para escolher -> REVISAO.
        "SEM_CORRESPONDENCIA"  -- leitura limpa (só dígitos) mas nenhuma
                                  existe na base -> REVISAO pelo caminho normal.
        "IRRECUPERAVEL"        -- sobrou caractere que não é dígito nem
                                  confusão conhecida, ou o comprimento é
                                  implausível -> REVISAO.

    `matricula` é sempre só dígitos (ou "" quando não houver leitura
    utilizável). `texto_original` preserva o que o OCR entregou.
    """
    texto_original: str
    matricula: str
    status: str
    candidatos: Optional[List[str]] = None

    @property
    def houve_recuperacao(self) -> bool:
        return self.status == "RECUPERADA"


def _gerar_leituras(texto: str) -> Optional[List[str]]:
    """
    Todas as leituras só-dígitos plausíveis para `texto`, na ordem de
    preferência (primeiro a leitura mais provável). Devolve None quando
    aparece um caractere que não é dígito nem confusão conhecida -- aí
    não há recuperação possível e não se deve chutar.
    """
    opcoes_por_posicao = []
    for caractere in texto.strip():
        if caractere.isdigit():
            opcoes_por_posicao.append((caractere,))
            continue
        leituras = _LEITURAS_POR_CARACTERE.get(caractere)
        if leituras is None:
            return None
        opcoes_por_posicao.append(leituras)

    if not opcoes_por_posicao:
        return []

    total = 1
    for opcoes in opcoes_por_posicao:
        total *= len(opcoes)
        if total > MAXIMO_LEITURAS:
            return None

    vistos = set()
    candidatos: List[str] = []
    for combinacao in product(*opcoes_por_posicao):
        candidato = "".join(combinacao)
        if not candidato or not candidato.isdigit():
            continue
        if not (COMPRIMENTO_MINIMO <= len(candidato) <= COMPRIMENTO_MAXIMO):
            continue
        if candidato not in vistos:
            vistos.add(candidato)
            candidatos.append(candidato)
    return candidatos


def resolver_matricula(
    texto_ocr: Optional[str],
    existe_na_base: Optional[Callable[[str], bool]] = None,
) -> ResultadoMatricula:
    """
    Resolve o texto da coluna MATRÍCULA para uma matrícula só com
    dígitos, usando a base como evidência.

    `existe_na_base`: função que diz se uma matrícula existe na base de
    colaboradores. Quando None (base indisponível), nenhuma recuperação é
    confirmada -- devolve a leitura preferida com status
    SEM_CORRESPONDENCIA, e a validação decide o resto como já decide hoje
    ("base de colaboradores indisponível" -> REVISAO).

    Nunca levanta exceção.
    """
    if not texto_ocr or not str(texto_ocr).strip():
        return ResultadoMatricula(texto_original=texto_ocr or "", matricula="", status="VAZIO")

    texto = str(texto_ocr).strip()

    if texto.isdigit():
        return ResultadoMatricula(texto_original=texto, matricula=texto, status="EXATA")

    candidatos = _gerar_leituras(texto)
    if not candidatos:
        # Caractere desconhecido, comprimento implausível ou ambiguidade
        # demais: não há leitura segura, e inventar uma seria pior do que
        # mandar para revisão com o texto original preservado.
        return ResultadoMatricula(texto_original=texto, matricula="", status="IRRECUPERAVEL")

    preferida = candidatos[0]

    if existe_na_base is None:
        return ResultadoMatricula(
            texto_original=texto, matricula=preferida,
            status="SEM_CORRESPONDENCIA", candidatos=candidatos,
        )

    try:
        na_base = [c for c in candidatos if existe_na_base(c)]
    except Exception:
        na_base = []

    if len(na_base) == 1:
        return ResultadoMatricula(
            texto_original=texto, matricula=na_base[0],
            status="RECUPERADA", candidatos=candidatos,
        )

    if len(na_base) > 1:
        # Mais de uma leitura plausível existe de verdade na base: são
        # duas pessoas diferentes possíveis. Escolher qualquer uma seria
        # exatamente o "CONFIRMADO incorreto" que o sistema evita.
        return ResultadoMatricula(
            texto_original=texto, matricula=preferida,
            status="AMBIGUA", candidatos=na_base,
        )

    return ResultadoMatricula(
        texto_original=texto, matricula=preferida,
        status="SEM_CORRESPONDENCIA", candidatos=candidatos,
    )
