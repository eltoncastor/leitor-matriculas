"""
web/backend/estado.py

Fase 24a (Web MVP). Estado do backend, desenhado em torno de `lote_id` --
NUNCA um "lote atual" global solto no processo (o jeito como o Tkinter
funciona, com uma única `App()` viva por vez). É o que permite, numa
extensão futura, isolar lotes por usuário sem reescrever nenhum endpoint:
hoje `_lotes` é só um dicionário process-wide porque só uma pessoa usa por
vez (fora de escopo desta fase autenticar/isolar) -- mas cada chamada já
passa e resolve por `lote_id`, nunca por "o lote".

Engine de OCR e `DataManager` são COMPARTILHADOS por todo o processo (não
por lote) de propósito -- é o mesmo padrão do Tkinter, onde
`self._ocr_engine`/`self._data_manager` vivem pela sessão inteira da
`App()` e não são recriados a cada lote processado nela, só na abertura do
programa. Recarregar o modelo do PaddleOCR ou reler as 3 planilhas de
referência a cada lote seria caro e não corresponderia ao comportamento
real que este backend está reaproveitando.

`ContextoLote`, ao contrário, é por LOTE -- nunca pode atravessar dois
lotes diferentes (ver `parsing/contexto_lote.py` e o invariante documentado
em CLAUDE.md), então cada `LoteState` tem o seu próprio.

O pipeline em si (OCR -> parser -> classificação) é `leitor_matriculas.
pipeline` -- a MESMA função que `ui/app.py` chama agora (Fase 24a). Este
módulo só orquestra ONDE guardar o resultado e COMO um cliente HTTP
acompanha o progresso -- o equivalente, aqui, à fila+thread do Tkinter.
"""
import dataclasses
import logging
import os
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional

import cv2
import numpy as np

from leitor_matriculas import pipeline
from leitor_matriculas.dados.data_manager import DataManager
from leitor_matriculas.ocr import pdf_reader
from leitor_matriculas.ocr.engine import get_ocr_engine
from leitor_matriculas.parsing.contexto_lote import ContextoLote
from leitor_matriculas.parsing.registro_parser import verificar_contagem_posicoes

STATUS_PENDENTE = "pendente"
STATUS_PROCESSANDO = "processando"
STATUS_CONCLUIDO = "concluido"
STATUS_ERRO = "erro"

TIPO_PDF = "pdf"
TIPO_IMAGENS = "imagens"


@dataclasses.dataclass
class LoteState:
    id: str
    tipo: str  # TIPO_PDF | TIPO_IMAGENS
    caminhos: List[str]
    pasta_temp: str
    status: str = STATUS_PENDENTE
    etapa_atual: str = ""
    pagina_atual: int = 0
    paginas_processadas: int = 0
    total_paginas: Optional[int] = None
    erro_fatal: Optional[str] = None
    registros: List[dict] = dataclasses.field(default_factory=list)
    erros_paginas: List[dict] = dataclasses.field(default_factory=list)
    avisos_contagem: List[dict] = dataclasses.field(default_factory=list)
    avisos_descarte: List[dict] = dataclasses.field(default_factory=list)
    # Fase 24c: a foto de cada página, comprimida (JPEG), para a tela de
    # Revisão poder mostrá-la ao lado do formulário -- mesma ideia de
    # `App._miniaturas_por_pagina` no Tkinter (Fase 10), inclusive o
    # motivo de ser comprimida e não a matriz numpy crua: um lote de ~50
    # folhas em memória bruta passaria de 1 GB. Chave é o número da
    # página (`numero`, a posição física no lote -- mesma coluna "Página"
    # que os registros já usam), nunca a página DENTRO de um PDF
    # multi-arquivo (mesma distinção da Fase 14).
    miniaturas_por_pagina: Dict[int, bytes] = dataclasses.field(default_factory=dict)
    # Contexto do lote (Fase 9): nunca compartilhado entre lotes -- cada
    # LoteState tem o seu, criado junto com o lote e nunca reaproveitado.
    contexto_lote: ContextoLote = dataclasses.field(default_factory=ContextoLote)
    criado_em: float = dataclasses.field(default_factory=time.time)
    # Protege as listas/contadores acima contra a corrida entre a thread de
    # processamento (que escreve) e as requisições GET de status/registros
    # (que leem) -- mesmo motivo pelo qual o Tkinter nunca deixa a worker
    # thread tocar widgets diretamente, só que aqui os dois lados só
    # tocam dados Python puros.
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def status_publico(self) -> dict:
        with self.lock:
            return {
                "lote_id": self.id,
                "tipo": self.tipo,
                "status": self.status,
                "etapa_atual": self.etapa_atual,
                "pagina_atual": self.pagina_atual,
                "total_paginas": self.total_paginas,
                "paginas_processadas": self.paginas_processadas,
                "paginas_com_erro": len(self.erros_paginas),
                "total_registros": len(self.registros),
                "erro_fatal": self.erro_fatal,
            }

    def registros_publicos(self) -> List[dict]:
        with self.lock:
            # Cópia rasa: cada dict de registro não é mutado in-place por
            # este módulo depois de anexado (só por `confirmar_revisao_
            # manual`, que passa pelo router, nunca por aqui) -- copiar a
            # LISTA já basta para o cliente não ver o array crescendo no
            # meio da leitura.
            return list(self.registros)

    def obter_miniatura(self, numero_pagina: int) -> Optional[bytes]:
        with self.lock:
            return self.miniaturas_por_pagina.get(numero_pagina)


