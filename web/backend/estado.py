"""
web/backend/estado.py

Estado do backend, desenhado em torno de `lote_id` -- NUNCA um "lote atual"
global solto no processo (o jeito como o Tkinter funciona, com uma única
`App()` viva por vez). É o que permite, numa extensão futura, isolar lotes
por usuário sem reescrever nenhum endpoint.

FASE 26a -- ESTE MÓDULO É O LADO "VPS" DA DIVISÃO
-------------------------------------------------
Até a Fase 25 este arquivo fazia as duas metades do trabalho: rodava o OCR
E classificava o resultado. A Fase 26 separa as duas, porque só a primeira
é cara:

    ── Worker (PC Windows, `web/backend/produtor_ocr.py` hoje; um processo
       remoto a partir da Sub-fase 26c) ────────────────────────────────
    1. renderizar/ler a imagem da folha           cv2 / PyMuPDF
    2. pipeline.processar_uma_pagina(...)          PaddleOCR (~40 s/folha)
    3. comprimir a foto da página                  cv2
    ── VPS (este módulo) ─────────────────────────────────────────────────
    4. contexto_lote.registrar_data(...)           barato
    5. pipeline.montar_registro_exportacao(...)    barato, precisa de dados/*.xlsx
    6. verificar_contagem_posicoes(...)            barato

O que atravessa a fronteira é `List[Registro]` -- dataclass de folhas
JSON-safe (ver `registro_parser.Registro.como_dicionario`). As REGRAS DE
NEGÓCIO e as planilhas de referência nunca saem da VPS: o Worker lê a
folha, ele não decide nada sobre ela.

POR QUE O LAÇO DE PÁGINAS NÃO FOI REESCRITO
-------------------------------------------
`processar_lote` continua sendo uma thread que percorre as páginas EM
ORDEM, uma de cada vez -- só que agora, em vez de chamar o OCR, ela espera
o resultado da página N chegar (`_aguardar_resultado_pagina`). Isso não é
detalhe de implementação, é o que preserva três invariantes que uma fila
sem ordem quebraria em silêncio:

  * a ordem FÍSICA das folhas na planilha (requisito da Fase 2);
  * o `ContextoLote`, que é DEPENDENTE DE PREFIXO -- `ano_do_lote()`
    decide contra o que foi registrado ATÉ ALI (`MINIMO_DATAS_CONFIAVEIS`,
    `FATOR_PREDOMINANCIA`). Trocar a ordem de chegada faz o ano ser eleito
    numa página diferente e muda a classificação de linhas reais;
  * os índices posicionais de `registros`, que `POST /registros/{indice}/
    confirmar` e `explicacao_revisao.sinais_de_contexto` usam -- este
    último inclusive OLHA OS VIZINHOS.

Quem chega fora de ordem simplesmente fica no buffer até a sua vez.
"""
import dataclasses
import logging
import os
import threading
import time
import uuid
from typing import Dict, List, Optional, Set

from leitor_matriculas import pipeline
from leitor_matriculas.dados.data_manager import DataManager
from leitor_matriculas.ocr import pdf_reader
from leitor_matriculas.parsing.contexto_lote import ContextoLote
from leitor_matriculas.parsing.registro_parser import Registro, verificar_contagem_posicoes

from . import armazenamento

# Vocabulário PÚBLICO de status -- o que o frontend conhece. Preservado
# exatamente como estava antes da Fase 26 (`PaginaLote.jsx` trata
# "concluido"/"erro" como terminais e qualquer outra coisa como "ainda
# rodando"), com uma única adição: `cancelado`, que só é alcançável por
# cancelamento explícito e nunca aparece no fluxo normal.
STATUS_PENDENTE = "pendente"
STATUS_PROCESSANDO = "processando"
STATUS_CONCLUIDO = "concluido"
STATUS_ERRO = "erro"
STATUS_CANCELADO = "cancelado"

STATUS_TERMINAIS = {STATUS_CONCLUIDO, STATUS_ERRO, STATUS_CANCELADO}

# Ciclo de vida INTERNO do Job perante os Workers. Deliberadamente separado
# do `status` público: são perguntas diferentes ("o que o usuário vê" vs.
# "quem está com este trabalho"), e misturá-las obrigaria o frontend a
# aprender estados que não mudam nada para ele.
FASE_LOCAL = "local"                        # produzido no próprio processo (modo desktop/dev)
FASE_AGUARDANDO_WORKER = "aguardando_worker"
FASE_ATRIBUIDO = "atribuido"
FASE_PROCESSANDO = "processando"

TIPO_PDF = "pdf"
TIPO_IMAGENS = "imagens"

# Fase 26a: quanto a thread-motora espera acordar para reavaliar se o lote
# foi cancelado / o lease expirou. Não é um timeout de página -- uma página
# pode legitimamente levar minutos.
_INTERVALO_REAVALIACAO_S = 1.0


