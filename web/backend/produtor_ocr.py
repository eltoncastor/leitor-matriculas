"""
web/backend/produtor_ocr.py

Fase 26a. A metade PESADA do processamento de um lote: renderizar/ler cada
folha, rodar o OCR e comprimir a foto. É o único módulo do backend que
importa OpenCV e o motor de OCR -- `web/backend/estado.py` (o lado VPS)
deixou de importar os dois nesta sub-fase, e é isso que permite instalar a
API sem PaddleOCR/OpenCV.

ESTE ARQUIVO É O MOLDE DO WORKER. Ele existe hoje como uma thread dentro
do próprio processo do backend, o que preserva exatamente o comportamento
anterior à Fase 26 (e é o que o modo desktop/`.exe` continuará usando). A
partir da Sub-fase 26c a mesma sequência roda num processo separado, no PC
Windows, falando com a VPS por HTTP -- e as chamadas a
`estado.depositar_*` viram requisições. Nenhuma decisão de negócio mora
aqui: o produtor LÊ a folha, ele não classifica nada.

Não levanta exceção para quem chama: cada página isola a própria falha
(mesmo padrão da Fase 7/14), e a falha é entregue como texto no resultado
da página, para a VPS transformar em uma linha ERRO.
"""
import logging
import threading
from typing import Optional

import cv2
import numpy as np

from leitor_matriculas import pipeline
from leitor_matriculas.ocr import pdf_reader

from . import armazenamento, estado as estado_mod

# Mesmos valores de `ui/app.py` (Fase 10) -- a foto é comodidade da
# revisão, não dado; comprimir demais perderia legibilidade do manuscrito,
# comprimir de menos custaria a explosão de RAM que a Fase 10 já mediu.
LARGURA_MAXIMA_MINIATURA = 1500
QUALIDADE_MINIATURA = 85


def _ler_imagem(caminho: str) -> np.ndarray:
    """Mesma leitura que `ui/app.py::_ler_imagem` (via `np.fromfile` +
    `cv2.imdecode`, que lida com acentos no caminho no Windows -- `cv2.
    imread` não). Não importado de lá de propósito: nada no backend web
    depende de `leitor_matriculas.ui` (via de mão única do projeto)."""
    dados = np.fromfile(caminho, dtype=np.uint8)
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError(f"Não foi possível abrir a imagem: {caminho}")
    return imagem


def _comprimir_para_miniatura(imagem_bgr) -> Optional[bytes]:
    """Nunca lança: a foto é comodidade da revisão, uma falha aqui não pode
    derrubar o processamento da página."""
    try:
        altura, largura = imagem_bgr.shape[:2]
        maior = max(altura, largura)
        if maior > LARGURA_MAXIMA_MINIATURA:
            fator = LARGURA_MAXIMA_MINIATURA / maior
            imagem_bgr = cv2.resize(
                imagem_bgr, (int(largura * fator), int(altura * fator)),
                interpolation=cv2.INTER_AREA,
            )
        ok, buffer = cv2.imencode(".jpg", imagem_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), QUALIDADE_MINIATURA])
        return buffer.tobytes() if ok else None
    except Exception:
        logging.exception("Falha ao preparar miniatura da página (revisão segue sem a foto)")
        return None


def _informar_etapa(estado):
    def _callback(texto: str):
        estado_mod.registrar_etapa(estado, texto)
    return _callback


def _ocr_de_uma_pagina(estado, numero: int, imagem_bgr) -> dict:
    """Roda o OCR de uma folha e devolve o resultado no formato do
    protocolo. O erro vai CRU (sem prefixo com o nome do arquivo): quem
    monta a frase que o operador lê é a VPS, que conhece o nome original
    do arquivo enviado -- ver `estado._mensagem_erro_pagina`."""
    engine = estado_mod.obter_ocr_engine()
    _imagem_processada, registros, erro = pipeline.processar_uma_pagina(
        imagem_bgr, engine, informar_etapa=_informar_etapa(estado)
    )
    if erro:
        return {"numero": numero, "erro": erro, "fase_erro": "pipeline", "registros": []}

    # A foto só existe no caminho de sucesso (mesma condição de antes da
    # Fase 26: uma página que falhou pode nem ter imagem válida). Canal
    # separado do resultado, e tolerante a falha.
    miniatura = _comprimir_para_miniatura(imagem_bgr)
    if miniatura is not None:
        estado_mod.depositar_miniatura(estado, numero, miniatura)

    return {
        "numero": numero,
        "erro": None,
        "fase_erro": None,
        "registros": [registro.como_dicionario() for registro in registros],
    }


def _ja_processada(lote_id: str, numero: int, ja_persistidas: set) -> bool:
    """Retomada: uma página cujo OCR já está em disco não é refeita. É o
    que torna barato devolver um Job à fila -- refazer a classificação
    custa milissegundos, refazer o OCR custa ~40 s por folha."""
    return numero in ja_persistidas


def _produzir_pdf(estado) -> None:
    caminho_pdf = estado.caminhos[0]
    ja_persistidas = armazenamento.paginas_persistidas(estado.id)

    for pagina_pdf in pdf_reader.iterar_paginas(caminho_pdf):
        if estado.parar:
            return
        numero = pagina_pdf.numero
        if _ja_processada(estado.id, numero, ja_persistidas):
            continue
        if pagina_pdf.erro:
            estado_mod.depositar_resultado_pagina(estado, numero, {
                "numero": numero, "erro": pagina_pdf.erro,
                "fase_erro": "renderizacao", "registros": [],
            })
            continue
        estado_mod.depositar_resultado_pagina(
            estado, numero, _ocr_de_uma_pagina(estado, numero, pagina_pdf.imagem)
        )


def _produzir_imagens(estado) -> None:
    ja_persistidas = armazenamento.paginas_persistidas(estado.id)

    for indice, caminho in enumerate(estado.caminhos, start=1):
        if estado.parar:
            return
        if _ja_processada(estado.id, indice, ja_persistidas):
            continue
        try:
            imagem_bgr = _ler_imagem(caminho)
        except Exception as exc:
            estado_mod.depositar_resultado_pagina(estado, indice, {
                "numero": indice, "erro": str(exc),
                "fase_erro": "leitura", "registros": [],
            })
            continue
        estado_mod.depositar_resultado_pagina(
            estado, indice, _ocr_de_uma_pagina(estado, indice, imagem_bgr)
        )


def produzir(lote_id: str) -> None:
    """Ponto de entrada da thread produtora."""
    estado = estado_mod.obter_lote(lote_id)
    if estado is None:
        return
    try:
        if estado.tipo == estado_mod.TIPO_PDF:
            _produzir_pdf(estado)
        else:
            _produzir_imagens(estado)
    except Exception as exc:
        # Falha de DOCUMENTO INTEIRO (arquivo que não abre, PDF sem
        # páginas). A thread-motora está esperando páginas que nunca vão
        # chegar, então o lote precisa ser marcado aqui.
        logging.exception("Falha do produtor de OCR no lote %s", lote_id)
        with estado.lock:
            estado.status = estado_mod.STATUS_ERRO
            estado.erro_fatal = str(exc)
            estado.parar = True
            estado.condicao.notify_all()
        estado_mod.persistir(estado, com_registros=True)


def iniciar_em_thread(lote_id: str) -> threading.Thread:
    thread = threading.Thread(target=produzir, args=(lote_id,), daemon=True,
                              name=f"produtor-ocr-{lote_id[:8]}")
    thread.start()
    return thread


__all__ = ["produzir", "iniciar_em_thread", "LARGURA_MAXIMA_MINIATURA", "QUALIDADE_MINIATURA"]
