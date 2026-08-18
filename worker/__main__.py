"""
worker/__main__.py

Fase 26c. Ponto de entrada do Worker Windows. Rodar (a partir da raiz do
projeto, com o venv do Worker ativo -- ver `requirements-worker.txt` e
`web/README.md`):

    python -m worker

Sobe a thread de heartbeat (prova de vida do PROCESSO, independente do
laço de OCR) e o laço principal (`worker.execucao.rodar`), que fica
fazendo polling em `GET /jobs/next` até um Ctrl+C. Uma falha de UM Job
nunca derruba o processo -- é isolada dentro de `processar_job`.

Logs no formato `[Worker] ...`. NUNCA logam o token nem qualquer dado
pessoal das folhas (matrícula, nome) -- só `worker_id`, `lote_id`,
números de página e mensagens de erro técnico.
"""
import logging
import os
import signal
import sys

if getattr(sys, "frozen", False):
    _RAIZ_PROJETO = sys._MEIPASS  # mesmo tratamento de web/desktop_app.py (Sub-fase 25b)
else:
    _RAIZ_PROJETO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # Rodando via `python -m worker` a partir da raiz, `src/` não entra no
    # sys.path sozinho -- mesmo motivo de `web/backend/main.py`/
    # `web/desktop_app.py`.
    sys.path.insert(0, _RAIZ_PROJETO)
    sys.path.insert(0, os.path.join(_RAIZ_PROJETO, "src"))

from worker import config, execucao  # noqa: E402
from worker.cliente import ClienteWorker  # noqa: E402
from worker.heartbeat import Heartbeat  # noqa: E402


def _configurar_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    _configurar_logging()
    log = logging.getLogger("worker")

    config.carregar_env(_RAIZ_PROJETO)
    try:
        cfg = config.ler_configuracao()
    except config.ConfiguracaoInvalida as exc:
        log.error("[Worker] %s", exc)
        return 1

    log.info("[Worker] iniciando -- worker_id=%s, servidor=%s", cfg.worker_id, cfg.api_base_url)

    cliente = ClienteWorker(cfg.api_base_url, cfg.worker_id, cfg.worker_token)
    try:
        cliente.registrar()
    except Exception as exc:
        log.error("[Worker] falha ao validar a configuração contra o servidor: %s", exc)
        return 1
    log.info("[Worker] autenticado com sucesso")

    heartbeat = Heartbeat(cliente, cfg.intervalo_heartbeat_s)
    heartbeat.iniciar()

    _parar = {"sim": False}

    def _pedir_parada(*_args) -> None:
        if not _parar["sim"]:
            log.info("[Worker] encerrando -- aguardando o Job atual terminar (Ctrl+C de novo para forçar)...")
        _parar["sim"] = True

    signal.signal(signal.SIGINT, _pedir_parada)
    try:
        signal.signal(signal.SIGTERM, _pedir_parada)
    except (AttributeError, ValueError):
        pass  # SIGTERM pode não existir/ser interceptável em todo ambiente Windows

    try:
        execucao.rodar(
            cliente, heartbeat, cfg.intervalo_polling_s,
            deve_continuar=lambda: not _parar["sim"],
        )
    finally:
        heartbeat.parar()

    log.info("[Worker] encerrado")
    return 0


if __name__ == "__main__":
    # Mesmo motivo de web/desktop_app.py (Sub-fase 25b): evita que um
    # `.exe` congelado reexecute o programa inteiro do zero a cada
    # subprocesso, se alguma dependência (paddle inclusive) usar
    # multiprocessing internamente.
    import multiprocessing

    multiprocessing.freeze_support()
    sys.exit(main())