@dataclasses.dataclass
class LoteState:
    id: str
    tipo: str  # TIPO_PDF | TIPO_IMAGENS
    caminhos: List[str]
    pasta_temp: str  # a pasta durável do lote (ver web/backend/armazenamento.py)
    status: str = STATUS_PENDENTE
    etapa_atual: str = ""
    pagina_atual: int = 0
    paginas_processadas: int = 0
    total_paginas: Optional[int] = None
    erro_fatal: Optional[str] = None
    registros: List[dict] = dataclasses.field(default_factory=list)
    erros_paginas: List[dict] = dataclasses.field(default_factory=list)
    avisos_contagem: List[dict] = dataclasses.field(default_factory=list)
    avisos_descarte: List[dict] = dataclasses.field(default_factory=list)
    # Contexto do lote (Fase 9): nunca compartilhado entre lotes -- cada
    # LoteState tem o seu, criado junto com o lote e nunca reaproveitado.
    contexto_lote: ContextoLote = dataclasses.field(default_factory=ContextoLote)
    criado_em: float = dataclasses.field(default_factory=time.time)

    # -- Fase 26a: Job perante os Workers --------------------------------
    fase_worker: str = FASE_LOCAL
    worker_id: Optional[str] = None
    # Ficha de cerca (fencing token). Cada reivindicação incrementa este
    # número. Um Worker cujo lease expirou continua VIVO e vai continuar
    # postando páginas de um Job que já pertence a outra tentativa -- sem
    # este contador, essas páginas seriam aceitas e corromperiam o
    # `ContextoLote` (não só desperdiçariam trabalho).
    tentativa: int = 0
    lease_ate: Optional[float] = None
    ultimo_heartbeat: Optional[float] = None
    # Fase 26b: relógio SEPARADO do heartbeat -- o heartbeat prova que o
    # PROCESSO do Worker está vivo; este prova que ele está PRODUZINDO. Um
    # processo pode heartbeat normalmente com o OCR travado (D6 do plano
    # desta fase); é para pegar esse caso que este campo existe. Atualizado
    # a cada página aceita, a cada aviso de progresso e a cada claim/
    # reivindicação -- nunca por uma simples consulta de status.
    ultimo_progresso: Optional[float] = None

    # Buffer de resultados de página que já chegaram mas cuja vez ainda não
    # chegou (ver o cabeçalho do módulo).
    resultados_pagina: Dict[int, dict] = dataclasses.field(default_factory=dict)
    # Páginas já ACEITAS (deduplicação). Consultado sob o mesmo lock que
    # guarda `contexto_lote.registrar_data` -- se a checagem ficasse fora,
    # um reenvio contaria o ano duas vezes e deslocaria `ano_do_lote()`.
    paginas_recebidas: Set[int] = dataclasses.field(default_factory=set)
    parar: bool = False

    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
    condicao: threading.Condition = dataclasses.field(default=None)

    def __post_init__(self):
        # A Condition compartilha o MESMO lock que já protegia os
        # contadores: assim `with estado.lock` continua valendo em todo
        # lugar e a espera da thread-motora solta o lock enquanto dorme.
        if self.condicao is None:
            self.condicao = threading.Condition(self.lock)

    # -- Leitura pública -------------------------------------------------

    def status_publico(self) -> dict:
        with self.lock:
            return {
                "lote_id": self.id,
                "tipo": self.tipo,
                "status": self.status,
                "etapa_atual": self.etapa_atual,
                "pagina_atual": self.pagina_atual,
                "total_paginas": self.total_paginas,
                "paginas_processadas": self.paginas_processadas,
                "paginas_com_erro": len(self.erros_paginas),
                "total_registros": len(self.registros),
                "erro_fatal": self.erro_fatal,
            }

    def registros_publicos(self) -> List[dict]:
        with self.lock:
            # Cópia rasa: cada dict de registro não é mutado in-place por
            # este módulo depois de anexado (só por `confirmar_revisao_
            # manual`, que passa pelo router, nunca por aqui) -- copiar a
            # LISTA já basta para o cliente não ver o array crescendo no
            # meio da leitura.
            return list(self.registros)

    def obter_miniatura(self, numero_pagina: int) -> Optional[bytes]:
        """
        Fase 26a: a foto passou a ser lida do DISCO em vez de um dicionário
        em memória. Duas razões, as duas medidas antes: quem produz a foto
        agora é outro processo (não teria como escrever num dict deste), e
        o dicionário crescia sem limite pela vida do processo -- um lote de
        ~50 folhas segurava dezenas de MB que ninguém mais lia depois da
        revisão. Custa alguns milissegundos por requisição contra ~40 s de
        OCR por página.
        """
        return armazenamento.ler_miniatura(self.id, numero_pagina)

    # -- Persistência ----------------------------------------------------

    def como_dicionario(self) -> dict:
        """Fotografia serializável do Job. Chamado sempre COM o lock tomado."""
        return {
            "id": self.id,
            "tipo": self.tipo,
            "caminhos": self.caminhos,
            "status": self.status,
            "etapa_atual": self.etapa_atual,
            "pagina_atual": self.pagina_atual,
            "paginas_processadas": self.paginas_processadas,
            "total_paginas": self.total_paginas,
            "erro_fatal": self.erro_fatal,
            "erros_paginas": self.erros_paginas,
            "avisos_contagem": self.avisos_contagem,
            "avisos_descarte": self.avisos_descarte,
            "contexto_lote": self.contexto_lote.como_dicionario(),
            "criado_em": self.criado_em,
            "fase_worker": self.fase_worker,
            "worker_id": self.worker_id,
            "tentativa": self.tentativa,
            "lease_ate": self.lease_ate,
            "ultimo_heartbeat": self.ultimo_heartbeat,
            "ultimo_progresso": self.ultimo_progresso,
            "paginas_recebidas": sorted(self.paginas_recebidas),
        }

    @classmethod
    def de_dicionario(cls, dados: dict, pasta: str) -> "LoteState":
        estado = cls(
            id=dados["id"],
            tipo=dados.get("tipo", TIPO_IMAGENS),
            caminhos=list(dados.get("caminhos") or []),
            pasta_temp=pasta,
            status=dados.get("status", STATUS_PENDENTE),
            etapa_atual=dados.get("etapa_atual", ""),
            pagina_atual=dados.get("pagina_atual", 0),
            paginas_processadas=dados.get("paginas_processadas", 0),
            total_paginas=dados.get("total_paginas"),
            erro_fatal=dados.get("erro_fatal"),
            erros_paginas=list(dados.get("erros_paginas") or []),
            avisos_contagem=list(dados.get("avisos_contagem") or []),
            avisos_descarte=list(dados.get("avisos_descarte") or []),
            contexto_lote=ContextoLote.de_dicionario(dados.get("contexto_lote")),
            criado_em=dados.get("criado_em", time.time()),
            fase_worker=dados.get("fase_worker", FASE_LOCAL),
            worker_id=dados.get("worker_id"),
            tentativa=dados.get("tentativa", 0),
            lease_ate=dados.get("lease_ate"),
            ultimo_heartbeat=dados.get("ultimo_heartbeat"),
            ultimo_progresso=dados.get("ultimo_progresso"),
            paginas_recebidas=set(dados.get("paginas_recebidas") or []),
        )
        estado.registros = armazenamento.ler_registros(estado.id) or []
        return estado


