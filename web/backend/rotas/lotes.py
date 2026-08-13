"""
web/backend/rotas/lotes.py

Endpoints do lote (Fase 24a). Cada rota resolve por `lote_id` -- nunca por
"o lote atual" -- e chama SÓ funções já existentes em `leitor_matriculas`
(`pipeline`, `validacao.confirmacao`, `exportacao.xlsx_exporter`) ou em
`web/backend/estado.py` (o mecanismo de acompanhar processamento em
background, equivalente aqui à fila+thread do Tkinter). Nenhuma regra de
negócio é reimplementada nesta camada.
"""
import logging
import os
import shutil
import tempfile
import threading
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from leitor_matriculas.exportacao import xlsx_exporter
from leitor_matriculas.validacao.confirmacao import confirmar_revisao_manual
# Fase 24c: explicacao_revisao mudou de ui/ para validacao/ nesta mesma
# sub-fase exatamente para o backend poder importá-la sem depender de
# `leitor_matriculas.ui` -- ver o motivo completo no docstring do módulo.
from leitor_matriculas.validacao import explicacao_revisao

from .. import estado
from ..esquemas import (
    ConfirmacaoRequest, ConfirmacaoResponse, ExplicacaoResposta, LoteCriado, StatusLote,
)

router = APIRouter(prefix="/lotes", tags=["lotes"])

EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSAO_PDF = ".pdf"


def _lote_ou_404(lote_id: str) -> estado.LoteState:
    lote = estado.obter_lote(lote_id)
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote '{lote_id}' não encontrado")
    return lote


@router.post("", response_model=LoteCriado, status_code=201)
async def criar_lote(files: List[UploadFile] = File(...)):
    """
    Recebe um PDF (um arquivo) OU várias imagens -- mesmas duas entradas
    que a aba Início do Tkinter oferece (`_on_selecionar_imagem`/`_on_
    selecionar_pdf`, Fase 21a). Salva em uma pasta temporária PRÓPRIA
    deste lote (nunca em `dados/`, que é só para as bases de referência) e
    devolve o `lote_id` -- o processamento em si só começa quando `POST
    /lotes/{lote_id}/processar` for chamado (upload e disparo são passos
    separados de propósito, para o cliente poder mostrar uma etapa de
    conferência antes de gastar ~40 s/folha de OCR -- mesma UX de Fase
    21a).
    """
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado")

    nomes = [f.filename or "" for f in files]
    extensoes = {os.path.splitext(n)[1].lower() for n in nomes}

    if len(files) == 1 and extensoes == {EXTENSAO_PDF}:
        tipo = estado.TIPO_PDF
    elif extensoes and extensoes.issubset(EXTENSOES_IMAGEM):
        tipo = estado.TIPO_IMAGENS
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Envie UM arquivo PDF ou uma ou mais imagens "
                f"({', '.join(sorted(EXTENSOES_IMAGEM))}); recebido: {sorted(extensoes)}"
            ),
        )

    pasta_temp = tempfile.mkdtemp(prefix="lote_web_")
    caminhos = []
    try:
        for arquivo in files:
            nome_seguro = os.path.basename(arquivo.filename or "arquivo")
            destino = os.path.join(pasta_temp, nome_seguro)
            conteudo = await arquivo.read()
            with open(destino, "wb") as saida:
                saida.write(conteudo)
            caminhos.append(destino)
    except Exception as exc:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Falha ao salvar os arquivos enviados: {exc}") from exc

    lote = estado.criar_lote(tipo=tipo, caminhos=caminhos, pasta_temp=pasta_temp)
    return LoteCriado(lote_id=lote.id, tipo=lote.tipo, total_arquivos=len(caminhos))


@router.post("/{lote_id}/processar", response_model=StatusLote, status_code=202)
def disparar_processamento(lote_id: str):
    """
    Dispara o processamento em background (thread separada -- o OCR é
    lento, isto NUNCA bloqueia a requisição HTTP até o lote inteiro
    terminar). Consultar o progresso é `GET /lotes/{lote_id}/status`.
    """
    lote = _lote_ou_404(lote_id)
    with lote.lock:
        if lote.status != estado.STATUS_PENDENTE:
            raise HTTPException(
                status_code=409,
                detail=f"Lote '{lote_id}' já está '{lote.status}' -- não pode ser disparado de novo",
            )
        lote.status = estado.STATUS_PROCESSANDO
    threading.Thread(target=estado.processar_lote, args=(lote_id,), daemon=True).start()
    return StatusLote(**lote.status_publico())


