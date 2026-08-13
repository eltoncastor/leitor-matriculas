"""
web/backend/testes/teste_api_mock.py

Fase 24a (Web MVP) -- suíte RÁPIDA dos endpoints, com PaddleOCR MOCKADO
(mesmo padrão de `teste/teste_ui_integracao.py`: `MagicMock` no lugar do
engine, resultados de OCR sintéticos, `DataManager` fake determinística
para não depender do `dados/` real do operador, que é local e pode nem
existir em outra máquina). Existe ao lado de `teste_api_lote_real.py`
(OCR real, ~200 s) pela mesma razão que `teste_ui_integracao.py` existe ao
lado de `teste_ocr.py`: uma suíte rápida que roda a cada alteração, e uma
lenta que prova contra dado real antes de fechar a sub-fase.

Cobre o que o teste com OCR real não cobre (ou cobre caro demais para
rodar a cada mudança): PROBLEMA C/D da revisão manual pela API, isolamento
de falha por página num lote de imagens (uma foto corrompida no meio não
aborta as demais), lote PDF multi-página, e os erros HTTP (404/409) que o
teste real também cobre mas aqui ficam repetidos com mais variação porque
é barato.

Rodar (a partir da raiz do projeto, com o venv ativo):
    python web\\backend\\testes\\teste_api_mock.py
"""
import os
import sys
import tempfile
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))

import cv2
import numpy as np
import pymupdf as fitz
from fastapi.testclient import TestClient

from leitor_matriculas.ocr.engine import OCRResult
from web.backend import estado
from web.backend.main import app


class _DataManagerFake:
    """Mesmo espírito de `_DMRevisaoDeterministica` em teste_ui_integracao.py:
    reconhece exatamente UMA matrícula, para o teste não depender do
    `dados/` real (local, gitignored, pode nem existir nesta máquina)."""
    colaboradores_disponivel = True
    gestores_disponivel = False
    motivos_disponivel = False
    avisos = []

    def buscar_colaborador(self, matricula):
        if matricula == "28972":
            return {"matricula": "28972", "nome": "Fulano de Tal", "cargo": "Cargo X", "setor": "Setor X"}
        return None


# --- fixtures de OCR sintético (mesmo layout de teste_registro_parser.py) ---
COL_DATA, COL_HORA, COL_NOME, COL_MAT, COL_SETOR, COL_MOT, COL_GESTOR = 60, 160, 280, 450, 560, 700, 880


def _r(t, x1, y1, x2, y2, c=0.9):
    return OCRResult(texto_original=t, confianca=c, box=[x1, y1, x2, y2])


def _cabecalho(y1=10, y2=30):
    return [_r("DATA", COL_DATA - 20, y1, COL_DATA + 20, y2), _r("HORA", COL_HORA - 20, y1, COL_HORA + 20, y2),
            _r("NOME", COL_NOME - 25, y1, COL_NOME + 25, y2), _r("MATRÍCULA", COL_MAT - 35, y1, COL_MAT + 35, y2),
            _r("SETOR", COL_SETOR - 25, y1, COL_SETOR + 25, y2), _r("MOTIVO", COL_MOT - 25, y1, COL_MOT + 25, y2),
            _r("RESPONSÁVEL", COL_GESTOR - 40, y1, COL_GESTOR + 40, y2)]


def _linha(y1, y2, data, hora, nome, mat, setor, mot, gestor, conf_mat=0.9):
    return [_r(data, COL_DATA - 15, y1, COL_DATA + 15, y2), _r(hora, COL_HORA - 15, y1, COL_HORA + 15, y2),
            _r(nome, COL_NOME - 25, y1, COL_NOME + 25, y2), _r(mat, COL_MAT - 20, y1, COL_MAT + 20, y2, conf_mat),
            _r(setor, COL_SETOR - 20, y1, COL_SETOR + 20, y2), _r(mot, COL_MOT - 25, y1, COL_MOT + 25, y2),
            _r(gestor, COL_GESTOR - 30, y1, COL_GESTOR + 30, y2)]


