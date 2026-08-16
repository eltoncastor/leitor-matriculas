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

Documentação interativa (Swagger): http://127.0.0.1:8000/docs (uso local) ou
http://<IP-tailscale-desta-máquina>:8000/docs (acesso remoto — ver seção
"Acesso remoto (Tailscale)" abaixo).

**Escopo**: sem autenticação, sem multiusuário real — decisão de projeto
inalterada (ver CLAUDE.md). **Ajuste pontual pós-Fase 24**: o servidor
passou a escutar em `0.0.0.0` (todas as interfaces de rede) em vez de só
`127.0.0.1`, para permitir acesso remoto via Tailscale — não é mais "nunca
exposta além de localhost". O que continua protegendo isto de virar um
servidor público é a ausência de qualquer port-forwarding no roteador e o
uso do Tailscale (VPN privada, só os dispositivos da própria conta) para o
acesso de fora da rede local — nunca a internet aberta. Ver
`saida/ajuste_acesso_tailscale.md` para o detalhe completo.

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

## Acesso remoto (Tailscale)

Ajuste pontual pós-Fase 24 — continua sendo uso de UMA pessoa só (o dono do lote), agora
a partir de qualquer dispositivo dela, não só a máquina onde os servidores rodam. Não é
o início do suporte a múltiplos usuários simultâneos, e não há autenticação nova.

1. **Instalar o Tailscale** nos dois dispositivos (a máquina que roda `uvicorn`/`vite dev`
   e o dispositivo remoto, ex. um notebook do trabalho) e entrar com a MESMA conta nos
   dois — configuração de conta/app do Tailscale, fora do escopo deste repositório.
2. **Descobrir o IP Tailscale** da máquina que roda os servidores: `tailscale ip -4` no
   terminal dela, ou o próprio app do Tailscale mostra (sempre começa com `100.`).
3. **Rodar os dois servidores normalmente**, na máquina de origem — nada aqui virou um
   serviço permanente/instalado; os dois processos continuam precisando estar rodando
   enquanto o acesso remoto é usado, exatamente como no uso local:
   ```powershell
   python web\backend\main.py         # agora escuta em 0.0.0.0:8000
   cd web\frontend; npm run dev        # agora escuta em 0.0.0.0:5173 (host: true)
   ```
4. **No dispositivo remoto**, com o Tailscale conectado, abrir no navegador:
   `http://<IP-tailscale-da-máquina-de-origem>:5173` — o `vite.config.js` já resolve o
   proxy de `/api/*` para o backend na MESMA máquina de origem (`127.0.0.1:8000` do
   ponto de vista dela), então não é preciso apontar o frontend para o backend
   manualmente.

**O que protege isto de virar um servidor público**: nenhum port-forwarding é feito no
roteador (em nenhuma das redes onde a máquina de origem estiver) — sem isso, a internet
aberta não alcança as portas 8000/5173 desta máquina. O acesso de fora da rede local é
sempre através da tailnet privada (só os dispositivos da própria conta), nunca da
internet pública. Ver o docstring de `web/backend/main.py` e
`saida/ajuste_acesso_tailscale.md` para o detalhe completo da mudança de decisão.

## Modo desktop — janela nativa (Sub-fase 25a)

Retomada da ideia de portabilidade (Fase 25, ver CLAUDE.md) — desta vez mirando a versão
WEB, não o Tkinter. Um processo Python SÓ, com uma janela nativa (`pywebview`) no lugar
do navegador — sem precisar do `vite dev` rodando à parte. Ainda não é um `.exe`
(isso é a Sub-fase 25b, empacotamento com PyInstaller); continua rodando via `python`.

```powershell
# 1. Build de produção do frontend (uma vez, ou de novo a cada mudança no frontend):
cd web\frontend
npm run build          # gera web\frontend\dist\
cd ..\..

# 2. Janela nativa (sobe o backend internamente, numa thread -- não é
#    um segundo processo/terminal):
python web\desktop_app.py
```

Fechar a janela encerra o servidor interno junto — não sobra nenhum processo
`python`/`uvicorn` rodando depois. Sem o build de produção (`dist/index.html` ausente),
o script avisa e sai, em vez de abrir uma janela mostrando só a API pura.

Este modo é independente do modo de desenvolvimento (`vite dev` + `python web\backend\main.py`
em dois terminais, seção acima) e do acesso remoto via Tailscale — os três continuam
existindo e funcionando lado a lado. Ver `saida/avaliacao_fase25_exe.md` para o detalhe
completo (decisão sobre CORS, tamanho de baseline medido, limitações).

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
