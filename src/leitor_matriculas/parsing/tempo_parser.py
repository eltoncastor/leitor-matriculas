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
          Data SEM ano (ex.: "23/04") continua sendo rejeitada por
          `interpretar_data`: o ano não está escrito, e supor um seria
          exatamente o "chute" que este módulo não faz. Quem tiver
          CONTEXTO REAL do lote (ver `parsing/contexto_lote.py`) pode
          reconhecer o dia/mês por `interpretar_data_sem_ano` e completar
          o ano a partir das outras folhas do MESMO lote — a evidência aí
          é externa e verificável, não uma suposição deste módulo.
    HORA: hh:mm, hh.mm, hh"h"mm (ex. "11h05"), hh mm (separador apagado
          pelo OCR, ex.: "07 53"), com segundos opcionais (hh:mm:ss).

FORMATO CANÔNICO DE SAÍDA (requisito funcional definitivo): a planilha
final nunca repete o separador que o OCR leu. `normalizar_data` devolve
sempre `dd/mm/aa` e `normalizar_hora` sempre `HH:MM` — assim "14.04.26",
"14-04-26" e "14.04:26" saem todos como "14/04/26", e "18.59", "11h27" e
"07:53" saem todos como "18:59"/"11:27"/"07:53". Normalizar o FORMATO não
afrouxa a validação: as duas funções são a interpretação estrita de
sempre seguida da formatação, então uma hora impossível ("90:24") ou uma
data sem ano ("23/04") continuam recusadas.

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

# DATA sem ano ("23.04"): NÃO é uma data completa e `interpretar_data`
# continua recusando esse texto. Este regex existe só para RECONHECER a
# estrutura dia/mês, para quem tiver contexto real do lote poder completar
# o ano (ver `interpretar_data_sem_ano` e `parsing/contexto_lote.py`).
# Note o `$` logo depois do mês: um texto com um terceiro bloco ("23.04.26",
# "23.0426") não cai aqui — ele já é uma data completa e é tratado acima.
_RE_DATA_SEM_ANO = re.compile(rf"^\s*(\d{{1,2}})\s*{_SEP_DATA}\s*(\d{{1,2}})\s*$")

# Último recurso para uma data cujo SEPARADOR o OCR multiplicou ou moveu,
# mas cujos dígitos estão todos lá e na ordem certa ("14.0.4.26" =
# 14/04/26). Condições deliberadamente estreitas:
#   - o texto tem de ser SÓ dígitos e separadores de data (nenhuma letra,
#     nenhum espaço) -- uma caixa com data e hora coladas ("14.04 -26
#     90:24") não entra aqui, e continua sendo tratada por
#     `tentar_separar_data_hora_mesclada`;
#   - tem de haver ao menos um separador (um bloco de 6 dígitos sozinho
#     poderia ser uma matrícula, não uma data);
#   - a quantidade de dígitos tem de ser exatamente 6 (ddmmaa) ou 8
#     (ddmmaaaa) -- qualquer outra quantidade é ambígua e é recusada.
# Nenhum dígito é inventado: só se ignora onde os separadores caíram. O
# resultado ainda passa pela mesma validação de calendário.
_RE_DATA_SO_DIGITOS_E_SEPARADORES = re.compile(rf"^\s*\d+(?:{_SEP_DATA}\d+)+\s*$")

# O espaço entra na classe de separadores de HORA:MINUTO porque o OCR real
# APAGA o separador da hora manuscrita ("07 53" no lugar de "07:53"). Isso
# não afrouxa a validação: continua exigindo separador (um "0753" colado,
# sem nada entre os dois blocos, continua recusado por ambíguo) e os dois
# números continuam tendo de formar uma hora possível. O separador dos
# SEGUNDOS não ganhou o espaço de propósito -- não há caso observado, e
# aceitá-lo faria "23 04 26" (uma data) passar por hora 23:04:26.
_RE_HORA = re.compile(
    r"^\s*(\d{1,2})\s*[:hH.\s]\s*(\d{2})\s*(?:[:mM.]\s*(\d{2}))?\s*$"
)

