"""
teste/teste_ui_integracao.py

Teste de integracao ponta-a-ponta da interface: imagem unica + PDF multi-
pagina + exportacao XLSX + revisao manual. Usa PaddleOCR MOCKADO (nao o
real). No Linux/CI roda sob Xvfb (display virtual); no Windows usa o
display nativo, sem precisar de nada extra.

Uso:
    xvfb-run -a python3 teste/teste_ui_integracao.py   (Linux/CI)
    python teste\\teste_ui_integracao.py                 (Windows)
"""
import time, os, sys, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, cv2
from unittest.mock import patch, MagicMock
import pymupdf as fitz

from ui import App, _ler_imagem
from ocr_engine import OCRResult

# --- fixtures: imagem sintética de teste ---
# Usa tempfile em vez de um caminho POSIX fixo ("/tmp/...") -- em Windows
# isso não é garantido existir/ser gravável, diferente de tempfile, que
# sempre resolve para uma pasta temporária válida na plataforma atual.
_tmp_dir_img = tempfile.mkdtemp()
_caminho_img_teste = os.path.join(_tmp_dir_img, 'teste_ui_img.jpg')
img = np.full((200, 900, 3), 255, dtype=np.uint8)
cv2.imwrite(_caminho_img_teste, img)

# --- resultados de OCR simulados (cabecalho + 2 registros, layout do teste_registro_parser) ---
COL_DATA, COL_HORA, COL_NOME, COL_MAT, COL_SETOR, COL_MOT, COL_GESTOR = 60,160,280,450,560,700,880
def r(t,x1,y1,x2,y2,c=0.9): return OCRResult(texto_original=t, confianca=c, box=[x1,y1,x2,y2])
def cabecalho(y1=10,y2=30):
    return [r("DATA",COL_DATA-20,y1,COL_DATA+20,y2), r("HORA",COL_HORA-20,y1,COL_HORA+20,y2),
            r("NOME",COL_NOME-25,y1,COL_NOME+25,y2), r("MATRÍCULA",COL_MAT-35,y1,COL_MAT+35,y2),
            r("SETOR",COL_SETOR-25,y1,COL_SETOR+25,y2), r("MOTIVO",COL_MOT-25,y1,COL_MOT+25,y2),
            r("RESPONSÁVEL",COL_GESTOR-40,y1,COL_GESTOR+40,y2)]
def linha(y1,y2,data,hora,nome,mat,setor,mot,gestor,conf_mat=0.9):
    return [r(data,COL_DATA-15,y1,COL_DATA+15,y2), r(hora,COL_HORA-15,y1,COL_HORA+15,y2),
            r(nome,COL_NOME-25,y1,COL_NOME+25,y2), r(mat,COL_MAT-20,y1,COL_MAT+20,y2,conf_mat),
            r(setor,COL_SETOR-20,y1,COL_SETOR+20,y2), r(mot,COL_MOT-25,y1,COL_MOT+25,y2),
            r(gestor,COL_GESTOR-30,y1,COL_GESTOR+30,y2)]

resultados_ocr = cabecalho() + linha(40,60,"23.04.2026","11:05","Fulano","28972","TI","RH","Gestor X") \
                              + linha(70,90,"23.04.2026","11:10","Beltrano","99999","RH","ADM","Gestor Y", conf_mat=0.5)

