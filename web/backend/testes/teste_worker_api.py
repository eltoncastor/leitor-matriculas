"""
web/backend/testes/teste_worker_api.py

Fase 26b. Cobre o PROTOCOLO `/api/worker/*` -- registro, autenticação,
claim atômico, lease/reenfileiramento, idempotência de resultado, ficha de
cerca e o caminho feliz completo (claim -> baixar arquivo -> entregar
página -> miniatura -> progresso -> concluir). Não roda OCR nem lê as
planilhas reais -- quem prova o pipeline de verdade contra o protocolo é a
Sub-fase 26c (Worker Windows real) e a regressão de `teste_api_lote_real.py`.

Todos os lotes aqui são do tipo IMAGENS com conteúdo de arquivo ARBITRÁRIO
(bytes quaisquer) -- suficiente porque nenhum destes testes decodifica a
imagem de verdade: quem "faz o papel do Worker" aqui é o próprio teste,
entregando resultados sintéticos por HTTP. `_descobrir_total_paginas` para
IMAGENS é `len(caminhos)`, sem tocar o conteúdo do arquivo -- por isso este
tipo foi escolhido em vez de PDF (que exigiria bytes de PDF de verdade só
para `pdf_reader.contar_paginas` abrir o documento).

Rodar (a partir da raiz do projeto, com o venv ativo):
    python web\\backend\\testes\\teste_worker_api.py
"""
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))

from fastapi.testclient import TestClient  # noqa: E402

from leitor_matriculas.parsing.registro_parser import CampoOcr, Registro  # noqa: E402

TOKEN = "chave-de-teste-com-mais-de-16-caracteres"
os.environ["LEITOR_WORKER_TOKEN"] = TOKEN
os.environ["LEITOR_MODO"] = "servidor"  # sem isto, o próprio processo tentaria rodar OCR

_RAIZ = tempfile.mkdtemp(prefix="armazenamento_teste_worker_")

from web.backend import armazenamento, estado  # noqa: E402

armazenamento.definir_raiz(_RAIZ)

from web.backend.main import app  # noqa: E402


def _cabecalhos(worker_id="worker-teste"):
    return {"Authorization": f"Bearer {TOKEN}", "X-Worker-Id": worker_id}


def _limpar():
    estado._lotes.clear()
    for lote_id in armazenamento.listar_lotes():
        armazenamento.remover_lote(lote_id)


def _criar_lote_de_imagens(client, n_arquivos=2):
    arquivos = [("files", (f"folha{i}.jpg", io.BytesIO(f"conteudo-{i}".encode()), "image/jpeg"))
                for i in range(n_arquivos)]
    r = client.post("/lotes", files=arquivos)
    assert r.status_code == 201, r.text
    lote_id = r.json()["lote_id"]
    r = client.post(f"/lotes/{lote_id}/processar")
    assert r.status_code == 202, r.text
    return lote_id


def _pagina_sintetica(tentativa, numero, matricula="28972"):
    """Devolve o corpo pronto para `POST .../paginas/{numero}` -- o
    chamador não precisa lembrar de sobrescrever `tentativa` depois."""
    registro = Registro(
        indice=1,
        campos={
            "matricula": CampoOcr(matricula, 0.95, [450, 10, 520, 40]),
            "data": CampoOcr("14/04/26", 0.95, [60, 10, 130, 40]),
            "gestor": CampoOcr("GR1", 0.9, [880, 10, 940, 40]),
            "motivo": CampoOcr("RH", 0.9, [700, 10, 760, 40]),
        },
        nao_associados=[], y_min=10, y_max=40,
    )
    return {"tentativa": tentativa, "erro": None, "fase_erro": None,
            "registros": [registro.como_dicionario()]}


