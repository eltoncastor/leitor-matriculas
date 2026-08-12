"""
integridade.py

Detecta CAMPO PERDIDO: um campo que o OCR de fato leu na linha, mas que o
parser não conseguiu associar à coluna certa e por isso chegou à validação
como se não existisse.

POR QUE ISTO EXISTE (achado real da medição da Fase 11): o registro da
matrícula 26319 saiu CONFIRMADO com a coluna Hora VAZIA, embora a folha
tenha `07:49` escrito e legível. Olhando o parser, o texto estava lá:

    L2: data='14.0.4.26'  hora=AUSENTE  matricula='26319' ...
          nao_associados: ['07:4', 'tiago', 'Clubi Prot.']
                           ^^^^^^ a hora, lida e descartada

O OCR cortou o segundo dígito do minuto (`07:49` -> `07:4`), e com isso o
filtro de formato da coluna HORA (`registro_parser._PARECE_HORA`, que exige
dois dígitos depois do separador) recusou o elemento -- corretamente, do
ponto de vista dele, que existe para impedir texto impresso de virar dado.
O elemento não foi descartado em silêncio: foi para `nao_associados`. É
exatamente essa sobra que este módulo lê.

A DISTINÇÃO QUE IMPORTA (e que a Fase 12 pede):

    hora ausente porque a folha não tem hora  -> campo opcional, não bloqueia
    hora ausente porque o OCR a perdeu        -> BLOQUEIA (-> REVISAO)

Sem esta distinção só existiriam duas saídas ruins: confirmar registros
incompletos (o que acontecia), ou tornar a hora obrigatória (o que
contraria o requisito funcional de que ela é opcional).

O QUE CONTA COMO EVIDÊNCIA: um elemento sobrando NA MESMA LINHA cujo
FORMATO só faz sentido para o campo que faltou. É evidência de captura,
não de conteúdo -- este módulo nunca diz qual é o valor do campo, só que
havia algo com a cara dele e que se perdeu. O valor continua sem ser
inventado; quem decide é uma pessoa, na revisão.

Verificação contra o lote real (5 folhas, 40 liberações): as 3 linhas que
perderam a hora têm evidência (`'07:4'`, `'11:0s Card'`, `'1108
fernamenta'`), e as 2 linhas cuja matrícula está REALMENTE em branco no
papel não têm nenhuma -- o sinal separa os dois casos sem confundi-los.
"""

import re
from typing import Dict, Optional

from leitor_matriculas.parsing.tempo_parser import interpretar_hora

# Anotações que o próprio pipeline acrescenta a `nao_associados` para
# auditoria (ver `_reparar_data_hora_mescladas` em ui/app.py) vêm entre
# colchetes. São texto NOSSO, não leitura do OCR: nunca podem valer como
# evidência de campo perdido -- elas inclusive contêm data/hora, o que
# faria o detector disparar sozinho.
_RE_ANOTACAO_INTERNA = re.compile(r"^\s*\[")

# Fragmento com cara de HORA. Deliberadamente mais frouxo que o filtro da
# coluna: aqui basta a ESTRUTURA hora-separador-minuto, mesmo truncada
# (`07:4`) ou com um dígito lido como letra (`11:0s`) -- é justamente o
# que o filtro estrito recusou, e o que se quer detectar como perda.
_RE_HORA_FRAGMENTO = re.compile(r"\d{1,2}\s*[:hH.]\s*\d{1,2}")

# Hora cujo separador o OCR comeu por completo, restando 4 dígitos
# colados (`1108` = 11:08, visto grudado no nome: `'1108 fernamenta'`).
# Só vale como evidência se formar uma hora POSSÍVEL -- assim uma
# matrícula curta de 4 dígitos (ex.: 3875 -> "38:75") não dispara nada.
_RE_HORA_COLADA = re.compile(r"(?<!\d)(\d{2})(\d{2})(?!\d)")

