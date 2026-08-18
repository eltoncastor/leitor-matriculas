"""
worker/testes/_servidor_real.py

Fase 26c. Helper compartilhado pelos testes deste pacote: sobe o backend
REAL (`web.backend.main.app`) num `uvicorn.Server` de verdade, numa
thread, numa porta livre -- é o que permite `worker/cliente.py` (que fala
`urllib.request` sobre socket de verdade, não o transporte ASGI in-memory
do `TestClient`) ser exercitado por completo, não só o protocolo em si
(que `web/backend/testes/teste_worker_api.py` já cobre via `TestClient`).

Mesmo padrão de `web/desktop_app.py` (Sub-fase 25a): `uvicorn.Server`
programático + polling em `/saude` até responder + `should_exit = True`
para encerrar de forma limpa.
"""
import socket
import threading
import time
import urllib.error
import urllib.request

import uvicorn


def porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServidorDeTeste:
    def __init__(self, app, porta=None):
        self.porta = porta or porta_livre()
        self.base_url = f"http://127.0.0.1:{self.porta}"
        config = uvicorn.Config(app, host="127.0.0.1", port=self.porta, log_level="warning")
        self._servidor = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._servidor.run, daemon=True, name="uvicorn-teste")

    def iniciar(self, timeout_s: float = 20.0) -> None:
        self._thread.start()
        inicio = time.monotonic()
        while time.monotonic() - inicio < timeout_s:
            try:
                with urllib.request.urlopen(f"{self.base_url}/saude", timeout=1) as resposta:
                    if resposta.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.1)
        raise TimeoutError(f"O servidor de teste não respondeu em {self.base_url}/saude a tempo")

    def parar(self) -> None:
        self._servidor.should_exit = True
        self._thread.join(timeout=5)
