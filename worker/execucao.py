"""
worker/execucao.py

Fase 26c. O laço principal do Worker: reivindica um Job, baixa os
arquivos, roda o MESMO pipeline (`leitor_matriculas.pipeline.
processar_uma_pagina`) que a VPS rodava internamente antes da Fase 26, e
entrega o resultado pelo protocolo `/api/worker/*`. Nenhuma regra de
negócio nova -- é a metade PESADA que `web/backend/produtor_ocr.py` já
isolava (Sub-fase 26a), só que falando HTTP em vez de escrever direto num
`LoteState` local.

`_ler_imagem`/`_comprimir_para_miniatura` são deliberadamente uma cópia
de `web/backend/produtor_ocr.py` -- mesma decisão, mesma justificativa
que aquele módulo já documenta para `estado.py::_ler_imagem`: importar de
`web.backend.*` arrastaria `estado`/`armazenamento`, que escrevem no
disco DA VPS -- o Worker não deve tocar em nenhum dos dois. Duplicar ~20
linhas de I/O trivial é mais barato que essa dependência na direção
errada.

Uma falha de UM Job nunca derruba o processo do Worker -- é isolada em
`processar_job` e reportada por `POST .../erro`; o laço em `rodar`
simplesmente segue para o próximo `GET /jobs/next`.
"""
import logging
import os
import shutil
import tempfile
import time
from typing import Callable, List, Optional, Set

import cv2
import numpy as np

from leitor_matriculas import pipeline
from leitor_matriculas.ocr import pdf_reader
from leitor_matriculas.ocr.engine import get_ocr_engine

from .cliente import ClienteWorker, ErroAutenticacao, ErroCliente, ErroConflito, JobReivindicado
from .heartbeat import Heartbeat

_LOG = logging.getLogger("worker.execucao")

# Mesmos valores de `web/backend/produtor_ocr.py` (Fase 26a, que por sua
# vez preserva os de `ui/app.py`, Fase 10) -- a foto é comodidade da
# revisão, não dado.
LARGURA_MAXIMA_MINIATURA = 1500
QUALIDADE_MINIATURA = 85

_engine_cache = None


def _obter_engine():
    """Uma instância por PROCESSO do Worker -- mesmo padrão de `estado.
    obter_ocr_engine` na VPS (Fase 24a): recarregar o modelo do PaddleOCR
    a cada Job seria caro e não corresponde a nada que a operação real
    precise."""
    global _engine_cache
    if _engine_cache is None:
        _engine_cache = get_ocr_engine("paddleocr")
    return _engine_cache


def _ler_imagem(caminho: str) -> np.ndarray:
    """Mesma leitura de `estado.py`/`ui/app.py` (via `np.fromfile` +
    `cv2.imdecode`, que lida com acentos no caminho no Windows -- `cv2.
    imread` não)."""
    dados = np.fromfile(caminho, dtype=np.uint8)
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError(f"Não foi possível abrir a imagem: {caminho}")
    return imagem


def _comprimir_para_miniatura(imagem_bgr) -> Optional[bytes]:
    """Nunca lança: a foto é comodidade da revisão, uma falha aqui não
    pode custar o resultado do OCR daquela página."""
    try:
        altura, largura = imagem_bgr.shape[:2]
        maior = max(altura, largura)
        if maior > LARGURA_MAXIMA_MINIATURA:
            fator = LARGURA_MAXIMA_MINIATURA / maior
            imagem_bgr = cv2.resize(
                imagem_bgr, (int(largura * fator), int(altura * fator)), interpolation=cv2.INTER_AREA,
            )
        ok, buffer = cv2.imencode(".jpg", imagem_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), QUALIDADE_MINIATURA])
        return buffer.tobytes() if ok else None
    except Exception:
        logging.exception("[Worker] falha ao preparar a miniatura (a revisão segue sem a foto)")
        return None


