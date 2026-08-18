"""
web/backend/armazenamento.py

Fase 26a (OCR Worker distribuído). Persistência em disco do estado de um
lote/Job. Existe por uma razão concreta e medida na auditoria: até a Fase
25 o backend guardava TUDO em `estado._lotes`, um dicionário de módulo --
um reinício do processo (deploy, queda, restart do serviço na VPS) apagava
lotes inteiros em silêncio, com o `status` congelado em "processando" e
nenhuma forma de recuperar. Com o OCR passando a rodar noutra máquina, a
janela em que isso pode acontecer deixa de ser "os segundos entre duas
requisições" e passa a ser "as horas em que o Worker está trabalhando" --
aí a perda deixa de ser aceitável.

POR QUE ARQUIVOS E NÃO SQLite
-----------------------------
Foi a decisão explicitamente pesada na auditoria desta fase. O backend é
single-process POR CONSTRUÇÃO: `estado._lotes`, `estado._ocr_engine` e
`estado._data_manager` são globais de módulo, e `web/backend/main.py` sobe
o uvicorn sem `workers=`. Nesse regime, a exclusão mútua que importa (dois
Workers não podem reivindicar o mesmo Job) é resolvida por um
`threading.Lock` que o `LoteState` JÁ TEM -- a atomicidade ENTRE PROCESSOS
que o SQLite oferece não compra nada utilizável aqui, e traria junto
`check_same_thread` (as rotas síncronas do FastAPI rodam em threads
arbitrárias do threadpool), `journal_mode=WAL`, `busy_timeout` e
`BEGIN IMMEDIATE` (sem o qual um `UPDATE` após `SELECT` toma SQLITE_BUSY
na hora, ignorando o timeout) -- superfície nova para resolver um problema
que não existe.

Um arquivo JSON por lote, escrito atomicamente, dá a MESMA durabilidade
com zero dependência nova e zero configuração. Quando o dispatcher sair do
processo do FastAPI (vários processos de API, ou uma fila fora dele), aí
sim SQLite passa a se justificar -- e este módulo é a fronteira que
concentra essa troca.

LAYOUT
------
    <raiz>/<lote_id>/
        estado.json          metadados do Job (status, fase, contadores,
                             avisos, contexto do lote) -- pequeno, reescrito
                             a cada mudança de estado
        entrada/<nome>       os arquivos que o usuário enviou
        paginas/NNN.json     o que o OCR leu naquela página (registros
                             crus, ANTES da classificação) -- é o que
                             torna a retomada barata: reprocessar a
                             classificação custa milissegundos, refazer o
                             OCR custa ~40 s por página
        paginas/NNN.jpg      a foto da página (comodidade da revisão)
        registros.json       o resultado JÁ classificado, reescrito ao
                             concluir e a cada confirmação manual

Nada aqui conhece OCR, regra de negócio ou HTTP: o módulo recebe e devolve
estruturas Python puras.
"""
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from typing import Dict, List, Optional

# Nome da pasta raiz de armazenamento. Fica ao lado de `dados/` (na raiz do
# projeto) ou ao lado do `.exe` quando empacotado -- mesmo critério que
# `estado._pasta_dados_ao_lado_do_executavel` já usava para as planilhas de
# referência, e pelo mesmo motivo: é conteúdo do usuário, tem que
# sobreviver a um reempacotamento e ser inspecionável sem descompactar
# nada.
NOME_PASTA_PADRAO = "armazenamento"

# Retenção: lotes mais velhos que isto são apagados na varredura de
# inicialização. Antes da Fase 26 os uploads iam para
# `tempfile.mkdtemp()`, e quem os recolhia era o sistema operacional;
# passando para uma pasta durável, essa rede de segurança some -- então a
# limpeza passa a ser responsabilidade explícita daqui. Por IDADE, não por
# cota de disco (cota exigiria decidir o que apagar primeiro, e não há
# critério óbvio que não arrisque apagar um lote que alguém ainda vai
# revisar).
DIAS_RETENCAO_PADRAO = 30

