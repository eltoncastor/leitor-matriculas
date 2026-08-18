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

# Fase 26a -- Job, persistência e ordem de chegada das páginas (rápido, sem OCR):
python web\backend\testes\teste_job_persistencia.py

# Fase 26b -- protocolo /api/worker/* (auth, claim, lease, ficha de cerca; rápido, sem OCR):
python web\backend\testes\teste_worker_api.py
```

Todos redirecionam o armazenamento para uma pasta temporária: rodar a suíte nunca escreve no
armazenamento real do operador nem deixa lixo no repositório.

## Modo de operação e armazenamento (Fase 26a)

A partir da Fase 26 o backend pode rodar o OCR ele mesmo ou delegá-lo a um **Worker** (um processo
separado, tipicamente no PC Windows do operador — ver `saida/auditoria_fase26_ocr_worker.md`).
Quem decide isso é uma variável de ambiente:

| Variável | Padrão | Para que serve |
|---|---|---|
| `LEITOR_MODO` | `local` | `local`: este processo roda o OCR (modo desktop, `.exe` e desenvolvimento). `servidor`: este processo **não** roda OCR — os lotes ficam aguardando um Worker. É o modo da VPS. |
| `LEITOR_ARMAZENAMENTO` | `<raiz>/armazenamento` | Onde ficam os lotes (arquivos enviados, resultado de OCR por página, fotos das folhas, planilha gerada). Na VPS, aponte para um caminho que sobreviva ao deploy. |
| `LEITOR_WORKER_TOKEN` | *(nenhum)* | Fase 26b. Token que autentica as rotas `/api/worker/*`. Sem ele configurado, TODA requisição de Worker é recusada (503) -- nunca aceita por padrão. Escolha uma string com pelo menos 16 caracteres; nunca commitar. |

O padrão é `local` de propósito: quem não configurar nada tem o comportamento de sempre, e um erro
de configuração na VPS resulta em "a máquina errada trabalhou", nunca em "o lote sumiu".

**O armazenamento passou a ser durável.** Antes da Fase 26 tudo vivia em memória e os uploads iam
para `tempfile` (recolhidos pelo sistema operacional) — um reinício do backend apagava lotes
inteiros em silêncio, com o `status` congelado em "processando". Agora um lote sobrevive ao
reinício, e um lote que estava sendo processado volta para a fila **sem refazer o OCR das páginas
já lidas**. Em troca, a limpeza virou explícita: lotes com mais de 30 dias são removidos na
inicialização. A pasta é gitignored (contém matrículas e nomes reais) e recriada sozinha.

## Protocolo de Worker (Fase 26b)

`/api/worker/*` (`web/backend/rotas/worker.py`) é o que o Worker (Sub-fase 26c, abaixo) fala com a
VPS -- a direção é sempre `Worker → VPS` (o Worker está atrás de NAT, faz polling e entrega resultado
por POST, nunca recebe conexão). Montado **só** sob `/api/worker`, nunca sob `/leitor/api/worker` --
como o Cloudflare Tunnel só roteia `/leitor/*` até este backend, essa decisão já torna a superfície
de Worker inalcançável da internet pública, por construção; o acesso real é pela Tailscale, e o
token (`LEITOR_WORKER_TOKEN`, acima) é a segunda camada, nunca a única.

Toda chamada exige `Authorization: Bearer <LEITOR_WORKER_TOKEN>` e `X-Worker-Id: <identificador>`
(o `worker_id` é só um rótulo de log -- quem decide autorização é sempre o token). Fluxo: `POST
/register` (opcional, valida a configuração) → `GET /jobs/next` (fila) → `POST /jobs/{id}/claim`
(reivindicação atômica -- devolve uma `tentativa`, a ficha de cerca que toda chamada seguinte
precisa repetir) → `GET /jobs/{id}/arquivos/{indice}` (baixar a folha) → por página: `PUT
/jobs/{id}/paginas/{n}/miniatura` **antes de** `POST /jobs/{id}/paginas/{n}` (ordem importa -- ver
`saida/auditoria_fase26_ocr_worker.md`, Sub-fase 26b) → `POST /jobs/{id}/progresso` (opcional) →
`POST /jobs/{id}/concluir`. Falha do documento inteiro (arquivo que não abre): `POST /jobs/{id}/erro`.

## Worker Windows (Fase 26c)

O pacote `worker/` (raiz do projeto, ao lado de `web/`) é o processo que roda o OCR de verdade --
tipicamente no PC Windows do operador, falando com a VPS pelo protocolo acima. **Não hospeda
servidor nenhum, não abre porta, não precisa de IP público** -- só faz requisições de saída.

### Requisitos

- Python 3.10.11 (mesma versão do resto do projeto).
- Um `venv` com `requirements-worker.txt` instalado -- **não** precisa de `requirements.txt`
  completo nem de `requirements-api.txt` (o Worker não hospeda FastAPI, não lê planilha de
  referência nenhuma).

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-worker.txt
```

### Configuração

Copie `.env.example` para `.env` (raiz do projeto) e preencha:

```
API_BASE_URL=http://100.x.x.x:8000      # IP Tailscale da VPS -- nunca o dominio publico
OCR_WORKER_ID=pc-do-operador            # so um rotulo de log
OCR_WORKER_TOKEN=<o MESMO valor de LEITOR_WORKER_TOKEN configurado na VPS>
POLL_INTERVAL=5                          # opcional
HEARTBEAT_INTERVAL=20                    # opcional
```

`.env` nunca é versionado. Uma variável de ambiente real (`$env:OCR_WORKER_TOKEN = "..."` no
PowerShell) sempre tem prioridade sobre o `.env`.

### Executar

```powershell
python -m worker
```

ou, com o venv já ativo, `iniciar_worker.bat` (mesma convenção dos outros atalhos `.bat` da raiz).
`Ctrl+C` pede uma parada educada (espera o Job atual terminar); um segundo `Ctrl+C` força.

### Logs

Formato `[Worker] ...` -- nunca inclui o token nem dado pessoal das folhas (matrícula, nome). O que
aparece: `worker_id`, endereço do servidor, `lote_id` de cada Job recebido/concluído, a etapa atual
de cada página (as mesmas frases que `Processamento.jsx` já mostra no navegador), e mensagens de
erro técnico (rede fora do ar, token inválido, falha de OCR numa página específica).

### Troubleshooting

| Sintoma | Causa provável |
|---|---|
| `[Worker] Configuração incompleta -- faltam: ...` | `.env` ausente/incompleto, ou variável de ambiente não definida. O programa não tenta nenhuma requisição sem essas três. |
| `401: Token de Worker inválido` | `OCR_WORKER_TOKEN` (Worker) diferente de `LEITOR_WORKER_TOKEN` (VPS) -- precisam ser IDÊNTICOS. |
| `503: Este servidor não tem um token de Worker configurado` | A VPS está rodando sem `LEITOR_WORKER_TOKEN` no ambiente -- configure lá, não aqui. |
| `[Worker] sem conexão com o servidor ... tentando de novo em Ns` | Rede fora do ar / `API_BASE_URL` errado / VPS caída. O Worker faz backoff exponencial sozinho (até 60s entre tentativas) e volta a funcionar assim que a conexão voltar -- não precisa reiniciar. |
| Um Job fica muito tempo em "aguardando" | Nenhum Worker está de pé, ou todos estão ocupados com outro Job. `GET /api/worker/status` (na VPS) mostra as contagens agregadas. |
| O Worker parece travado numa página | Normal em folhas grandes/complexas -- OCR real leva ~40s/página, e o carregamento do modelo do PaddleOCR na PRIMEIRA página de um processo novo adiciona mais alguns segundos. O heartbeat continua batendo em thread própria enquanto isso acontece (ver `worker/heartbeat.py`). |

### Verificado

`worker/testes/teste_worker_real.py` processa `entrada/pdf/teste.pdf` (as mesmas 5 folhas reais desde
a Fase 9) através do pacote `worker/` real, com PaddleOCR real, sobre um servidor HTTP real (socket
de verdade, não simulado) -- baseline **40 registros, 19 CONFIRMADO, 21 REVISAO, 0 ERRO**, idêntica
à medida em toda sub-fase anterior desta macrofase.

**Nota sobre o modo desktop/`.exe`**: eles continuam usando `LEITOR_MODO=local` (Sub-fase 26a,
`web/backend/produtor_ocr.py`) -- rodam o OCR no mesmo processo, sem nenhum Worker remoto envolvido.
`worker/` é um pacote independente, pensado para o PC Windows remoto do operador falando com uma VPS
via Tailscale; ver `saida/auditoria_fase26_ocr_worker.md` (Sub-fase 26c) para a justificativa completa
dessa separação.

## Colocando em produção: VPS + Worker Windows (Fase 26e)

Passo a passo para o par completo — API em modo `servidor` na VPS (Oracle Cloud, já publicada em
`https://eltonmarques.com/leitor` desde a Fase 25, ver "Deploy atrás de sub-path" abaixo) mais um
Worker real no PC Windows do operador. **Nenhum destes passos foi executado contra a VPS real nem
contra um PC físico a partir deste repositório** -- o que existe até aqui (26a/26b/26c) foi verificado
ponta a ponta com um servidor e um cliente HTTP reais, no mesmo processo/máquina (`worker/testes/
teste_worker_real.py`); a validação **entre duas máquinas distintas** exige acesso à VPS e ao PC de
verdade, que só o operador tem. Esta seção é o roteiro para ele executar essa validação, não um
relato de que ela já aconteceu.

### 1. Na VPS -- instalar e configurar

```bash
# clonar/atualizar o repositório, então:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-api.txt   # NUNCA requirements.txt inteiro -- sem OpenCV/PaddleOCR aqui
```

Criar `deploy/leitor-api.env` (a partir de `deploy/leitor-api.env.example`, ver os comentários lá
dentro para o que cada variável faz) com `LEITOR_MODO=servidor`, `LEITOR_WORKER_TOKEN` (um segredo
gerado agora, ≥16 caracteres -- ex. `openssl rand -hex 24`) e `LEITOR_ARMAZENAMENTO` apontando para
uma pasta **fora** do checkout do repositório (precisa sobreviver a um `git pull`/deploy novo):

```bash
cp deploy/leitor-api.env.example deploy/leitor-api.env
nano deploy/leitor-api.env
chmod 600 deploy/leitor-api.env
```

### 2. Na VPS -- manter o processo vivo (systemd)

Antes desta fase não havia registro, no repositório, de COMO o processo da VPS é mantido rodando
entre reinícios -- essa era uma pergunta explicitamente em aberto no início da Fase 26 (ver
`saida/auditoria_fase26_ocr_worker.md`). `deploy/leitor-api.service` é um **modelo** de unit do
systemd para isso -- reinicia sozinho em crash e sobrevive a um reboot da VPS. Ele parte do princípio
de que nada assim existia ainda; se a VPS já tiver algum mecanismo próprio (outro systemd unit, PM2,
supervisor, tmux manual), prefira integrar a esse mecanismo existente em vez de rodar os dois em
paralelo -- é o operador quem sabe qual é o caso, por isso o modelo não se autoinstala.

```bash
sudo cp deploy/leitor-api.service /etc/systemd/system/leitor-api.service
sudo nano /etc/systemd/system/leitor-api.service   # ajustar User/WorkingDirectory/caminhos
sudo systemctl daemon-reload
sudo systemctl enable --now leitor-api
sudo systemctl status leitor-api                   # deve mostrar "active (running)"
sudo journalctl -u leitor-api -f                   # acompanhar os logs ao vivo
```

Confirme que a Tailscale já está ativa na VPS (`tailscale status`) -- é o caminho que o Worker vai
usar para alcançá-la (ver "Ajuste pontual pós-Fase 24" em `saida/ajuste_acesso_tailscale.md`; as
rotas `/api/worker/*` nunca ficam expostas pelo Cloudflare Tunnel/domínio público, só sob `/leitor`
-- ver "Protocolo de Worker" acima).

### 3. No PC Windows -- Worker

Seguir a seção "Worker Windows (Fase 26c)" acima, com `API_BASE_URL` apontando para o **IP Tailscale
da VPS** (`tailscale ip -4` rodado NA VPS) e `OCR_WORKER_TOKEN` igual ao `LEITOR_WORKER_TOKEN` do
passo 1. Rodar `python -m worker` (ou `iniciar_worker.bat`) e conferir no log `[Worker] registrado`
sem erro de autenticação.

### 4. Validação ponta a ponta (fazer isto de verdade, uma vez, antes de considerar a fase fechada)

- [ ] Upload de um lote pelo navegador (`https://eltonmarques.com/leitor`), **sem** o Worker rodando
      ainda -- o lote deve ficar "Aguardando um computador de leitura..." (Fase 26d) indefinidamente,
      sem erro.
- [ ] Ligar o Worker -- o lote deve sair do estado de espera sozinho, sem recarregar a página nem
      disparar nada manualmente.
- [ ] Acompanhar `GET /api/worker/status` (`curl http://<ip-tailscale-vps>:8000/api/worker/status`)
      durante o processamento -- contagens batendo com a realidade.
- [ ] Resultado final aparece na tela de Resultado, planilha baixável, revisão manual funcionando.
- [ ] Desligar o Worker (`Ctrl+C`) NO MEIO de um lote -- a VPS e o frontend continuam de pé, o lote
      fica pendente (não trava, não vira erro).
- [ ] Religar o Worker -- o lote retoma sozinho, **sem refazer o OCR das páginas já lidas**
      (`etapa_atual` deve mostrar "Retomando o processamento").
- [ ] Reiniciar o processo da VPS (`sudo systemctl restart leitor-api`) com um lote em andamento --
      mesmo comportamento de retomada, agora do lado da VPS.

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
do navegador — sem precisar do `vite dev` rodando à parte.

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
existindo e funcionando lado a lado.

## Empacotamento em .exe portátil (Sub-fase 25b — fecha a Fase 25)

Gera uma pasta portátil (`--onedir`, ver justificativa medida em
`saida/avaliacao_fase25_exe.md`) com `LeitorDeMatriculas.exe` + tudo que ele precisa —
copia a pasta inteira pra qualquer Windows e roda, sem instalar Python/Node.

```powershell
# 1. Instalar as ferramentas de build (só quem for GERAR o .exe precisa disto --
#    nunca quem só vai RODAR o .exe já pronto):
pip install pyinstaller pyinstaller-hooks-contrib

# 2. Build de produção do frontend (mesmo passo do modo desktop acima):
cd web\frontend; npm run build; cd ..\..

# 3. Empacotar:
pyinstaller web\desktop_app.spec --distpath dist_exe --workpath build_exe --noconfirm

# 4. Copiar as planilhas de referência para dentro da pasta gerada (ficam FORA do
#    .exe de propósito -- editáveis sem reempacotar, ver web/backend/estado.py):
copy dados\*.xlsx dist_exe\LeitorDeMatriculas\dados\

# 5. Rodar:
dist_exe\LeitorDeMatriculas\LeitorDeMatriculas.exe
```

`dist_exe/`/`build_exe/` são gerados sob demanda (gitignored) — o `.spec` é a receita
versionada. Ver `saida/avaliacao_fase25_exe.md` para as decisões medidas (`--onedir` vs
`--onefile`, o que foi investigado para reduzir tamanho, os problemas reais resolvidos
no `.spec`) e o tamanho final do pacote.

## Deploy atrás de sub-path (ex.: VPS + Cloudflare Tunnel)

Ajuste pontual pós-Fase 25 — ver `saida/ajuste_subpath_leitor.md` para o relatório
completo (problema, causa raiz, testes). Resumo: quando este app é publicado num domínio
compartilhado, sob um prefixo de caminho (ex. `https://eltonmarques.com/leitor`, atrás de
um Cloudflare Tunnel que roteia só `/leitor/*` até este backend), o build de produção
precisa saber disso — senão os assets (`/assets/*.js`, `/favicon.svg`) são referenciados
sem o prefixo e o proxy não encontra pra onde encaminhar (404, tela branca).

```bash
# Na VPS (ou em qualquer build destinado a rodar sob um sub-path):
cd web/frontend
VITE_BASE_PATH=/leitor/ npm run build
cd ../..
python web/backend/main.py
```

**Sem a variável `VITE_BASE_PATH`, o build continua idêntico a antes** (`base: "/"`) — é
o que o modo desktop (seção acima) e o `.exe` (Sub-fase 25b) continuam usando, sem
nenhuma mudança de comportamento. O backend (`web/backend/main.py`) responde nos dois
formatos (com e sem o prefixo `/leitor`) independentemente de como o `dist/` local foi
construído, então testar localmente sem proxy nenhum (`http://127.0.0.1:8000/leitor`)
também funciona.

Ajuste o valor de `VITE_BASE_PATH` (e a regra de ingress do proxy correspondente) se o
sub-path publicado for outro — não há nada fixo em `/leitor` além do valor passado nesse
comando.

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
