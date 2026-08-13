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

## Frontend (Fase 24b)

React + Tailwind v4 (Vite), em `web/frontend/`. Precisa do backend acima rodando em
`127.0.0.1:8000` — o dev server do Vite faz proxy de `/api/*` para lá (ver
`web/frontend/vite.config.js`).

```powershell
cd web\frontend
npm install
npm run dev       # http://localhost:5173
```

**Sem Node.js instalado?** Se `winget install OpenJS.NodeJS.LTS` travar esperando
elevação de administrador (ambiente sem privilégio interativo), baixe a distribuição
portátil oficial (zip, sem instalador) em https://nodejs.org/en/download e extraia-a em
qualquer pasta local — não precisa instalar no sistema, só ter `node`/`npm` no `PATH` da
sessão em que você rodar os comandos acima. Foi assim que esta sub-fase foi desenvolvida
(pasta `.tools/`, gitignored — ver `saida/avaliacao_fase24_web.md`, seção 24b).

Outros comandos:

```powershell
npm run test       # Vitest -- rápido, roda a cada alteração
npm run build       # build de produção em web\frontend\dist
npm run lint         # oxlint
```

### Estrutura

```
web/frontend/src/
  lib/api.js               -- único ponto que fala com o backend (10 endpoints)
  components/ui/            -- Button, GlassCard, ProgressBar, StatusBadge
  components/layout/         -- AppShell (cabeçalho + fundo, sem lógica; prop `largo`)
  features/lote/               -- telas do fluxo de um lote (Seleção, Processamento, Resultado)
  features/revisao/              -- useRevisao (controlador), ListaPendencias, FotoFolha,
                                     FormularioRevisao, vocabulario (rótulos/cores por campo)
  pages/                           -- rotas: "/" , "/lote/:loteId", "/lote/:loteId/revisao"
```

### O que já existe (24a/24b/24c) / o que falta (24d)

Fluxo principal completo: Seleção → Conferência → Processamento (progresso ao vivo por
polling) → Resultado (contagens + baixar planilha + ir para Revisão). A tela de Revisão
(24c) está completa: as três áreas (pendências / foto da folha / campo bloqueante +
formulário), explicação humana da Fase 18 ("Por que está em revisão?" / "Ver detalhes"),
confirmação real via `confirmar_revisao_manual` (a mesma função do Tkinter). Falta só a
Sub-fase 24d: polimento visual final e a verificação de fidelidade comportamental
completa contra o Tkinter.
