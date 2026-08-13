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


class ErroResposta(BaseModel):
    detalhe: str