# Fragmento com cara de DATA: três blocos de dígitos, ou uma sequência
# longa de dígitos sem separador nenhum (`13104126`, que é `13|04|26`
# com as barras lidas como o dígito 1).
_RE_DATA_FRAGMENTO = re.compile(r"\d{1,2}\s*[./\-]\s*\d{1,2}\s*[./\-]\s*\d{2,4}|(?<!\d)\d{6,8}(?!\d)")

# Fragmento com cara de MATRÍCULA: uma corrida de 3 a 8 dígitos. Vale
# mesmo colada a outro texto -- o caso real é `'28972 tente de Lga'`, a
# matrícula grudada no setor.
_RE_MATRICULA_FRAGMENTO = re.compile(r"(?<!\d)\d{3,8}(?!\d)")

# Campos para os quais existe teste de formato confiável. MOTIVO e
# RESPONSÁVEL são texto livre: qualquer sobra da linha (nome, setor)
# "pareceria" um deles, então detectá-los por formato geraria evidência
# falsa. Os dois já bloqueiam quando ausentes (ver validacao/regras.py),
# de modo que não há lacuna de segurança em ficarem de fora daqui.
CAMPOS_COM_EVIDENCIA_DE_FORMATO = ("hora", "data", "matricula")


def _parece_hora(texto: str) -> bool:
    if _RE_HORA_FRAGMENTO.search(texto):
        return True
    for correspondencia in _RE_HORA_COLADA.finditer(texto):
        if interpretar_hora(f"{correspondencia.group(1)}:{correspondencia.group(2)}") is not None:
            return True
    return False


_TESTES_POR_CAMPO = {
    "hora": _parece_hora,
    "data": lambda texto: bool(_RE_DATA_FRAGMENTO.search(texto)),
    "matricula": lambda texto: bool(_RE_MATRICULA_FRAGMENTO.search(texto)),
}


def _campo_ausente(registro, nome_campo: str) -> bool:
    campo = registro.campos.get(nome_campo)
    return campo is None or not (campo.texto or "").strip()


def _sobras_do_ocr(registro):
    """Texto que sobrou na linha, sem as anotações internas do pipeline."""
    for elemento in getattr(registro, "nao_associados", None) or []:
        texto = (getattr(elemento, "texto", "") or "").strip()
        if texto and not _RE_ANOTACAO_INTERNA.match(texto):
            yield texto


def detectar_campo_perdido(registro, nome_campo: str) -> Optional[str]:
    """
    Devolve o TEXTO SUSPEITO quando há evidência de que `nome_campo` foi
    lido pelo OCR nesta linha e se perdeu antes de chegar à validação; ou
    None quando o campo está preenchido, quando não há teste de formato
    confiável para ele, ou quando nada na linha tem a cara dele.

    None NÃO significa "o campo existe na folha": significa apenas que não
    há evidência de perda. Um campo genuinamente em branco no papel cai
    aqui, e continua sendo tratado pela regra normal daquele campo.
    """
    if not _campo_ausente(registro, nome_campo):
        return None
    teste = _TESTES_POR_CAMPO.get(nome_campo)
    if teste is None:
        return None
    for texto in _sobras_do_ocr(registro):
        if teste(texto):
            return texto
    return None


def detectar_campos_perdidos(registro) -> Dict[str, str]:
    """
    Todos os campos com evidência de perda nesta linha, no formato
    `{nome_campo: texto_suspeito}`. Dicionário vazio quando não há
    nenhuma evidência -- que é o caso normal.
    """
    perdidos = {}
    for nome_campo in CAMPOS_COM_EVIDENCIA_DE_FORMATO:
        suspeito = detectar_campo_perdido(registro, nome_campo)
        if suspeito is not None:
            perdidos[nome_campo] = suspeito
    return perdidos


def descrever_perda(nome_campo: str, texto_suspeito: str) -> str:
    """Mensagem objetiva para a Observação, nomeando o campo e mostrando o
    texto que o OCR chegou a ler -- sem o qual o operador não teria como
    saber onde procurar na folha."""
    return (
        f"{nome_campo} não capturada com segurança: o OCR leu "
        f"'{texto_suspeito}' nesta linha, mas não foi possível associar à "
        f"coluna {nome_campo.upper()} -- conferir no papel"
    )