_lotes: Dict[str, LoteState] = {}
_lotes_trava = threading.Lock()

_engine_trava = threading.Lock()
_ocr_engine = None
_data_manager: Optional[DataManager] = None


def _pasta_dados_ao_lado_do_executavel() -> Optional[str]:
    """
    Sub-fase 25b (empacotamento com PyInstaller): `DataManager()` sem
    argumento resolve `dados/` a partir do PRÓPRIO `__file__` de
    `data_manager.py`, três níveis acima (ver o docstring dele) -- isso
    continua correto rodando `python web/backend/main.py` direto do
    repositório, mas quebra (ou, pior, resolve para um lugar ERRADO sem
    avisar) dentro de um `.exe` empacotado:

      - em `--onedir`, o `__file__` sintético que o PyInstaller atribui ao
        módulo congelado ainda aponta para dentro da PASTA do próprio
        pacote (`sys._MEIPASS`, que em onedir É a pasta onde o `.exe`
        está) -- então o cálculo "três níveis acima" até funcionaria por
        acidente, mas depende de detalhe de implementação do PyInstaller,
        não de nada garantido;
      - em `--onefile`, `sys._MEIPASS` é uma pasta TEMPORÁRIA nova a cada
        execução (`%TEMP%\\_MEIxxxxxx`) -- gravar/ler `dados/` ali seria
        efetivamente `dados/` sumir a cada reinício, o oposto do pedido
        desta sub-fase ("editável pelo usuário sem reempacotar").

    A forma robusta e igual nos dois modos é `os.path.dirname(sys.
    executable)` -- SEMPRE a pasta onde o `.exe` real está, nos dois casos
    (nunca a pasta temporária de extração). Fora de um build congelado
    (`sys.frozen` ausente -- o caso de sempre, rodando via `python`),
    devolve `None` e `DataManager()` resolve exatamente como sempre
    resolveu -- este ajuste é invisível fora do `.exe`.
    """
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "dados")
    return None


def obter_data_manager() -> DataManager:
    """Instância única por processo -- ver docstring do módulo."""
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager(pasta_dados=_pasta_dados_ao_lado_do_executavel())
    return _data_manager


def obter_ocr_engine():
    """Instância única por processo, carregada sob demanda na primeira
    página que qualquer lote processar (mesmo comportamento de
    `App._processar_uma_pagina`: o modelo só é carregado quando a
    primeira folha de verdade chega)."""
    global _ocr_engine
    with _engine_trava:
        if _ocr_engine is None:
            _ocr_engine = get_ocr_engine("paddleocr")
        return _ocr_engine


