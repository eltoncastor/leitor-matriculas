"""
image_processor.py

Pré-processamento de imagens de folhas com matrículas manuscritas.

Regra importante: a imagem original NUNCA é modificada. Toda função aqui
recebe a imagem original e devolve uma NOVA imagem processada.

O processamento é propositalmente conservador (poucos filtros, sem
binarização agressiva por padrão) porque a escrita é manuscrita: filtros
fortes tendem a apagar traços finos de caneta em vez de ajudar o OCR.
"""

import cv2
import numpy as np

# Fotos de celular atuais costumam vir com o lado maior bem acima de 4000px.
# O PaddleOCR já teria que redimensionar sozinho (e avisa sobre isso), então
# fazemos esse redimensionamento aqui de forma controlada, preservando a
# proporção, para ter um processamento mais previsível e rápido.
#
# O VALOR (Fase 13 -- benchmark de resolução): 2339 é a resolução em que o
# PDF do mês já chega ao OCR (o `pdf_reader` renderiza a 200 DPI, o que dá
# 2339x1317 nestas folhas) e que a operação vinha usando de fato. O
# benchmark comparou 5 resoluções sobre as MESMAS 5 folhas reais, com a
# resolução como única variável, e mediu, contra 3500 (o valor anterior):
#
#     tempo   66,0 -> 40,3 s por página   (-39%)
#     RAM     5272 -> 2633 MB de pico     (-50%)
#     acerto  17 -> 19 CONFIRMADO corretos, com o MESMO único defeito
#
# A 3500 o OCR perdia campos que a 2339 ele lê (uma matrícula e duas horas),
# e a Fase 12 corretamente barrava esses registros -- daí os 2 CONFIRMADO a
# menos. Abaixo de 2339 o resultado se degrada e não pôde ser adotado:
# 2000 inventou uma linha fantasma e leu 29306 como 99306; 1800 trocou uma
# matrícula ambígua; 1600 confirmou o RESPONSÁVEL ERRADO (GRL lido como
# GR4). Ver o relatório da Fase 13.
#
# Para voltar ao comportamento anterior basta este número (ou passar
# `lado_maximo=` na chamada). Reduzir mais exige repetir o benchmark: a
# degradação abaixo de 2339 é silenciosa e aparece como dado errado
# confirmado, não como erro.
LADO_MAXIMO_PADRAO = 2339


def _limitar_tamanho(imagem: np.ndarray, lado_maximo: int) -> np.ndarray:
    """Reduz a imagem, preservando a proporção, se o lado maior exceder o limite."""
    altura, largura = imagem.shape[:2]
    lado_maior = max(altura, largura)

    if lado_maior <= lado_maximo:
        return imagem

    fator = lado_maximo / lado_maior
    nova_largura = int(largura * fator)
    nova_altura = int(altura * fator)
    return cv2.resize(imagem, (nova_largura, nova_altura), interpolation=cv2.INTER_AREA)


def preprocess_image(
    original_bgr: np.ndarray,
    lado_maximo: int = LADO_MAXIMO_PADRAO,
    apply_adaptive_threshold: bool = False,
) -> np.ndarray:
    """
    Aplica uma sequência conservadora de técnicas de pré-processamento
    pensadas para melhorar a leitura de números manuscritos à caneta, sem
    destruir traços finos.

    Etapas:
        1. Cópia da imagem (nunca mexemos na original)
        2. Limite de tamanho (fotos muito grandes são reduzidas preservando proporção)
        3. Escala de cinza
        4. Redução de ruído
        5. Aumento de contraste (CLAHE)
        6. Nitidez (sharpen)
        7. Threshold adaptativo (OPCIONAL — desligado por padrão)

    Args:
        original_bgr: imagem original, no formato BGR (como o OpenCV lê).
        lado_maximo: maior dimensão (largura ou altura) permitida antes do
            processamento; fotos maiores são reduzidas preservando a proporção.
        apply_adaptive_threshold: se True, aplica threshold adaptativo no final.
            Desligado por padrão porque pode apagar traços finos de caneta;
            ligue apenas se, na prática, ajudar o OCR na sua folha.

    Returns:
        Imagem processada (escala de cinza, ou binarizada se
        apply_adaptive_threshold=True), pronta para o OCR.
    """
    if original_bgr is None:
        raise ValueError("Imagem original inválida (None).")

    # 1. Trabalhamos sempre em cópia
    image = original_bgr.copy()

    # 2. Limite de tamanho (conservador: só reduz, nunca amplia)
    image = _limitar_tamanho(image, lado_maximo)

    # 3. Escala de cinza
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 4. Redução de ruído (preserva bordas melhor que um blur simples)
    denoised = cv2.fastNlMeansDenoising(gray, h=8, templateWindowSize=7, searchWindowSize=21)

    # 5. Aumento de contraste com CLAHE (melhor que equalizeHist para texto)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(denoised)

    # 6. Nitidez (unsharp mask simples, suave)
    blurred = cv2.GaussianBlur(contrasted, (0, 0), sigmaX=2)
    sharpened = cv2.addWeighted(contrasted, 1.3, blurred, -0.3, 0)

    # 7. Threshold adaptativo (opcional; desligado por padrão — ver docstring)
    if apply_adaptive_threshold:
        processed = cv2.adaptiveThreshold(
            sharpened,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=31,
            C=15,
        )
    else:
        processed = sharpened

    return processed


def to_display_rgb(image: np.ndarray) -> np.ndarray:
    """
    Converte uma imagem (BGR ou escala de cinza) para RGB, formato usado
    para exibição na interface gráfica (PIL/Tkinter esperam RGB).
    """
    if image is None:
        raise ValueError("Imagem inválida (None).")

    if len(image.shape) == 2:
        # Imagem em escala de cinza / binarizada
        return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

    # Imagem colorida (BGR do OpenCV)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
