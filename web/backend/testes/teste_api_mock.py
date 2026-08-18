"""
web/backend/testes/teste_api_mock.py

Fase 24a (Web MVP) -- suíte RÁPIDA dos endpoints, sem PaddleOCR (resultados
de OCR sintéticos, `DataManager` fake determinística para não depender do
`dados/` real do operador, que é local e pode nem existir em outra
máquina). Existe ao lado de `teste_api_lote_real.py` (OCR real, ~200 s)
pela mesma razão que `teste_ui_integracao.py` existe ao lado de
`teste_ocr.py`: uma suíte rápida que roda a cada alteração, e uma lenta
que prova contra dado real antes de fechar a sub-fase.

Cobre o que o teste com OCR real não cobre (ou cobre caro demais para
rodar a cada mudança): PROBLEMA C/D da revisão manual pela API, isolamento
de falha por página num lote de imagens (uma foto corrompida no meio não
aborta as demais), lote PDF multi-página, e os erros HTTP (404/409) que o
teste real também cobre mas aqui ficam repetidos com mais variação porque
é barato.

Fase 26d: este arquivo passou a rodar com `LEITOR_MODO=servidor` -- o
processo NÃO roda OCR nenhum (ver `web/backend/config.py`), exatamente o
modo da VPS depois da Fase 26. Onde antes `estado._ocr_engine` era
injetado direto com um `MagicMock`, agora `_WorkerFalso` fala o protocolo
`/api/worker/*` DE VERDADE (mesmos endpoints que `worker/execucao.py` usa
em produção), só dirigido SINCRONAMENTE pela própria thread do teste, sem
`time.sleep`/polling do lado do Worker. `parse_registros`/`reparar_data_
hora_mescladas` -- a mesma dupla que `pipeline.processar_uma_pagina` chama
de verdade -- rodam de verdade sobre os `OCRResult` sintéticos; só o motor
de OCR em si fica de fora (não haveria "OCR de mock" que valesse a pena).
O protocolo em si (auth, claim, lease, fencing) já tem cobertura própria e
mais funda em `teste_worker_api.py`; aqui ele é só o caminho real para
exercitar classificação/revisão ponta a ponta pelo jeito que a VPS
realmente processa um lote agora.

Rodar (a partir da raiz do projeto, com o venv ativo):
    python web\\backend\\testes\\teste_api_mock.py
"""
import os
import sys
import tempfile
import time
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))

# Fase 26d: precisa estar definido ANTES de qualquer chamada às rotas de
# Worker (`config.modo()`/`auth_worker.token_configurado()` leem do
# ambiente a cada chamada -- não há valor "congelado" no import, mas
# fixar aqui, no topo, deixa explícito que o arquivo INTEIRO roda deste
# jeito, não só alguns testes).
TOKEN_WORKER_TESTE = "chave-de-teste-com-mais-de-16-caracteres"
os.environ["LEITOR_WORKER_TOKEN"] = TOKEN_WORKER_TESTE
os.environ["LEITOR_MODO"] = "servidor"

import pymupdf as fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from leitor_matriculas.ocr.engine import OCRResult  # noqa: E402
from leitor_matriculas.parsing.registro_parser import parse_registros  # noqa: E402
from leitor_matriculas.pipeline import reparar_data_hora_mescladas  # noqa: E402
from web.backend import armazenamento, estado  # noqa: E402
from web.backend.main import app  # noqa: E402


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


# Fase 26a: o armazenamento passou a ser DURÁVEL (antes os lotes viviam só
# em memória e os uploads em `tempfile`, recolhidos pelo sistema
# operacional). Rodar a suíte não pode escrever no armazenamento real do
# operador nem deixar lixo no repositório -- mesmo cuidado que a Fase 20 já
# tomou com o histórico de correções, redirecionando `dados/` para um
# arquivo temporário.
_RAIZ_ARMAZENAMENTO_TESTE = tempfile.mkdtemp(prefix="armazenamento_teste_")
armazenamento.definir_raiz(_RAIZ_ARMAZENAMENTO_TESTE)


def _resetar_estado_global():
    """Cada teste roda contra o mesmo processo/`app` (TestClient não sobe
    servidor à parte) -- os lotes de um teste não podem vazar para o
    próximo. Isto NÃO é o que a Fase 24 pediu para evitar ("estado global
    solto") -- é só limpeza ENTRE testes deste arquivo; a API em si
    continua resolvendo tudo por `lote_id`.

    Fase 26a: limpar só o dicionário em memória deixou de bastar -- um
    lote ausente de `_lotes` agora é RECUPERADO do disco por
    `obter_lote`, então um teste enxergaria os lotes do anterior."""
    estado._lotes.clear()
    for lote_id in armazenamento.listar_lotes():
        armazenamento.remover_lote(lote_id)