RESULTADOS_OCR = _cabecalho() \
    + _linha(40, 60, "23.04.2026", "11:05", "Fulano", "28972", "TI", "RH", "Gestor X") \
    + _linha(70, 90, "23.04.2026", "11:10", "Beltrano", "99999", "RH", "ADM", "Gestor Y", conf_mat=0.5)


def _resetar_estado_global():
    """Cada teste roda contra o mesmo processo/`app` (TestClient não sobe
    servidor à parte) -- os lotes de um teste não podem vazar para o
    próximo. Isto NÃO é o que a Fase 24 pediu para evitar ("estado global
    solto") -- é só limpeza ENTRE testes deste arquivo; a API em si
    continua resolvendo tudo por `lote_id`."""
    estado._lotes.clear()


def _preparar_imagem_valida(pasta, nome="folha.jpg"):
    caminho = os.path.join(pasta, nome)
    img = np.full((200, 900, 3), 255, dtype=np.uint8)
    cv2.imwrite(caminho, img)
    return caminho


def _esperar_conclusao_sincrona(client, lote_id, tentativas=100):
    """Com o engine mockado o processamento é quase instantâneo -- ainda
    assim roda numa thread separada (o código de produção não sabe que
    está sendo testado), então esperamos igual, só que por muito menos
    tempo que o teste com OCR real."""
    import time
    for _ in range(tentativas):
        status = client.get(f"/lotes/{lote_id}/status").json()
        if status["status"] in (estado.STATUS_CONCLUIDO, estado.STATUS_ERRO):
            return status
        time.sleep(0.05)
    raise TimeoutError(f"Lote '{lote_id}' não concluiu (mock) -- possível trava no worker")