def _processar_uma_pagina(cliente: ClienteWorker, job: JobReivindicado, numero: int, imagem_bgr) -> None:
    """
    PUT da miniatura ANTES do POST do resultado -- ordem que evita a
    corrida documentada na Sub-fase 26b: entregar o resultado da ÚLTIMA
    página de um Job pode fazer a VPS concluí-lo (e liberar a posse)
    antes de uma chamada seguinte deste mesmo Worker executar.
    """
    def _informar(texto: str) -> None:
        try:
            cliente.progresso(job.lote_id, job.tentativa, etapa_atual=texto)
        except ErroCliente:
            pass  # puramente informativo -- nunca aborta a página por isso

    _imagem_processada, registros, erro = pipeline.processar_uma_pagina(
        imagem_bgr, _obter_engine(), informar_etapa=_informar
    )
    if erro:
        cliente.entregar_pagina(job.lote_id, numero, job.tentativa, erro=erro, fase_erro="pipeline", registros=[])
        return

    miniatura = _comprimir_para_miniatura(imagem_bgr)
    if miniatura is not None:
        try:
            cliente.entregar_miniatura(job.lote_id, numero, job.tentativa, miniatura)
        except ErroCliente as exc:
            _LOG.warning("[Worker] falha ao entregar a miniatura da página %s (segue sem a foto): %s", numero, exc)

    resultado = cliente.entregar_pagina(
        job.lote_id, numero, job.tentativa, erro=None, fase_erro=None,
        registros=[registro.como_dicionario() for registro in registros],
    )
    if resultado == "obsoleto":
        # Este Worker já não é mais dono do Job (lease expirado, outra
        # tentativa assumiu) -- continuar OCR-ando páginas que ninguém
        # mais vai aplicar seria desperdício puro. `ErroConflito` propaga
        # por `_processar_pdf`/`_processar_imagens` até `processar_job`,
        # que já sabe abortar limpo nesse caso (ver mais abaixo).
        raise ErroConflito(f"tentativa {job.tentativa} não é mais dona do lote {job.lote_id}")


def _paginas_prontas(job: JobReivindicado) -> Set[int]:
    """
    Quais páginas JÁ têm OCR gravado na VPS -- para PULAR na retomada
    (job.paginas_pendentes é o complemento, ver `web/backend/estado.py::
    paginas_pendentes`). Devolve vazio para um Job novo (nada pronto
    ainda) OU quando o total ainda não é conhecido (aí não há nada a
    calcular -- processa tudo que vier).
    """
    if job.total_paginas is None:
        return set()
    todas = set(range(1, job.total_paginas + 1))
    pendentes = set(job.paginas_pendentes) if job.paginas_pendentes else todas
    return todas - pendentes


def _processar_pdf(cliente: ClienteWorker, job: JobReivindicado, caminho_pdf: str) -> None:
    """
    `job.total_paginas` já vem preenchido no `claim` na quase totalidade
    dos casos -- a VPS calcula sozinha (`estado._descobrir_total_
    paginas`), contra a cópia que ELA recebeu no upload, antes de
    qualquer Worker existir. O Worker não precisa (nem chama)
    `pdf_reader.contar_paginas` por conta própria.
    """
    prontas = _paginas_prontas(job)
    for pagina_pdf in pdf_reader.iterar_paginas(caminho_pdf):
        if pagina_pdf.numero in prontas:
            continue
        if pagina_pdf.erro:
            cliente.entregar_pagina(job.lote_id, pagina_pdf.numero, job.tentativa,
                                    erro=pagina_pdf.erro, fase_erro="renderizacao", registros=[])
            continue
        _processar_uma_pagina(cliente, job, pagina_pdf.numero, pagina_pdf.imagem)


def _processar_imagens(cliente: ClienteWorker, job: JobReivindicado, caminhos: List[str]) -> None:
    prontas = _paginas_prontas(job)
    for indice, caminho in enumerate(caminhos, start=1):
        if indice in prontas:
            continue
        try:
            imagem = _ler_imagem(caminho)
        except Exception as exc:
            cliente.entregar_pagina(job.lote_id, indice, job.tentativa,
                                    erro=str(exc), fase_erro="leitura", registros=[])
            continue
        _processar_uma_pagina(cliente, job, indice, imagem)


