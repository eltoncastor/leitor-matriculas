"""
web/backend/main.py

Ponto de entrada do backend web (Fase 24a -- Web MVP). Importa o pacote
`leitor_matriculas` já existente em `src/` -- NÃO reescreve OCR, parser,
validação, regras, evidências, associação, exportação nem aprendizado; só
expõe o que já existe via HTTP. A versão Tkinter (`main.py`, na raiz)
continua existindo e funcionando exatamente igual -- este arquivo é uma
segunda porta de entrada para o MESMO pacote, não uma substituição.

Como o projeto roda direto do diretório, sem instalação via pip (mesma
decisão do `main.py` da raiz), este arquivo também acrescenta `src/` ao
sys.path antes de importar `leitor_matriculas` -- sem isso, rodar `python
web/backend/main.py` (ou `uvicorn web.backend.main:app`) de qualquer outro
diretório de trabalho falharia ao importar o pacote.

ESCOPO DESTA FASE (ver CLAUDE.md, Fase 24): sem autenticação, sem
multiusuário real (`lote_id` isola o ESTADO, não isola por USUÁRIO -- ver
`estado.py`), e a API NUNCA deve ser exposta além de localhost/rede local
-- por isso o `uvicorn.run` abaixo (usado só quando este arquivo roda
diretamente) fixa `host="127.0.0.1"`. Publicar isto num servidor acessível
pela empresa é conversa de uma fase futura, depois do MVP validado.

Rodar (a partir da raiz do projeto):
    python web/backend/main.py
ou, com autorreload durante o desenvolvimento:
    venv\\Scripts\\python.exe -m uvicorn web.backend.main:app --reload --host 127.0.0.1 --port 8000

A documentação interativa (Swagger) fica em http://127.0.0.1:8000/docs
"""
import os
import sys

_RAIZ_PROJETO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
# `src/` para importar `leitor_matriculas` (mesma decisão do main.py da
# raiz) e a RAIZ do projeto para importar este próprio pacote (`web.
# backend...`) por caminho absoluto -- necessário para `python web/
# backend/main.py` funcionar (nesse modo o Python só coloca `web/backend/`
# no sys.path automaticamente, não a raiz) e continua funcionando também
# com `uvicorn web.backend.main:app` (que já roda com a raiz no caminho).
sys.path.insert(0, os.path.join(_RAIZ_PROJETO, "src"))
sys.path.insert(0, _RAIZ_PROJETO)

from fastapi import FastAPI  # noqa: E402  (precisa vir depois do sys.path)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from web.backend.rotas import lotes  # noqa: E402

app = FastAPI(
    title="Leitor de Matrículas -- API Web (MVP)",
    description=(
        "Backend FastAPI que reaproveita o pacote leitor_matriculas "
        "(OCR/parser/validação/exportação) já usado pela versão Tkinter. "
        "Fase 24a -- ver CLAUDE.md."
    ),
    version="24a",
)

# CORS liberado só para origens locais de desenvolvimento -- o frontend
# (Fase 24b, Vite) roda numa porta diferente da API. Isto não é a mesma
# coisa que "expor além de localhost": o servidor continua ouvindo só em
# 127.0.0.1 (ver uvicorn.run abaixo); CORS apenas decide quais ORIGENS
# um navegador aceita chamar, e aqui só origens da própria máquina.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lotes.router)


@app.get("/saude")
def saude():
    """Checagem simples de que o processo está de pé -- não toca em
    OCR/bases, só confirma que a API responde."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