@router.get("/{lote_id}/status", response_model=StatusLote)
def consultar_status(lote_id: str):
    lote = _lote_ou_404(lote_id)
    return StatusLote(**lote.status_publico())


def _campos_bloqueantes(registro: dict) -> List[str]:
    """
    Fase 24c: só o(s) NOME(s) do(s) campo(s) que bloqueiam a linha --
    `explicacao_revisao.explicar(...).campos_bloqueantes`, sem o resto da
    explicação (que é cara demais para calcular em massa: `sinais_de_
    contexto` varre o lote inteiro por linha). Usado para colorir a lista
    de pendências por tipo (mesma ideia de `CORES_TIPO_PENDENCIA` no
    Tkinter) sem o cliente precisar de N requisições extras só para
    montar a lista. Nunca lança: uma linha sem dossiê (sessão antiga)
    simplesmente não tem campo bloqueante calculável.
    """
    try:
        return explicacao_revisao.explicar(
            registro.get("evidencias"), registro.get("observacao") or ""
        ).campos_bloqueantes
    except Exception:
        logging.exception("Falha ao calcular campos_bloqueantes (apenas apresentação)")
        return []


@router.get("/{lote_id}/registros")
def consultar_registros(lote_id: str):
    """
    Devolve os registros JÁ classificados até agora, na ordem física em
    que foram produzidos (mesma ordem que `_registros_exportacao` no
    Tkinter) -- pode ser chamado durante o processamento (resultado indo
    enchendo, mesma ideia da tabela ao vivo) ou depois de concluído. Cada
    item é o dict de `pipeline.montar_registro_exportacao`
    (`data`/`hora`/.../`evidencias`/`ocr_nao_associados`) mais
    `campos_bloqueantes` (Fase 24c, ver `_campos_bloqueantes` acima) --
    a ÚNICA chave acrescentada nesta camada, e é apresentação pura (o
    dossiê já continha essa informação; só não vinha destacada). Devolve
    CÓPIAS (`{**r, ...}`) -- nunca muta os dicts que `estado.LoteState`
    guarda, mesma garantia que `registros_publicos()` já documenta.
    """
    lote = _lote_ou_404(lote_id)
    return [{**r, "campos_bloqueantes": _campos_bloqueantes(r)} for r in lote.registros_publicos()]


@router.get("/{lote_id}/registros/{indice}/explicacao", response_model=ExplicacaoResposta)
def explicacao_registro(lote_id: str, indice: int):
    """
    "Por que preciso revisar?" -- forma HTTP de `App._explicacao_revisao_
    atual()` (Fase 18): a cadeia OCR->normalização->base->regra em
    linguagem de operador, mais os sinais de contexto (Fase 16, "este
    lote usa N responsáveis", "esta linha quebra a ordem cronológica da
    folha") -- nunca pré-seleciona nada, nunca decide nada, só explica o
    que o motor de evidências (Fase 17) já registrou. Precisa da lista
    INTEIRA de registros do lote (não só o registro pedido) porque
    `sinais_de_contexto` compara a linha atual contra as outras do
    mesmo lote/folha.
    """
    lote = _lote_ou_404(lote_id)
    registros = lote.registros_publicos()
    if not (0 <= indice < len(registros)):
        raise HTTPException(status_code=404, detail=f"Registro {indice} não existe no lote '{lote_id}'")

    registro = registros[indice]
    explicacao = explicacao_revisao.explicar(registro.get("evidencias"), registro.get("observacao") or "")
    sinais = explicacao_revisao.sinais_de_contexto(registros, indice)
    return ExplicacaoResposta(
        explicacao={
            "campos_bloqueantes": explicacao.campos_bloqueantes,
            "titulo": explicacao.titulo,
            "detalhes": explicacao.detalhes,
            "por_campo": explicacao.por_campo,
        },
        sinais_contexto=[sinal.como_dicionario() for sinal in sinais],
    )


