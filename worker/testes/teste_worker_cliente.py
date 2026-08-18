"""
worker/testes/teste_worker_cliente.py

Fase 26c. Prova que `worker/cliente.py` fala o protocolo `/api/worker/*`
DE VERDADE, por socket real (`urllib.request`) contra um `uvicorn.Server`
de verdade -- não o transporte ASGI in-memory do `TestClient`, que
`web/backend/testes/teste_worker_api.py` já usa para testar a SEMÂNTICA
do protocolo. Aqui o que se prova é a PLUMBING: cabeçalhos de auth
realmente enviados e recebidos, corpo JSON codificado/decodificado,
mapeamento de erro HTTP real (`HTTPError`/`URLError`) para as exceções de
`worker/cliente.py`, download binário, PUT de bytes crus.

Sem OCR -- os "registros" entregues são sintéticos, como se um Worker já
tivesse rodado o pipeline. `worker/testes/teste_worker_real.py` é quem
prova o pipeline de verdade, ponta a ponta, contra o baseline conhecido.

Rodar (a partir da raiz do projeto, com o venv ativo):
    python worker\\testes\\teste_worker_cliente.py
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
os.environ["LEITOR_MODO"] = "servidor"

_RAIZ_ARMAZENAMENTO = tempfile.mkdtemp(prefix="armazenamento_teste_worker_cliente_")

from web.backend import armazenamento  # noqa: E402

armazenamento.definir_raiz(_RAIZ_ARMAZENAMENTO)

from fastapi.testclient import TestClient  # noqa: E402

from leitor_matriculas.parsing.registro_parser import CampoOcr, Registro  # noqa: E402
from web.backend.main import app  # noqa: E402
from worker.cliente import ClienteWorker, ErroAutenticacao, ErroConflito  # noqa: E402
from worker.testes._servidor_real import ServidorDeTeste  # noqa: E402

_servidor = ServidorDeTeste(app)
_client_local = TestClient(app)  # só para criar/despachar lotes (rápido, in-process)


def _criar_lote(n_arquivos=1):
    arquivos = [("files", (f"folha{i}.jpg", io.BytesIO(f"conteudo-{i}".encode()), "image/jpeg"))
                for i in range(n_arquivos)]
    r = _client_local.post("/lotes", files=arquivos)
    assert r.status_code == 201, r.text
    lote_id = r.json()["lote_id"]
    r = _client_local.post(f"/lotes/{lote_id}/processar")
    assert r.status_code == 202, r.text
    return lote_id


def _pagina_sintetica():
    registro = Registro(
        indice=1,
        campos={"matricula": CampoOcr("28972", 0.95, [450, 10, 520, 40]),
                "data": CampoOcr("14/04/26", 0.95, [60, 10, 130, 40])},
        nao_associados=[], y_min=10, y_max=40,
    )
    return [registro.como_dicionario()]


def teste_autenticacao_via_socket_real():
    print("\n=== Bloco 1: autenticação sobre socket real ===")
    cliente_sem_auth = ClienteWorker(_servidor.base_url, "w1", "token-completamente-errado")
    try:
        cliente_sem_auth.proximo_job()
        raise AssertionError("token errado deveria ter levantado ErroAutenticacao")
    except ErroAutenticacao:
        pass

    cliente = ClienteWorker(_servidor.base_url, "worker-cliente-teste", TOKEN)
    cliente.registrar()  # não levanta
    assert cliente.proximo_job() is None
    print("  OK: token errado rejeitado por HTTPError real (401); token certo autentica")


def teste_claim_e_conflito_via_socket_real():
    print("\n=== Bloco 2: claim atômico sobre socket real ===")
    lote_id = _criar_lote(1)
    cliente_a = ClienteWorker(_servidor.base_url, "worker-A", TOKEN)
    cliente_b = ClienteWorker(_servidor.base_url, "worker-B", TOKEN)

    job = cliente_a.reivindicar(lote_id)
    assert job.lote_id == lote_id and job.tentativa == 1
    assert job.nomes_arquivos == ["folha0.jpg"]

    try:
        cliente_b.reivindicar(lote_id)
        raise AssertionError("o segundo claim deveria ter levantado ErroConflito")
    except ErroConflito:
        pass
    print(f"  OK: worker-A reivindicou (tentativa {job.tentativa}), worker-B recebeu ErroConflito")


def teste_fluxo_completo_via_socket_real():
    print("\n=== Bloco 3: caminho feliz completo (download, página, miniatura, progresso, concluir) ===")
    lote_id = _criar_lote(1)
    cliente = ClienteWorker(_servidor.base_url, "worker-fluxo", TOKEN)
    job = cliente.reivindicar(lote_id)

    pasta_temp = tempfile.mkdtemp(prefix="worker_teste_download_")
    try:
        destino = os.path.join(pasta_temp, job.nomes_arquivos[0])
        cliente.baixar_arquivo(lote_id, 0, job.tentativa, destino)
        with open(destino, "rb") as arquivo:
            conteudo = arquivo.read()
        assert conteudo == b"conteudo-0", "o download por socket real precisa devolver os bytes exatos"

        cliente.entregar_miniatura(lote_id, 1, job.tentativa, b"\xff\xd8\xff-jpeg-de-teste")
        resultado = cliente.entregar_pagina(lote_id, 1, job.tentativa, erro=None, fase_erro=None,
                                            registros=_pagina_sintetica())
        assert resultado == "aceito"

        cliente.progresso(lote_id, job.tentativa, etapa_atual="Conferindo os dados contra as bases")
        cliente.concluir(lote_id, job.tentativa)

        prazo = time.monotonic() + 10
        status = None
        while time.monotonic() < prazo:
            status = _client_local.get(f"/lotes/{lote_id}/status").json()
            if status["status"] in ("concluido", "erro"):
                break
            time.sleep(0.05)
        assert status["status"] == "concluido", f"não concluiu a tempo: {status}"
        assert status["total_registros"] == 1
    finally:
        shutil.rmtree(pasta_temp, ignore_errors=True)
    print(f"  OK: download, miniatura, página, progresso e conclusão -- status final '{status['status']}'")


def teste_erro_de_documento_via_socket_real():
    print("\n=== Bloco 4: falha de documento inteiro sobre socket real ===")
    lote_id = _criar_lote(1)
    cliente = ClienteWorker(_servidor.base_url, "worker-erro", TOKEN)
    job = cliente.reivindicar(lote_id)
    cliente.erro_de_documento(lote_id, job.tentativa, "arquivo corrompido, não abre")

    status = _client_local.get(f"/lotes/{lote_id}/status").json()
    assert status["status"] == "erro" and status["erro_fatal"] == "arquivo corrompido, não abre"
    print(f"  OK: status='{status['status']}'")


def main():
    _servidor.iniciar()
    try:
        teste_autenticacao_via_socket_real()
        teste_claim_e_conflito_via_socket_real()
        teste_fluxo_completo_via_socket_real()
        teste_erro_de_documento_via_socket_real()
        print("\n" + "=" * 70)
        print("CLIENTE HTTP DO WORKER, SOBRE SOCKET REAL (FASE 26c): TUDO OK")
    finally:
        _servidor.parar()
        shutil.rmtree(_RAIZ_ARMAZENAMENTO, ignore_errors=True)


if __name__ == "__main__":
    main()