# Versões "embutidas" (não ancoradas com ^$, aceitam espaço como separador
# de data) usadas só por `tentar_separar_data_hora_mesclada` para LOCALIZAR
# um trecho candidato dentro de um texto maior -- nunca para validar. A
# validação de verdade continua sendo sempre `_RE_DATA`/`_RE_HORA` via
# `interpretar_data`/`interpretar_hora`.
#
# O separador da hora aparece DUPLICADO em leituras reais ("14.:08"), daí
# o `{1,2}`: continua sendo um separador só, lido duas vezes pelo OCR.
_RE_DATA_EMBUTIDA = re.compile(r"(\d{1,2})\s*[./\-\s]\s*(\d{1,2})\s*[./\-\s]\s*(\d{2}|\d{4})")
_RE_HORA_EMBUTIDA = re.compile(r"(\d{1,2})\s*[:hH.]{1,2}\s*(\d{2})(?:\s*[:mM.]\s*(\d{2}))?")


def _partes_de_data_deformada(texto: str):
    """
    Último recurso de `interpretar_data` para uma data cujo SEPARADOR o
    OCR deformou ("14.0.4.26"). Devolve `(dia, mes, ano)` como texto, ou
    None quando as condições estreitas de
    `_RE_DATA_SO_DIGITOS_E_SEPARADORES` não são atendidas. Não valida
    calendário -- quem chama já faz isso logo em seguida.
    """
    if not _RE_DATA_SO_DIGITOS_E_SEPARADORES.match(texto):
        return None

    digitos = "".join(c for c in texto if c.isdigit())
    if len(digitos) == 6:
        return digitos[0:2], digitos[2:4], digitos[4:6]
    if len(digitos) == 8:
        return digitos[0:2], digitos[2:4], digitos[4:8]
    return None


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
    if correspondencia:
        dia_str, mes_str, ano_str = correspondencia.groups()
    else:
        partes = _partes_de_data_deformada(texto)
        if partes is None:
            return None
        dia_str, mes_str, ano_str = partes
    dia, mes, ano = int(dia_str), int(mes_str), int(ano_str)
    if len(ano_str) == 2:
        ano += 2000

    try:
        return date(ano, mes, dia)
    except ValueError:
        return None  # data impossível (ex.: 31/04, mês 13, dia 32...)


def interpretar_data_sem_ano(texto: Optional[str]):
    """
    Reconhece um texto de data SEM ano ("23.04", "23/04", "14-04") e
    devolve `(dia, mes)`, ou None quando o texto não tem essa estrutura ou
    quando dia/mês estão fora de faixa.

    Isto NÃO é uma data: sozinha, ela continua sem poder ser validada, e
    `interpretar_data` continua devolvendo None para o mesmo texto. A
    função existe só para que quem tem CONTEXTO REAL do lote (ver
    `parsing/contexto_lote.py`) possa completar o ano a partir das outras
    folhas do mesmo lote — evidência externa e verificável, não uma
    suposição. Este módulo, sozinho, nunca completa ano nenhum.

    A faixa de dia/mês é checada aqui só para descartar o que é
    impossível em qualquer ano (dia 0/32, mês 0/13); a validade de
    calendário de verdade (29/02, 31/04) só pode ser decidida com o ano,
    e acontece depois, em `interpretar_data`.
    """
    if not texto or not texto.strip():
        return None

    correspondencia = _RE_DATA_SEM_ANO.match(texto.strip())
    if not correspondencia:
        return None

    dia, mes = int(correspondencia.group(1)), int(correspondencia.group(2))
    if not (1 <= dia <= 31 and 1 <= mes <= 12):
        return None
    return dia, mes


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


def formatar_hora_hh_mm(hora: time) -> str:
    """Formato canônico de saída da HORA na planilha: `HH:MM`."""
    return f"{hora.hour:02d}:{hora.minute:02d}"


