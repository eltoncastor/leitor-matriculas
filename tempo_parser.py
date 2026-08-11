"""
tempo_parser.py

Interpretação estruturada de DATA e HORA reconhecidos pelo OCR na folha.

REGRA DE OURO (requisito funcional definitivo): nunca corrigir ou inventar
um valor de data/hora só porque existe uma hipótese provável. Um texto que
não possa ser interpretado com segurança — formato inesperado, campo
vazio, data/hora impossível, ano ausente/ambíguo — devolve None. Quem
chama (validacao.py) decide o que fazer com isso, e a decisão é sempre
REVISAO; este módulo nunca "adivinha".

Formatos aceitos:
    DATA: dd/mm/aaaa, dd/mm/aa, dd-mm-aaaa, dd-mm-aa, dd.mm.aaaa, dd.mm.aa
          Ano com 2 dígitos é expandido para 20xx — isso NÃO é "inventar":
          o dígito do ano está de fato escrito na folha, só abreviado.
          Data SEM ano (ex.: "23/04") é rejeitada de propósito: não há
          como determinar o ano com segurança sem supor algo que não está
          escrito, então devolve None (-> REVISAO).
    HORA: hh:mm, hh.mm, hh"h"mm (ex. "11h05"), com segundos opcionais
          (hh:mm:ss).

Este módulo não sabe nada sobre OCR, registros ou a folha — só interpreta
texto já extraído. Fica combinado (via `interpretar_data_hora`) apenas
para servir de chave de ordenação cronológica.

`tentar_separar_data_hora_mesclada` (Fase 1 de precisão da extração)
trata um caso real observado: o detector de texto do OCR às vezes cola
DATA e HORA em uma única caixa (ex.: "14.04 26 20:24"). Separa os dois
pedaços só quando ambos validam com segurança — mesma regra de ouro.
"""

import re
from datetime import date, datetime, time
from typing import Optional

_RE_DATA = re.compile(
    r"^\s*(\d{1,2})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(\d{2}|\d{4})\s*$"
)
_RE_HORA = re.compile(
    r"^\s*(\d{1,2})\s*[:hH.]\s*(\d{2})\s*(?:[:mM.]\s*(\d{2}))?\s*$"
)

# Versões "embutidas" (não ancoradas com ^$, aceitam espaço como separador
# de data) usadas só por `tentar_separar_data_hora_mesclada` para LOCALIZAR
# um trecho candidato dentro de um texto maior -- nunca para validar. A
# validação de verdade continua sendo sempre `_RE_DATA`/`_RE_HORA` via
# `interpretar_data`/`interpretar_hora`.
_RE_DATA_EMBUTIDA = re.compile(r"(\d{1,2})\s*[./\-\s]\s*(\d{1,2})\s*[./\-\s]\s*(\d{2}|\d{4})")
_RE_HORA_EMBUTIDA = re.compile(r"(\d{1,2})\s*[:hH.]\s*(\d{2})(?:\s*[:mM.]\s*(\d{2}))?")


def interpretar_data(texto: Optional[str]) -> Optional[date]:
    """
    Converte um texto de data em `datetime.date`, ou devolve None se não
    puder ser interpretado com segurança (vazio, formato inesperado, sem
    ano, ou data impossível como 31/04 ou mês 13).
    """
    if not texto or not texto.strip():
        return None

    correspondencia = _RE_DATA.match(texto.strip())
    if not correspondencia:
        return None

    dia_str, mes_str, ano_str = correspondencia.groups()
    dia, mes, ano = int(dia_str), int(mes_str), int(ano_str)
    if len(ano_str) == 2:
        ano += 2000

    try:
        return date(ano, mes, dia)
    except ValueError:
        return None  # data impossível (ex.: 31/04, mês 13, dia 32...)


def interpretar_hora(texto: Optional[str]) -> Optional[time]:
    """
    Converte um texto de hora em `datetime.time`, ou devolve None se não
    puder ser interpretado com segurança (vazio, formato inesperado, ou
    hora/minuto/segundo fora do intervalo válido).
    """
    if not texto or not texto.strip():
        return None

    correspondencia = _RE_HORA.match(texto.strip())
    if not correspondencia:
        return None

    hora_str, minuto_str, segundo_str = correspondencia.groups()
    hora, minuto = int(hora_str), int(minuto_str)
    segundo = int(segundo_str) if segundo_str else 0

    if not (0 <= hora <= 23 and 0 <= minuto <= 59 and 0 <= segundo <= 59):
        return None  # hora impossível

    return time(hora, minuto, segundo)


