"""
tempo_parser.py

Interpretação estruturada de DATA e HORA reconhecidos pelo OCR na folha.

REGRA DE OURO (requisito funcional definitivo): nunca corrigir ou inventar
um valor de data/hora só porque existe uma hipótese provável. Um texto que
não possa ser interpretado com segurança — formato inesperado, campo
vazio, data/hora impossível, ano ausente/ambíguo — devolve None. Quem
chama (validacao.py) decide o que fazer com isso; este módulo nunca
"adivinha".

DATA É OBRIGATÓRIA, HORA É OPCIONAL (requisito funcional definitivo):
    - DATA que não possa ser interpretada com segurança BLOQUEIA a
      confirmação (-> REVISAO). Ver `validar_data`.
    - HORA NUNCA bloqueia a confirmação. Ausente ou ilegível, o registro
      ainda pode ser CONFIRMADO desde que data/matrícula/motivo/
      responsável estejam confirmados. Ver `avaliar_hora_opcional`.
      Quando a hora não puder ser reconhecida com segurança, o campo sai
      VAZIO na planilha — nunca com o texto ilegível do OCR, que seria
      indistinguível de uma hora de verdade (o texto bruto continua
      preservado na Observação, para auditoria: não some em silêncio).

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
texto já extraído.

`tentar_separar_data_hora_mesclada` (Fase 1 de precisão da extração)
trata um caso real observado: o detector de texto do OCR às vezes cola
DATA e HORA em uma única caixa (ex.: "14.04 26 20:24"). Separa os dois
pedaços só quando ambos validam com segurança — mesma regra de ouro.
"""

import re
from datetime import date, datetime, time
from typing import Optional

# Separadores aceitos entre dia/mês/ano. O ":" entra aqui porque é um erro
# de OCR REAL e recorrente nas folhas ("14.04:26"): o ponto da data sai
# lido como dois-pontos. Aceitar o separador não afrouxa nada -- os três
# números continuam tendo de formar uma data de calendário válida.
_SEP_DATA = r"[./\-:]"

_RE_DATA = re.compile(
    rf"^\s*(\d{{1,2}})\s*{_SEP_DATA}\s*(\d{{1,2}})\s*{_SEP_DATA}\s*(\d{{2}}|\d{{4}})\s*$"
)

# Caso real: o OCR perde o separador entre MÊS e ANO e cola os dois
# ("23.0426" = 23/04/26). A leitura é inequívoca porque o bloco colado só
# pode ser mês(2) + ano(2 ou 4) -- nenhum dígito é inventado, só se
# reconhece onde o separador sumiu. Continua passando pela mesma validação
# de calendário depois.
_RE_DATA_MES_ANO_COLADOS = re.compile(
    rf"^\s*(\d{{1,2}})\s*{_SEP_DATA}\s*(\d{{2}})(\d{{2}}|\d{{4}})\s*$"
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

    texto = texto.strip()
    correspondencia = _RE_DATA.match(texto) or _RE_DATA_MES_ANO_COLADOS.match(texto)
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


def formatar_data_dd_mm_aa(data: date) -> str:
    """Formato canônico de saída da DATA na planilha: `dd/mm/aa`."""
    return f"{data.day:02d}/{data.month:02d}/{data.year % 100:02d}"


def normalizar_data(texto: Optional[str]) -> Optional[str]:
    """
    Devolve a DATA já no formato canônico `dd/mm/aa`, ou None quando o
    texto não puder ser interpretado com segurança.

    Isto NÃO afrouxa nada: é `interpretar_data` (mesma validação estrita
    de calendário, mesma recusa a data sem ano) seguida da formatação
    canônica. Serve para que a planilha final tenha sempre um formato
    único de data, em vez do texto cru do OCR com o separador que ele
    tiver lido ("14.04.26", "14-04-26", "14.04:26" -> todos "14/04/26").
    """
    data = interpretar_data(texto)
    return formatar_data_dd_mm_aa(data) if data is not None else None


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
    Combina data + hora em um único `datetime`. Devolve None se qualquer
    um dos dois não puder ser interpretado com segurança (nunca combina um
    válido com um "chute" para o outro).

    NOTA: nenhum módulo de produção usa esta função hoje. Ela existia para
    servir de chave da ordenação cronológica do XLSX, que foi REMOVIDA (a
    planilha preserva a ordem física da folha — ver xlsx_exporter.py).
    Mantida por ser utilitário legítimo e coberto por teste; se continuar
    sem uso, é candidata a remoção na limpeza de código morto.
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
    mantém o campo como estava (ausente continua ausente: DATA ausente vai
    para REVISAO via `validar_data`; HORA ausente é aceitável, ver
    `avaliar_hora_opcional`. Nunca inventa um valor).

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


def validar_data(texto_data: Optional[str]) -> Optional[str]:
    """
    Verifica se a DATA (texto já extraído pelo OCR) pode ser interpretada
    com segurança. A data É OBRIGATÓRIA: esta é uma checagem BLOQUEANTE.

    Devolve None quando a data é válida, ou uma mensagem de observação
    (para status REVISAO) explicando o que não pôde ser confirmado —
    cobrindo campo vazio, formato inesperado, data impossível e ano
    ausente.
    """
    if not (texto_data and texto_data.strip()):
        return "data não identificada pelo OCR"

    if interpretar_data(texto_data) is None:
        return f"data não pôde ser interpretada com segurança: '{texto_data}'"

    return None


def avaliar_hora_opcional(texto_hora: Optional[str]) -> Optional[str]:
    """
    Avalia a HORA, que é OPCIONAL (requisito funcional definitivo): esta
    checagem NUNCA bloqueia a confirmação de um registro.

    Devolve:
        - None quando a hora está ausente (caso normal e aceitável — a
          folha simplesmente não teve a hora preenchida/legível) OU quando
          ela é válida. Em ambos os casos não há nada a observar.
        - uma mensagem de AVISO (não de erro) quando existe texto na
          coluna HORA mas ele não pôde ser interpretado com segurança. Quem
          chama registra isso na Observação e deixa o campo Hora VAZIO —
          nunca escreve o texto ilegível na planilha (seria indistinguível
          de uma hora real), mas também nunca o descarta em silêncio.

    Para saber SE a hora pode ser usada, quem chama usa `interpretar_hora`
    (None = não usar). Esta função só produz o texto do aviso.
    """
    if not (texto_hora and texto_hora.strip()):
        return None  # hora ausente é aceitável: campo opcional

    if interpretar_hora(texto_hora) is None:
        return f"hora ilegível, exportada em branco (texto do OCR: '{texto_hora}')"

    return None