def processar_job(cliente: ClienteWorker, job: JobReivindicado) -> None:
    """
    Processa um Job do início ao fim: baixa os arquivos, roda o OCR
    página a página, sinaliza conclusão. Isola a própria falha -- uma
    exceção aqui (documento inteiro que não abre) vira `POST .../erro`,
    nunca propaga para `rodar` (ver mais abaixo). Temporários sempre
    apagados ao final, inclusive em erro.
    """
    pasta_temp = tempfile.mkdtemp(prefix="worker_job_")
    try:
        caminhos = []
        for indice, nome in enumerate(job.nomes_arquivos):
            destino = os.path.join(pasta_temp, nome)
            cliente.baixar_arquivo(job.lote_id, indice, job.tentativa, destino)
            caminhos.append(destino)

        if job.tipo == "pdf":
            _processar_pdf(cliente, job, caminhos[0])
        else:
            _processar_imagens(cliente, job, caminhos)

        cliente.concluir(job.lote_id, job.tentativa)
    except (ErroAutenticacao, ErroConflito):
        raise  # quem chama decide: auth -> parar; conflito -> este Worker já não é mais dono
    except Exception as exc:
        _LOG.exception("[Worker] falha processando o lote %s", job.lote_id)
        try:
            cliente.erro_de_documento(job.lote_id, job.tentativa, str(exc))
        except ErroCliente:
            pass  # nem isso foi possível -- o lease vai expirar e o Job volta pra fila sozinho
    finally:
        shutil.rmtree(pasta_temp, ignore_errors=True)


def rodar(cliente: ClienteWorker, heartbeat: Heartbeat, intervalo_polling_s: float,
          deve_continuar: Callable[[], bool]) -> None:
    """
    Laço principal, chamado por `worker/__main__.py`. `deve_continuar` é
    injetada (em vez de um `while True` fixo) para permitir um número
    finito de voltas em teste, e para o ponto de entrada real poder
    encerrar de forma limpa (Ctrl+C) sem um `sys.exit` no meio do laço.

    Backoff exponencial simples só na perda de CONEXÃO (servidor fora do
    ar) -- nunca em falha de UM Job, que já é isolada em `processar_job`.
    """
    atraso_reconexao_s = intervalo_polling_s
    atraso_maximo_s = 60.0

    while deve_continuar():
        try:
            lote_id = cliente.proximo_job()
        except ErroAutenticacao as exc:
            _LOG.error("[Worker] configuração inválida (%s) -- parando", exc)
            return
        except ErroCliente as exc:
            _LOG.warning("[Worker] sem conexão com o servidor (%s) -- tentando de novo em %.0fs",
                        exc, atraso_reconexao_s)
            time.sleep(atraso_reconexao_s)
            atraso_reconexao_s = min(atraso_reconexao_s * 2, atraso_maximo_s)
            continue

        atraso_reconexao_s = intervalo_polling_s  # sucesso: reseta o backoff

        if lote_id is None:
            time.sleep(intervalo_polling_s)
            continue

        try:
            job = cliente.reivindicar(lote_id)
        except ErroConflito:
            _LOG.info("[Worker] outro Worker chegou primeiro no lote %s", lote_id)
            continue
        except ErroAutenticacao as exc:
            _LOG.error("[Worker] configuração inválida (%s) -- parando", exc)
            return
        except ErroCliente as exc:
            _LOG.warning("[Worker] falha ao reivindicar o lote %s: %s", lote_id, exc)
            time.sleep(intervalo_polling_s)
            continue

        _LOG.info("[Worker] Job recebido: lote %s (tentativa %s)", job.lote_id, job.tentativa)
        heartbeat.definir_job(job.lote_id, job.tentativa)
        try:
            processar_job(cliente, job)
            _LOG.info("[Worker] Job concluído: lote %s", job.lote_id)
        except ErroAutenticacao as exc:
            _LOG.error("[Worker] configuração inválida (%s) -- parando", exc)
            return
        except ErroConflito:
            _LOG.info("[Worker] perdi a posse do lote %s no meio do trabalho -- seguindo em frente", job.lote_id)
        finally:
            heartbeat.limpar_job()