# ---------------------------------------------------------------------------
def teste_registro_e_autenticacao():
    print("\n=== Bloco 1: registro e as três formas de autenticação recusada ===")
    client = TestClient(app)

    r = client.get("/api/worker/jobs/next")
    assert r.status_code == 401, "sem cabeçalho Authorization precisa ser recusado"

    r = client.get("/api/worker/jobs/next", headers={"Authorization": "Bearer errado", "X-Worker-Id": "w1"})
    assert r.status_code == 401, "token errado precisa ser recusado"

    r = client.get("/api/worker/jobs/next", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 401, "sem X-Worker-Id precisa ser recusado"

    r = client.post("/api/worker/register", headers=_cabecalhos("worker-1"))
    assert r.status_code == 200 and r.json()["worker_id"] == "worker-1"

    r = client.get("/api/worker/jobs/next", headers=_cabecalhos())
    assert r.status_code == 200 and r.json()["lote_id"] is None
    print("  OK: sem token, token errado e sem worker_id recusados; registro e fila vazia funcionam")


def teste_rota_worker_nunca_sob_leitor():
    print("\n=== Bloco 2: rotas de Worker fora do prefixo /leitor (D9) ===")
    client = TestClient(app)
    r = client.get("/leitor/api/worker/jobs/next", headers=_cabecalhos())
    assert r.status_code == 404, "o Cloudflare Tunnel só roteia /leitor/* -- isto NUNCA pode responder"
    assert "application/json" in r.headers.get("content-type", "")
    print(f"  OK: /leitor/api/worker/jobs/next -> {r.status_code} JSON (nunca a SPA, nunca uma resposta de Worker)")


def teste_upload_sem_worker_nunca_vira_erro():
    print("\n=== Bloco 3: upload sem nenhum Worker disponível nunca vira 500 ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 2)

    for _ in range(3):
        r = client.get(f"/lotes/{lote_id}/status")
        assert r.status_code == 200
        assert r.json()["status"] == "processando"
        assert r.json()["erro_fatal"] is None

    r = client.get("/api/worker/jobs/next", headers=_cabecalhos())
    assert r.json()["lote_id"] == lote_id, "o lote precisa aparecer na fila para o Worker"
    print("  OK: lote fica 'processando'/aguardando, nunca 500, e aparece em jobs/next")


def teste_claim_atomico():
    print("\n=== Bloco 4: dois Workers disputando o mesmo Job -- só um ganha ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 1)

    ra = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-A"))
    rb = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-B"))

    assert ra.status_code == 200, ra.text
    assert rb.status_code == 409, "o segundo Worker precisa ser recusado"
    assert ra.json()["tentativa"] == 1
    assert ra.json()["nomes_arquivos"] == ["folha0.jpg"]
    assert ra.json()["total_paginas"] == 1, "IMAGENS conhece o total de graça, sem pedir ao Worker"

    r = client.get("/api/worker/jobs/next", headers=_cabecalhos())
    assert r.json()["lote_id"] is None, "um Job já reivindicado não pode aparecer como disponível de novo"
    print("  OK: worker-A reivindicou (tentativa 1), worker-B recebeu 409, fila ficou vazia")


def teste_baixar_arquivo_exige_posse():
    print("\n=== Bloco 5: baixar arquivo de entrada exige ser o dono do Job ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 1)
    claim = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-A")).json()

    r_intruso = client.get(f"/api/worker/jobs/{lote_id}/arquivos/0",
                           params={"tentativa": claim["tentativa"]}, headers=_cabecalhos("worker-B"))
    assert r_intruso.status_code == 409, "um Worker que nunca reivindicou não pode baixar o arquivo"

    r = client.get(f"/api/worker/jobs/{lote_id}/arquivos/0",
                   params={"tentativa": claim["tentativa"]}, headers=_cabecalhos("worker-A"))
    assert r.status_code == 200
    assert r.content == b"conteudo-0", "o conteudo baixado precisa ser IDENTICO ao enviado no upload"
    print("  OK: dono baixa o conteúdo exato; um Worker alheio (mesmo token) é recusado")


def teste_fluxo_completo_ate_concluido():
    print("\n=== Bloco 6: caminho feliz completo -- claim até status 'concluido' ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 2)

    claim = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-A")).json()
    tentativa = claim["tentativa"]
    assert claim["paginas_pendentes"] == [1, 2]

    for numero in (1, 2):
        # ORDEM IMPORTA: a miniatura sobe ANTES do resultado da página, não
        # depois -- mesma ordem que `produtor_ocr._ocr_de_uma_pagina` já
        # segue no modo local. Na última página, entregar o RESULTADO pode
        # fazer a VPS concluir o lote e liberar a posse (`worker_id`/
        # `fase_worker` voltam a vazio) antes da próxima chamada HTTP deste
        # mesmo teste rodar -- entregar a miniatura primeiro elimina essa
        # corrida em vez de torná-la "geralmente rápida o bastante".
        r = client.put(f"/api/worker/jobs/{lote_id}/paginas/{numero}/miniatura",
                       params={"tentativa": tentativa}, content=b"\xff\xd8\xff-jpeg-falso",
                       headers=_cabecalhos("worker-A"))
        assert r.status_code == 204

        corpo = _pagina_sintetica(tentativa, numero, matricula=f"2897{numero}")
        r = client.post(f"/api/worker/jobs/{lote_id}/paginas/{numero}", json=corpo, headers=_cabecalhos("worker-A"))
        assert r.status_code == 202 and r.json()["resultado"] == "aceito", r.text

    r = client.post(f"/api/worker/jobs/{lote_id}/progresso",
                    json={"tentativa": tentativa, "etapa_atual": "Conferindo os dados contra as bases"},
                    headers=_cabecalhos("worker-A"))
    assert r.status_code == 204

    r = client.post(f"/api/worker/jobs/{lote_id}/concluir", json={"tentativa": tentativa}, headers=_cabecalhos("worker-A"))
    assert r.status_code == 204

    prazo = time.monotonic() + 10
    status = None
    while time.monotonic() < prazo:
        status = client.get(f"/lotes/{lote_id}/status").json()
        if status["status"] in ("concluido", "erro"):
            break
        time.sleep(0.05)
    assert status["status"] == "concluido", f"o lote não concluiu a tempo: {status}"
    assert status["total_registros"] == 2

    registros = client.get(f"/lotes/{lote_id}/registros").json()
    assert sorted(r["pagina_origem"] for r in registros) == [1, 2]
    assert sorted(r["matricula"] for r in registros) == ["28971", "28972"]

    r = client.get(f"/lotes/{lote_id}/paginas/1/imagem")
    assert r.status_code == 200 and r.content == b"\xff\xd8\xff-jpeg-falso"
    print(f"  OK: claim -> 2 páginas -> miniaturas -> progresso -> concluir -> status='{status['status']}', "
          f"{status['total_registros']} registros, ordem física e miniaturas corretas")


def teste_reenvio_de_pagina_nao_duplica_via_http():
    print("\n=== Bloco 7: reenviar a mesma página pela API não duplica ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 1)
    claim = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-A")).json()
    tentativa = claim["tentativa"]
    corpo = _pagina_sintetica(tentativa, 1)

    r1 = client.post(f"/api/worker/jobs/{lote_id}/paginas/1", json=corpo, headers=_cabecalhos("worker-A"))
    r2 = client.post(f"/api/worker/jobs/{lote_id}/paginas/1", json=corpo, headers=_cabecalhos("worker-A"))
    assert r1.json()["resultado"] == "aceito"
    assert r2.json()["resultado"] == "duplicado"

    client.post(f"/api/worker/jobs/{lote_id}/concluir", json={"tentativa": tentativa}, headers=_cabecalhos("worker-A"))
    prazo = time.monotonic() + 10
    while time.monotonic() < prazo:
        if client.get(f"/lotes/{lote_id}/status").json()["status"] == "concluido":
            break
        time.sleep(0.05)
    registros = client.get(f"/lotes/{lote_id}/registros").json()
    assert len(registros) == 1, f"o reenvio duplicou o registro: {len(registros)}"
    print("  OK: primeira entrega 'aceito', reenvio 'duplicado', só 1 registro no resultado final")


def teste_lease_expirado_reenfileira_e_worker_antigo_e_rejeitado():
    print("\n=== Bloco 8: lease expirado -- Job recuperado e o Worker antigo (zumbi) rejeitado ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 1)
    claim = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-A")).json()
    tentativa_antiga = claim["tentativa"]

    lote = estado.obter_lote(lote_id)
    with lote.lock:
        lote.lease_ate = time.time() - 1  # já venceu

    reenfileirados = estado.varrer_leases_expirados()
    assert lote_id in reenfileirados

    r = client.get("/api/worker/jobs/next", headers=_cabecalhos("worker-B"))
    assert r.json()["lote_id"] == lote_id, "o Job precisa voltar a aparecer na fila"

    corpo = _pagina_sintetica(tentativa_antiga, 1)
    r_zumbi = client.post(f"/api/worker/jobs/{lote_id}/paginas/1", json=corpo, headers=_cabecalhos("worker-A"))
    # /paginas/{numero} nunca usa a checagem estrita de posse (ver o
    # docstring de `entregar_pagina`) -- a tentativa vencida é rejeitada
    # dentro de `depositar_resultado_pagina`, que devolve "obsoleto" com
    # 202, não 409. O worker zumbi ainda precisa PARAR ao ler essa
    # resposta -- só não é tratado como erro HTTP.
    assert r_zumbi.status_code == 202 and r_zumbi.json()["resultado"] == "obsoleto", \
        "o Worker da tentativa vencida precisa ser rejeitado, mesmo vivo e postando"

    claim_b = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-B")).json()
    # +2, não +1: uma vez por `reenfileirar` (a varredura de lease) e outra
    # por `reivindicar` (o claim de worker-B em si) -- cada um incrementa
    # a ficha de cerca por conta própria.
    assert claim_b["tentativa"] == tentativa_antiga + 2
    assert claim_b["paginas_pendentes"] == [1], "nenhuma página foi perdida na recuperação"
    print(f"  OK: reenfileirado, worker-A (tentativa {tentativa_antiga}) recebeu 'obsoleto', "
          f"worker-B reivindicou na tentativa {claim_b['tentativa']}")


def teste_falha_de_documento_inteiro():
    print("\n=== Bloco 9: falha de documento inteiro marca o Job como erro ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 1)
    claim = client.post(f"/api/worker/jobs/{lote_id}/claim", headers=_cabecalhos("worker-A")).json()

    r = client.post(f"/api/worker/jobs/{lote_id}/erro",
                    json={"tentativa": claim["tentativa"], "mensagem": "arquivo corrompido, não abre"},
                    headers=_cabecalhos("worker-A"))
    assert r.status_code == 204

    status = client.get(f"/lotes/{lote_id}/status").json()
    assert status["status"] == "erro"
    assert status["erro_fatal"] == "arquivo corrompido, não abre"
    print(f"  OK: status='{status['status']}', erro_fatal preservado")


def teste_cancelar_lote():
    print("\n=== Bloco 10: cancelar um lote aguardando Worker ===")
    _limpar()
    client = TestClient(app)
    lote_id = _criar_lote_de_imagens(client, 1)

    r = client.post(f"/lotes/{lote_id}/cancelar")
    assert r.status_code == 200 and r.json()["status"] == "cancelado"

    assert client.get("/api/worker/jobs/next", headers=_cabecalhos()).json()["lote_id"] is None, \
        "um lote cancelado não pode continuar disponível para reivindicação"

    r2 = client.post(f"/lotes/{lote_id}/cancelar")
    assert r2.status_code == 200 and r2.json()["status"] == "cancelado", "cancelar de novo é seguro (idempotente)"

    # Achado real desta sub-fase: `cancelar` esquecia de zerar `fase_
    # worker`, então um lote CANCELADO continuava contando como
    # "aguardando_worker" no resumo -- ver `teste_status_worker_nao_
    # vaza_token`, que verifica isto de fato com o resumo zerado.
    resumo = estado.resumo_jobs()
    assert resumo["jobs_aguardando_worker"] == 0, \
        f"lote cancelado não pode contar como aguardando Worker: {resumo}"
    print("  OK: cancelado, some da fila, cancelar de novo não quebra nada, e some do resumo agregado")


def teste_status_worker_nao_vaza_token():
    print("\n=== Bloco 11: GET /api/worker/status é público e nunca expõe o token ===")
    _limpar()
    client = TestClient(app)
    r = client.get("/api/worker/status")
    assert r.status_code == 200
    corpo = r.text
    assert TOKEN not in corpo
    assert r.json() == {
        "modo": "servidor", "jobs_aguardando_worker": 0,
        "jobs_em_processamento": 0, "jobs_concluidos_recentes": 0,
    }, f"resumo deveria estar zerado sem nenhum lote: {r.json()}"
    print(f"  OK: {r.json()}")


def main():
    try:
        teste_registro_e_autenticacao()
        teste_rota_worker_nunca_sob_leitor()
        teste_upload_sem_worker_nunca_vira_erro()
        teste_claim_atomico()
        teste_baixar_arquivo_exige_posse()
        teste_fluxo_completo_ate_concluido()
        teste_reenvio_de_pagina_nao_duplica_via_http()
        teste_lease_expirado_reenfileira_e_worker_antigo_e_rejeitado()
        teste_falha_de_documento_inteiro()
        teste_cancelar_lote()
        teste_status_worker_nao_vaza_token()
        print("\n" + "=" * 70)
        print("PROTOCOLO DE WORKER (FASE 26b): TUDO OK")
    finally:
        shutil.rmtree(_RAIZ, ignore_errors=True)


if __name__ == "__main__":
    main()