def persistir(estado: LoteState, com_registros: bool = False) -> None:
    """
    Grava o estado do Job. `com_registros=True` também reescreve
    `registros.json` -- feito ao concluir e a cada confirmação manual, NÃO
    a cada página: durante o processamento quem garante a durabilidade é
    `paginas/NNN.json` (o resultado caro do OCR), e reescrever a lista
    inteira a cada página seria trabalho de disco quadrático num lote de
    200 folhas sem proteger nada que já não esteja protegido.
    """
    try:
        with estado.lock:
            dados = estado.como_dicionario()
            registros = list(estado.registros) if com_registros else None
        armazenamento.gravar_estado(estado.id, dados)
        if registros is not None:
            armazenamento.gravar_registros(estado.id, registros)
    except Exception:
        # Nunca derruba o processamento: perder a durabilidade é ruim, mas
        # perder o lote que está rodando é pior (mesmo critério da
        # miniatura na Fase 10 e do histórico de correções na Fase 20).
        logging.exception("Falha ao persistir o estado do lote %s", estado.id)


# ---------------------------------------------------------------------------
# Registro de lotes e singletons de processo
# ---------------------------------------------------------------------------

_lotes: Dict[str, LoteState] = {}
_lotes_trava = threading.Lock()

_engine_trava = threading.Lock()
_ocr_engine = None
_data_manager_trava = threading.Lock()
_data_manager: Optional[DataManager] = None


def _pasta_dados_ao_lado_do_executavel() -> Optional[str]:
    """
    Sub-fase 25b (empacotamento com PyInstaller): `DataManager()` sem
    argumento resolve `dados/` a partir do PRÓPRIO `__file__` de
    `data_manager.py`, três níveis acima -- correto rodando do
    repositório, errado (ou pior, silenciosamente errado) dentro de um
    `.exe`. `os.path.dirname(sys.executable)` é a forma robusta e igual
    nos dois modos (`--onedir` e `--onefile`). Fora de um build congelado
    devolve `None` e nada muda.
    """
    import sys

    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "dados")
    return None


def obter_data_manager() -> DataManager:
    """Instância única por processo -- ver docstring do módulo."""
    global _data_manager
    # Fase 26a: o lock estava faltando aqui (só `obter_ocr_engine` tinha).
    # As rotas síncronas do FastAPI rodam no threadpool, então duas
    # requisições simultâneas num processo frio construíam DOIS
    # DataManager, relendo as três planilhas em paralelo.
    with _data_manager_trava:
        if _data_manager is None:
            _data_manager = DataManager(pasta_dados=_pasta_dados_ao_lado_do_executavel())
        return _data_manager


def obter_ocr_engine():
    """Instância única por processo, carregada sob demanda na primeira
    página que qualquer lote processar."""
    global _ocr_engine
    with _engine_trava:
        if _ocr_engine is None:
            from leitor_matriculas.ocr.engine import get_ocr_engine

            _ocr_engine = get_ocr_engine("paddleocr")
        return _ocr_engine


def reservar_lote_id() -> str:
    return uuid.uuid4().hex


def criar_lote(tipo: str, caminhos: List[str], pasta_temp: str, lote_id: Optional[str] = None) -> LoteState:
    estado = LoteState(
        id=lote_id or reservar_lote_id(), tipo=tipo, caminhos=caminhos, pasta_temp=pasta_temp
    )
    with _lotes_trava:
        _lotes[estado.id] = estado
    persistir(estado)
    return estado


def obter_lote(lote_id: str) -> Optional[LoteState]:
    with _lotes_trava:
        estado = _lotes.get(lote_id)
    if estado is not None:
        return estado
    return _recuperar_do_disco(lote_id)