_ARQUIVO_ESTADO = "estado.json"
_ARQUIVO_REGISTROS = "registros.json"
_PASTA_ENTRADA = "entrada"
_PASTA_PAGINAS = "paginas"

# `lote_id` é gerado por `uuid.uuid4().hex` -- só hexadecimal. Validar isso
# antes de montar qualquer caminho é o que impede um `lote_id` vindo da URL
# de virar `../../algo` (o mesmo cuidado que `main.py` já toma ao servir
# arquivos estáticos, com `Path.is_relative_to`).
_LOTE_ID_VALIDO = re.compile(r"^[0-9a-f]{8,64}$")


def _raiz_padrao() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), NOME_PASTA_PADRAO)
    # web/backend/armazenamento.py -> web/backend -> web -> raiz
    raiz_projeto = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(raiz_projeto, NOME_PASTA_PADRAO)


_raiz: Optional[str] = None


def definir_raiz(caminho: Optional[str]) -> None:
    """
    Troca a pasta raiz de armazenamento. Serve para dois casos reais: a
    variável de ambiente `LEITOR_ARMAZENAMENTO` (a VPS aponta para um
    volume que sobrevive ao deploy) e os testes, que precisam de uma pasta
    descartável -- rodar a suíte NUNCA pode escrever no armazenamento real
    do operador (mesmo critério já adotado para `dados/` no teste de
    registro de correções, Fase 20).
    """
    global _raiz
    _raiz = caminho


def raiz() -> str:
    if _raiz is not None:
        return _raiz
    return os.environ.get("LEITOR_ARMAZENAMENTO") or _raiz_padrao()


def _validar_lote_id(lote_id: str) -> str:
    if not isinstance(lote_id, str) or not _LOTE_ID_VALIDO.match(lote_id):
        raise ValueError(f"lote_id inválido: {lote_id!r}")
    return lote_id


def pasta_lote(lote_id: str) -> str:
    return os.path.join(raiz(), _validar_lote_id(lote_id))


def pasta_entrada(lote_id: str) -> str:
    return os.path.join(pasta_lote(lote_id), _PASTA_ENTRADA)


def pasta_paginas(lote_id: str) -> str:
    return os.path.join(pasta_lote(lote_id), _PASTA_PAGINAS)


def criar_lote(lote_id: str) -> str:
    """Cria a estrutura de pastas do lote e devolve a pasta de entrada."""
    os.makedirs(pasta_entrada(lote_id), exist_ok=True)
    os.makedirs(pasta_paginas(lote_id), exist_ok=True)
    return pasta_entrada(lote_id)


# ---------------------------------------------------------------------------
# Nome de arquivo enviado pelo usuário
# ---------------------------------------------------------------------------

# Caracteres que o Windows recusa em nome de arquivo, mais os separadores de
# caminho. Não é uma lista de "caracteres perigosos" genérica: o objetivo é
# que o nome NUNCA consiga apontar para fora da pasta do lote e que o
# arquivo consiga de fato ser criado no Windows (onde o operador roda).
_CARACTERES_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
LIMITE_NOME_ARQUIVO = 120


def nome_seguro(nome: Optional[str], indice: int = 0) -> str:
    """
    Reduz um nome vindo do cliente a algo que só pode existir DENTRO da
    pasta do lote. `os.path.basename` sozinho não basta: ele não trata
    `..`, nem nomes reservados do Windows, nem caminho no formato da outra
    plataforma ("a/b.jpg" no Windows passa inteiro por `basename`).

    O nome é preservado sempre que possível porque ele aparece nas
    mensagens de erro que o operador lê ("Falha ao abrir 'b.jpg'") -- por
    isso não se troca tudo por um UUID.
    """
    bruto = (nome or "").strip()
    # Corta em QUALQUER separador, dos dois sistemas, antes do basename.
    bruto = bruto.replace("\\", "/").split("/")[-1]
    bruto = _CARACTERES_PROIBIDOS.sub("_", bruto)
    bruto = bruto.strip(". ")  # ".." e nomes terminados em ponto/espaço

    raiz_nome, extensao = os.path.splitext(bruto)
    # Nomes reservados do Windows (CON, PRN, NUL, COM1..9, LPT1..9) -- criar
    # um arquivo com esse nome falha ou faz algo inesperado.
    if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", raiz_nome, re.IGNORECASE):
        raiz_nome = f"_{raiz_nome}"

    if not raiz_nome:
        raiz_nome = f"arquivo_{indice}"

    return (raiz_nome[:LIMITE_NOME_ARQUIVO] + extensao[:16]) or f"arquivo_{indice}"


