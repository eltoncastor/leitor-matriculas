"""
pdf_reader.py

Leitura de PDF, página por página, convertendo cada página em uma imagem
(array NumPy BGR — mesmo formato que `image_processor.py` já espera), sem
carregar todas as páginas do PDF como imagem na memória de uma vez.

Usa PyMuPDF (pacote pip "PyMuPDF", módulo `pymupdf`/`fitz`) porque é um
único pacote instalável via pip, sem dependência externa de um programa
como o Poppler (diferente de `pdf2image`) — o que facilita bastante a
instalação em Windows, conforme pedido.

Este módulo não sabe nada sobre OCR, folhas de liberação, ou registros —
ele só faz "PDF com N páginas" -> "uma imagem BGR por vez". A ligação com
o resto do fluxo (pré-processamento, OCR, parser espacial) é feita em
`ui.py`, iterando sobre o gerador `iterar_paginas`.
"""

import os
from dataclasses import dataclass
from typing import Iterator, Optional

import numpy as np

try:
    import pymupdf as fitz  # nome atual recomendado do pacote PyMuPDF
except ImportError:
    try:
        import fitz  # nome antigo (versões mais velhas do PyMuPDF); ainda funciona
    except ImportError:
        fitz = None


@dataclass
class PaginaPdf:
    """
    Uma página do PDF já renderizada como imagem (ou o erro que impediu
    isso, se algo deu errado só naquela página específica).
    """
    numero: int  # número da página, começando em 1
    imagem: Optional[np.ndarray]  # BGR (uint8), ou None se `erro` estiver preenchido
    erro: Optional[str] = None


def _verificar_disponibilidade():
    if fitz is None:
        raise RuntimeError(
            "A biblioteca 'PyMuPDF' não está instalada. Rode: pip install -r requirements.txt"
        )


def _abrir_documento(caminho_pdf: str):
    _verificar_disponibilidade()

    if not os.path.isfile(caminho_pdf):
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_pdf}")

    try:
        documento = fitz.open(caminho_pdf)
    except Exception as exc:
        raise RuntimeError(f"Não foi possível abrir o PDF '{caminho_pdf}': {exc}") from exc

    if documento.page_count == 0:
        documento.close()
        raise ValueError(f"O PDF '{caminho_pdf}' não tem nenhuma página.")

    return documento


def contar_paginas(caminho_pdf: str) -> int:
    """Abre o PDF só para descobrir quantas páginas ele tem (para a barra de progresso)."""
    documento = _abrir_documento(caminho_pdf)
    try:
        return documento.page_count
    finally:
        documento.close()


def iterar_paginas(caminho_pdf: str, dpi: int = 200) -> Iterator[PaginaPdf]:
    """
    Gerador que abre o PDF UMA ÚNICA VEZ e devolve uma `PaginaPdf` por vez,
    renderizando cada página sob demanda — as páginas ainda não pedidas não
    são processadas, e a imagem de uma página anterior pode ser liberada
    pelo Python assim que quem consome o gerador não precisar mais dela.
    Isso evita carregar as ~200 páginas de um mês inteiro como imagem na
    memória de uma vez só.

    Se uma página especificamente falhar ao renderizar (página corrompida,
    conteúdo inesperado, etc.), a `PaginaPdf` daquela página vem com
    `erro` preenchido e `imagem=None`, e o gerador CONTINUA normalmente
    para a próxima página — um problema em uma página não deve derrubar o
    processamento do PDF inteiro (ver regra de tratamento de erro por
    página combinada para o processamento em lote).

    Levanta exceção (FileNotFoundError / RuntimeError / ValueError) apenas
    para problemas que impedem abrir o PDF como um todo (arquivo ausente,
    PDF corrompido, PDF sem nenhuma página) — isso sim é um erro fatal, não
    dá pra "continuar para a próxima página" se nem o documento abriu.

    Args:
        caminho_pdf: caminho do arquivo .pdf.
        dpi: resolução usada para renderizar cada página como imagem. 200
            é um equilíbrio razoável entre qualidade para OCR e tamanho de
            imagem/tempo de processamento; pode ser ajustado se necessário.
    """
    documento = _abrir_documento(caminho_pdf)

    try:
        zoom = dpi / 72  # o PyMuPDF usa 72 DPI como base de referência
        matriz = fitz.Matrix(zoom, zoom)

        for indice in range(documento.page_count):
            numero = indice + 1
            try:
                pagina = documento.load_page(indice)
                pixmap = pagina.get_pixmap(matrix=matriz, colorspace=fitz.csRGB)

                imagem_rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                # PyMuPDF devolve RGB; o resto do projeto (OpenCV) usa BGR.
                # .copy() para não depender do buffer interno do pixmap
                # depois que ele sair de escopo.
                imagem_bgr = imagem_rgb[:, :, ::-1].copy()

                yield PaginaPdf(numero=numero, imagem=imagem_bgr, erro=None)
            except Exception as exc:
                yield PaginaPdf(numero=numero, imagem=None, erro=str(exc))
    finally:
        documento.close()
