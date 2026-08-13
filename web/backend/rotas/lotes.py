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
from fastapi.responses import FileResponse

from leitor_matriculas.exportacao import xlsx_exporter
from leitor_matriculas.validacao.confirmacao import confirmar_revisao_manual

from .. import estado
from ..esquemas import ConfirmacaoRequest, ConfirmacaoResponse, LoteCriado, StatusLote

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


@router.get("/{lote_id}/registros")
def consultar_registros(lote_id: str):
    """
    Devolve os registros JÁ classificados até agora, na ordem física em
    que foram produzidos (mesma ordem que `_registros_exportacao` no
    Tkinter) -- pode ser chamado durante o processamento (resultado indo
    enchendo, mesma ideia da tabela ao vivo) ou depois de concluído. Cada
    item é o dict puro de `pipeline.montar_registro_exportacao`
    (`data`/`hora`/.../`evidencias`/`ocr_nao_associados`), sem
    transformação nenhuma.
    """
    lote = _lote_ou_404(lote_id)
    return lote.registros_publicos()


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