def _recuperar_do_disco(lote_id: str) -> Optional[LoteState]:
    """
    Um lote que não está em memória pode existir em disco -- é o caso
    depois de um reinício do backend. Reidrata sob demanda em vez de
    carregar tudo no boot: um lote antigo que ninguém vai abrir não
    precisa ocupar memória.
    """
    try:
        dados = armazenamento.ler_estado(lote_id)
    except ValueError:
        return None  # lote_id malformado (veio da URL)
    if not dados:
        return None
    estado = LoteState.de_dicionario(dados, armazenamento.pasta_lote(lote_id))
    with _lotes_trava:
        # Outra thread pode ter reidratado o mesmo lote enquanto líamos.
        return _lotes.setdefault(lote_id, estado)


def recuperar_lotes_do_disco() -> Dict[str, int]:
    """
    Varredura de inicialização. Faz duas coisas que o backend nunca fez:
    aplica retenção (antes os uploads iam para `tempfile`, e quem limpava
    era o sistema operacional) e devolve à fila todo Job que ficou preso em
    `processando` -- o caso real de o processo ter morrido no meio do lote,
    que antes deixava o `status` congelado para sempre, sem forma de
    recuperar.
    """
    resumo = {"recuperados": 0, "reenfileirados": 0, "removidos": 0}
    try:
        resumo["removidos"] = len(armazenamento.aplicar_retencao())
        for lote_id in armazenamento.listar_lotes():
            dados = armazenamento.ler_estado(lote_id)
            if not dados:
                continue
            resumo["recuperados"] += 1
            if dados.get("status") == STATUS_PROCESSANDO:
                estado = _recuperar_do_disco(lote_id)
                if estado is None:
                    continue
                reenfileirar(estado, "o servidor foi reiniciado durante o processamento")
                resumo["reenfileirados"] += 1
    except Exception:
        logging.exception("Falha na varredura de inicialização do armazenamento")
    return resumo


# ---------------------------------------------------------------------------
# Fila / lease / fencing (o lado do Job que os Workers enxergam)
# ---------------------------------------------------------------------------

# Batidas de heartbeat perdidas antes de considerar o Worker morto. O
# heartbeat é uma thread PRÓPRIA do Worker, independente do laço de OCR --
# por isso o lease pode ser curto sem ser sensível à duração de uma página
# (que legitimamente passa de 40 s, e muito mais no primeiro carregamento
# do modelo do PaddleOCR).
INTERVALO_HEARTBEAT_S = 30.0
LEASE_S = 120.0
# Detector separado, para o caso que o heartbeat NÃO pega: processo vivo,
# batendo normalmente, com o OCR travado. Medido contra o avanço de
# `paginas_processadas`, não contra o relógio de heartbeat.
LIMITE_SEM_PROGRESSO_S = 600.0


def enfileirar(estado: LoteState) -> None:
    """Coloca o Job à disposição dos Workers."""
    with estado.lock:
        estado.status = STATUS_PROCESSANDO
        estado.fase_worker = FASE_AGUARDANDO_WORKER
        estado.etapa_atual = "Aguardando um computador de leitura ficar disponível"
        estado.parar = False
    persistir(estado)


def reenfileirar(estado: LoteState, motivo: str) -> None:
    """
    Devolve um Job à fila. As páginas cujo OCR já está em disco NÃO são
    perdidas -- `paginas_pendentes` só devolve o que falta. É por isso que
    um lease expirado custa segundos e não horas.

    A `tentativa` é incrementada: qualquer chamada do Worker anterior
    passa a ser rejeitada (ver o comentário do campo) -- essa rejeição
    acontece em `depositar_resultado_pagina`/`tentativa_valida`, contra o
    valor ATUAL de `estado.tentativa`, nunca contra um valor congelado.

    NÃO mexe em `estado.parar`. A thread-motora (`processar_lote`) é uma
    ÚNICA thread por Job, do início ao fim -- ela só espera páginas
    aparecerem (`_aguardar_resultado_pagina`), sem nenhuma noção de QUEM
    as produziu; a ficha de cerca é inteiramente um cuidado do lado
    PRODUTOR (rejeitar quem não é mais dono), não do lado consumidor.
    Interromper a motora aqui já foi tentado e quebrava o caso mais
    simples de todos: a PRIMEIRA reivindicação de um Job também incrementa
    `tentativa` (0 -> 1, ver `reivindicar`), e uma motora que abortasse
    nisso nunca aplicaria página nenhuma -- reproduzido durante esta
    sub-fase, não hipotético (ver `teste_worker_api.py`, Bloco 6).
    `estado.parar` continua existindo só para `cancelar()`.
    """
    with estado.lock:
        estado.tentativa += 1
        estado.worker_id = None
        estado.lease_ate = None
        estado.ultimo_heartbeat = None
        estado.fase_worker = FASE_AGUARDANDO_WORKER
        estado.status = STATUS_PROCESSANDO
        estado.etapa_atual = f"Retomando o processamento ({motivo})"
        estado.condicao.notify_all()
    persistir(estado)


def paginas_pendentes(estado: LoteState) -> List[int]:
    """Páginas que ainda não têm resultado de OCR gravado em disco."""
    ja_temos = armazenamento.paginas_persistidas(estado.id)
    with estado.lock:
        total = estado.total_paginas or 0
    return [n for n in range(1, total + 1) if n not in ja_temos]


