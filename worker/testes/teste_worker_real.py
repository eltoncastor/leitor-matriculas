"""
worker/testes/teste_worker_real.py

Fase 26c. A verificação DECISIVA desta sub-fase: o pacote `worker/` real
(não um mock, não um "faz de conta") processando o MESMO PDF de 5 folhas
reais usado desde a Fase 9 (`entrada/pdf/teste.pdf`), com PaddleOCR de
verdade, através do protocolo `/api/worker/*` sobre um `uvicorn.Server`
real -- e batendo a MESMA baseline que todas as sub-fases desta macrofase
já reconfirmaram: 40 registros, 19 CONFIRMADO, 21 REVISAO, 0 ERRO.

O fluxo exercitado é literalmente `navegador -> VPS -> Job -> Worker ->
OCR real -> resultado -> VPS`, só que com o "navegador" substituído por
chamadas HTTP diretas (o que a Sub-fase 26d fará de verdade pelo
frontend) e a VPS/Worker rodando no MESMO processo Python -- mas em DOIS
LADOS DE UM SOCKET REAL, exatamente como rodariam em máquinas diferentes.

Lento (~3-4 min, mesmo tempo de `teste_api_lote_real.py`, mesmo motivo:
OCR de verdade). Roda antes de fechar a sub-fase, não a cada alteração.

Rodar (a partir da raiz do projeto, com o venv ativo):
    python worker\\testes\\teste_worker_real.py
"""
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

TOKEN = "chave-de-teste-com-mais-de-16-caracteres"
os.environ["LEITOR_WORKER_TOKEN"] = TOKEN
os.environ["LEITOR_MODO"] = "servidor"  # a VPS não roda OCR -- só o Worker

_RAIZ_ARMAZENAMENTO = tempfile.mkdtemp(prefix="armazenamento_teste_worker_real_")

from web.backend import armazenamento  # noqa: E402

armazenamento.definir_raiz(_RAIZ_ARMAZENAMENTO)

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.main import app  # noqa: E402
from worker import execucao  # noqa: E402
from worker.cliente import ClienteWorker  # noqa: E402
from worker.heartbeat import Heartbeat  # noqa: E402
from worker.testes._servidor_real import ServidorDeTeste  # noqa: E402

CAMINHO_PDF = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "entrada", "pdf", "teste.pdf",
))
TIMEOUT_PROCESSAMENTO_S = 400  # mesmo valor de teste_api_lote_real.py -- OCR real, ~3-4 min

_servidor = ServidorDeTeste(app)
_client_local = TestClient(app)  # só para criar o lote e ler/confirmar registros (rápido, in-process)


def _esperar_conclusao(lote_id: str) -> dict:
    prazo = time.monotonic() + TIMEOUT_PROCESSAMENTO_S
    ultimo = None
    while time.monotonic() < prazo:
        ultimo = _client_local.get(f"/lotes/{lote_id}/status").json()
        print(f"  status: {ultimo['status']} -- folha {ultimo['pagina_atual']}/{ultimo['total_paginas']} "
              f"-- etapa: {ultimo['etapa_atual']!r}")
        if ultimo["status"] in ("concluido", "erro"):
            return ultimo
        time.sleep(3)
    raise TimeoutError(f"O lote '{lote_id}' não concluiu a tempo: {ultimo}")


