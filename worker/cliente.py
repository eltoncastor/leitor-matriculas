"""
worker/cliente.py

Fase 26c. Cliente HTTP do protocolo `/api/worker/*` (ver `web/backend/
rotas/worker.py` e `saida/auditoria_fase26_ocr_worker.md`, Sub-fase 26b)
-- usa só a biblioteca padrão (`urllib.request`), sem `requests`: o
Worker fala com UM servidor, um punhado de métodos, e o volume medido na
auditoria (~15-20 KB/s sustentado) não justifica uma dependência nova.

Toda chamada carrega `Authorization: Bearer <token>` e `X-Worker-Id:
<worker_id>` -- o token nunca é logado (ver `worker/__main__.py`, que só
loga o `worker_id`).
"""
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_LOG = logging.getLogger("worker.cliente")


class ErroCliente(Exception):
    """Base de todos os erros deste módulo."""


class ErroAutenticacao(ErroCliente):
    """401 (token inválido) ou 503 (servidor sem token configurado) --
    problema de CONFIGURAÇÃO, não vale ficar tentando de novo sozinho."""


class ErroConflito(ErroCliente):
    """409 -- perda de corrida no claim, ou perda de posse (lease
    expirado/tentativa obsoleta). Esperado em operação normal; quem chama
    decide o que fazer (ex.: voltar para `GET /jobs/next`)."""


class ErroTemporario(ErroCliente):
    """Rede fora do ar, timeout, ou erro 5xx do servidor -- vale tentar de
    novo com backoff (ver `worker/execucao.py::rodar`)."""


@dataclass
class JobReivindicado:
    lote_id: str
    tentativa: int
    tipo: str
    total_paginas: Optional[int]
    nomes_arquivos: List[str]
    paginas_pendentes: List[int]


def _job_de_json(dados: Dict[str, Any]) -> JobReivindicado:
    return JobReivindicado(
        lote_id=dados["lote_id"],
        tentativa=dados["tentativa"],
        tipo=dados["tipo"],
        total_paginas=dados.get("total_paginas"),
        nomes_arquivos=list(dados.get("nomes_arquivos") or []),
        paginas_pendentes=list(dados.get("paginas_pendentes") or []),
    )


def _detalhe_do_corpo(exc: urllib.error.HTTPError) -> str:
    try:
        corpo = json.loads(exc.read().decode("utf-8"))
        return corpo.get("detail", "") if isinstance(corpo, dict) else str(corpo)
    except Exception:
        return ""