def lease_expirado(estado: LoteState, agora: Optional[float] = None) -> bool:
    agora = agora or time.time()
    with estado.lock:
        if estado.fase_worker not in (FASE_ATRIBUIDO, FASE_PROCESSANDO):
            return False
        return estado.lease_ate is not None and estado.lease_ate < agora


def cancelar(estado: LoteState) -> None:
    with estado.lock:
        if estado.status in STATUS_TERMINAIS:
            return
        estado.status = STATUS_CANCELADO
        estado.etapa_atual = ""
        estado.parar = True
        # Mesma limpeza que a conclusão normal já faz (ver o fim de
        # `processar_lote`) -- sem isto, um lote cancelado ainda em
        # `FASE_AGUARDANDO_WORKER`/`FASE_ATRIBUIDO` continuaria contando
        # como "esperando" ou "em processamento" em `resumo_jobs`, e um
        # Worker que ainda não soube do cancelamento continuaria "dono"
        # de um Job que não existe mais para efeitos práticos.
        estado.fase_worker = FASE_LOCAL
        estado.worker_id = None
        estado.lease_ate = None
        estado.condicao.notify_all()
    persistir(estado, com_registros=True)


# ---------------------------------------------------------------------------
# Fase 26b: registro, claim atômico e renovação de lease -- o que os
# endpoints de `rotas/worker.py` chamam. Nada aqui decide OCR nem
# classificação; é só o protocolo de "quem está com qual Job".
# ---------------------------------------------------------------------------

def proximo_job_disponivel() -> Optional[str]:
    """
    O `lote_id` mais antigo aguardando um Worker, ou `None`. Só olha
    `_lotes` em memória -- suficiente porque todo Job que pode ser
    reivindicado já está lá: `criar_lote`/`enfileirar` colocam o lote em
    `_lotes` na hora, e a varredura de inicialização já reidrata para
    `_lotes` qualquer Job que estava em andamento antes de um reinício.
    """
    with _lotes_trava:
        candidatos = list(_lotes.values())
    disponiveis = []
    for estado in candidatos:
        with estado.lock:
            if estado.fase_worker == FASE_AGUARDANDO_WORKER and estado.status == STATUS_PROCESSANDO:
                disponiveis.append((estado.criado_em, estado.id))
    if not disponiveis:
        return None
    disponiveis.sort()
    return disponiveis[0][1]


def resumo_jobs() -> Dict[str, int]:
    """Contagens agregadas para `GET /api/worker/status` -- não vaza
    `_lotes`/`_lotes_trava` para fora deste módulo; quem monta a resposta
    HTTP só lê o dicionário devolvido aqui."""
    with _lotes_trava:
        candidatos = list(_lotes.values())
    aguardando = em_processamento = concluidos = 0
    for estado in candidatos:
        with estado.lock:
            # Mesma dupla condição de `proximo_job_disponivel` -- `fase_
            # worker` sozinho não basta (um lote cancelado só é limpo em
            # `cancelar`, e checar `status` também é o que evita depender
            # só disso).
            if estado.fase_worker == FASE_AGUARDANDO_WORKER and estado.status == STATUS_PROCESSANDO:
                aguardando += 1
            elif estado.fase_worker in (FASE_ATRIBUIDO, FASE_PROCESSANDO) and estado.status == STATUS_PROCESSANDO:
                em_processamento += 1
            elif estado.status == STATUS_CONCLUIDO:
                concluidos += 1
    return {
        "jobs_aguardando_worker": aguardando,
        "jobs_em_processamento": em_processamento,
        "jobs_concluidos_recentes": concluidos,
    }


def reivindicar(estado: LoteState, worker_id: str) -> Optional[int]:
    """
    Claim atômico: só sai `FASE_AGUARDANDO_WORKER` para o worker que
    chegou primeiro. Devolve a `tentativa` (a ficha de cerca desta
    reivindicação) em caso de sucesso, ou `None` se o Job já não estava
    mais disponível (outro Worker chegou antes -- quem chama devolve 409 e
    o cliente tenta `GET /jobs/next` de novo).
    """
    agora = time.time()
    with estado.lock:
        if estado.fase_worker != FASE_AGUARDANDO_WORKER:
            return None
        estado.tentativa += 1
        estado.worker_id = worker_id
        estado.fase_worker = FASE_ATRIBUIDO
        estado.lease_ate = agora + LEASE_S
        estado.ultimo_heartbeat = agora
        estado.ultimo_progresso = agora
        estado.etapa_atual = "Um computador de leitura assumiu esta folha"
        tentativa = estado.tentativa
    persistir(estado)
    return tentativa


def tentativa_valida(estado: LoteState, worker_id: str, tentativa: int) -> bool:
    """
    Confere a ficha de cerca E o `worker_id`. As duas juntas: a ficha
    sozinha impediria um Worker zumbi de uma tentativa VELHA, mas não
    impediria um Worker totalmente ALHEIO de adulterar o Job de outro
    dizendo "tentativa 1" por acaso -- ele precisa ser, ao mesmo tempo, o
    dono ATUAL do Job.
    """
    with estado.lock:
        return (
            estado.fase_worker in (FASE_ATRIBUIDO, FASE_PROCESSANDO)
            and estado.worker_id == worker_id
            and estado.tentativa == tentativa
        )


