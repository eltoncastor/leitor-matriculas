"""
ocr_engine.py

Camada de OCR. Mantém uma interface simples (OCREngine) para que, no futuro,
seja fácil trocar o PaddleOCR por outro motor sem mexer na interface gráfica.

IMPORTANTE (leia se for atualizar o PaddleOCR no futuro):
Este arquivo foi escrito para a API do PaddleOCR 3.x (testado com 3.7.0).
A API 3.x é INCOMPATÍVEL com a API 2.x:

    - Construtor não aceita mais `show_log`.
    - `ocr.ocr(image, cls=True)` não existe mais -> agora é `ocr.predict(image)`.
    - O retorno não é mais uma lista de [box, (texto, confiança)], e sim uma
      lista de objetos "Result" (um por imagem), cada um expondo os dados
      via `.json` como um dicionário com as chaves `rec_texts`, `rec_scores`,
      `rec_boxes` (e `rec_polys`, com o polígono completo em vez do
      retângulo).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

# Fase 26a: `cv2` NÃO é importado aqui no topo de propósito. Ele é usado em
# um único ponto deste módulo (a conversão para 3 canais dentro de
# `PaddleOCREngine.recognize`) -- ou seja, só no caminho que de fato roda
# OCR, que a partir da Fase 26 mora no Worker, nunca na VPS. A VPS importa
# este módulo assim mesmo (por `OCRResult`, que o parser espacial usa, e
# por `normalizar_matricula`, que a classificação usa), e um import de topo
# obrigaria a instalar o OpenCV (~90 MB) num processo que jamais abre uma
# imagem. O import vive dentro de `recognize`; depois da primeira chamada
# ele sai do cache de módulos do Python, então não há custo por página.
# `numpy` continua no topo porque é usado nas ANOTAÇÕES de tipo abaixo,
# avaliadas na definição das funções.


@dataclass
class OCRResult:
    """
    Resultado bruto de uma leitura de OCR sobre um trecho de imagem.

    box: [x1, y1, x2, y2] em pixels da imagem processada (retângulo
    delimitador), quando o motor de OCR fornecer essa informação. Guardamos
    isso desde já porque a folha é uma tabela e, no futuro, a posição será
    usada para descobrir a qual linha/coluna cada texto pertence.
    """
    texto_original: str
    confianca: Optional[float]  # 0.0 a 1.0, ou None se o motor não informar
    box: Optional[List[int]] = None


# ---------------------------------------------------------------------------
# Interface abstrata: qualquer motor de OCR novo deve implementar isso.
# ---------------------------------------------------------------------------
class OCREngine(ABC):
    @abstractmethod
    def recognize(self, image: np.ndarray) -> List[OCRResult]:
        """
        Recebe uma imagem já pré-processada e devolve uma lista de
        OCRResult (um por trecho de texto identificado).
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Implementação usando PaddleOCR 3.x
# ---------------------------------------------------------------------------
class PaddleOCREngine(OCREngine):
    """
    Motor de OCR usando PaddleOCR 3.x (API baseada em `predict()`).

    Desativamos de propósito os submódulos de classificação de orientação de
    documento e "unwarping" (`use_doc_orientation_classify`,
    `use_doc_unwarping`, `use_textline_orientation`):

    1. Nossas fotos são folhas simples fotografadas de frente, não
       documentos escaneados tortos/dobrados — não precisamos desses
       submódulos.
    2. Foram justamente esses submódulos (em especial o de "unwarping",
       modelo UVDoc) que dispararam o erro do oneDNN
       (`ConvertPirAttribute2RuntimeAttribute not support ...`) em CPU no
       Windows. Desativá-los remove a causa do erro em vez de mascará-lo.

    Também passamos `enable_mkldnn=False`. Esse é o parâmetro oficial e
    documentado do PaddleOCR/PaddleX para desligar o acelerador oneDNN — a
    variável de ambiente `PFLAGS_USE_ONEDNN` mencionada nos testes não é o
    nome correto (nem da flag do Paddle, que seria `FLAGS_use_mkldnn`, nem
    de um parâmetro do PaddleOCR), por isso não tinha efeito. Esse mesmo
    erro de oneDNN em CPU com PaddlePaddle 3.3.x já foi relatado por outros
    usuários do PaddleOCR, e `enable_mkldnn=False` é o contorno oficial.
    """

    def __init__(self, lang: str = "en"):
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ImportError(
                "PaddleOCR não está instalado. Rode: pip install -r requirements.txt"
            ) from exc

        self._ocr = PaddleOCR(
            lang=lang,
            device="cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )

    def recognize(self, image: np.ndarray) -> List[OCRResult]:
        # O pré-processamento (image_processor.py) devolve, por padrão, uma
        # imagem em escala de cinza — matriz 2D, shape (altura, largura).
        # O PaddleOCR 3.x espera uma imagem com 3 canais (altura, largura,
        # canais) e, ao receber uma imagem 2D, quebra internamente com
        # "not enough values to unpack (expected 3, got 2)" — porque o
        # próprio PaddleOCR tenta ler (h, w, c) = image.shape. Convertemos
        # aqui para 3 canais (sem alterar o conteúdo, só o formato) para
        # evitar esse erro.
        if image.ndim == 2:
            import cv2  # Fase 26a: import tardio -- ver comentário no topo do módulo.

            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        raw_results = self._ocr.predict(image)

        results: List[OCRResult] = []
        if not raw_results:
            return results

        for pagina in raw_results:
            # `.json` devolve um dicionário no mesmo formato salvo por
            # save_to_json(); em algumas versões vem embrulhado em {"res": {...}}.
            dados = pagina.json
            dados = dados.get("res", dados)

            textos = dados.get("rec_texts") or []
            confiancas = dados.get("rec_scores") or []
            boxes = dados.get("rec_boxes")

            for i, texto in enumerate(textos):
                if not texto:
                    continue

                confianca = float(confiancas[i]) if i < len(confiancas) else None

                box = None
                if boxes is not None and i < len(boxes):
                    x1, y1, x2, y2 = boxes[i]
                    box = [int(x1), int(y1), int(x2), int(y2)]

                results.append(
                    OCRResult(texto_original=texto, confianca=confianca, box=box)
                )

        return results


# ---------------------------------------------------------------------------
# Fábrica de motores: facilita trocar o motor padrão no futuro
# ---------------------------------------------------------------------------
def get_ocr_engine(name: str = "paddleocr") -> OCREngine:
    if name == "paddleocr":
        return PaddleOCREngine()
    raise ValueError(f"Motor de OCR desconhecido: {name}")


# ---------------------------------------------------------------------------
# Normalização de matrícula (sugestão, nunca sobrescreve o original)
# ---------------------------------------------------------------------------

# Confusões comuns entre letras e números no OCR de manuscritos
_CONFUSOES_COMUNS = {
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "S": "5",
    "s": "5",
    "B": "8",
}

# Caracteres que uma matrícula pode conter: dígitos + letras comumente
# confundidas com dígitos pelo OCR manuscrito.
_CARACTERES_DE_MATRICULA = set("0123456789OoIlSsB")


def parece_matricula(texto: str) -> bool:
    """
    Heurística simples para decidir se um trecho de OCR É CANDIDATO a ser
    uma matrícula, antes de sugerir qualquer normalização.

    Isso existe porque a folha tem várias colunas (data, nome, setor,
    motivo, gestor...) e o MVP ainda não sabe identificar em qual coluna
    cada texto está (isso é trabalho futuro, item 7 do escopo). Sem essa
    checagem, a substituição O->0, I->1, S->5, B->8 acabaria sendo aplicada
    também a nomes e motivos (ex.: "Costa" virando "C05ta"), o que não é
    aceitável.

    Critério (conservador, só isso): o texto, sem espaços, deve ter entre
    3 e 8 caracteres, ser composto só por dígitos e pelas letras
    confundíveis (O, I, l, S, B), e ter maioria de dígitos.
    """
    if not texto:
        return False

    t = texto.strip().replace(" ", "")
    if not (3 <= len(t) <= 8):
        return False
    if not all(ch in _CARACTERES_DE_MATRICULA for ch in t):
        return False

    digitos = sum(ch.isdigit() for ch in t)
    # Permite no máximo 2 caracteres "confundíveis" no meio de dígitos
    return digitos >= max(1, len(t) - 2)


def normalizar_matricula(texto_original: str) -> str:
    """
    Sugere uma versão normalizada de um texto QUE PARECE SER uma matrícula,
    aplicando apenas substituições de confusões conhecidas (ex.: O -> 0) e
    removendo espaços.

    NÃO inventa dígitos, NÃO sobrescreve o texto original (apenas devolve
    uma sugestão) e, principalmente, NÃO aplica a substituição em textos
    que não parecem matrícula (nomes, motivos, setores) — para esses casos,
    devolve o próprio texto original, sem alteração.

    Exemplo:
        "3O244"  -> "30244"      (parece matrícula: normaliza)
        "Costa"  -> "Costa"      (não parece matrícula: preserva)
    """
    if not texto_original:
        return ""

    texto = texto_original.strip()

    if not parece_matricula(texto):
        return texto

    texto_sem_espacos = texto.replace(" ", "")
    return "".join(_CONFUSOES_COMUNS.get(ch, ch) for ch in texto_sem_espacos)