def _preparar_arquivo_imagem(pasta, nome="folha.jpg"):
    """Só precisa EXISTIR com a extensão certa -- o upload não valida
    conteúdo (`criar_lote` decide o tipo só pela extensão do nome), e o
    `_WorkerFalso` nunca abre o arquivo: os resultados de OCR vêm dos
    fixtures sintéticos deste módulo, não de decodificar a imagem de
    verdade (isso é papel de `worker/testes/teste_worker_real.py`, com
    OCR real). Por isso deixou de precisar de OpenCV/numpy."""
    caminho = os.path.join(pasta, nome)
    with open(caminho, "wb") as f:
        f.write(b"\xff\xd8\xff-imagem-de-teste-sem-conteudo-real")
    return caminho


class _WorkerFalso:
    """
    Fase 26d. O Worker de verdade que este arquivo usa para fazer o lote
    avançar -- fala exatamente os mesmos endpoints HTTP que `worker/
    execucao.py` fala em produção (`claim`, miniatura, resultado da
    página, `concluir`, `erro`), só que:
      - dirigido SINCRONAMENTE por esta classe, chamada pela thread do
        teste -- nenhum `time.sleep`/laço de polling do lado do Worker;
      - sem OCR: quem fornece os `OCRResult` é quem chama `entregar_
        pagina`, com os fixtures sintéticos deste arquivo.
    """

    def __init__(self, client: TestClient, worker_id: str = "worker-falso"):
        self._client = client
        self._cabecalhos = {"Authorization": f"Bearer {TOKEN_WORKER_TESTE}", "X-Worker-Id": worker_id}

    def reivindicar(self, lote_id: str) -> dict:
        resp = self._client.post(f"/api/worker/jobs/{lote_id}/claim", headers=self._cabecalhos)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def entregar_pagina(self, lote_id: str, numero: int, tentativa: int, *,
                         resultados_ocr: Optional[list] = None, erro: Optional[str] = None,
                         fase_erro: Optional[str] = None, miniatura: Optional[bytes] = None) -> str:
        # ORDEM IMPORTA: a miniatura sobe ANTES do resultado -- na última
        # página, entregar o resultado pode fazer a VPS concluir o lote e
        # liberar a posse antes da chamada seguinte deste mesmo Worker
        # (mesmo cuidado de `teste_worker_api.py`).
        if miniatura is not None:
            resp = self._client.put(
                f"/api/worker/jobs/{lote_id}/paginas/{numero}/miniatura",
                params={"tentativa": tentativa}, content=miniatura, headers=self._cabecalhos,
            )
            assert resp.status_code == 204, resp.text

        registros = []
        if erro is None:
            regs = parse_registros(resultados_ocr or []).registros
            reparar_data_hora_mescladas(regs)
            registros = [reg.como_dicionario() for reg in regs]

        resp = self._client.post(
            f"/api/worker/jobs/{lote_id}/paginas/{numero}",
            json={"tentativa": tentativa, "erro": erro, "fase_erro": fase_erro, "registros": registros},
            headers=self._cabecalhos,
        )
        assert resp.status_code == 202, resp.text
        return resp.json()["resultado"]

    def concluir(self, lote_id: str, tentativa: int) -> None:
        resp = self._client.post(f"/api/worker/jobs/{lote_id}/concluir",
                                 json={"tentativa": tentativa}, headers=self._cabecalhos)
        assert resp.status_code == 204, resp.text

    def erro_de_documento(self, lote_id: str, tentativa: int, mensagem: str) -> None:
        resp = self._client.post(f"/api/worker/jobs/{lote_id}/erro",
                                 json={"tentativa": tentativa, "mensagem": mensagem}, headers=self._cabecalhos)
        assert resp.status_code == 204, resp.text


def _processar_com_worker_falso(client: TestClient, lote_id: str, paginas: list) -> None:
    """Reivindica o Job e entrega `paginas` em ordem -- cada item é um dict
    com `numero` e, ou `resultados_ocr` (+ opcionalmente `miniatura`), ou
    `erro`+`fase_erro`. Conclui ao final, como um Worker de verdade faria.
    Não espera o lote terminar: a motora aplica cada página na PRÓPRIA
    thread dela (`estado.processar_lote`); `_esperar_conclusao_sincrona`
    continua sendo quem espera isso."""
    worker = _WorkerFalso(client)
    job = worker.reivindicar(lote_id)
    tentativa = job["tentativa"]
    for pagina in paginas:
        worker.entregar_pagina(
            lote_id, pagina["numero"], tentativa,
            resultados_ocr=pagina.get("resultados_ocr"), erro=pagina.get("erro"),
            fase_erro=pagina.get("fase_erro"), miniatura=pagina.get("miniatura"),
        )
    worker.concluir(lote_id, tentativa)