def criar_lote(tipo: str, caminhos: List[str], pasta_temp: str) -> LoteState:
    lote_id = uuid.uuid4().hex
    estado = LoteState(id=lote_id, tipo=tipo, caminhos=caminhos, pasta_temp=pasta_temp)
    with _lotes_trava:
        _lotes[lote_id] = estado
    return estado


def obter_lote(lote_id: str) -> Optional[LoteState]:
    with _lotes_trava:
        return _lotes.get(lote_id)


def _ler_imagem(caminho: str) -> np.ndarray:
    """Mesma leitura que `ui/app.py::_ler_imagem` (via `np.fromfile` +
    `cv2.imdecode`, que lida com acentos no caminho no Windows -- `cv2.
    imread` não). Não importado de lá de propósito: nada no backend web
    depende de `leitor_matriculas.ui` (via de mão única do projeto -- ver
    CLAUDE.md, "ui/app.py é o único módulo autorizado a coordenar os
    outros"). É I/O trivial, não lógica de negócio; duplicar 4 linhas é
    mais barato que criar uma dependência na direção errada."""
    dados = np.fromfile(caminho, dtype=np.uint8)
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError(f"Não foi possível abrir a imagem: {caminho}")
    return imagem


# Mesmos valores de `ui/app.py` (Fase 10) -- a foto é comodidade da
# revisão, não dado; comprimir demais perderia legibilidade do
# manuscrito, comprimir de menos custaria a mesma explosão de RAM que a
# Fase 10 já mediu e evitou no Tkinter.
LARGURA_MAXIMA_MINIATURA = 1500
QUALIDADE_MINIATURA = 85


def _comprimir_para_miniatura(imagem_bgr) -> Optional[bytes]:
    """Mesma lógica de `ui/app.py::_comprimir_para_miniatura` (Fase 10),
    duplicada aqui pelo mesmo motivo que `_ler_imagem` acima -- é I/O/
    processamento de imagem trivial, não lógica de negócio, e nada no
    backend web pode importar de dentro de `ui/`. Nunca lança: a foto é
    comodidade da revisão, uma falha aqui não pode derrubar o
    processamento da página."""
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


def _informar_etapa(estado: LoteState):
    def _callback(texto: str):
        with estado.lock:
            estado.etapa_atual = texto
    return _callback


def _processar_pagina_e_registrar(estado: LoteState, numero: int, imagem_bgr, origem_erro_prefix: Optional[str] = None):
    """Equivalente a `App._processar_item` (o consumo da fila) + `App.
    _adicionar_registros` combinados -- só que sem fila: escreve direto no
    LoteState, sob lock. Isola a falha de UMA página (nunca aborta o
    lote), mesmo padrão da Fase 7/14."""
    engine = obter_ocr_engine()
    imagem_processada, registros, erro = pipeline.processar_uma_pagina(
        imagem_bgr, engine, informar_etapa=_informar_etapa(estado)
    )
    if erro:
        mensagem = f"{origem_erro_prefix}: {erro}" if origem_erro_prefix else erro
        with estado.lock:
            estado.registros.append(pipeline.registro_erro_pagina(numero, mensagem))
            estado.erros_paginas.append({"pagina": numero, "mensagem": mensagem})
            estado.pagina_atual = numero
            estado.paginas_processadas += 1
        return

    # Foto da página para a tela de Revisão -- só no caminho de sucesso,
    # mesma condição de `App._processar_item` (Fase 10): uma página que
    # falhou pode nem ter uma imagem válida para comprimir. Fora do
    # `with estado.lock` de propósito -- comprimir/reamostrar é CPU-bound
    # e não precisa do lock, só a escrita no dict abaixo precisa.
    miniatura = _comprimir_para_miniatura(imagem_bgr)
    if miniatura is not None:
        with estado.lock:
            estado.miniaturas_por_pagina[numero] = miniatura

    # Contexto do lote ANTES de classificar (Fase 9): mesma ordem de
    # `App._adicionar_registros`.
    with estado.lock:
        for registro in registros:
            campo_data = registro.campos.get("data")
            estado.contexto_lote.registrar_data(campo_data.texto if campo_data else "")

    dm = obter_data_manager()
    for registro in registros:
        registro_exportacao, aviso_sem_matricula = pipeline.montar_registro_exportacao(
            registro, numero, dm, estado.contexto_lote,
        )
        with estado.lock:
            estado.registros.append(registro_exportacao)
            if aviso_sem_matricula:
                estado.avisos_descarte.append({"pagina": numero, "mensagem": aviso_sem_matricula})

    aviso_contagem = verificar_contagem_posicoes(len(registros))
    with estado.lock:
        if aviso_contagem:
            estado.avisos_contagem.append({"pagina": numero, "mensagem": aviso_contagem})
        estado.pagina_atual = numero
        estado.paginas_processadas += 1


