"""
web/backend/esquemas.py

Modelos Pydantic da API (request/response). Os REGISTROS em si (o que sai
de `pipeline.montar_registro_exportacao`/entra e sai de `validacao.
confirmacao.confirmar_revisao_manual`) trafegam como `dict` puro
(`Dict[str, Any]`), sem um modelo Pydantic próprio -- são exatamente as
mesmas chaves que `ui/app.py` já usa para montar a tabela/exportação
(`data`, `hora`, `matricula`, ..., `evidencias`, `ocr_nao_associados`), e
criar um segundo esquema espelhando essas chaves só arriscaria os dois
divergirem. Só o que é de fato "forma da requisição/resposta HTTP" ganha
modelo aqui.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LoteCriado(BaseModel):
    lote_id: str
    tipo: str
    total_arquivos: int


class StatusLote(BaseModel):
    lote_id: str
    tipo: str
    status: str
    etapa_atual: str
    pagina_atual: int
    total_paginas: Optional[int]
    paginas_processadas: int
    paginas_com_erro: int
    total_registros: int
    erro_fatal: Optional[str]


class ConfirmacaoRequest(BaseModel):
    """
    Os cinco campos que a folha traz e que a revisão manual pode editar --
    mesmos nomes/semântica de `revisao_vars` no Tkinter (Fase 10). Uma
    string vazia (o padrão) significa "o operador não preencheu esse
    campo", nunca "apagar" -- mesma convenção de `confirmar_revisao_
    manual`.
    """
    data: str = ""
    hora: str = ""
    matricula: str = ""
    gestor: str = ""
    motivo: str = ""


class ConfirmacaoResponse(BaseModel):
    registro: Dict[str, Any]
    status_anterior: str
    confirmou_agora: bool
    observacao_classificacao: str


class ExplicacaoResposta(BaseModel):
    """
    Fase 24c: forma HTTP de `validacao.explicacao_revisao.explicar()` +
    `.sinais_de_contexto()` (Fase 18) -- exposição pura, sem decisão
    nenhuma nova. `explicacao`/`sinais_contexto` trafegam como `dict`
    puro (mesma razão do `registro` em `ConfirmacaoResponse`): são
    exatamente os campos que `ExplicacaoRevisao`/`Evidencia` já produzem
    (`campos_bloqueantes`/`titulo`/`detalhes`/`por_campo` e
    `campo`/`tipo`/`origem`/`resultado`/`motivo`/`valor_observado`/
    `valor_relacionado`), sem reformulação.
    """
    explicacao: Dict[str, Any]
    sinais_contexto: List[Dict[str, Any]]


class ErroResposta(BaseModel):
    detalhe: str


# ---------------------------------------------------------------------------
# Fase 26b -- protocolo Worker <-> VPS. `worker_id` viaja no cabeçalho
# `X-Worker-Id` (ver `auth_worker.py`), nunca no corpo -- não há por que
# repeti-lo em cada modelo.
# ---------------------------------------------------------------------------

class ProximoJobResposta(BaseModel):
    """`GET /api/worker/jobs/next`. `lote_id=None` quando não há Job
    disponível -- resposta normal (200), não erro; o Worker deve fazer
    polling de novo depois de um intervalo, nunca tratar isso como falha."""
    lote_id: Optional[str] = None


class JobReivindicado(BaseModel):
    """`POST /api/worker/jobs/{id}/claim`. `tentativa` é a ficha de cerca
    desta reivindicação -- o Worker precisa devolvê-la em toda chamada
    seguinte sobre este Job (heartbeat, páginas, progresso, conclusão,
    erro); um valor errado é sempre recusado com 409."""
    lote_id: str
    tentativa: int
    tipo: str
    total_paginas: Optional[int]
    # Nomes dos arquivos de entrada, na ordem em que `GET .../arquivos/
    # {indice}` os serve (índice 0-based) -- o Worker nunca lê o caminho
    # local do disco da VPS, só o nome, por transparência de log.
    nomes_arquivos: List[str]
    # Só as páginas cujo OCR AINDA NÃO está gravado (retomada barata --
    # ver `web/backend/armazenamento.py`). Vazio quando `total_paginas`
    # ainda não é conhecido (o Worker calcula lendo o PDF que baixou).
    paginas_pendentes: List[int]


class HeartbeatRequest(BaseModel):
    tentativa: int
    lote_id: Optional[str] = None


class HeartbeatResposta(BaseModel):
    """`ainda_dono=False` quando o lease já expirou e o Job foi
    reenfileirado -- o Worker deve parar de trabalhar nele imediatamente,
    mesmo que ainda tenha páginas para entregar."""
    ainda_dono: bool


class ResultadoPaginaRequest(BaseModel):
    tentativa: int
    erro: Optional[str] = None
    # "renderizacao" | "leitura" | "pipeline" | None -- ver `estado.
    # _mensagem_erro_pagina`, que usa isto para escolher a frase.
    fase_erro: Optional[str] = None
    # `Registro.como_dicionario()` por registro da página -- vazio quando
    # `erro` está preenchido.
    registros: List[Dict[str, Any]] = Field(default_factory=list)


class ResultadoPaginaResposta(BaseModel):
    resultado: str  # "aceito" | "duplicado" | "obsoleto"


class ProgressoRequest(BaseModel):
    tentativa: int
    etapa_atual: Optional[str] = None
    # Reforço redundante, quase nunca precisa ser enviado: a VPS já
    # calcula sozinha, ANTES de qualquer Worker existir (ver `estado.
    # _descobrir_total_paginas`, que roda contra a cópia do arquivo que
    # ela própria recebeu no upload).
    total_paginas: Optional[int] = None


class ConcluirRequest(BaseModel):
    tentativa: int


class ErroDeDocumentoRequest(BaseModel):
    tentativa: int
    mensagem: str


class StatusWorkerResposta(BaseModel):
    """`GET /api/worker/status` -- nunca inclui o token nem qualquer
    segredo, só contagens agregadas."""
    modo: str
    jobs_aguardando_worker: int
    jobs_em_processamento: int
    jobs_concluidos_recentes: int
