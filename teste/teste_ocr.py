"""
teste/teste_ocr.py

Teste simples e direto do OCR pelo terminal, SEM interface gráfica.
Serve para confirmar que o PaddleOCR está funcionando antes de usar o
programa completo (main.py).

Uso:
    python teste\\teste_ocr.py caminho\\para\\foto.jpg

Se nenhum caminho for passado, tenta usar "foto_teste.jpg" na pasta atual.
"""

import sys
import os

# Permite rodar "python teste\teste_ocr.py" a partir da raiz do projeto,
# importando os módulos que estão na pasta principal (um nível acima).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cv2
import numpy as np

from leitor_matriculas.ocr.image_processor import preprocess_image
from leitor_matriculas.ocr.engine import get_ocr_engine, normalizar_matricula


def carregar_imagem(path: str) -> np.ndarray:
    """Lê a imagem do disco de forma segura, mesmo com acentos no caminho (Windows)."""
    dados = np.fromfile(path, dtype=np.uint8)
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError(f"Não foi possível abrir a imagem: {path}")
    return imagem


def main():
    caminho = sys.argv[1] if len(sys.argv) > 1 else "foto_teste.jpg"

    if not os.path.isfile(caminho):
        print(f"Arquivo não encontrado: {caminho}")
        print("Uso: python teste\\teste_ocr.py caminho\\para\\foto.jpg")
        sys.exit(1)

    print(f"Carregando imagem: {caminho}")
    imagem_original = carregar_imagem(caminho)
    print("Imagem carregada com sucesso!")

    print("Pré-processando imagem...")
    imagem_processada = preprocess_image(imagem_original)

    print("Inicializando PaddleOCR (pode demorar na primeira vez, baixa modelos)...")
    engine = get_ocr_engine("paddleocr")

    print("Executando reconhecimento...")
    resultados = engine.recognize(imagem_processada)

    print()
    print(f"=== {len(resultados)} trecho(s) reconhecido(s) ===")
    print()

    if not resultados:
        print("Nenhum texto foi reconhecido nesta imagem.")
        return

    for i, res in enumerate(resultados, start=1):
        sugestao = normalizar_matricula(res.texto_original)
        confianca_str = f"{res.confianca * 100:.2f}%" if res.confianca is not None else "N/D"
        box_str = str(res.box) if res.box else "N/D"

        print(f"[{i}] OCR original : {res.texto_original}")
        print(f"    Sugestão     : {sugestao}")
        print(f"    Confiança    : {confianca_str}")
        print(f"    Posição      : {box_str}")
        print()


if __name__ == "__main__":
    main()