with patch('ui.messagebox.showerror') as m_err, patch('ui.messagebox.showinfo') as m_info, \
     patch('ui.messagebox.showwarning') as m_warn:
    app = App()
    fake_engine = MagicMock()
    fake_engine.recognize.return_value = resultados_ocr
    app._ocr_engine = fake_engine

    # -------- fluxo imagem única --------
    app._imagem_original = _ler_imagem(_caminho_img_teste)
    app._arquivo_atual = 'teste.jpg'
    app._iniciar_processamento("...")
    import threading
    threading.Thread(target=app._worker_imagem, args=(app._imagem_original,), daemon=True).start()
    app.after(100, app._verificar_fila)
    for _ in range(60):
        app.update(); time.sleep(0.05)
        if not app._processando: break

    linhas = app.tabela.get_children()
    print("Linhas na tabela (imagem única):", len(linhas))
    assert len(linhas) == 2
    valores = [app.tabela.item(i)['values'] for i in linhas]
    print(valores[0]); print(valores[1])
    # Ordem atual da tabela: pagina(0), status(1), data(2), hora(3), matricula(4), ...
    assert '28972' in str(valores[0][4])
    assert 'CONFIRMADO' not in valores[1][1]  # matricula 99999 nao existe na base -> revisao (sem base carregada tb cai em revisao)
    assert app._contador_confirmados + app._contador_revisao == 2
    print("Confirmados:", app._contador_confirmados, "Revisao:", app._contador_revisao)
    assert str(app.btn_salvar.cget('state')) == 'normal'

    # -------- fluxo PDF (2 páginas) --------
    tmp = tempfile.mkdtemp()
    caminho_pdf = os.path.join(tmp, 'mes.pdf')
    doc = fitz.open()
    for i in range(2):
        doc.new_page(width=600, height=800)
    doc.save(caminho_pdf); doc.close()

    app._arquivo_atual = 'mes.pdf'
    app._iniciar_processamento("...")
    threading.Thread(target=app._worker_pdf, args=(caminho_pdf,), daemon=True).start()
    app.after(100, app._verificar_fila)
    for _ in range(600):
        app.update(); time.sleep(0.05)
        if not app._processando: break
    else:
        print("AVISO: loop esgotado sem terminar")

    print("Paginas processadas total:", app._paginas_processadas, "erros:", app._erros_paginas, "paginas_com_erro:", app._paginas_com_erro)
    assert app._paginas_processadas == 3  # 1 imagem + 2 paginas pdf
    linhas2 = app.tabela.get_children()
    print("Linhas na tabela apos PDF:", len(linhas2))
    assert len(linhas2) == 6  # 2 (imagem) + 2 (pagina1 pdf) + 2 (pagina2 pdf), mesmo mock em todas

    # -------- salvar XLSX --------
    saida_xlsx = os.path.join(tmp, 'saida.xlsx')
    with patch('ui.filedialog.asksaveasfilename', return_value=saida_xlsx):
        app._on_salvar()
    assert m_info.called
    assert os.path.isfile(saida_xlsx)
    import openpyxl
    wb = openpyxl.load_workbook(saida_xlsx)
    print("Abas do XLSX:", wb.sheetnames)
    assert wb.sheetnames == ["Liberações","Revisão","Resumo"]
    print("Linhas Liberacoes:", wb["Liberações"].max_row)

    # -------- revisao manual --------
    print("Botao revisao:", app.btn_revisao.cget('text'))
    app._abrir_revisao()
    # pega a janela Toplevel criada
    toplevels = [w for w in app.winfo_children() if isinstance(w, __import__('tkinter').Toplevel)]
    assert toplevels, "janela de revisao nao foi criada"
    janela = toplevels[0]
    tabela_rev = [w for w in janela.winfo_children() if isinstance(w, __import__('tkinter').ttk.Treeview)][0]
    itens = tabela_rev.get_children()
    print("Itens pendentes na revisao:", len(itens))
    assert len(itens) == app._contador_revisao

    revisao_antes = app._contador_revisao
    confirmados_antes = app._contador_confirmados
    tabela_rev.selection_set(itens[0])
    tabela_rev.event_generate("<<TreeviewSelect>>")
    app.update()

    import tkinter as _tk
    frame_edicao = [w for w in janela.winfo_children() if isinstance(w, _tk.ttk.LabelFrame)][0]
    botao_confirmar = [w for w in frame_edicao.winfo_children() if isinstance(w, _tk.ttk.Button)][0]
    botao_confirmar.invoke()
    app.update()

    assert app._contador_revisao == revisao_antes - 1
    assert app._contador_confirmados == confirmados_antes + 1
    print("OK: correcao manual moveu 1 registro de Revisao para Confirmado")
    print("Botao revisao apos correcao:", app.btn_revisao.cget("text"))

    linhas_apos_correcao = app.tabela.get_children()
    status_corrigido = [app.tabela.item(i)["values"][1] for i in linhas_apos_correcao]  # status agora é o índice 1
    assert any("CONFIRMADO" in s for s in status_corrigido)
    print("OK: tabela principal refletiu a correcao (sincronizacao)")

    if janela.winfo_exists():
        janela.destroy()

    shutil.rmtree(tmp, ignore_errors=True)
    app.destroy()

shutil.rmtree(_tmp_dir_img, ignore_errors=True)
print("TESTE DE INTEGRACAO UI COMPLETO: OK")
