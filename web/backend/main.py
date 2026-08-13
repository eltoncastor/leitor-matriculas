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

app.include_router(lotes.router)


@app.get("/saude")
def saude():
    """Checagem simples de que o processo está de pé -- não toca em
    OCR/bases, só confirma que a API responde."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    # host="0.0.0.0" (ajuste pós-Fase 24, acesso remoto via Tailscale) --
    # ver a explicação completa de risco/mitigação na docstring do módulo.
    uvicorn.run(app, host="0.0.0.0", port=8000)