def main():
    if not os.path.isfile(CAMINHO_PDF):
        print(f"AVISO: {CAMINHO_PDF} não encontrado -- pulando o teste real (precisa do PDF de 5 folhas).")
        return

    _servidor.iniciar()
    heartbeat = None
    try:
        print("=== Sub-fase 26c: Worker real, PDF real (5 folhas), protocolo /api/worker/* sobre socket real ===")

        with open(CAMINHO_PDF, "rb") as arquivo:
            r = _client_local.post("/lotes", files=[("files", ("teste.pdf", io.BytesIO(arquivo.read()), "application/pdf"))])
        assert r.status_code == 201, r.text
        lote_id = r.json()["lote_id"]

        r = _client_local.post(f"/lotes/{lote_id}/processar")
        assert r.status_code == 202, r.text

        cliente = ClienteWorker(_servidor.base_url, "worker-teste-real", TOKEN)
        cliente.registrar()
        heartbeat = Heartbeat(cliente, intervalo_s=5.0)
        heartbeat.iniciar()

        # `rodar` é o MESMO laço que `python -m worker` usa de verdade
        # (worker/__main__.py) -- não uma chamada direta a `processar_job`.
        # `deve_continuar` para assim que ESTE lote sair de "processando",
        # o que basta porque só existe um lote no ar neste teste.
        def _deve_continuar() -> bool:
            status = _client_local.get(f"/lotes/{lote_id}/status").json()
            return status["status"] not in ("concluido", "erro", "cancelado")

        execucao.rodar(cliente, heartbeat, intervalo_polling_s=1.0, deve_continuar=_deve_continuar)

        status_final = _esperar_conclusao(lote_id)
        assert status_final["status"] == "concluido", status_final

        registros = _client_local.get(f"/lotes/{lote_id}/registros").json()
        confirmados = sum(1 for r in registros if r["status"] == "CONFIRMADO")
        revisao = sum(1 for r in registros if r["status"] == "REVISAO")
        erro = sum(1 for r in registros if r["status"] == "ERRO")

        assert len(registros) == 40, f"esperava 40 registros, veio {len(registros)}"
        assert confirmados == 19, f"esperava 19 CONFIRMADO, veio {confirmados}"
        assert revisao == 21, f"esperava 21 REVISAO, veio {revisao}"
        assert erro == 0, f"esperava 0 ERRO, veio {erro}"
        print(f"\nOK: 40/19/21/0 confirmado através do Worker real -- idêntico à baseline histórica "
              f"(ver CLAUDE.md) e à medida diretamente pelo pipeline.py/pela API em modo local.")

        # As mesmas duas correções REAIS e conhecidas desde as Fases 12/16
        # -- ver web/backend/testes/teste_api_lote_real.py, Teste 15, para
        # o histórico completo. Reaproveita o MESMO lote, nenhuma chamada
        # de OCR nova.
        def _registro_por_matricula(matricula):
            for i, r in enumerate(registros):
                if r["matricula"] == matricula and r["status"] == "REVISAO":
                    return i, r
            return None, None

        def _campos_atuais(registro):
            return {"data": registro.get("data") or "", "hora": registro.get("hora") or "",
                    "matricula": registro.get("matricula") or "", "gestor": registro.get("gestor") or "",
                    "motivo": registro.get("motivo") or ""}

        idx_27325, registro_27325 = _registro_por_matricula("27325")
        if idx_27325 is not None:
            campos = _campos_atuais(registro_27325)
            campos["data"] = "13/04/26"
            resp = _client_local.post(f"/lotes/{lote_id}/registros/{idx_27325}/confirmar", json=campos)
            assert resp.status_code == 200 and resp.json()["confirmou_agora"] is True, resp.text
            print("OK: matrícula 27325 -- DATA corrigida para 13/04/26 -> CONFIRMADO de verdade")

        idx_26319, registro_26319 = _registro_por_matricula("26319")
        if idx_26319 is not None:
            campos = _campos_atuais(registro_26319)
            campos["hora"] = "07:49"
            resp = _client_local.post(f"/lotes/{lote_id}/registros/{idx_26319}/confirmar", json=campos)
            assert resp.status_code == 200 and resp.json()["confirmou_agora"] is True, resp.text
            print("OK: matrícula 26319 -- HORA corrigida para 07:49 -> CONFIRMADO de verdade")

        print("\n" + "=" * 70)
        print("WORKER REAL, PONTA A PONTA (SUB-FASE 26c): TUDO OK")
    finally:
        if heartbeat is not None:
            heartbeat.parar()
        _servidor.parar()
        shutil.rmtree(_RAIZ_ARMAZENAMENTO, ignore_errors=True)


if __name__ == "__main__":
    main()