def renovar_lease(estado: LoteState, worker_id: str, tentativa: int) -> bool:
    """
    Chamado pelo heartbeat do Worker (independente do laço de OCR -- ver
    D6 no relatório desta fase) e, de bônus, por qualquer chamada de
    progresso/entrega de página, já que estas também provam que o Worker
    está vivo. Devolve `False` sem renovar nada quando o chamador não é
    mais o dono do Job (lease já expirado e reenfileirado, ou nunca foi o
    dono) -- o Worker deve então parar de trabalhar nesse Job.
    """
    if not tentativa_valida(estado, worker_id, tentativa):
        return False
    agora = time.time()
    with estado.lock:
        estado.lease_ate = agora + LEASE_S
        estado.ultimo_heartbeat = agora
        if estado.fase_worker == FASE_ATRIBUIDO:
            # Primeira atividade real após o claim -- passa a PROCESSANDO
            # (só cosmético para quem observa o Job; a thread-motora não
            # depende disso).
            estado.fase_worker = FASE_PROCESSANDO
    persistir(estado)
    return True


def registrar_progresso_worker(estado: LoteState, worker_id: str, tentativa: int) -> None:
    """Marca `ultimo_progresso` -- separado do heartbeat de propósito (ver
    o campo em `LoteState`). Chamado a cada entrega de página aceita e a
    cada aviso explícito de progresso do Worker."""
    if not tentativa_valida(estado, worker_id, tentativa):
        return
    with estado.lock:
        estado.ultimo_progresso = time.time()


def liberar_apos_producao(estado: LoteState, worker_id: str, tentativa: int) -> bool:
    """
    O Worker sinaliza que já entregou todas as páginas que ia entregar
    (`POST /jobs/{id}/concluir`). Isto NÃO conclui o Job -- quem decide
    isso é a thread-motora, ao aplicar a última página -- só libera a
    "posse" perante outros Workers, para o campo `fase_worker` não ficar
    mostrando um dono que já terminou o trabalho dele.
    """
    if not tentativa_valida(estado, worker_id, tentativa):
        return False
    with estado.lock:
        if estado.fase_worker in (FASE_ATRIBUIDO, FASE_PROCESSANDO):
            estado.fase_worker = FASE_LOCAL
    persistir(estado)
    return True


def marcar_falha_de_documento(estado: LoteState, worker_id: str, tentativa: int, mensagem: str) -> bool:
    """
    Falha do DOCUMENTO INTEIRO (arquivo que não abre, PDF sem páginas) --
    equivalente ao que `produtor_ocr.produzir` já isolava quando rodava
    localmente. A thread-motora está esperando páginas que nunca vão
    chegar, então o Job precisa ser marcado aqui, não só a página.
    """
    if not tentativa_valida(estado, worker_id, tentativa):
        return False
    with estado.lock:
        estado.status = STATUS_ERRO
        estado.erro_fatal = mensagem
        estado.parar = True
        estado.condicao.notify_all()
    persistir(estado, com_registros=True)
    return True


def varrer_leases_expirados(agora: Optional[float] = None) -> List[str]:
    """
    Devolve à fila todo Job cujo lease expirou OU cuja produção estagnou
    (dois relógios independentes -- ver D6). Função PURA de varredura, sem
    laço/sleep -- testável diretamente, sem esperar o relógio de verdade
    passar. Quem faz o laço com intervalo é `_vigiar_leases_em_thread`,
    abaixo, chamada pela thread de fundo do processo.
    """
    agora = agora or time.time()
    with _lotes_trava:
        candidatos = list(_lotes.values())
    reenfileirados = []
    for estado in candidatos:
        with estado.lock:
            em_posse = estado.fase_worker in (FASE_ATRIBUIDO, FASE_PROCESSANDO)
            lease_venceu = em_posse and estado.lease_ate is not None and estado.lease_ate < agora
            referencia_progresso = estado.ultimo_progresso or estado.criado_em
            sem_progresso = (
                em_posse and estado.fase_worker == FASE_PROCESSANDO
                and (agora - referencia_progresso) > LIMITE_SEM_PROGRESSO_S
            )
        if lease_venceu:
            reenfileirar(estado, "o computador de leitura parou de responder")
            reenfileirados.append(estado.id)
        elif sem_progresso:
            reenfileirar(estado, "o computador de leitura ficou muito tempo sem enviar novidade")
            reenfileirados.append(estado.id)
    return reenfileirados


_vigia_lock = threading.Lock()
_vigia_iniciada = False
_vigia_parar = threading.Event()

# Intervalo entre varreduras -- bem menor que `LEASE_S`/`LIMITE_SEM_
# PROGRESSO_S` para que a detecção nunca atrase por mais que este valor.
_INTERVALO_VIGIA_S = 15.0


def _vigiar_leases_em_thread() -> None:
    while not _vigia_parar.wait(timeout=_INTERVALO_VIGIA_S):
        try:
            varrer_leases_expirados()
        except Exception:
            logging.exception("Falha na varredura de leases expirados")


def iniciar_vigilante_de_leases() -> None:
    """
    Sobe a thread de fundo que aplica `varrer_leases_expirados`
    periodicamente. Idempotente -- chamado a cada `startup` do FastAPI, e
    os testes de backend criam um `TestClient(app)` por função, cada um
    disparando o evento de novo; sem a trava isto acumularia uma thread
    nova por teste.
    """
    global _vigia_iniciada
    with _vigia_lock:
        if _vigia_iniciada:
            return
        _vigia_iniciada = True
    threading.Thread(target=_vigiar_leases_em_thread, daemon=True, name="vigia-leases").start()