def interpretar_data_hora(texto_data: Optional[str], texto_hora: Optional[str]) -> Optional[datetime]:
    """
    Combina data + hora em um único `datetime`, para uso como chave de
    ordenação cronológica. Devolve None se qualquer um dos dois não puder
    ser interpretado com segurança (nunca combina um válido com um
    "chute" para o outro).
    """
    data = interpretar_data(texto_data)
    hora = interpretar_hora(texto_hora)
    if data is None or hora is None:
        return None
    return datetime.combine(data, hora)


def tentar_separar_data_hora_mesclada(texto: Optional[str]):
    """
    Tenta separar um único texto que aparentemente mistura DATA e HORA em
    uma coisa só -- ex.: "14.04 26 20:24" (caso real observado: o próprio
    detector de texto do OCR colou duas caixas vizinhas antes mesmo do
    parser espacial ver os dados; ver PROBLEMA 5 / registro_parser.py).

    Correção DELIBERADAMENTE conservadora, no mesmo espírito de
    `ocr_engine.normalizar_matricula`: localiza um trecho com "cara" de
    data e um trecho com "cara" de hora dentro do texto, monta uma versão
    canônica de cada um usando só os dígitos que já estavam escritos
    (nunca inventa dígito) e só aceita a separação se AMBOS os pedaços
    resultantes validarem de verdade em `interpretar_data`/
    `interpretar_hora` -- a mesma validação estrita usada no resto do
    sistema, não uma cópia mais permissiva dela.

    Se qualquer uma dessas condições falhar, devolve None -- quem chama
    mantém o campo como estava (ausente continua ausente -> REVISAO via
    `validar_data_hora`; nunca inventa um valor).

    Devolve (texto_data_canonico, texto_hora_canonico) ou None.
    """
    if not texto or not texto.strip():
        return None

    correspondencia_data = _RE_DATA_EMBUTIDA.search(texto)
    if not correspondencia_data:
        return None

    dia, mes, ano = correspondencia_data.groups()
    texto_data_canonico = f"{dia}.{mes}.{ano}"

    # Procura a hora fora do trecho já consumido pela data, para não
    # reaproveitar os mesmos dígitos nos dois campos.
    resto = texto[: correspondencia_data.start()] + " " + texto[correspondencia_data.end() :]
    correspondencia_hora = _RE_HORA_EMBUTIDA.search(resto)
    if not correspondencia_hora:
        return None

    hora, minuto, segundo = correspondencia_hora.groups()
    texto_hora_canonico = f"{hora}:{minuto}" + (f":{segundo}" if segundo else "")

    if interpretar_data(texto_data_canonico) is None:
        return None
    if interpretar_hora(texto_hora_canonico) is None:
        return None

    return texto_data_canonico, texto_hora_canonico


def validar_data_hora(texto_data: Optional[str], texto_hora: Optional[str]) -> Optional[str]:
    """
    Verifica se DATA e HORA (textos já extraídos pelo OCR) podem ser
    interpretados com segurança.

    Devolve None se ambos forem válidos, ou uma mensagem de observação
    (para status REVISAO) explicando o que não pôde ser confirmado —
    cobrindo os casos exigidos: data ilegível, data impossível, hora
    ilegível, hora impossível, formato inesperado, campo vazio, e
    combinação que não possa ser interpretada com segurança.
    """
    data_vazia = not (texto_data and texto_data.strip())
    hora_vazia = not (texto_hora and texto_hora.strip())

    if data_vazia and hora_vazia:
        return "data e hora não identificadas pelo OCR"
    if data_vazia:
        return "data não identificada pelo OCR"
    if hora_vazia:
        return "hora não identificada pelo OCR"

    data = interpretar_data(texto_data)
    hora = interpretar_hora(texto_hora)

    if data is None and hora is None:
        return f"data ('{texto_data}') e hora ('{texto_hora}') não puderam ser interpretadas com segurança"
    if data is None:
        return f"data não pôde ser interpretada com segurança: '{texto_data}'"
    if hora is None:
        return f"hora não pôde ser interpretada com segurança: '{texto_hora}'"

    return None