@router.get("/{lote_id}/paginas/{numero}/imagem")
def imagem_pagina(lote_id: str, numero: int):
    """
    A foto da página de origem (JPEG comprimido -- ver `estado.
    _comprimir_para_miniatura`, mesmos parâmetros de `ui/app.py`), para a
    tela de Revisão mostrar ao lado do formulário. `404` (não um JPEG em
    branco) quando a página não tem foto disponível -- página com ERRO de
    renderização, ou lote carregado de uma sessão sem imagem -- mesmo
    texto de causa que `_mostrar_foto_pagina` já trata no Tkinter
    ("(foto indisponível)"), decidido pelo CLIENTE a partir do 404, não
    inventado aqui.
    """
    lote = _lote_ou_404(lote_id)
    miniatura = lote.obter_miniatura(numero)
    if miniatura is None:
        raise HTTPException(status_code=404, detail=f"Sem foto disponível para a página {numero}")
    return Response(content=miniatura, media_type="image/jpeg")


@router.post("/{lote_id}/registros/{indice}/confirmar", response_model=ConfirmacaoResponse)
def confirmar_registro(lote_id: str, indice: int, corpo: ConfirmacaoRequest):
    """
    Único caminho de confirmação manual -- chama `validacao.confirmacao.
    confirmar_revisao_manual`, a MESMA função que `App._revisao_confirmar`
    chama no Tkinter (Fase 24a). Não reimplementa a decisão: só localiza o
    registro pelo índice (a mesma posição em `registros_publicos()`, igual
    ao `iid` da tabela do Tkinter -- ver Fase 10) e repassa os campos
    digitados.
    """
    lote = _lote_ou_404(lote_id)
    with lote.lock:
        if not (0 <= indice < len(lote.registros)):
            raise HTTPException(status_code=404, detail=f"Registro {indice} não existe no lote '{lote_id}'")
        registro = lote.registros[indice]
        contexto_lote = lote.contexto_lote

    resultado = confirmar_revisao_manual(
        registro,
        data=corpo.data,
        hora=corpo.hora,
        matricula=corpo.matricula,
        gestor=corpo.gestor,
        motivo=corpo.motivo,
        data_manager=estado.obter_data_manager(),
        contexto_lote=contexto_lote,
    )
    return ConfirmacaoResponse(
        registro=resultado.registro,
        status_anterior=resultado.status_anterior,
        confirmou_agora=resultado.confirmou_agora,
        observacao_classificacao=resultado.observacao_classificacao,
    )


@router.get("/{lote_id}/listas")
def listas_de_apoio(lote_id: str):
    """
    Motivos/Responsáveis cadastrados -- para o formulário de revisão
    sugerir (`<datalist>`, nunca um `<select>` fechado: o operador
    continua podendo colar/ajustar um texto que não está na lista, mesma
    liberdade do `Combobox` editável do Tkinter -- ver `_montar_aba_
    revisao`). Só leitura de `DataManager.listar_motivos`/`listar_
    gestores`, que já existiam desde antes da Fase 24 -- nenhuma lista
    nova, nenhuma decisão. Sob `/lotes/{lote_id}` por consistência de
    rota, mas o conteúdo é global ao processo (mesma base para todo
    lote, ver `estado.obter_data_manager`).
    """
    _lote_ou_404(lote_id)
    dm = estado.obter_data_manager()
    return {
        "motivos": sorted(dm.listar_motivos() or []),
        "gestores": sorted(dm.listar_gestores() or []),
    }


@router.get("/{lote_id}/exportar")
def exportar_xlsx(lote_id: str):
    """
    Gera a planilha XLSX do lote (mesmo `exportacao.xlsx_exporter.
    export_to_xlsx` do Tkinter, 3 abas/ordem física preservada) e devolve
    como download. Não exige que o processamento tenha terminado -- um
    lote parcialmente processado pode ser exportado com o que já tem,
    mesma liberdade que o botão "Gerar planilha" sempre teve no Tkinter.
    """
    lote = _lote_ou_404(lote_id)
    registros = lote.registros_publicos()
    if not registros:
        raise HTTPException(status_code=409, detail="Lote ainda não tem nenhum registro para exportar")

    status_publico = lote.status_publico()
    caminho_saida = os.path.join(lote.pasta_temp, f"liberacoes_{lote_id}.xlsx")
    try:
        xlsx_exporter.export_to_xlsx(
            registros,
            caminho_saida,
            paginas_processadas=status_publico["paginas_processadas"],
            paginas_com_erro=status_publico["paginas_com_erro"],
            paginas_com_contagem_divergente=len(lote.avisos_contagem),
        )
    except Exception as exc:
        logging.exception("Falha ao gerar a planilha do lote %s", lote_id)
        raise HTTPException(status_code=500, detail=f"Falha ao gerar a planilha: {exc}") from exc

    return FileResponse(
        caminho_saida,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"liberacoes_{lote_id}.xlsx",
    )
