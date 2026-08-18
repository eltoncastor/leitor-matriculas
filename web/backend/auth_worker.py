"""
web/backend/auth_worker.py

Fase 26b. Autenticação das rotas de Worker -- máquina-a-máquina, não login
de usuário (o projeto continua deliberadamente sem autenticação
multiusuário; ver CLAUDE.md). O token nunca aparece no código, no Git, em
log ou em resposta HTTP: é lido de uma variável de ambiente,
`LEITOR_WORKER_TOKEN`, configurada localmente em cada instalação.

DUAS CAMADAS DE PROTEÇÃO, NÃO UMA SÓ
-------------------------------------
As rotas de Worker (`web/backend/rotas/worker.py`) são montadas em
`web/backend/main.py` **fora** do prefixo `/leitor` -- e o Cloudflare
Tunnel da VPS só roteia `/leitor/*` até este backend (ver a seção "Ajuste
pontual pós-Fase 25" do CLAUDE.md). Isso já torna a superfície de Worker
INALCANÇÁVEL da internet pública, por construção -- o acesso real é pela
Tailscale. O token é a segunda camada, defesa em profundidade, nunca a
única.

FAIL-CLOSED, NUNCA FAIL-OPEN
-----------------------------
Se `LEITOR_WORKER_TOKEN` não estiver configurado, TODA requisição de
Worker é recusada (503) -- nunca aceita. Um servidor sem token configurado
não é "um servidor aberto para qualquer um", é um servidor que ainda não
decidiu quem pode processar os lotes dele.

O `worker_id` que cada requisição declara (cabeçalho `X-Worker-Id`) é
metadado descritivo -- aparece em log e nos campos `worker_id` do Job, útil
para saber QUAL máquina está processando o quê -- mas NUNCA decide
autorização sozinho: quem decide é sempre o token. Isto é o que a missão
pediu com "worker_id nunca confiado cegamente".
"""
import hmac
import os
from typing import Optional

from fastapi import Header, HTTPException

VARIAVEL_TOKEN = "LEITOR_WORKER_TOKEN"

# Tamanho mínimo exigido do token quando configurado -- não impede um
# operador de escolher algo fraco, mas pega o erro mais comum (deixar uma
# string de exemplo tipo "mudeme" ou vazia por engano).
_TAMANHO_MINIMO_TOKEN = 16


def token_configurado() -> Optional[str]:
    valor = os.environ.get(VARIAVEL_TOKEN)
    return valor if valor and len(valor) >= _TAMANHO_MINIMO_TOKEN else None


def _extrair_bearer(cabecalho_autorizacao: Optional[str]) -> Optional[str]:
    if not cabecalho_autorizacao:
        return None
    partes = cabecalho_autorizacao.split(" ", 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return None
    return partes[1].strip() or None


def verificar_worker(
    authorization: Optional[str] = Header(default=None),
    x_worker_id: Optional[str] = Header(default=None),
) -> str:
    """
    Dependência do FastAPI: valida `Authorization: Bearer <token>` contra
    `LEITOR_WORKER_TOKEN` com `hmac.compare_digest` (tempo constante --
    comparar token com `==` vazaria, por tempo de resposta, quantos
    caracteres do início batem). Devolve o `worker_id` declarado (só para
    log/observabilidade -- ver docstring do módulo).
    """
    token_servidor = token_configurado()
    if token_servidor is None:
        raise HTTPException(
            status_code=503,
            detail="Este servidor não tem um token de Worker configurado (LEITOR_WORKER_TOKEN)",
        )

    token_recebido = _extrair_bearer(authorization)
    if token_recebido is None:
        raise HTTPException(status_code=401, detail="Cabeçalho Authorization ausente ou mal formado")

    if not hmac.compare_digest(token_recebido, token_servidor):
        raise HTTPException(status_code=401, detail="Token de Worker inválido")

    worker_id = (x_worker_id or "").strip()
    if not worker_id:
        raise HTTPException(status_code=401, detail="Cabeçalho X-Worker-Id ausente")
    if len(worker_id) > 128:
        raise HTTPException(status_code=401, detail="X-Worker-Id inválido")

    return worker_id