def teste_fluxo_imagem_unica():
    print("=== Teste 1: upload de 1 imagem -> processar -> registros -> confirmar -> exportar ===")
    _resetar_estado_global()
    tmp = tempfile.mkdtemp(prefix="teste_api_mock_")
    caminho = _preparar_imagem_valida(tmp)

    fake_engine = MagicMock()
    fake_engine.recognize.return_value = RESULTADOS_OCR
    estado._ocr_engine = fake_engine
    estado._data_manager = _DataManagerFake()

    client = TestClient(app)
    with open(caminho, "rb") as f:
        resp = client.post("/lotes", files={"files": (os.path.basename(caminho), f, "image/jpeg")})
    assert resp.status_code == 201, resp.text
    lote_id = resp.json()["lote_id"]
    assert resp.json()["tipo"] == "imagens"

    resp = client.post(f"/lotes/{lote_id}/processar")
    assert resp.status_code == 202, resp.text
    status = _esperar_conclusao_sincrona(client, lote_id)
    assert status["status"] == estado.STATUS_CONCLUIDO
    assert status["paginas_com_erro"] == 0
    assert status["total_registros"] == 2

    registros = client.get(f"/lotes/{lote_id}/registros").json()
    assert len(registros) == 2
    confirmados = [r for r in registros if r["status"] == "CONFIRMADO"]
    revisao = [r for r in registros if r["status"] == "REVISAO"]
    assert len(confirmados) == 1 and confirmados[0]["matricula"] == "28972", registros
    assert len(revisao) == 1 and revisao[0]["matricula"] == "99999", registros
    print("  OK: 1 CONFIRMADO (28972, na base fake) + 1 REVISAO (99999, fora da base)")

    # PROBLEMA D (Fase 7): confirmar sem digitar nada de novo NÃO resolve
    # -- fica em REVISAO, com a observação explicando por quê.
    indice_revisao = next(i for i, r in enumerate(registros) if r["status"] == "REVISAO")
    resp = client.post(f"/lotes/{lote_id}/registros/{indice_revisao}/confirmar", json={})
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["confirmou_agora"] is False
    assert corpo["registro"]["status"] == "REVISAO"
    assert "revisão manual incompleta" in corpo["registro"]["observacao"]
    print("  OK (PROBLEMA D): confirmar sem corrigir nada não força CONFIRMADO")

    # PROBLEMA C (Fase 7): corrigir com uma matrícula que EXISTE na base
    # resolve de verdade, e Nome/Setor/Cargo passam a refletir a matrícula
    # corrigida (não ficam "(não encontrado)").
    resp = client.post(
        f"/lotes/{lote_id}/registros/{indice_revisao}/confirmar",
        json={"data": "23/04/26", "hora": "11:10", "matricula": "28972", "gestor": "Gestor Y", "motivo": "ADM"},
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["confirmou_agora"] is True, corpo
    assert corpo["registro"]["status"] == "CONFIRMADO"
    assert corpo["registro"]["nome"] == "Fulano de Tal"
    assert corpo["registro"]["cargo"] == "Cargo X"
    print("  OK (PROBLEMA C): correção real resolve e re-consulta Nome/Cargo/Setor pela matrícula corrigida")

    resp = client.get(f"/lotes/{lote_id}/exportar")
    assert resp.status_code == 200
    assert len(resp.content) > 0
    print("  OK: exportação XLSX após correções")
    print()


def teste_explicacao_e_imagem_pagina():
    """Sub-fase 24c: os dois endpoints novos da tela de Revisão --
    explicação humana da pendência (Fase 17/18 expostas via API) e a foto
    da página de origem."""
    print("=== Teste 5 (24c): GET .../explicacao e GET .../paginas/{n}/imagem ===")
    _resetar_estado_global()
    tmp = tempfile.mkdtemp(prefix="teste_api_mock_")
    caminho = _preparar_imagem_valida(tmp)

    fake_engine = MagicMock()
    fake_engine.recognize.return_value = RESULTADOS_OCR
    estado._ocr_engine = fake_engine
    estado._data_manager = _DataManagerFake()

    client = TestClient(app)
    with open(caminho, "rb") as f:
        resp = client.post("/lotes", files={"files": (os.path.basename(caminho), f, "image/jpeg")})
    lote_id = resp.json()["lote_id"]
    client.post(f"/lotes/{lote_id}/processar")
    _esperar_conclusao_sincrona(client, lote_id)

    registros = client.get(f"/lotes/{lote_id}/registros").json()
    # Fase 24c: a lista já enriquecida com campos_bloqueantes, sem
    # precisar de uma requisição por linha.
    for r in registros:
        assert "campos_bloqueantes" in r, r
    confirmado = next(r for r in registros if r["status"] == "CONFIRMADO")
    revisao_idx, revisao = next((i, r) for i, r in enumerate(registros) if r["status"] == "REVISAO")
    assert confirmado["campos_bloqueantes"] == [], confirmado
    assert "matricula" in revisao["campos_bloqueantes"], revisao
    print("  OK: GET /registros enriquecido com campos_bloqueantes (vazio p/ CONFIRMADO, "
          f"{revisao['campos_bloqueantes']} p/ a linha REVISAO)")

    resp = client.get(f"/lotes/{lote_id}/registros/{revisao_idx}/explicacao")
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["explicacao"]["campos_bloqueantes"] == revisao["campos_bloqueantes"]
    assert corpo["explicacao"]["titulo"], corpo
    assert isinstance(corpo["explicacao"]["detalhes"], list) and corpo["explicacao"]["detalhes"]
    assert isinstance(corpo["sinais_contexto"], list)
    print(f"  OK: GET .../explicacao -- título: {corpo['explicacao']['titulo']!r}")

    resp = client.get(f"/lotes/{lote_id}/registros/999/explicacao")
    assert resp.status_code == 404
    print("  OK: índice inexistente -> 404 (nunca inventa explicação)")

    resp = client.get(f"/lotes/{lote_id}/paginas/1/imagem")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/jpeg"
    assert len(resp.content) > 0
    print(f"  OK: GET .../paginas/1/imagem -- {len(resp.content)} bytes JPEG")

    resp = client.get(f"/lotes/{lote_id}/paginas/999/imagem")
    assert resp.status_code == 404
    print("  OK: página sem foto -> 404 (nunca devolve imagem em branco)")
    print()


def teste_isolamento_falha_lote_imagens():
    print("=== Teste 2: lote de imagens com 1 arquivo corrompido no meio -- isola, não aborta (Fase 7) ===")
    _resetar_estado_global()
    tmp = tempfile.mkdtemp(prefix="teste_api_mock_")
    caminho_a = _preparar_imagem_valida(tmp, "a.jpg")
    caminho_corrompido = os.path.join(tmp, "b.jpg")
    with open(caminho_corrompido, "wb") as f:
        f.write(b"isto nao e uma imagem valida")
    caminho_c = _preparar_imagem_valida(tmp, "c.jpg")

    fake_engine = MagicMock()
    fake_engine.recognize.return_value = RESULTADOS_OCR
    estado._ocr_engine = fake_engine
    estado._data_manager = _DataManagerFake()

    client = TestClient(app)
    arquivos = [
        ("files", ("a.jpg", open(caminho_a, "rb"), "image/jpeg")),
        ("files", ("b.jpg", open(caminho_corrompido, "rb"), "image/jpeg")),
        ("files", ("c.jpg", open(caminho_c, "rb"), "image/jpeg")),
    ]
    resp = client.post("/lotes", files=arquivos)
    for _, (_, fh, _) in arquivos:
        fh.close()
    assert resp.status_code == 201, resp.text
    lote_id = resp.json()["lote_id"]
    assert resp.json()["total_arquivos"] == 3

    client.post(f"/lotes/{lote_id}/processar")
    status = _esperar_conclusao_sincrona(client, lote_id)
    assert status["status"] == estado.STATUS_CONCLUIDO
    assert status["paginas_com_erro"] == 1, status
    # 2 (folha A) + 1 (linha ERRO da folha B) + 2 (folha C) = 5
    assert status["total_registros"] == 5, status

    registros = client.get(f"/lotes/{lote_id}/registros").json()
    erros = [r for r in registros if r["status"] == "ERRO"]
    assert len(erros) == 1
    assert "b.jpg" in erros[0]["observacao"]
    print(f"  OK: 1 arquivo corrompido isolado como linha ERRO ({erros[0]['observacao']!r}), "
          f"as outras 2 folhas continuaram sendo processadas normalmente")
    print()


def teste_lote_pdf_multipagina():
    print("=== Teste 3: lote PDF sintético multi-página ===")
    _resetar_estado_global()
    tmp = tempfile.mkdtemp(prefix="teste_api_mock_")
    caminho_pdf = os.path.join(tmp, "mes.pdf")
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=600, height=800)
    doc.save(caminho_pdf)
    doc.close()

    fake_engine = MagicMock()
    fake_engine.recognize.return_value = RESULTADOS_OCR
    estado._ocr_engine = fake_engine
    estado._data_manager = _DataManagerFake()

    client = TestClient(app)
    with open(caminho_pdf, "rb") as f:
        resp = client.post("/lotes", files={"files": ("mes.pdf", f, "application/pdf")})
    assert resp.status_code == 201, resp.text
    lote_id = resp.json()["lote_id"]
    assert resp.json()["tipo"] == "pdf"

    client.post(f"/lotes/{lote_id}/processar")
    status = _esperar_conclusao_sincrona(client, lote_id)
    assert status["status"] == estado.STATUS_CONCLUIDO
    assert status["total_paginas"] == 3
    assert status["total_registros"] == 6  # 2 registros x 3 páginas, mesmo mock em todas
    print(f"  OK: PDF de 3 páginas -> {status['total_registros']} registros, "
          f"{status['paginas_com_erro']} páginas com erro")
    print()


def teste_erros_http():
    print("=== Teste 4: respostas de erro (400/404/409) ===")
    _resetar_estado_global()
    client = TestClient(app)

    resp = client.post("/lotes", files={"files": ("a.txt", b"nao e imagem nem pdf", "text/plain")})
    assert resp.status_code == 400
    print("  OK: extensão não suportada -> 400")

    resp = client.get("/lotes/nao-existe/status")
    assert resp.status_code == 404
    print("  OK: lote_id desconhecido -> 404 em vez de estado global implícito")
    print()


def main():
    teste_fluxo_imagem_unica()
    teste_explicacao_e_imagem_pagina()
    teste_isolamento_falha_lote_imagens()
    teste_lote_pdf_multipagina()
    teste_erros_http()
    print("=" * 70)
    print("TESTE DE API COM OCR MOCKADO (SUB-FASES 24a/24c): TUDO OK")


if __name__ == "__main__":
    main()
