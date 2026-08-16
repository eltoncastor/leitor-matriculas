"""
web/backend/testes/teste_estaticos_spa.py

Sub-fase 25a (retomada da Fase 25 -- empacotamento web em .exe portátil):
`web/backend/main.py` passou a também servir o build de produção do
frontend (`web/frontend/dist/`, quando existe) -- este teste confirma que
essa mudança NÃO "roubou" nenhuma rota de API para o catch-all da SPA (a
armadilha explícita desta sub-fase) e que o roteamento de estáticos em si
funciona. Sem OCR, sem PaddleOCR mockado -- é roteamento puro, testável
com `TestClient` e nada mais.

`web/frontend/dist/` é gitignored (artefato de build, não versionado) --
então este teste tem DOIS modos, dependendo do que encontrar no disco:

  - COM o build presente (`npm run build` já rodado): testa o cenário
    completo -- API continua respondendo, estáticos são servidos, rotas
    do React Router caem no mesmo index.html, e um subcaminho de API mal
    formado continua devolvendo 404 (não vira HTML da SPA por engano).
  - SEM o build (clone novo, build nunca rodado): só confirma que a API
    continua funcionando exatamente como sem esta sub-fase (nenhuma
    regressão) -- não falha por falta de um artefato que é opcional por
    natureza, mesmo padrão de `dados/` ausente não derrubar a suíte.

Rodar (a partir da raiz do projeto, com o venv ativo):
    python web\\backend\\testes\\teste_estaticos_spa.py
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))

from fastapi.testclient import TestClient

from web.backend.main import app

_DIST_DIR = pathlib.Path(__file__).resolve().parents[3] / "web" / "frontend" / "dist"


def main():
    client = TestClient(app)

    print("=== Bloco 1: rotas de API continuam respondendo (com ou sem o build) ===")
    r = client.get("/saude")
    assert r.status_code == 200 and r.json() == {"status": "ok"}, r.text
    r = client.get("/api/saude")
    assert r.status_code == 200 and r.json() == {"status": "ok"}, r.text
    r = client.get("/lotes/nao-existe/status")
    assert r.status_code == 404 and "não encontrado" in r.json()["detail"]
    r = client.get("/api/lotes/nao-existe/status")
    assert r.status_code == 404 and "não encontrado" in r.json()["detail"]
    print("  OK: /saude, /api/saude, /lotes/.../status e /api/lotes/.../status (dual-mount)")

    if not (_DIST_DIR / "index.html").is_file():
        print(
            "\n(build de produção não encontrado em web/frontend/dist/ -- "
            "rode 'npm run build' em web/frontend para exercitar os blocos "
            "de estáticos/SPA abaixo; sem ele, este teste só confirma que a "
            "API não regrediu, o que já foi feito acima.)"
        )
        print("\nTESTE DE ESTÁTICOS/SPA (SUB-FASE 25a): OK (modo sem build)")
        return

    print("\n=== Bloco 2: build presente -- index.html na raiz ===")
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert '<div id="root">' in r.text
    corpo_index = r.text
    print("  OK: GET / devolve o index.html do build")

    print("=== Bloco 3: rota do React Router cai no MESMO index.html (SPA fallback) ===")
    for rota in ("/lote/qualquer-coisa", "/lote/abc123/revisao", "/uma/rota/que/nao/existe/no/backend"):
        r = client.get(rota)
        assert r.status_code == 200, (rota, r.status_code)
        assert r.text == corpo_index, f"{rota} devolveu HTML diferente do index.html"
    print("  OK: rotas do cliente (React Router) devolvem o mesmo index.html, não um 404")

    print("=== Bloco 4: arquivos estáticos reais são servidos ===")
    algum_css = next((_DIST_DIR / "assets").glob("*.css"))
    r = client.get(f"/assets/{algum_css.name}")
    assert r.status_code == 200 and "text/css" in r.headers["content-type"]
    r = client.get("/favicon.svg")
    assert r.status_code == 200 and "svg" in r.headers["content-type"]
    print("  OK: /assets/*.css e /favicon.svg (arquivo solto na raiz do build) servidos corretamente")

    print("=== Bloco 5 (a armadilha desta sub-fase): subcaminho de API mal formado NÃO vira HTML ===")
    for rota_invalida in ("/lotes/abc/rota-que-nao-existe", "/api/lotes/abc/rota-que-nao-existe"):
        r = client.get(rota_invalida)
        assert r.status_code == 404, f"{rota_invalida} deveria ser 404, veio {r.status_code}"
        assert "application/json" in r.headers["content-type"], (
            f"{rota_invalida} deveria devolver JSON de erro, não a página da SPA "
            f"(content-type veio {r.headers['content-type']!r}) -- a rota catch-all "
            f"'roubou' um subcaminho de API"
        )
    print("  OK: subcaminho de API sem endpoint real continua 404 JSON, nunca vira a página da SPA")

    print("=== Bloco 6: defesa contra path traversal na rota catch-all ===")
    r = client.get("/assets/../../../../requirements.txt")
    assert r.status_code == 200 and r.text == corpo_index, (
        "tentativa de path traversal deveria cair no fallback do index.html, "
        "nunca vazar um arquivo de fora de dist/"
    )
    assert "paddleocr" not in r.text.lower(), "path traversal vazou conteúdo de fora de dist/!"
    print("  OK: tentativa de escapar de dist/ cai no fallback do index.html, não vaza nada")

    print("\nTESTE DE ESTÁTICOS/SPA (SUB-FASE 25a): TUDO OK (modo com build)")


if __name__ == "__main__":
    main()
