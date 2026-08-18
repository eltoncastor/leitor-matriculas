"""
worker/heartbeat.py

Fase 26c. Prova de vida do PROCESSO do Worker, numa thread PRÓPRIA,
independente do laço de OCR -- exatamente o que o lado servidor já espera
desde a Sub-fase 26b (`LoteState.ultimo_heartbeat` vs. `ultimo_progresso`,
dois relógios separados; ver CLAUDE.md/`saida/auditoria_fase26_ocr_
worker.md`). Um heartbeat que só rodasse ENTRE páginas ficaria minutos
sem bater durante uma única folha demorada (~40 s, mais o carregamento do
modelo do PaddleOCR na primeira), e o lease (120 s no servidor) venceria
à toa, mesmo com o Worker vivo e trabalhando.
"""
import logging
import threading
from typing import Optional

from .cliente import ClienteWorker, ErroCliente

_LOG = logging.getLogger("worker.heartbeat")


class Heartbeat:
    """
    `definir_job`/`limpar_job` são chamados pelo laço principal
    (`worker/execucao.py`) ao reivindicar/terminar um Job -- a thread de
    heartbeat só lê esse estado, nunca decide nada sobre o Job em si.
    """

    def __init__(self, cliente: ClienteWorker, intervalo_s: float):
        self._cliente = cliente
        self._intervalo_s = intervalo_s
        self._lock = threading.Lock()
        self._lote_id: Optional[str] = None
        self._tentativa: Optional[int] = None
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def definir_job(self, lote_id: str, tentativa: int) -> None:
        with self._lock:
            self._lote_id = lote_id
            self._tentativa = tentativa

    def limpar_job(self) -> None:
        with self._lock:
            self._lote_id = None
            self._tentativa = None

    def _job_atual(self):
        with self._lock:
            return self._lote_id, self._tentativa

    def _laco(self) -> None:
        while not self._parar.wait(timeout=self._intervalo_s):
            lote_id, tentativa = self._job_atual()
            if lote_id is None:
                continue  # ocioso -- nada para bater
            try:
                ainda_dono = self._cliente.heartbeat(lote_id, tentativa)
                if not ainda_dono:
                    _LOG.warning("[Worker] lease do lote %s expirou -- outro Worker já assumiu", lote_id)
            except ErroCliente as exc:
                # Nunca derruba a thread por uma falha de rede passageira
                # -- a próxima batida tenta de novo sozinha.
                _LOG.warning("[Worker] falha no heartbeat: %s", exc)

    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._laco, daemon=True, name="worker-heartbeat")
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
