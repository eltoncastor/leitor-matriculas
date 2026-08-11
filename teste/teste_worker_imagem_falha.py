"""
teste/teste_worker_imagem_falha.py

FASE FINAL -- estabilizacao cirurgica: garante que _worker_imagem (ui.py)
nunca deixa a UI presa em "Processando..." quando algo falha durante a
inicializacao/execucao do OCR de uma imagem unica.

Antes da correcao, _worker_imagem nao tinha nenhum try/except: qualquer
excecao que escapasse de _processar_uma_pagina (ex.: get_ocr_engine
lancando algo diferente de ImportError) matava a thread em silencio, sem
nunca colocar ("fim", ...) na fila -- self._processando ficava True para
sempre e os botoes permaneciam desabilitados.

Usa PaddleOCR MOCKADO. Roda sob Xvfb (Linux/CI) ou display nativo
(Windows).
"""
import sys, time, threading, tempfile, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, cv2
from unittest.mock import patch, MagicMock
from ui import App, _ler_imagem

_tmp_dir = tempfile.mkdtemp()
_caminho_img = os.path.join(_tmp_dir, 'teste_falha.jpg')
cv2.imwrite(_caminho_img, np.full((100, 300, 3), 255, dtype=np.uint8))


def _rodar_worker_imagem(app, imagem):
    app._iniciar_processamento("...")
    threading.Thread(target=app._worker_imagem, args=(imagem,), daemon=True).start()
    app.after(100, app._verificar_fila)
    for _ in range(200):
        app.update()
        time.sleep(0.05)
        if not app._processando:
            break
    else:
        raise AssertionError("_worker_imagem nunca terminou -- UI ficaria presa em 'Processando...'")


def _checar_ui_recuperada(app, m_err):
    assert app._processando is False, "self._processando deveria voltar a False"
    assert str(app.btn_imagem.cget('state')) == 'normal', "botao 'Selecionar imagem' deveria voltar a ficar habilitado"
    assert str(app.btn_pdf.cget('state')) == 'normal', "botao 'Selecionar PDF' deveria voltar a ficar habilitado"
    assert str(app.btn_limpar.cget('state')) == 'normal', "botao 'Limpar resultados' deveria voltar a ficar habilitado"
    assert m_err.called, "messagebox.showerror deveria ter sido chamado para informar o erro"
    assert "Erro" in app.lbl_status.cget('text')


# ---------------------------------------------------------------------
# Caso 1: excecao inesperada em qualquer ponto de _processar_uma_pagina
# (simula, por exemplo, get_ocr_engine falhando com algo != ImportError,
# que _processar_uma_pagina nao blinda internamente).
# ---------------------------------------------------------------------
print("=== Caso 1: excecao generica escapando de _processar_uma_pagina ===")
with patch('ui.messagebox.showerror') as m_err, patch('ui.messagebox.showwarning'):
    app = App()
    imagem = _ler_imagem(_caminho_img)
    with patch.object(App, '_processar_uma_pagina', side_effect=RuntimeError("falha simulada de inicializacao do OCR")):
        _rodar_worker_imagem(app, imagem)
    _checar_ui_recuperada(app, m_err)
    titulo, mensagem = m_err.call_args[0]
    assert "falha simulada de inicializacao do OCR" in mensagem
    print("OK: excecao generica nao trava a UI; botoes e status restaurados, erro informado")
    app.destroy()


# ---------------------------------------------------------------------
# Caso 2: get_ocr_engine falha com uma excecao que NAO e ImportError --
# _processar_uma_pagina so blinda ImportError nesse ponto; o worker
# precisa capturar o resto.
# ---------------------------------------------------------------------
print("=== Caso 2: get_ocr_engine falha com excecao != ImportError ===")
with patch('ui.messagebox.showerror') as m_err, patch('ui.messagebox.showwarning'):
    app = App()
    imagem = _ler_imagem(_caminho_img)
    app._ocr_engine = None  # força _processar_uma_pagina a tentar recriar o engine
    with patch('ui.get_ocr_engine', side_effect=RuntimeError("modelo do PaddleOCR nao pode ser carregado")):
        _rodar_worker_imagem(app, imagem)
    _checar_ui_recuperada(app, m_err)
    print("OK: falha na criacao do engine (excecao nao-ImportError) nao trava a UI")
    app.destroy()


# ---------------------------------------------------------------------
# Caso 3: fluxo normal (sem falha) continua funcionando -- garante que a
# correcao nao alterou o caminho feliz.
# ---------------------------------------------------------------------
print("=== Caso 3: fluxo normal (sem falha) continua igual ===")
with patch('ui.messagebox.showerror') as m_err, patch('ui.messagebox.showwarning'):
    app = App()
    imagem = _ler_imagem(_caminho_img)
    fake_engine = MagicMock()
    fake_engine.recognize.return_value = []
    app._ocr_engine = fake_engine
    _rodar_worker_imagem(app, imagem)
    assert app._processando is False
    assert str(app.btn_imagem.cget('state')) == 'normal'
    assert not m_err.called, "nao deveria ter havido erro no fluxo normal"
    assert app._paginas_processadas == 1
    print("OK: fluxo normal (sem falha) nao regrediu")
    app.destroy()

import shutil
shutil.rmtree(_tmp_dir, ignore_errors=True)
print("TESTE WORKER IMAGEM (CAMINHOS DE FALHA): OK")
