"""
web/backend/testes/teste_api_lote_real.py

Fase 24a (Web MVP) -- verificação com chamadas de API REAIS (via
`fastapi.testclient.TestClient`, que roda a aplicação FastAPI de verdade
em processo, sem subir um servidor HTTP à parte) contra as MESMAS 5 folhas
reais usadas desde a Fase 9 (`entrada/pdf/teste.pdf`). Usa PaddleOCR REAL
(não mockado) -- por isso demorado (~40 s/folha, ~200 s no total) e por
isso este arquivo, como `teste_ocr.py`, não faz parte do "roda tudo em
segundos" da suíte principal; roda-se sob demanda.

O que este arquivo prova, que nenhum outro teste prova:

  1. upload -> disparo -> polling de status -> registros -> exportação
     funcionam de ponta a ponta através da API HTTP de verdade (não só
     chamando funções Python diretamente);
  2. o resultado bate com a baseline conhecida (40 registros, 19
     CONFIRMADO, 21 REVISAO, 0 ERRO -- ver CLAUDE.md, Fases 9/11/12...);
  3. confirmar um registro REVISAO pela API produz o MESMO resultado que
     chamar `confirmar_revisao_manual` diretamente em processo sobre uma
     cópia do mesmo registro -- ou seja, a camada HTTP não altera nem
     perde nada entre o cliente e a função de decisão compartilhada com o
     Tkinter (é essa igualdade, campo a campo, que substitui "comparar
     com o que o Tkinter faria": desde a Fase 24a, `_revisao_confirmar` no
     Tkinter É essa mesma função).

Rodar (a partir da raiz do projeto, com o venv ativo):
    python web\\backend\\testes\\teste_api_lote_real.py
"""
import copy
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))

from fastapi.testclient import TestClient

from leitor_matriculas.validacao.confirmacao import confirmar_revisao_manual
from web.backend import estado
from web.backend.main import app

CAMINHO_PDF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "entrada", "pdf", "teste.pdf"
)
TIMEOUT_PROCESSAMENTO_S = 400
INTERVALO_POLLING_S = 3


def _esperar_conclusao(client: TestClient, lote_id: str) -> dict:
    inicio = time.monotonic()
    while True:
        resp = client.get(f"/lotes/{lote_id}/status")
        assert resp.status_code == 200, resp.text
        status = resp.json()
        print(f"  status: {status['status']} -- folha {status['pagina_atual']}/{status['total_paginas']} "
              f"-- etapa: {status['etapa_atual']!r}")
        if status["status"] in (estado.STATUS_CONCLUIDO, estado.STATUS_ERRO):
            return status
        if time.monotonic() - inicio > TIMEOUT_PROCESSAMENTO_S:
            raise TimeoutError(f"Lote '{lote_id}' não concluiu em {TIMEOUT_PROCESSAMENTO_S}s")
        time.sleep(INTERVALO_POLLING_S)