def _processar_lote_pdf(estado: LoteState):
    caminho_pdf = estado.caminhos[0]
    nome_pdf = os.path.basename(caminho_pdf)
    total = pdf_reader.contar_paginas(caminho_pdf)
    with estado.lock:
        estado.total_paginas = total

    for pagina_pdf in pdf_reader.iterar_paginas(caminho_pdf):
        numero = pagina_pdf.numero
        if pagina_pdf.erro:
            mensagem = f"Falha ao renderizar a página {numero} de '{nome_pdf}': {pagina_pdf.erro}"
            with estado.lock:
                estado.registros.append(pipeline.registro_erro_pagina(numero, mensagem))
                estado.erros_paginas.append({"pagina": numero, "mensagem": mensagem})
                estado.pagina_atual = numero
                estado.paginas_processadas += 1
            continue
        _processar_pagina_e_registrar(
            estado, numero, pagina_pdf.imagem,
            origem_erro_prefix=f"página {numero} de '{nome_pdf}'",
        )


def _processar_lote_imagens(estado: LoteState):
    total = len(estado.caminhos)
    with estado.lock:
        estado.total_paginas = total

    for indice, caminho in enumerate(estado.caminhos, start=1):
        nome_arquivo = os.path.basename(caminho)
        try:
            imagem_bgr = _ler_imagem(caminho)
        except Exception as exc:
            mensagem = f"Falha ao abrir '{nome_arquivo}': {exc}"
            with estado.lock:
                estado.registros.append(pipeline.registro_erro_pagina(indice, mensagem))
                estado.erros_paginas.append({"pagina": indice, "mensagem": mensagem})
                estado.pagina_atual = indice
                estado.paginas_processadas += 1
            continue
        _processar_pagina_e_registrar(estado, indice, imagem_bgr, origem_erro_prefix=f"'{nome_arquivo}'")


def processar_lote(lote_id: str) -> None:
    """
    Roda numa thread separada (chamada por `rotas/lotes.py` via
    `threading.Thread`), mesmo motivo do worker do Tkinter: o OCR é lento
    (~40 s/folha) e uma requisição HTTP não pode ficar bloqueada esperando
    o lote inteiro. Uma falha inesperada aqui (fora do que `pipeline.
    processar_uma_pagina` já isola por página) marca o lote inteiro como
    STATUS_ERRO -- equivalente a `("erro_fatal", ...)` na fila do Tkinter.
    """
    estado = obter_lote(lote_id)
    if estado is None:
        return
    with estado.lock:
        estado.status = STATUS_PROCESSANDO
    try:
        if estado.tipo == TIPO_PDF:
            _processar_lote_pdf(estado)
        else:
            _processar_lote_imagens(estado)
        with estado.lock:
            estado.status = STATUS_CONCLUIDO
            estado.etapa_atual = ""
    except Exception as exc:
        logging.exception("Falha inesperada processando o lote %s", lote_id)
        with estado.lock:
            estado.status = STATUS_ERRO
            estado.erro_fatal = str(exc)