# ---------------------------------------------------------------------------
# Entrega de resultados (chamada pelo produtor local hoje; pelo Worker a
# partir da Sub-fase 26b)
# ---------------------------------------------------------------------------

def depositar_resultado_pagina(estado: LoteState, numero: int, resultado: dict,
                               tentativa: Optional[int] = None) -> str:
    """
    Entrega o resultado do OCR de UMA página. Devolve:
        "aceito"     -- entrou no buffer, a thread-motora vai consumir
        "duplicado"  -- essa página já foi aceita (reenvio após queda de
                        conexão); no-op seguro, nunca conta duas vezes
        "obsoleto"   -- veio de uma tentativa anterior do Job (Worker
                        zumbi); recusado

    `resultado` traz `registros` (lista de `Registro.como_dicionario()`),
    `erro` (texto cru, SEM prefixo -- ver `_mensagem_erro_pagina`) e
    `fase_erro`.
    """
    with estado.lock:
        if tentativa is not None and tentativa != estado.tentativa:
            return "obsoleto"
        if numero in estado.paginas_recebidas:
            return "duplicado"
        estado.paginas_recebidas.add(numero)
        estado.resultados_pagina[numero] = resultado
        # Fase 26b: a entrega de uma página É produção -- prova de vida
        # independente do heartbeat (ver D6 e `LoteState.ultimo_progresso`).
        estado.ultimo_progresso = time.time()
        estado.condicao.notify_all()
    # Fora do lock: I/O de disco não precisa segurar quem está lendo status.
    try:
        armazenamento.gravar_pagina(estado.id, numero, resultado)
    except Exception:
        logging.exception("Falha ao persistir a página %s do lote %s", numero, estado.id)
    return "aceito"


def depositar_miniatura(estado: LoteState, numero: int, conteudo: bytes) -> bool:
    """A foto da folha. Canal separado do resultado de propósito: ela é
    comodidade da revisão, não dado -- uma falha aqui jamais pode custar o
    OCR daquela página, que levou ~40 s."""
    return armazenamento.gravar_miniatura(estado.id, numero, conteudo)


def registrar_etapa(estado: LoteState, texto: str) -> None:
    with estado.lock:
        estado.etapa_atual = texto


def registrar_total_paginas(estado: LoteState, total: int) -> None:
    with estado.lock:
        estado.total_paginas = total
        estado.condicao.notify_all()
    persistir(estado)


# ---------------------------------------------------------------------------
# Thread-motora: consome os resultados EM ORDEM e classifica
# ---------------------------------------------------------------------------

def _aguardar_resultado_pagina(estado: LoteState, numero: int) -> Optional[dict]:
    """
    Bloqueia até o resultado da página `numero` estar disponível -- vindo
    do buffer (acabou de chegar) ou do disco (já tinha chegado numa
    tentativa anterior, ou antes de um reinício do servidor).

    Devolve `None` quando o lote foi cancelado ou reenfileirado, para a
    thread-motora encerrar sem processar nada pela metade.
    """
    # Uma página já persistida dispensa qualquer espera -- é o caminho da
    # retomada barata (ver `reenfileirar`).
    persistida = armazenamento.ler_pagina(estado.id, numero)
    if persistida is not None:
        with estado.lock:
            estado.paginas_recebidas.add(numero)
            estado.resultados_pagina.pop(numero, None)
        return persistida

    with estado.condicao:
        while numero not in estado.resultados_pagina:
            if estado.parar or estado.status in STATUS_TERMINAIS:
                return None
            estado.condicao.wait(timeout=_INTERVALO_REAVALIACAO_S)
        return estado.resultados_pagina.pop(numero)


def _nome_do_arquivo(estado: LoteState, numero: int) -> str:
    if estado.tipo == TIPO_PDF:
        return os.path.basename(estado.caminhos[0]) if estado.caminhos else ""
    indice = numero - 1
    if 0 <= indice < len(estado.caminhos):
        return os.path.basename(estado.caminhos[indice])
    return ""


def _mensagem_erro_pagina(estado: LoteState, numero: int, erro: str, fase_erro: str) -> str:
    """
    As mensagens de erro continuam sendo FORMATADAS AQUI, na VPS, e não no
    Worker. Motivo: elas citam o nome do arquivo que o USUÁRIO enviou, e o
    Worker só tem uma cópia local com um nome que pode ter sido saneado.
    Manter a formatação aqui preserva as frases exatamente como estavam
    antes da Fase 26 (há teste que casa com elas).
    """
    nome = _nome_do_arquivo(estado, numero)
    if fase_erro == "renderizacao":
        return f"Falha ao renderizar a página {numero} de '{nome}': {erro}"
    if fase_erro == "leitura":
        return f"Falha ao abrir '{nome}': {erro}"
    prefixo = f"página {numero} de '{nome}'" if estado.tipo == TIPO_PDF else f"'{nome}'"
    return f"{prefixo}: {erro}"


