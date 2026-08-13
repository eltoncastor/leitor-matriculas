# Leitor de Matrículas — Web (Fase 24)

Versão web do Leitor de Matrículas: mesmo pacote `leitor_matriculas` (em
`src/`) que a versão Tkinter usa — OCR, parser, validação, regras,
evidências, exportação e aprendizado não são reescritos aqui, só expostos
via API. A versão Tkinter (`python main.py`, na raiz) continua existindo
e funcionando exatamente igual — esta é uma segunda porta de entrada para
o mesmo pacote, não uma substituição.

Ver `CLAUDE.md` (seção Architecture, Fase 24) para o desenho completo e o
que cada sub-fase entregou.

## Backend (Fase 24a)

```powershell
# Da raiz do projeto, com o venv já ativo (mesmo venv do app Tkinter —
# só precisa instalar fastapi/uvicorn/python-multipart a mais, já
# listados em requirements.txt):
python web\backend\main.py
# ou, com autorreload durante o desenvolvimento:
python -m uvicorn web.backend.main:app --reload --host 127.0.0.1 --port 8000
```

Documentação interativa (Swagger): http://127.0.0.1:8000/docs

**Escopo desta fase**: sem autenticação, sem multiusuário real — a API
nunca deve ser exposta além de `localhost`/rede local. Isso é decisão de
projeto (ver CLAUDE.md), não uma limitação a corrigir aqui.

### Testes do backend

```powershell
# Rápido (~segundos), PaddleOCR MOCKADO -- roda a cada alteração:
python web\backend\testes\teste_api_mock.py

# Lento (~3-4 min), PaddleOCR REAL contra as mesmas 5 folhas reais usadas
# desde a Fase 9 (entrada\pdf\teste.pdf) -- roda antes de fechar uma
# sub-fase, não a cada alteração:
python web\backend\testes\teste_api_lote_real.py
```

## Frontend (Fase 24b — ainda não implementado)

React + Tailwind (Vite), planejado para `web/frontend/`.
