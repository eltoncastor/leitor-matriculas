"""
worker/config.py

Fase 26c. Configuração do Worker via variáveis de ambiente e,
opcionalmente, um arquivo `.env` na raiz do projeto (nunca versionado --
ver `.env.example`). Sem dependência nova: o "parser" de `.env` é um laço
de poucas linhas, não `python-dotenv` -- o formato que este projeto
precisa (`CHAVE=valor`, uma por linha, `#` de comentário) não justifica
mais que isso.
"""
import os
from dataclasses import dataclass
from typing import Optional

_NOME_ARQUIVO_ENV = ".env"


def _carregar_dotenv(caminho: str) -> None:
    """
    Só define uma variável se ela AINDA NÃO estiver no ambiente -- uma
    variável de ambiente real (`set OCR_WORKER_TOKEN=...` antes de rodar)
    sempre vence o que está no `.env`. Sem suporte a aspas/interpolação:
    o `.env` deste projeto só guarda valores simples (URL, token,
    números). Arquivo ausente não é erro -- configurar só por variável de
    ambiente continua funcionando.
    """
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            linhas = arquivo.readlines()
    except OSError:
        return
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def carregar_env(raiz_projeto: Optional[str] = None) -> None:
    """
    Chamado uma vez, no início do processo (`worker/__main__.py`). Procura
    `.env` na raiz do projeto (dois níveis acima deste arquivo por
    padrão) -- mesma pasta onde `dados/`/`entrada/` já vivem.
    """
    if raiz_projeto is None:
        raiz_projeto = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    _carregar_dotenv(os.path.join(raiz_projeto, _NOME_ARQUIVO_ENV))


class ConfiguracaoInvalida(Exception):
    """Levantada com uma mensagem clara quando falta algo essencial --
    falhar rápido e alto (antes de tentar a primeira requisição) é melhor
    que o Worker subir e só descobrir "token inválido" silenciosamente."""


@dataclass
class ConfiguracaoWorker:
    api_base_url: str
    worker_id: str
    worker_token: str
    intervalo_polling_s: float
    intervalo_heartbeat_s: float


def _numero_positivo(nome: str, padrao: float) -> float:
    bruto = os.environ.get(nome)
    if not bruto:
        return padrao
    try:
        valor = float(bruto)
    except ValueError:
        raise ConfiguracaoInvalida(f"{nome}={bruto!r} não é um número válido")
    if valor <= 0:
        raise ConfiguracaoInvalida(f"{nome} precisa ser maior que zero")
    return valor


def ler_configuracao() -> ConfiguracaoWorker:
    base_url = (os.environ.get("API_BASE_URL") or "").rstrip("/")
    worker_id = os.environ.get("OCR_WORKER_ID") or ""
    worker_token = os.environ.get("OCR_WORKER_TOKEN") or ""

    faltando = [nome for nome, valor in (
        ("API_BASE_URL", base_url), ("OCR_WORKER_ID", worker_id), ("OCR_WORKER_TOKEN", worker_token),
    ) if not valor]
    if faltando:
        raise ConfiguracaoInvalida(
            "Configuração incompleta -- faltam: " + ", ".join(faltando) + ". Defina como variável de "
            "ambiente ou num arquivo .env na raiz do projeto (veja .env.example)."
        )

    return ConfiguracaoWorker(
        api_base_url=base_url,
        worker_id=worker_id,
        worker_token=worker_token,
        intervalo_polling_s=_numero_positivo("POLL_INTERVAL", 5.0),
        # Bem menor que o LEASE_S=120s do servidor (web/backend/estado.py)
        # -- várias batidas de folga antes do lease poder vencer.
        intervalo_heartbeat_s=_numero_positivo("HEARTBEAT_INTERVAL", 20.0),
    )
