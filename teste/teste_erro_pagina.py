"""
teste/teste_erro_pagina.py

Teste de que uma pagina de PDF com falha de renderizacao nao interrompe o
lote (as demais paginas continuam sendo processadas), e do botao Limpar.
Usa PaddleOCR MOCKADO. Roda sob Xvfb.
"""
import sys, time, threading, tempfile, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pymupdf as fitz
from unittest.mock import patch, MagicMock
from leitor_matriculas.ui.app import App
from leitor_matriculas.ocr.engine import OCRResult

tmp = tempfile.mkdtemp()
caminho = os.path.join(tmp, 'mes.pdf')
doc = fitz.open()
for i in range(3):
    doc.new_page(width=400, height=500)
doc.save(caminho); doc.close()

original_get_pixmap = fitz.Page.get_pixmap
def get_pixmap_falha_pagina2(self, *a, **kw):
    if self.number == 1:
        raise RuntimeError("falha simulada")
    return original_get_pixmap(self, *a, **kw)

with patch('leitor_matriculas.ui.app.messagebox.showerror'), patch('leitor_matriculas.ui.app.messagebox.showwarning') as m_warn:
    app = App()
    fake = MagicMock()
    fake.recognize.return_value = []
    app._ocr_engine = fake

    with patch.object(fitz.Page, 'get_pixmap', get_pixmap_falha_pagina2):
        app._iniciar_processamento("...")
        threading.Thread(target=app._worker_pdf, args=(caminho,), daemon=True).start()
        app.after(100, app._verificar_fila)
        for _ in range(400):
            app.update(); time.sleep(0.05)
            if not app._processando: break

    print("paginas_processadas:", app._paginas_processadas)
    print("paginas_com_erro:", app._paginas_com_erro)
    print("erros_paginas:", app._erros_paginas)
    assert app._paginas_processadas == 3
    assert app._paginas_com_erro == 1
    assert app._erros_paginas[0]['pagina'] == 2
    assert 'falha simulada' in app._erros_paginas[0]['mensagem']

    # o registro de erro deve estar na lista de exportacao com status ERRO
    erros_export = [r for r in app._registros_exportacao if r['status'] == 'ERRO']
    assert len(erros_export) == 1
    print("OK: pagina com erro nao derrubou o lote, e foi registrada com status ERRO")

    app._mostrar_erros_paginas()
    assert m_warn.called
    print("OK: botao 'Ver erros de pagina' mostra o detalhe")

    # testa Limpar
    app._on_limpar()
    assert len(app.tabela.get_children()) == 0
    assert app._registros_exportacao == []
    assert app._erros_paginas == []
    assert str(app.btn_salvar.cget('state')) == 'disabled'
    print("OK: Limpar resultados reseta tudo")

    app.destroy()
print("TESTE ERRO DE PAGINA + LIMPAR: OK")