# ---------------------------------------------------------------------------
# Escrita atômica
# ---------------------------------------------------------------------------

# Serializa as escritas de um mesmo lote. Sem isto, a thread-motora e uma
# requisição HTTP podem persistir o mesmo lote ao mesmo tempo e gravar
# fotografias FORA DE ORDEM (a mais velha sobrescrevendo a mais nova).
# Um lock por lote, não um global: um lote grande sendo salvo não pode
# segurar a resposta de outro.
_travas_por_lote: Dict[str, threading.Lock] = {}
_trava_das_travas = threading.Lock()


def _trava_do_lote(lote_id: str) -> threading.Lock:
    with _trava_das_travas:
        return _travas_por_lote.setdefault(lote_id, threading.Lock())


def escrever_bytes_atomico(caminho: str, conteudo: bytes) -> None:
    """
    Escreve num arquivo temporário na MESMA pasta e troca com `os.replace`,
    que é atômico dentro de um sistema de arquivos. Sem isso, uma queda no
    meio da escrita deixaria um `estado.json` truncado -- ou seja, um lote
    que não volta a abrir. Com isso, ou o arquivo antigo continua inteiro,
    ou o novo já está inteiro; nunca um meio-termo.

    O nome do temporário carrega um sufixo ÚNICO por escrita. Não é
    detalhe: com um nome fixo (`caminho + ".tmp"`), duas escritas
    simultâneas do mesmo arquivo disputam o MESMO temporário e, no
    Windows, `os.replace` falha com `PermissionError [WinError 32]` --
    reproduzido de verdade durante esta sub-fase, com a thread-motora e
    uma requisição HTTP salvando o mesmo lote no mesmo instante.
    """
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = f"{caminho}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temporario, "wb") as saida:
            saida.write(conteudo)
            saida.flush()
            os.fsync(saida.fileno())
        os.replace(temporario, caminho)
    except Exception:
        # Não deixa o temporário para trás quando a troca falha.
        try:
            os.remove(temporario)
        except OSError:
            pass
        raise


def escrever_json_atomico(caminho: str, dados) -> None:
    conteudo = json.dumps(dados, ensure_ascii=False, indent=None).encode("utf-8")
    escrever_bytes_atomico(caminho, conteudo)