def _aplicar_erro_de_pagina(estado: LoteState, numero: int, mensagem: str) -> None:
    """Mesma sequência de antes da Fase 26: a página vira UMA linha ERRO,
    entra na lista de erros e avança os contadores -- sem contexto do lote,
    sem classificação e sem aviso de contagem (uma página que falhou não
    tem contagem de posições a conferir)."""
    with estado.lock:
        estado.registros.append(pipeline.registro_erro_pagina(numero, mensagem))
        estado.erros_paginas.append({"pagina": numero, "mensagem": mensagem})
        estado.pagina_atual = numero
        estado.paginas_processadas += 1


def _aplicar_resultado_pagina(estado: LoteState, numero: int, resultado: dict) -> None:
    """A metade LEVE do pipeline -- exatamente a mesma sequência (e a mesma
    ordem) que `_processar_pagina_e_registrar` executava antes da Fase 26,
    só que a partir de `Registro`s que vieram serializados."""
    erro = resultado.get("erro")
    if erro:
        _aplicar_erro_de_pagina(
            estado, numero,
            _mensagem_erro_pagina(estado, numero, erro, resultado.get("fase_erro") or "pipeline"),
        )
        return

    try:
        registros = [Registro.de_dicionario(d) for d in (resultado.get("registros") or [])]
    except Exception as exc:
        _aplicar_erro_de_pagina(
            estado, numero,
            _mensagem_erro_pagina(estado, numero, f"resultado ilegível do leitor: {exc}", "pipeline"),
        )
        return

    # Contexto do lote ANTES de classificar (Fase 9) -- e sob o MESMO lock
    # que a deduplicação usa, para um reenvio nunca contar o ano duas vezes.
    with estado.lock:
        for registro in registros:
            campo_data = registro.campos.get("data")
            estado.contexto_lote.registrar_data(campo_data.texto if campo_data else "")

    dm = obter_data_manager()
    for registro in registros:
        registro_exportacao, aviso_sem_matricula = pipeline.montar_registro_exportacao(
            registro, numero, dm, estado.contexto_lote,
        )
        with estado.lock:
            estado.registros.append(registro_exportacao)
            if aviso_sem_matricula:
                estado.avisos_descarte.append({"pagina": numero, "mensagem": aviso_sem_matricula})

    aviso_contagem = verificar_contagem_posicoes(len(registros))
    with estado.lock:
        if aviso_contagem:
            estado.avisos_contagem.append({"pagina": numero, "mensagem": aviso_contagem})
        estado.pagina_atual = numero
        estado.paginas_processadas += 1


def _descobrir_total_paginas(estado: LoteState) -> int:
    """
    O total é calculado na VPS, não pedido ao Worker. Para imagens é
    `len(caminhos)`, de graça. Para PDF é `pdf_reader.contar_paginas` --
    que só abre o documento e lê o cabeçalho (a RENDERIZAÇÃO, essa sim
    cara, continua sendo trabalho do Worker). Mantém o PyMuPDF instalado
    na VPS, e em troca a barra de progresso mostra "Folha X de Y" desde o
    primeiro instante, como antes da Fase 26 -- pedir o total ao Worker
    deixaria o denominador vazio durante todo o download do arquivo.
    """
    if estado.tipo == TIPO_PDF:
        return pdf_reader.contar_paginas(estado.caminhos[0])
    return len(estado.caminhos)


def processar_lote(lote_id: str) -> None:
    """
    Thread-motora do Job: percorre as páginas EM ORDEM, espera o resultado
    de cada uma e classifica. Não roda OCR -- ver o cabeçalho do módulo.

    Uma ÚNICA thread por Job, do início ao fim -- nunca reiniciada, mesmo
    que o Job seja reenfileirado (`reenfileirar`) uma ou mais vezes no
    meio do caminho. A ficha de cerca (`tentativa`) é assunto do lado
    PRODUTOR (quem pode entregar página), não deste laço: ele só espera
    pacientemente a página N aparecer, não importa quem/quantas
    reivindicações tenham acontecido nesse meio tempo -- ver a nota em
    `reenfileirar` sobre por que uma versão anterior comparava `tentativa`
    aqui e quebrava a primeira reivindicação de todo Job.

    Uma falha inesperada aqui (fora do que já é isolado por página) marca o
    lote inteiro como STATUS_ERRO.
    """
    estado = obter_lote(lote_id)
    if estado is None:
        return
    with estado.lock:
        estado.status = STATUS_PROCESSANDO
        estado.parar = False

    try:
        total = _descobrir_total_paginas(estado)
        registrar_total_paginas(estado, total)

        for numero in range(1, total + 1):
            resultado = _aguardar_resultado_pagina(estado, numero)
            if resultado is None:
                # Cancelado -- sair sem concluir (ver `cancelar`; um
                # reenfileiramento NÃO cai aqui, a espera continua).
                return
            _aplicar_resultado_pagina(estado, numero, resultado)
            persistir(estado)

        with estado.lock:
            if estado.status in STATUS_TERMINAIS:
                return
            estado.status = STATUS_CONCLUIDO
            estado.etapa_atual = ""
            estado.fase_worker = FASE_LOCAL
            estado.worker_id = None
            estado.lease_ate = None
        persistir(estado, com_registros=True)
    except Exception as exc:
        logging.exception("Falha inesperada processando o lote %s", lote_id)
        with estado.lock:
            estado.status = STATUS_ERRO
            estado.erro_fatal = str(exc)
        persistir(estado, com_registros=True)