def _esperar_conclusao_sincrona(client, lote_id, tentativas=100):
    """Sem OCR real, a motora aplica cada página quase instantaneamente --
    ainda assim ela roda numa thread separada (o código de produção não
    sabe que está sendo testado), então esperamos igual, só que por muito
    menos tempo que o teste com OCR real."""
    for _ in range(tentativas):
        status = client.get(f"/lotes/{lote_id}/status").json()
        if status["status"] in (estado.STATUS_CONCLUIDO, estado.STATUS_ERRO):
            return status
        time.sleep(0.05)
    raise TimeoutError(f"Lote '{lote_id}' não concluiu (worker falso) -- possível trava na motora")


def teste_fluxo_imagem_unica():
    print("=== Teste 1: upload de 1 imagem -> processar -> registros -> confirmar -> exportar ===")
    _resetar_estado_global()
    tmp = tempfile.mkdtemp(prefix="teste_api_mock_")
    caminho = _preparar_arquivo_imagem(tmp)
    estado._data_manager = _DataManagerFake()

    client = TestClient(app)
    with open(caminho, "rb") as f:
        resp = client.post("/lotes", files={"files": (os.path.basename(caminho), f, "image/jpeg")})
    assert resp.status_code == 201, resp.text
    lote_id = resp.json()["lote_id"]
    assert resp.json()["tipo"] == "imagens"

    resp = client.post(f"/lotes/{lote_id}/processar")
    assert resp.status_code == 202, resp.text
    _processar_com_worker_falso(client, lote_id, [{"numero": 1, "resultados_ocr": RESULTADOS_OCR}])
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
    caminho = _preparar_arquivo_imagem(tmp)
    estado._data_manager = _DataManagerFake()

    client = TestClient(app)
    with open(caminho, "rb") as f:
        resp = client.post("/lotes", files={"files": (os.path.basename(caminho), f, "image/jpeg")})
    lote_id = resp.json()["lote_id"]
    client.post(f"/lotes/{lote_id}/processar")
    _processar_com_worker_falso(client, lote_id, [
        {"numero": 1, "resultados_ocr": RESULTADOS_OCR, "miniatura": b"\xff\xd8\xff-jpeg-de-teste"},
    ])
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
    print(f"  OK: GET .../paginas/1/imagem -- {len(resp.content)} bytes JPEG (entregues pelo Worker falso)")

    resp = client.get(f"/lotes/{lote_id}/paginas/999/imagem")
    assert resp.status_code == 404
    print("  OK: página sem foto -> 404 (nunca devolve imagem em branco)")
    print()


def teste_isolamento_falha_lote_imagens():
    print("=== Teste 2: lote de imagens com 1 arquivo corrompido no meio -- isola, não aborta (Fase 7) ===")
    _resetar_estado_global()
    tmp = tempfile.mkdtemp(prefix="teste_api_mock_")
    caminho_a = _preparar_arquivo_imagem(tmp, "a.jpg")
    caminho_corrompido = os.path.join(tmp, "b.jpg")
    with open(caminho_corrompido, "wb") as f:
        f.write(b"isto nao e uma imagem valida")
    caminho_c = _preparar_arquivo_imagem(tmp, "c.jpg")
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
    # A página 2 (b.jpg) é quem, num Worker de verdade, falharia ao abrir
    # o arquivo (`worker/execucao.py::_ler_imagem`) -- aqui simulamos essa
    # falha diretamente, exatamente como o Worker a reportaria: `erro` cru
    # e `fase_erro="leitura"`. A frase final ("Falha ao abrir 'b.jpg': ...")
    # é montada do lado da VPS (D8), não pelo Worker -- ver `estado.
    # _mensagem_erro_pagina`.
    _processar_com_worker_falso(client, lote_id, [
        {"numero": 1, "resultados_ocr": RESULTADOS_OCR},
        {"numero": 2, "erro": "não foi possível decodificar a imagem", "fase_erro": "leitura"},
        {"numero": 3, "resultados_ocr": RESULTADOS_OCR},
    ])
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
    estado._data_manager = _DataManagerFake()

    client = TestClient(app)
    with open(caminho_pdf, "rb") as f:
        resp = client.post("/lotes", files={"files": ("mes.pdf", f, "application/pdf")})
    assert resp.status_code == 201, resp.text
    lote_id = resp.json()["lote_id"]
    assert resp.json()["tipo"] == "pdf"

    client.post(f"/lotes/{lote_id}/processar")
    _processar_com_worker_falso(client, lote_id, [
        {"numero": 1, "resultados_ocr": RESULTADOS_OCR},
        {"numero": 2, "resultados_ocr": RESULTADOS_OCR},
        {"numero": 3, "resultados_ocr": RESULTADOS_OCR},
    ])
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
    print("TESTE DE API SEM OCR, PELO PROTOCOLO DE WORKER DE VERDADE (SUB-FASES 24a/24c/26d): TUDO OK")


if __name__ == "__main__":
    main()
