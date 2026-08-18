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

ESCOPO (ver CLAUDE.md, Fase 24): sem autenticação, sem multiusuário real
(`lote_id` isola o ESTADO, não isola por USUÁRIO -- ver `estado.py`).
Continua sendo assim -- este ajuste NÃO adiciona autenticação nem começa o
suporte a múltiplos usuários simultâneos.

AJUSTE PONTUAL PÓS-FASE 24 (acesso remoto via Tailscale, ver CLAUDE.md e
`saida/ajuste_acesso_tailscale.md`): o `uvicorn.run` abaixo passou a
escutar em `host="0.0.0.0"` (todas as interfaces de rede da máquina) em
vez de só `127.0.0.1`. Isto substitui a decisão anterior ("a API NUNCA
deve ser exposta além de localhost"), registrada aqui com todas as letras
porque é uma mudança de RISCO, não cosmética:

  - `0.0.0.0` faz o processo aceitar conexões vindas de QUALQUER interface
    de rede da máquina -- inclusive a rede Wi-Fi/Ethernet local onde ela
    estiver conectada, não só a interface do Tailscale. Não existe em
    `uvicorn`/sockets uma forma de escutar "só na interface do Tailscale"
    sem amarrar o processo ao IP Tailscale específico (que muda entre
    reinicializações do Tailscale) -- por isso a escolha foi `0.0.0.0` mais
    as duas proteções abaixo, não um IP fixo.
  - O que continua protegendo esta API de virar um servidor público são
    DUAS coisas fora deste código: (1) nenhum port-forwarding é feito no
    roteador da rede onde a máquina estiver -- sem isso, a internet aberta
    não alcança a porta 8000 desta máquina, só quem já está na mesma rede
    local ou na mesma tailnet; (2) o acesso remoto de verdade (de outro
    dispositivo, ex. do trabalho) é feito através do Tailscale -- uma VPN
    mesh privada entre só os dispositivos da conta do próprio usuário, não
    a internet pública.
  - Continua sem autenticação de aplicação (usuário único, decisão
    inalterada) -- a superfície de proteção é inteiramente de REDE
    (Tailscale + ausência de port-forwarding), não de login.

Rodar (a partir da raiz do projeto):
    python web/backend/main.py
ou, com autorreload durante o desenvolvimento:
    venv\\Scripts\\python.exe -m uvicorn web.backend.main:app --reload --host 0.0.0.0 --port 8000

A documentação interativa (Swagger) fica em http://127.0.0.1:8000/docs
(uso local) ou http://<IP-tailscale-desta-máquina>:8000/docs (acesso remoto).

SUB-FASE 25a (retomada da Fase 25 -- empacotamento web em .exe portátil,
ver CLAUDE.md e `saida/avaliacao_fase25_exe.md`): este processo passou a
também SERVIR o build de produção do frontend (`npm run build` em
`web/frontend/dist/`), além da API -- é o que permite um processo Python
SÓ (sem `vite dev` separado), pré-requisito para a janela nativa
(`web/desktop_app.py`) e para o empacotamento em `.exe` da 25b. O modo de
desenvolvimento com dois processos (`vite dev` + este arquivo) CONTINUA
existindo e funcionando -- ver `web/README.md` -- esta sub-fase só
ACRESCENTA o modo de processo único, não remove o modo dev. Se
`web/frontend/dist/index.html` não existir (build nunca rodado), este
arquivo funciona exatamente como antes: só API, sem servir nada estático
-- ver o `if` logo antes da rota catch-all, mais abaixo.

CORS -- decisão revisada e mantida como estava, com justificativa nova: em
processo único (frontend e API na MESMA origem/porta), CORS se torna
inerte para esse modo -- não há requisição cross-origin nenhuma para
filtrar. Mas o modo de DESENVOLVIMENTO (`vite dev` em outra porta) e o
acesso remoto via Tailscale a esse modo dev CONTINUAM existindo como fluxo
suportado (ver `saida/ajuste_acesso_tailscale.md`), e esses SIM se
beneficiam do CORS já configurado -- então o middleware abaixo não foi
removido nem simplificado. Mantê-lo não tem custo (é inerte, não
intrusivo, no modo processo único) e continua necessário no modo que
ainda existe.
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

import logging  # noqa: E402
import pathlib  # noqa: E402

from fastapi import FastAPI, HTTPException  # noqa: E402  (precisa vir depois do sys.path)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from web.backend import config, estado  # noqa: E402
from web.backend.rotas import lotes, worker  # noqa: E402

app = FastAPI(
    title="Leitor de Matrículas -- API Web (MVP)",
    description=(
        "Backend FastAPI que reaproveita o pacote leitor_matriculas "
        "(OCR/parser/validação/exportação) já usado pela versão Tkinter. "
        "Fase 24a -- ver CLAUDE.md."
    ),
    version="24a",
)

# CORS liberado para origens locais de desenvolvimento (o frontend, Fase
# 24b/Vite, roda numa porta diferente da API) MAIS a faixa de IP que o
# Tailscale usa (ajuste pós-Fase 24, ver docstring do módulo acima e
# `saida/ajuste_acesso_tailscale.md`). CORS decide quais ORIGENS um
# navegador aceita chamar -- é independente de em quais interfaces o
# processo escuta (isso é o `host=` do uvicorn.run abaixo).
#
# `100\.\d{1,3}\.\d{1,3}\.\d{1,3}` cobre o CGNAT `100.64.0.0/10` que o
# Tailscale atribui a cada dispositivo da tailnet (todo IP Tailscale
# começa com "100.") -- é uma faixa PRIVADA roteável só dentro da rede
# Tailscale do próprio usuário, nunca um IP público de internet aberta.
# Deliberadamente NÃO usa `allow_origins=["*"]` nem qualquer regex mais
# permissivo que isso -- só origens locais e só a faixa Tailscale.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|100\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def _recuperar_lotes_persistidos():
    """
    Fase 26a. Duas coisas que o backend nunca fez ao subir:

      * RETENÇÃO -- até a Fase 25 os uploads iam para `tempfile.mkdtemp()`
        e quem os recolhia era o sistema operacional. Numa pasta durável
        essa rede de segurança não existe mais, então a limpeza virou
        responsabilidade explícita;
      * RECUPERAÇÃO -- um lote que estava sendo processado quando o
        processo morreu ficava com o `status` congelado em "processando"
        para sempre, sem nenhuma forma de retomar. Agora ele volta para a
        fila, e as páginas cujo OCR já estava gravado NÃO são refeitas.

    Nunca levanta: uma falha aqui não pode impedir o servidor de subir.
    """
    resumo = estado.recuperar_lotes_do_disco()
    logging.info(
        "Armazenamento: %s lote(s) recuperado(s), %s reenfileirado(s), %s removido(s) por retenção. Modo: %s",
        resumo.get("recuperados"), resumo.get("reenfileirados"), resumo.get("removidos"), config.modo(),
    )
    # Fase 26b: a thread que devolve à fila todo Job com lease vencido ou
    # sem progresso (D6) -- precisa estar de pé mesmo em modo `local`
    # (onde nunca vai encontrar nada para reenfileirar, mas custa nada
    # deixá-la rodando; simplifica não ter dois caminhos de inicialização).
    estado.iniciar_vigilante_de_leases()


app.include_router(lotes.router)
# Sub-fase 25a: MESMO router, montado TAMBÉM sob "/api" -- é o prefixo que
# `src/lib/api.js` (`BASE = "/api"`) sempre usou. Em modo dev, quem faz
# esse prefixo virar as rotas nuas (`/lotes/...`) é o proxy do Vite
# (`vite.config.js`, `rewrite: path.replace(/^\/api/, '')`); em modo
# processo único NÃO HÁ Vite nenhum reescrevendo nada -- o próprio
# navegador chama `/api/lotes` direto contra este processo. Duplicar o
# `include_router` (mesmas funções, mesma lógica, zero reimplementação) é
# mais simples e mais seguro do que ensinar o backend a fazer sua própria
# reescrita de path, e mantém as DUAS formas funcionando: `/lotes/...`
# (o que os testes existentes -- `teste_api_mock.py`/`teste_api_lote_
# real.py` -- e o uso direto da API sempre chamaram) e `/api/lotes/...`
# (o que o frontend buildado chama, nos dois modos).
app.include_router(lotes.router, prefix="/api")
# Ajuste pontual pós-Fase 25 (deploy atrás de sub-path, ver CLAUDE.md e
# saida/ajuste_subpath_leitor.md): na VPS, atrás do Cloudflare Tunnel, o
# app fica publicado em "https://eltonmarques.com/leitor" -- o mesmo
# MESMO router, uma terceira vez, sob "/leitor/api" (a base que o
# frontend buildado com `VITE_BASE_PATH=/leitor/` chama, ver
# src/lib/api.js). Não se sabe, e não é controlado por este repositório,
# se o encaminhamento do túnel remove o prefixo "/leitor" antes de chegar
# aqui -- por isso o backend responde nos dois formatos (com e sem o
# prefixo), igual já fazia para "/api" desde a Sub-fase 25a.
app.include_router(lotes.router, prefix="/leitor/api")

# Fase 26b: as rotas de Worker (`/api/worker/*`) são montadas SÓ sob
# "/api" -- deliberadamente NUNCA sob "/leitor/api", ao contrário de
# `lotes.router` logo acima. O Cloudflare Tunnel da VPS só roteia
# "/leitor/*" até este backend (ver o ajuste pós-Fase 25 no CLAUDE.md) --
# não montar aqui é o que torna esta superfície INALCANÇÁVEL da internet
# pública por construção, sem depender de nenhuma regra de firewall. O
# acesso real é pela Tailscale (`http://<ip-100.x>:8000/api/worker/...`);
# o token (`auth_worker.py`) é a segunda camada, nunca a única. Uma
# requisição para "/leitor/api/worker/..." cai no catch-all da SPA
# abaixo e recebe 404 JSON (o segmento "api" já é reservado ali), nunca
# uma resposta de Worker.
app.include_router(worker.router, prefix="/api")


@app.get("/saude")
@app.get("/api/saude")
@app.get("/leitor/api/saude")
def saude():
    """Checagem simples de que o processo está de pé -- não toca em
    OCR/bases, só confirma que a API responde. Espelhada em /api/saude
    pelo mesmo motivo do router acima (Sub-fase 25a) e em
    /leitor/api/saude pelo mesmo motivo do ajuste de sub-path pós-Fase 25."""
    return {"status": "ok"}


# ======================================================================
# Sub-fase 25a -- serve o build de produção do frontend (SPA React), só
# quando ele existe (`npm run build` já rodado). Registrado por ÚLTIMO,
# de propósito: o Starlette resolve rotas na ORDEM DE REGISTRO, e toda
# rota mais específica definida ACIMA (`/lotes/...`, `/api/...`,
# `/saude`, mais `/docs`/`/redoc`/`/openapi.json` que o FastAPI já
# registrou dentro do `FastAPI(...)` no topo do arquivo) já "ganha" a
# correspondência antes do catch-all abaixo sequer ser avaliado -- é
# exatamente a armadilha que se pretende evitar: uma rota catch-all de
# SPA registrada CEDO demais roubaria essas rotas de API.
# ======================================================================
_DIST_DIR = pathlib.Path(_RAIZ_PROJETO) / "web" / "frontend" / "dist"
_DIST_INDEX = _DIST_DIR / "index.html"

if _DIST_INDEX.is_file():
    # Só os arquivos hasheados (JS/CSS/fontes) -- os poucos arquivos soltos
    # na raiz do build (favicon.svg, icons.svg) são tratados pelo
    # catch-all abaixo, junto com o próprio index.html.
    app.mount("/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="frontend-assets")
    # Ajuste pontual pós-Fase 25 (sub-path /leitor, ver CLAUDE.md e
    # saida/ajuste_subpath_leitor.md): MESMO diretório, montado também sob
    # "/leitor/assets" -- é o caminho que o build feito com
    # `VITE_BASE_PATH=/leitor/` referencia dentro do próprio index.html
    # (`<script src="/leitor/assets/index-*.js">`). Um build padrão (sem a
    # variável) nunca gera link para este caminho, então este mount fica
    # simplesmente sem uso nesse caso -- inofensivo.
    app.mount(
        "/leitor/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="frontend-assets-leitor"
    )

    # Nomes que já são rotas de API reais (ou prefixos delas) -- usados
    # abaixo como DEFESA EM PROFUNDIDADE, não como o mecanismo principal
    # de roteamento (que já é garantido pela ordem de registro acima).
    # Sem isto, um subcaminho de API mal formado que não bate o padrão de
    # NENHUM endpoint real (ex. "/lotes/abc/rota-que-nao-existe") cairia
    # neste catch-all e devolveria a página HTML da SPA em vez de um 404
    # -- escondendo o erro real (rota de API inexistente) atrás de uma
    # tela do React tentando (e falhando silenciosamente) interpretar
    # HTML como se fosse a resposta JSON esperada.
    _PRIMEIRO_SEGMENTO_RESERVADO = {"api", "lotes", "saude", "docs", "redoc", "openapi.json"}

    def _sem_prefixo_leitor(caminho: str) -> str:
        """Ajuste pontual pós-Fase 25 (sub-path /leitor): remove um único
        segmento "leitor" inicial, se houver, antes do catch-all decidir o
        que fazer. Não se sabe se o Cloudflare Tunnel da VPS já remove esse
        prefixo antes de encaminhar para este processo -- esta função faz
        "/leitor", "/leitor/", "/leitor/favicon.svg", "/leitor/lote/<id>"
        e um "/leitor/api/<inexistente>" malformado se comportarem
        EXATAMENTE como os equivalentes sem o prefixo, nos dois cenários."""
        partes = caminho.split("/", 1)
        if partes[0] == "leitor":
            return partes[1] if len(partes) > 1 else ""
        return caminho

    @app.get("/{caminho:path}")
    def servir_frontend(caminho: str):
        """
        Catch-all da SPA: qualquer caminho que nenhuma rota de API
        reconheceu. Dois casos: (1) um arquivo real do build que não está
        em "/assets" (hoje só `favicon.svg`/`icons.svg`, na raiz de
        `dist/`) -- devolve o arquivo; (2) qualquer outra coisa -- é uma
        rota do REACT ROUTER (`/lote/:id`, `/lote/:id/revisao`), que só o
        JAVASCRIPT carregado sabe resolver, então devolve sempre o MESMO
        `index.html` (o padrão universal de "SPA fallback"). Um prefixo
        "/leitor" inicial (ver `_sem_prefixo_leitor`, ajuste pós-Fase 25)
        é removido antes desta decisão, então tudo abaixo vale igualmente
        com ou sem esse prefixo.
        """
        caminho_efetivo = _sem_prefixo_leitor(caminho)
        primeiro_segmento = caminho_efetivo.split("/", 1)[0]
        if primeiro_segmento in _PRIMEIRO_SEGMENTO_RESERVADO:
            raise HTTPException(status_code=404, detail=f"Rota de API não encontrada: /{caminho}")

        # Resolve dentro de `_DIST_DIR` e confere que o resultado continua
        # DENTRO dela antes de servir -- impede um caminho tipo
        # "../../../Windows/win.ini" de escapar da pasta do build (o
        # processo passou a escutar em 0.0.0.0 desde o ajuste do
        # Tailscale, então esta rota é alcançável pela rede, não só de
        # localhost).
        candidato = (_DIST_DIR / caminho_efetivo).resolve()
        if caminho_efetivo and candidato.is_file() and candidato.is_relative_to(_DIST_DIR.resolve()):
            return FileResponse(candidato)
        return FileResponse(_DIST_INDEX)


if __name__ == "__main__":
    import uvicorn

    # host="0.0.0.0" (ajuste pós-Fase 24, acesso remoto via Tailscale) --
    # ver a explicação completa de risco/mitigação na docstring do módulo.
    uvicorn.run(app, host="0.0.0.0", port=8000)