def _ler_json(caminho: str):
    try:
        with open(caminho, "rb") as entrada:
            return json.loads(entrada.read().decode("utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        # Arquivo corrompido (queda antes do `os.replace` de uma versão
        # antiga, disco com problema). Tratar como ausente é a falha
        # segura: no pior caso a página é reprocessada.
        logging.exception("Arquivo de estado ilegível, ignorando: %s", caminho)
        return None


# ---------------------------------------------------------------------------
# Estado do lote / Job
# ---------------------------------------------------------------------------

def gravar_estado(lote_id: str, dados: Dict) -> None:
    with _trava_do_lote(lote_id):
        escrever_json_atomico(os.path.join(pasta_lote(lote_id), _ARQUIVO_ESTADO), dados)


def ler_estado(lote_id: str) -> Optional[Dict]:
    return _ler_json(os.path.join(pasta_lote(lote_id), _ARQUIVO_ESTADO))


def gravar_registros(lote_id: str, registros: List[Dict]) -> None:
    with _trava_do_lote(lote_id):
        escrever_json_atomico(os.path.join(pasta_lote(lote_id), _ARQUIVO_REGISTROS), registros)


def ler_registros(lote_id: str) -> Optional[List[Dict]]:
    return _ler_json(os.path.join(pasta_lote(lote_id), _ARQUIVO_REGISTROS))


# ---------------------------------------------------------------------------
# Resultado de OCR por página (o trabalho caro)
# ---------------------------------------------------------------------------

def _caminho_pagina(lote_id: str, numero: int) -> str:
    return os.path.join(pasta_paginas(lote_id), f"{int(numero):04d}.json")


def caminho_miniatura(lote_id: str, numero: int) -> str:
    return os.path.join(pasta_paginas(lote_id), f"{int(numero):04d}.jpg")


def gravar_pagina(lote_id: str, numero: int, dados: Dict) -> None:
    """
    Grava o que o OCR leu numa página, ANTES de classificar. É esta gravação
    que torna a retomada barata (ver o cabeçalho do módulo): quando um Job
    é devolvido à fila, só as páginas que faltam voltam para o Worker.
    """
    escrever_json_atomico(_caminho_pagina(lote_id, numero), dados)


def ler_pagina(lote_id: str, numero: int) -> Optional[Dict]:
    return _ler_json(_caminho_pagina(lote_id, numero))


def paginas_persistidas(lote_id: str) -> set:
    """Números das páginas cujo OCR já está salvo em disco."""
    try:
        nomes = os.listdir(pasta_paginas(lote_id))
    except OSError:
        return set()
    numeros = set()
    for nome in nomes:
        raiz_nome, extensao = os.path.splitext(nome)
        if extensao == ".json" and raiz_nome.isdigit():
            numeros.add(int(raiz_nome))
    return numeros


def gravar_miniatura(lote_id: str, numero: int, conteudo: bytes) -> bool:
    """
    A foto é comodidade da revisão, não dado (mesma regra desde a Fase 10):
    falhar aqui nunca pode derrubar o processamento da página, então o
    retorno é booleano e nenhuma exceção escapa.
    """
    try:
        escrever_bytes_atomico(caminho_miniatura(lote_id, numero), conteudo)
        return True
    except Exception:
        logging.exception("Falha ao gravar a miniatura da página %s do lote %s", numero, lote_id)
        return False


def ler_miniatura(lote_id: str, numero: int) -> Optional[bytes]:
    try:
        with open(caminho_miniatura(lote_id, numero), "rb") as entrada:
            return entrada.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Varredura e retenção
# ---------------------------------------------------------------------------

def listar_lotes() -> List[str]:
    """Ids de lote presentes no disco (a fonte de verdade após um restart)."""
    try:
        nomes = os.listdir(raiz())
    except OSError:
        return []
    return [nome for nome in nomes if _LOTE_ID_VALIDO.match(nome)
            and os.path.isdir(os.path.join(raiz(), nome))]


def remover_lote(lote_id: str) -> None:
    shutil.rmtree(pasta_lote(lote_id), ignore_errors=True)


def aplicar_retencao(dias: int = DIAS_RETENCAO_PADRAO) -> List[str]:
    """
    Apaga lotes mais velhos que `dias`, usando o `criado_em` gravado no
    próprio `estado.json` (não a data do sistema de arquivos, que um
    backup/rsync altera). Devolve os ids removidos. Nunca levanta: uma
    falha de limpeza não pode impedir o servidor de subir.
    """
    limite = time.time() - dias * 86400
    removidos = []
    for lote_id in listar_lotes():
        try:
            dados = ler_estado(lote_id)
            criado_em = (dados or {}).get("criado_em")
            if criado_em is None:
                # Sem estado legível não há o que revisar nem exportar --
                # é lixo de um lote que nunca chegou a ser gravado.
                criado_em = os.path.getmtime(pasta_lote(lote_id))
            if criado_em < limite:
                remover_lote(lote_id)
                removidos.append(lote_id)
        except Exception:
            logging.exception("Falha ao aplicar retenção ao lote %s", lote_id)
    return removidos