class ClienteWorker:
    def __init__(self, base_url: str, worker_id: str, token: str, timeout_s: float = 60.0):
        self._base = base_url.rstrip("/") + "/api/worker"
        self._worker_id = worker_id
        self._token = token
        self._timeout_s = timeout_s

    def _cabecalhos(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        cabecalhos = {"Authorization": f"Bearer {self._token}", "X-Worker-Id": self._worker_id}
        if extra:
            cabecalhos.update(extra)
        return cabecalhos

    def _pedir(self, metodo: str, caminho: str, corpo: Optional[bytes] = None,
              headers_extra: Optional[Dict[str, str]] = None,
              params: Optional[Dict[str, Any]] = None) -> bytes:
        url = f"{self._base}{caminho}"
        if params:
            # Só inteiros passam por `params` neste protocolo (`tentativa`,
            # `indice`) -- sem caractere que precise de escape de URL.
            url += "?" + "&".join(f"{chave}={valor}" for chave, valor in params.items())
        requisicao = urllib.request.Request(url, data=corpo, method=metodo, headers=self._cabecalhos(headers_extra))
        try:
            with urllib.request.urlopen(requisicao, timeout=self._timeout_s) as resposta:
                return resposta.read()
        except urllib.error.HTTPError as exc:
            detalhe = _detalhe_do_corpo(exc)
            if exc.code in (401, 503):
                raise ErroAutenticacao(f"{exc.code}: {detalhe}") from exc
            if exc.code == 409:
                raise ErroConflito(detalhe or "409") from exc
            if exc.code == 404:
                raise ErroCliente(f"404: {detalhe}") from exc
            raise ErroTemporario(f"{exc.code}: {detalhe}") from exc
        except urllib.error.URLError as exc:
            raise ErroTemporario(f"Falha de conexão com {self._base}: {exc.reason}") from exc

    def _pedir_json(self, metodo: str, caminho: str, corpo_dict: Optional[Dict[str, Any]] = None,
                    params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        corpo = json.dumps(corpo_dict).encode("utf-8") if corpo_dict is not None else None
        headers = {"Content-Type": "application/json"} if corpo is not None else None
        bruto = self._pedir(metodo, caminho, corpo=corpo, headers_extra=headers, params=params)
        return json.loads(bruto.decode("utf-8")) if bruto else {}

    # -- endpoints ---------------------------------------------------------

    def registrar(self) -> None:
        self._pedir_json("POST", "/register")

    def heartbeat(self, lote_id: Optional[str], tentativa: Optional[int]) -> bool:
        """Devolve `False` quando o lease já expirou e o Job foi
        reenfileirado -- quem chama (`worker/heartbeat.py`) só loga um
        aviso; é `worker/execucao.py` (o dono do laço de OCR) quem decide
        parar de fato, ao receber `ErroConflito`/`obsoleto` na próxima
        entrega de página."""
        corpo = {"tentativa": tentativa if lote_id else 0, "lote_id": lote_id}
        resposta = self._pedir_json("POST", "/heartbeat", corpo)
        return bool(resposta.get("ainda_dono", True))

    def proximo_job(self) -> Optional[str]:
        resposta = self._pedir_json("GET", "/jobs/next")
        return resposta.get("lote_id")

    def reivindicar(self, lote_id: str) -> JobReivindicado:
        resposta = self._pedir_json("POST", f"/jobs/{lote_id}/claim")
        return _job_de_json(resposta)

    def baixar_arquivo(self, lote_id: str, indice: int, tentativa: int, destino: str) -> None:
        conteudo = self._pedir("GET", f"/jobs/{lote_id}/arquivos/{indice}", params={"tentativa": tentativa})
        with open(destino, "wb") as saida:
            saida.write(conteudo)

    def entregar_pagina(self, lote_id: str, numero: int, tentativa: int, *, erro: Optional[str],
                        fase_erro: Optional[str], registros: List[Dict[str, Any]]) -> str:
        """Devolve `"aceito" | "duplicado" | "obsoleto"` -- os três são
        sucesso HTTP (ver `web/backend/rotas/worker.py::entregar_pagina`);
        só `"obsoleto"` significa "pare de trabalhar neste Job"."""
        corpo = {"tentativa": tentativa, "erro": erro, "fase_erro": fase_erro, "registros": registros}
        resposta = self._pedir_json("POST", f"/jobs/{lote_id}/paginas/{numero}", corpo)
        return resposta.get("resultado", "aceito")

    def entregar_miniatura(self, lote_id: str, numero: int, tentativa: int, conteudo: bytes) -> None:
        self._pedir("PUT", f"/jobs/{lote_id}/paginas/{numero}/miniatura", corpo=conteudo,
                    headers_extra={"Content-Type": "image/jpeg"}, params={"tentativa": tentativa})

    def progresso(self, lote_id: str, tentativa: int, *, etapa_atual: Optional[str] = None,
                  total_paginas: Optional[int] = None) -> None:
        corpo = {"tentativa": tentativa, "etapa_atual": etapa_atual, "total_paginas": total_paginas}
        self._pedir_json("POST", f"/jobs/{lote_id}/progresso", corpo)

    def concluir(self, lote_id: str, tentativa: int) -> None:
        self._pedir_json("POST", f"/jobs/{lote_id}/concluir", {"tentativa": tentativa})

    def erro_de_documento(self, lote_id: str, tentativa: int, mensagem: str) -> None:
        self._pedir_json("POST", f"/jobs/{lote_id}/erro", {"tentativa": tentativa, "mensagem": mensagem})