def main():
    assert os.path.isfile(CAMINHO_PDF), f"PDF de teste não encontrado: {CAMINHO_PDF}"

    client = TestClient(app)

    print("=== Teste 1: saúde da API ===")
    resp = client.get("/saude")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    print("  OK")

    print("\n=== Teste 2: upload do PDF real (5 folhas) -> lote_id ===")
    with open(CAMINHO_PDF, "rb") as f:
        resp = client.post("/lotes", files={"files": ("teste.pdf", f, "application/pdf")})
    assert resp.status_code == 201, resp.text
    lote = resp.json()
    lote_id = lote["lote_id"]
    assert lote["tipo"] == "pdf"
    assert lote["total_arquivos"] == 1
    print(f"  OK: lote_id={lote_id}")

    print("\n=== Teste 3: status antes de processar ===")
    resp = client.get(f"/lotes/{lote_id}/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == estado.STATUS_PENDENTE
    print("  OK: status inicial 'pendente'")

    print("\n=== Teste 4: registro/exportação antes de processar (comportamento seguro) ===")
    assert client.get(f"/lotes/{lote_id}/registros").json() == []
    resp_exportar_cedo = client.get(f"/lotes/{lote_id}/exportar")
    assert resp_exportar_cedo.status_code == 409, "exportar lote vazio deveria falhar com 409, nunca gerar planilha vazia"
    print("  OK: registros=[] e exportar recusa lote sem nenhum registro (409)")

    print("\n=== Teste 5: disparar processamento (thread em background, OCR REAL ~200s) ===")
    resp = client.post(f"/lotes/{lote_id}/processar")
    assert resp.status_code == 202, resp.text
    print("  OK: 202 aceito, processando em background -- iniciando polling de status...")

    print("\n=== Teste 6: polling até concluir ===")
    status_final = _esperar_conclusao(client, lote_id)
    assert status_final["status"] == estado.STATUS_CONCLUIDO, status_final
    assert status_final["erro_fatal"] is None, status_final
    print(f"  OK: concluído em {status_final}")

    print("\n=== Teste 7: uma segunda chamada de 'processar' é recusada (409) ===")
    resp = client.post(f"/lotes/{lote_id}/processar")
    assert resp.status_code == 409
    print("  OK: reprocessar um lote já concluído é recusado, não silenciosamente ignorado nem duplicado")

    print("\n=== Teste 8: baseline campo a campo (40 registros, 19 CONFIRMADO, 21 REVISAO, 0 ERRO) ===")
    resp = client.get(f"/lotes/{lote_id}/registros")
    assert resp.status_code == 200
    registros = resp.json()
    assert len(registros) == 40, f"esperava 40 registros, veio {len(registros)}"
    confirmados = [r for r in registros if r["status"] == "CONFIRMADO"]
    revisao = [r for r in registros if r["status"] == "REVISAO"]
    erro = [r for r in registros if r["status"] == "ERRO"]
    assert len(confirmados) == 19, f"esperava 19 CONFIRMADO, veio {len(confirmados)}"
    assert len(revisao) == 21, f"esperava 21 REVISAO, veio {len(revisao)}"
    assert len(erro) == 0, f"esperava 0 ERRO, veio {len(erro)}"
    # Cada registro tem a mesma FORMA que ui/app.py monta -- as chaves
    # técnicas (evidências/Fase 17, ocr_nao_associados/Fase 12) precisam
    # estar presentes, senão a Fase 24c (revisão no frontend) não teria
    # como explicar a pendência como a Fase 18 já faz no Tkinter.
    exemplo = registros[0]
    for chave in ("data", "hora", "matricula", "nome", "cargo", "setor", "gestor", "motivo",
                  "pagina_origem", "status", "observacao", "ocr_nao_associados", "evidencias"):
        assert chave in exemplo, f"chave '{chave}' ausente no registro exportado pela API"
    print(f"  OK: 40/19/21/0 confirmado via API (idêntico à baseline medida diretamente pelo pipeline.py "
          f"e à baseline histórica do Tkinter -- ver CLAUDE.md)")

    print("\n=== Teste 9: exportar XLSX do lote concluído ===")
    resp = client.get(f"/lotes/{lote_id}/exportar")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(resp.content) > 0
    print(f"  OK: XLSX gerado, {len(resp.content)} bytes")

    print("\n=== Teste 10: confirmar um registro REVISAO pela API == confirmar_revisao_manual direto ===")
    indice_revisao = next(i for i, r in enumerate(registros) if r["status"] == "REVISAO")
    registro_original_api = registros[indice_revisao]
    print(f"  registro escolhido: índice {indice_revisao}, página {registro_original_api['pagina_origem']}, "
          f"observação original: {registro_original_api['observacao']!r}")

    # A correção em si não precisa RESOLVER o registro para provar a
    # equivalência -- só precisa ser a MESMA entrada nos dois caminhos
    # (PROBLEMA D, Fase 7: uma correção que não resolve tem que se
    # comportar identicamente nos dois lugares também, não só a que
    # resolve). Usa os próprios valores já presentes no registro (podem
    # estar vazios) mais uma matrícula claramente inválida para forçar um
    # cenário determinístico e comparável nos dois lados.
    correcao = {
        "data": registro_original_api.get("data") or "",
        "hora": registro_original_api.get("hora") or "",
        "matricula": registro_original_api.get("matricula") or "",
        "gestor": registro_original_api.get("gestor") or "",
        "motivo": registro_original_api.get("motivo") or "",
    }

    # Caminho A: direto em processo, sobre uma CÓPIA do registro original
    # (antes de qualquer confirmação), com um ContextoLote NOVO e
    # equivalente (mesmas datas do lote já registradas via a mesma
    # sequência que o backend usou) -- para eliminar qualquer diferença
    # que não seja da função de confirmação em si, comparamos contra o
    # ContextoLote que o PRÓPRIO lote já acumulou (obtido do estado
    # interno, é o mesmo objeto que a rota usa).
    lote_state = estado.obter_lote(lote_id)
    copia_para_comparacao = copy.deepcopy(registro_original_api)
    resultado_direto = confirmar_revisao_manual(
        copia_para_comparacao,
        data=correcao["data"], hora=correcao["hora"], matricula=correcao["matricula"],
        gestor=correcao["gestor"], motivo=correcao["motivo"],
        data_manager=estado.obter_data_manager(),
        contexto_lote=lote_state.contexto_lote,
    )

    # Caminho B: pela API, sobre o registro de verdade do lote.
    resp = client.post(f"/lotes/{lote_id}/registros/{indice_revisao}/confirmar", json=correcao)
    assert resp.status_code == 200, resp.text
    resultado_api = resp.json()

    # Os dois caminhos partiram do MESMO estado (o registro original ainda
    # não tinha sido tocado por nenhuma confirmação em nenhum dos dois até
    # aqui) e receberam a MESMA entrada -- o resultado tem que bater campo
    # a campo, prova de que a API não reimplementa nem altera a decisão.
    for campo in ("data", "hora", "matricula", "nome", "cargo", "setor", "gestor", "motivo",
                  "status", "observacao", "confianca_matricula", "confianca_gestor", "confianca_motivo"):
        valor_direto = copia_para_comparacao[campo]
        valor_api = resultado_api["registro"][campo]
        assert valor_direto == valor_api, (
            f"campo '{campo}' divergiu entre confirmar_revisao_manual direto ({valor_direto!r}) "
            f"e via API ({valor_api!r}) -- a API deveria produzir EXATAMENTE o mesmo resultado"
        )
    assert resultado_direto.confirmou_agora == resultado_api["confirmou_agora"]
    assert resultado_direto.status_anterior == resultado_api["status_anterior"] == "REVISAO"
    print(f"  OK: confirmação via API idêntica, campo a campo, a confirmar_revisao_manual chamada direto "
          f"(confirmou_agora={resultado_api['confirmou_agora']}, status final={resultado_api['registro']['status']!r})")

    print("\n=== Teste 11: confirmar um índice inexistente devolve 404 (nunca inventa registro) ===")
    resp = client.post(f"/lotes/{lote_id}/registros/9999/confirmar", json=correcao)
    assert resp.status_code == 404
    print("  OK")

    print("\n=== Teste 12: lote_id inexistente devolve 404 em toda rota, nunca estado global vazando ===")
    for rota in (
        ("get", "/lotes/lote-que-nao-existe/status"),
        ("get", "/lotes/lote-que-nao-existe/registros"),
        ("post", "/lotes/lote-que-nao-existe/processar"),
        ("get", "/lotes/lote-que-nao-existe/exportar"),
    ):
        metodo, caminho = rota
        resp = getattr(client, metodo)(caminho)
        assert resp.status_code == 404, f"{caminho} -> {resp.status_code}"
    print("  OK: todo endpoint isola por lote_id -- nenhum 'estado atual' implícito")

    print("\n" + "=" * 70)
    print("TESTE DE API CONTRA O LOTE REAL (SUB-FASE 24a): TUDO OK")


if __name__ == "__main__":
    main()
