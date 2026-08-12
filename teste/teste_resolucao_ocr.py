"""
teste/teste_resolucao_ocr.py

Fase 13 -- trava de regressão da resolução entregue ao OCR.

A resolução é a única variável que o benchmark da Fase 13 mediu, e ela tem
efeito NÃO MONOTÔNICO na precisão: reduzir demais não degrada aos poucos,
degrada em saltos e em silêncio -- a 1600 o sistema confirmou o
RESPONSÁVEL ERRADO (GRL lido como GR4), e a 2000 inventou uma linha
fantasma. Como nada disso aparece como erro (aparece como dado errado
CONFIRMADO), o valor precisa de uma trava explícita.

Este teste não mede qualidade de OCR -- isso exige as folhas reais. Ele
garante o contrato mecânico: qual resolução sai do pré-processamento, que
a proporção é preservada, e que o valor em vigor é o que o benchmark
aprovou.

Uso:
    python teste\\teste_resolucao_ocr.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from leitor_matriculas.ocr.image_processor import (  # noqa: E402
    LADO_MAXIMO_PADRAO,
    preprocess_image,
)

# Valor aprovado pelo benchmark da Fase 13. É a mesma resolução em que o
# PDF já chega ao OCR (pdf_reader renderiza a 200 DPI). Mudar isto exige
# repetir o benchmark contra as folhas reais -- ver o comentário em
# image_processor.py.
RESOLUCAO_APROVADA = 2339

falhas = []


def checar(cond, msg):
    print(("  OK    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def _foto(largura, altura):
    """Imagem sintética; só o TAMANHO importa para este teste."""
    return np.full((altura, largura, 3), 200, dtype=np.uint8)


def teste_valor_em_vigor():
    print("=== O valor em vigor é o que o benchmark aprovou ===")
    checar(LADO_MAXIMO_PADRAO == RESOLUCAO_APROVADA,
           f"LADO_MAXIMO_PADRAO == {RESOLUCAO_APROVADA} (obtido: {LADO_MAXIMO_PADRAO})")
    print()


def teste_foto_grande_e_reduzida_ao_limite():
    print("=== Foto de celular é reduzida ao limite, preservando a proporção ===")
    # Tamanho real das folhas fotografadas (16:9).
    processada = preprocess_image(_foto(4080, 2296))
    altura, largura = processada.shape[:2]
    checar(largura == RESOLUCAO_APROVADA,
           f"4080x2296 -> largura {RESOLUCAO_APROVADA} (obtido: {largura})")
    checar(abs((largura / altura) - (4080 / 2296)) < 0.01,
           f"proporção preservada (obtido: {largura}x{altura})")
    print()


def teste_imagem_pequena_nao_e_ampliada():
    print("=== Imagem menor que o limite não é ampliada ===")
    processada = preprocess_image(_foto(1200, 800))
    altura, largura = processada.shape[:2]
    checar((largura, altura) == (1200, 800),
           f"1200x800 permanece 1200x800 (obtido: {largura}x{altura})")
    print()


def teste_pdf_ja_chega_no_limite_e_nao_e_reduzido_de_novo():
    print("=== A página de PDF (200 DPI) não sofre segunda redução ===")
    # O pdf_reader entrega ~2339x1317 nestas folhas: o limite não deve
    # mexer nela (senão o caminho do PDF, já validado, mudaria de
    # comportamento por tabela).
    processada = preprocess_image(_foto(2339, 1317))
    altura, largura = processada.shape[:2]
    checar((largura, altura) == (2339, 1317),
           f"2339x1317 permanece intacta (obtido: {largura}x{altura})")
    print()


def teste_limite_continua_configuravel():
    print("=== O limite continua configurável por chamada (reversão simples) ===")
    processada = preprocess_image(_foto(4080, 2296), lado_maximo=3500)
    largura = processada.shape[1]
    checar(largura == 3500,
           f"lado_maximo=3500 volta ao comportamento anterior (obtido: {largura})")
    print()


def teste_orientacao_retrato_usa_o_maior_lado():
    print("=== Em retrato, o limite se aplica ao MAIOR lado ===")
    processada = preprocess_image(_foto(2296, 4080))
    altura, largura = processada.shape[:2]
    checar(altura == RESOLUCAO_APROVADA,
           f"2296x4080 -> altura {RESOLUCAO_APROVADA} (obtido: {largura}x{altura})")
    print()


TESTES = [
    teste_valor_em_vigor,
    teste_foto_grande_e_reduzida_ao_limite,
    teste_imagem_pequena_nao_e_ampliada,
    teste_pdf_ja_chega_no_limite_e_nao_e_reduzido_de_novo,
    teste_limite_continua_configuravel,
    teste_orientacao_retrato_usa_o_maior_lado,
]


if __name__ == "__main__":
    for teste in TESTES:
        teste()
    print("=" * 62)
    if falhas:
        print(f"{len(falhas)} FALHA(S):")
        for f in falhas:
            print("   - " + f)
        sys.exit(1)
    print("TODAS AS VERIFICAÇÕES PASSARAM.")