def normalizar_hora(texto: Optional[str]) -> Optional[str]:
    """
    Devolve a HORA já no formato canônico `HH:MM`, ou None quando o texto
    não puder ser interpretado com segurança.

    Mesmo papel de `normalizar_data` para a DATA, e com a mesma ressalva:
    isto NÃO afrouxa nada. É `interpretar_hora` (mesma validação estrita de
    intervalo -- "90:24" continua sendo recusado) seguida da formatação
    canônica. Serve para que a planilha final não misture "18.59", "07.55",
    "11h27" e "07:53" -- todos saem como `HH:MM`.

    Os segundos, quando o OCR os lê, são descartados de propósito: o
    formato mandatório da coluna é `HH:MM`, e o segundo não é informação
    que a folha registre.
    """
    hora = interpretar_hora(texto)
    return formatar_hora_hh_mm(hora) if hora is not None else None


def recuperar_hora(texto: Optional[str]) -> Optional[str]:
    """
    `normalizar_hora` com UMA recuperação a mais: o caso real em que o
    detector do OCR colou a hora a um texto vizinho na mesma caixa
    ("12:55 Miguel", "11:06 Faina") -- o mesmo artefato de caixa mesclada
    que `tentar_separar_data_hora_mesclada` trata para DATA+HORA, aqui na
    versão "hora + texto que não é número".

    Condições estreitas, para não transformar qualquer texto com números
    em hora:
        - o texto contém EXATAMENTE UM trecho com forma de hora (dois
          trechos = ambíguo, ninguém escolhe);
        - o que sobra depois de tirar esse trecho NÃO tem nenhum dígito
          (se tiver, os dígitos restantes podem ser parte da hora de
          verdade, e aí não há leitura segura);
        - e o trecho encontrado ainda passa por `interpretar_hora`, a
          mesma validação estrita de sempre ("90:24" continua recusado).

    Devolve `HH:MM` ou None. Nenhum dígito é inventado.
    """
    normalizada = normalizar_hora(texto)
    if normalizada is not None:
        return normalizada

    if not texto or not texto.strip():
        return None

    encontrados = list(_RE_HORA_EMBUTIDA.finditer(texto))
    if len(encontrados) != 1:
        return None

    correspondencia = encontrados[0]
    resto = texto[: correspondencia.start()] + texto[correspondencia.end():]
    if any(c.isdigit() for c in resto):
        return None

    hora, minuto, segundo = correspondencia.groups()
    return normalizar_hora(f"{hora}:{minuto}" + (f":{segundo}" if segundo else ""))


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

    Devolve `(texto_data_canonico, texto_hora_canonico)` ou None. A hora
    vem como None quando a caixa mesclada tinha mesmo um trecho de hora,
    só que impossível: aí a DATA legível é aproveitada e a HORA (campo
    opcional) simplesmente não existe -- nunca sai com o texto impossível.
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
        # A DATA é boa e a caixa comprovadamente misturava data e hora (o
        # trecho com forma de hora está lá), só que a hora saiu impossível
        # ("14.04 -26 90:24"). Recusar a separação inteira faria a DATA
        # legível ser perdida por causa da HORA -- e a hora é o campo
        # OPCIONAL. Devolve só a data; a hora fica AUSENTE (nunca com o
        # texto impossível, que seria indistinguível de uma hora real).
        return texto_data_canonico, None

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

    Para saber SE a hora pode ser usada, quem chama usa `recuperar_hora`
    (None = não usar). Esta função só produz o texto do aviso, e usa a
    MESMA função para decidir se há algo a avisar -- uma hora que a
    recuperação conseguiu ler não é "ilegível" e não gera aviso.
    """
    if not (texto_hora and texto_hora.strip()):
        return None  # hora ausente é aceitável: campo opcional

    if recuperar_hora(texto_hora) is None:
        return f"hora ilegível, exportada em branco (texto do OCR: '{texto_hora}')"

    return None
