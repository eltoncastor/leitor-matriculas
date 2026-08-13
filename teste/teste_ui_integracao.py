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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import numpy as np, cv2
from unittest.mock import patch, MagicMock
import pymupdf as fitz

from leitor_matriculas.ui.app import App, _ler_imagem
from leitor_matriculas.ocr.engine import OCRResult


class _DMRevisaoDeterministica:
    """
    DataManager fake usado só a partir da etapa de revisão manual, Fase 7.

    A revisão manual agora REAVALIA de verdade a correção digitada (ver
    PROBLEMAS C/D em app.py) em vez de forçar CONFIRMADO -- então o
    resultado da correção passa a depender do conteúdo de `dados/`. Como
    `dados/` é local/gitignored (pode nem existir em outra máquina, ver
    CLAUDE.md), o teste não pode depender do que essas planilhas reais
    contêm para ser determinístico. Esta base fake substitui a real só
    para o passo de revisão, e reconhece exatamente UMA matrícula.
    """
    colaboradores_disponivel = True
    gestores_disponivel = False  # sem base -> gestor não bloqueia (mesma regra já existente)
    motivos_disponivel = False
    avisos = []

    def buscar_colaborador(self, matricula):
        if matricula == "28972":
            return {"matricula": "28972", "nome": "Fulano Corrigido", "cargo": "Cargo X", "setor": "Setor X"}
        return None

    def listar_gestores(self):
        return []

    def listar_motivos(self):
        return []

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

# Fase 20 (H5): o histórico de correções vai para um arquivo TEMPORÁRIO
# durante o teste. Rodar a suíte não pode escrever no `dados/` real do
# operador -- e este patch é também o que garante que o teste observe
# exatamente o que a interface gravou.
_tmp_dir_correcoes = tempfile.mkdtemp(prefix="teste_ui_correcoes_")
_arquivo_correcoes = os.path.join(_tmp_dir_correcoes, "correcoes_humanas.jsonl")

with patch('leitor_matriculas.ui.app.messagebox.showerror') as m_err, patch('leitor_matriculas.ui.app.messagebox.showinfo') as m_info, \
     patch('leitor_matriculas.ui.app.messagebox.showwarning') as m_warn, \
     patch('leitor_matriculas.dados.registro_correcoes.caminho_padrao',
           return_value=_arquivo_correcoes):
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
    with patch('leitor_matriculas.ui.app.filedialog.asksaveasfilename', return_value=saida_xlsx):
        app._on_salvar()
    assert m_info.called
    assert os.path.isfile(saida_xlsx)
    import openpyxl
    wb = openpyxl.load_workbook(saida_xlsx)
    print("Abas do XLSX:", wb.sheetnames)
    assert wb.sheetnames == ["Liberações","Revisão","Resumo"]
    print("Linhas Liberacoes:", wb["Liberações"].max_row)

    # -------- revisao manual (Fase 7: reavaliação real, não force-confirm) --------
    # A partir daqui a base real de dados/ deixa de importar -- ver
    # _DMRevisaoDeterministica. Isso NÃO reclassifica os registros já
    # processados (o status já foi decidido, com a base real, lá em
    # cima); só passa a valer para o que `_confirmar` reavaliar agora.
    app._data_manager = _DMRevisaoDeterministica()

    # A revisão deixou de ser uma janela Toplevel (Fase 10) e virou uma
    # ABA da janela principal. Este trecho passou a dirigi-la pela API
    # programática (_indices_pendentes_revisao / _revisao_ir_para /
    # _revisao_confirmar / revisao_vars) em vez de caçar widgets na árvore
    # do Tk. O que é verificado continua sendo exatamente o mesmo
    # COMPORTAMENTO da Fase 7 (PROBLEMAS C/D/E) -- só o caminho até ele
    # mudou, e agora não quebra a cada ajuste de layout.
    print("Botao revisao:", app.btn_revisao.cget('text'))
    app._abrir_revisao()
    pendentes = app._indices_pendentes_revisao()
    print("Itens pendentes na revisao:", len(pendentes))
    assert len(pendentes) == app._contador_revisao
    # PROBLEMA E: a revisão só pode listar linhas REVISAO -- nenhuma ERRO
    # (página que falhou não tem campo nenhum de verdade a corrigir).
    assert app._paginas_com_erro == 0  # este lote não teve página com erro

    # -------- 1) correção REAL (matrícula corrigida para uma que a base
    # (fake) reconhece) -- deve virar CONFIRMADO, e Nome/Setor/Cargo
    # devem ser re-consultados (PROBLEMA C), não ficar em "(não encontrado)".
    revisao_antes = app._contador_revisao
    confirmados_antes = app._contador_confirmados
    app._revisao_ir_para(0)
    app.update()
    app.revisao_vars["matricula"].set("28972")  # matrícula reconhecida pela fake DM
    app._revisao_confirmar()
    app.update()

    assert app._contador_revisao == revisao_antes - 1
    assert app._contador_confirmados == confirmados_antes + 1
    print("OK: correcao manual REAL moveu 1 registro de Revisao para Confirmado")
    print("Botao revisao apos correcao:", app.btn_revisao.cget("text"))

    linhas_apos_correcao = app.tabela.get_children()
    status_corrigido = [app.tabela.item(i)["values"][1] for i in linhas_apos_correcao]  # status agora é o índice 1
    assert any("CONFIRMADO" in s for s in status_corrigido)
    print("OK: tabela principal refletiu a correcao (sincronizacao)")

    corrigidos = [r for r in app._registros_exportacao if r.get("nome") == "Fulano Corrigido"]
    assert len(corrigidos) == 1, corrigidos
    assert corrigidos[0]["status"] == "CONFIRMADO"
    assert corrigidos[0]["setor"] == "Setor X" and corrigidos[0]["cargo"] == "Cargo X"
    print("OK: PROBLEMA C -- Nome/Setor/Cargo re-consultados pela matricula corrigida (nao ficaram '(não encontrado)')")

    # -------- 2) correção que NÃO resolve o problema real -- Fase 7
    # (PROBLEMA D): não pode virar CONFIRMADO só por ter clicado o botão.
    pendentes_2 = app._indices_pendentes_revisao()
    if pendentes_2:
        indice_pendente = pendentes_2[0]
        app._revisao_ir_para(0)
        app.update()
        app.revisao_vars["matricula"].set("00000")  # a fake DM não reconhece
        revisao_antes_2 = app._contador_revisao
        app._revisao_confirmar()
        app.update()
        assert app._contador_revisao == revisao_antes_2, "registro nao corrigido de verdade nao pode virar CONFIRMADO"
        assert indice_pendente in app._indices_pendentes_revisao(), "registro ainda pendente deve continuar na lista"
        print("OK: PROBLEMA D -- correcao que nao resolve o problema real permanece em REVISAO")

    # -------- 3) Fase 10: DATA e HORA agora são editáveis na revisão.
    # Antes uma linha barrada pela data era impossível de resolver dentro
    # do programa (não havia campo para corrigi-la).
    assert "data" in app.revisao_vars and "hora" in app.revisao_vars, \
        "a revisão precisa permitir editar DATA e HORA"
    pendentes_3 = app._indices_pendentes_revisao()
    if pendentes_3:
        app._revisao_ir_para(0)
        app.update()
        registro_alvo = app._registros_exportacao[pendentes_3[0]]
        app.revisao_vars["matricula"].set("28972")
        app.revisao_vars["data"].set("23/04/2026")
        app.revisao_vars["hora"].set("11:05")
        app._revisao_confirmar()
        app.update()
        assert registro_alvo["data"] == "23/04/26", registro_alvo
        assert registro_alvo["hora"] == "11:05", registro_alvo
        print("OK: Fase 10 -- DATA/HORA editadas na revisao saem no formato canonico")

    # -------- PROBLEMA E: uma linha ERRO nunca pode entrar na revisão ------
    app._registros_exportacao.append({
        "data": "", "hora": "", "matricula": "", "nome": "", "cargo": "", "setor": "",
        "gestor": "", "motivo": "", "pagina_origem": 999, "status": "ERRO",
        "confianca_matricula": "", "confianca_gestor": "", "confianca_motivo": "",
        "observacao": "falha simulada de pagina", "texto_ocr_original": "",
    })
    indice_erro = len(app._registros_exportacao) - 1
    assert indice_erro not in app._indices_pendentes_revisao(), \
        "linha ERRO nao pode aparecer na revisao manual"
    paginas_pendentes = [
        app._registros_exportacao[i]["pagina_origem"] for i in app._indices_pendentes_revisao()
    ]
    assert 999 not in paginas_pendentes, "linha ERRO nao pode aparecer na revisao manual"
    print("OK: PROBLEMA E -- linha ERRO nunca aparece na revisao manual")

    # -------- Fase 18: a revisao EXPLICA a duvida ------------------------
    # Dirigido pelo contrato programatico (_explicacao_revisao_atual /
    # _revisao_ir_para / revisao_vars), nunca cacando widgets na arvore do
    # Tk -- que e o erro que a Fase 10 corrigiu.
    pendentes_18 = app._indices_pendentes_revisao()
    if pendentes_18:
        for posicao in range(len(pendentes_18)):
            app._revisao_ir_para(posicao)
            explicacao, sinais = app._explicacao_revisao_atual()
            indice_atual, registro_atual = app._revisao_registro_atual()

            # 1. toda linha em REVISAO tem explicacao
            assert not explicacao.vazia, f"linha {indice_atual} ficou sem explicacao"
            assert explicacao.como_texto(), f"linha {indice_atual} explicou vazio"

            # 2. a explicacao nomeia o campo que bloqueou (quando ha dossie)
            if registro_atual.get("evidencias"):
                assert explicacao.campos_bloqueantes, \
                    f"linha {indice_atual} nao identificou o campo bloqueante"
                for campo in explicacao.campos_bloqueantes:
                    assert campo in app.revisao_vars, \
                        f"campo bloqueante {campo!r} nao existe no formulario"

            # 3. NENHUM campo do formulario chega pre-preenchido com sugestao:
            #    o valor exibido e sempre o que ja estava no registro.
            for chave, var in app.revisao_vars.items():
                assert var.get() == (registro_atual.get(chave) or ""), (
                    f"campo {chave!r} da linha {indice_atual} foi pre-preenchido "
                    f"({var.get()!r} != {registro_atual.get(chave)!r})"
                )

            # 4. sinais de contexto sao informativos: nao mexem em revisao_vars
            antes = {k: v.get() for k, v in app.revisao_vars.items()}
            sinais_2 = app._explicacao_revisao_atual()[1]
            depois = {k: v.get() for k, v in app.revisao_vars.items()}
            assert antes == depois, "montar os sinais de contexto alterou revisao_vars"
            assert len(sinais) == len(sinais_2), "sinais de contexto nao sao deterministicos"
            for sinal in sinais:
                assert sinal.tipo == "contexto", sinal
                assert sinal.origem in (
                    "gestores_do_lote", "ordem_cronologica_da_folha",
                ), f"sinal de contexto nao previsto: {sinal.origem}"
        print(f"OK: Fase 18 -- {len(pendentes_18)} linha(s) em revisao com explicacao, "
              "nenhum campo pre-preenchido")

    # A explicacao nunca inventa: sem dossie e sem observacao, sai vazia.
    from leitor_matriculas.ui import explicacao_revisao as _expl
    assert _expl.explicar([], "").vazia, "explicacao sem dado nenhum deveria sair vazia"
    assert not _expl.explicar([], "algum motivo").vazia, \
        "sem dossie, a observacao antiga ainda deve ser mostrada"
    print("OK: Fase 18 -- explicacao nunca inventa texto")

    # -------- Fase 20 (H5): o histórico registrou as correções ----------
    # Infraestrutura de COLETA: grava depois da decisão e não participa
    # dela. O que se verifica aqui é que ela captura o que se perdia --
    # qual campo mudou, o valor anterior e o texto que o OCR havia lido --
    # e que a linha que NÃO resolveu também foi registrada.
    from leitor_matriculas.dados import registro_correcoes as _rc

    correcoes = _rc.ler_correcoes(_arquivo_correcoes)
    assert correcoes, "nenhuma correcao humana foi registrada"

    # A correção 1 (matrícula 28972) resolveu; a 2 (matrícula 00000) não.
    resolvidas = [c for c in correcoes if c["resolveu"]]
    nao_resolvidas = [c for c in correcoes if not c["resolveu"]]
    assert resolvidas, "correcao que virou CONFIRMADO nao foi registrada"
    assert nao_resolvidas, "correcao que permaneceu em REVISAO nao foi registrada"

    primeira = resolvidas[0]
    assert primeira["status_antes"] == "REVISAO"
    assert primeira["status_depois"] == "CONFIRMADO"
    assert primeira["campos"]["matricula"]["depois"] == "28972"
    # `campos_alterados` PODE ser vazio, e isso é informação, não falha:
    # aqui o operador conferiu a linha e confirmou o valor que já estava
    # (o que a destravou foi a base, não uma digitação). "Revisado e
    # mantido" é evidência tão real quanto "revisado e trocado" -- e é a
    # que some primeiro de qualquer registro informal.
    assert isinstance(primeira["campos_alterados"], list)
    # O texto BRUTO do OCR, que a planilha exportada só preservava para a
    # matrícula, e que `_revisao_confirmar` sobrescreve no dict.
    assert primeira["campos"]["matricula"]["ocr"], primeira["campos"]["matricula"]
    assert set(primeira["campos"]) == set(_rc.CAMPOS_REGISTRADOS)
    # Pelo menos UMA das correções da sessão mudou algum campo de fato
    # (a de matrícula 00000, que não resolveu).
    assert any(c["campos_alterados"] for c in correcoes), \
        "nenhuma correcao registrou campo alterado"
    # E o campo que bloqueava a linha antes da correção.
    assert any(c["campos_bloqueantes_antes"] for c in correcoes), \
        "nenhuma correcao registrou o campo bloqueante anterior"
    assert primeira["esquema"] == _rc.ESQUEMA and primeira["quando"]
    print(f"OK: Fase 20 -- {len(correcoes)} correcao(oes) humana(s) registradas "
          f"({len(resolvidas)} resolveram, {len(nao_resolvidas)} nao)")

    # A gravação é observacional: não alterou nenhum status nem a lista de
    # pendentes (o registro é feito DEPOIS da decisão).
    assert all(r["status"] in ("CONFIRMADO", "REVISAO", "ERRO")
               for r in app._registros_exportacao)
    print("OK: Fase 20 -- registrar a correcao nao alterou nenhuma decisao")

    # ==================================================================
    # Sub-fase 21b -- revisão como fluxo (lista de pendências, campo
    # bloqueante em destaque, "Ver detalhes", contador de progresso) e a
    # garantia de que `_revisao_confirmar` continua sendo o ÚNICO caminho
    # para sair de REVISAO (mesma proteção travada desde a Fase 12).
    # ==================================================================
    pendentes_21b = app._indices_pendentes_revisao()
    assert len(app.tabela_revisao_lista.get_children()) == len(pendentes_21b), (
        "a lista de pendencias (area 1) tem que refletir _indices_pendentes_revisao "
        "linha a linha -- e' a MESMA fonte de verdade que orienta a navegacao"
    )
    print("OK: Sub-fase 21b -- lista de pendencias reflete _indices_pendentes_revisao")

    # O contador "N de M revisados": N tem que ser exatamente quantas
    # correções desta sessão REALMENTE viraram CONFIRMADO (as `resolvidas`
    # já apuradas na secao da Fase 20 acima) -- nunca "quantas vezes o
    # botao foi clicado".
    assert app._revisao_resolvidos_sessao == len(resolvidas), (
        f"contador de progresso ({app._revisao_resolvidos_sessao}) nao bate com as "
        f"correcoes que realmente confirmaram ({len(resolvidas)})"
    )
    texto_progresso = app._texto_progresso_revisao(pendentes_21b)
    esperado_progresso = f"{len(resolvidas)} de {len(resolvidas) + len(pendentes_21b)} revisados"
    assert texto_progresso == esperado_progresso, (texto_progresso, esperado_progresso)
    print(f"OK: Sub-fase 21b -- contador de progresso: {texto_progresso!r}")

    if pendentes_21b:
        # Clicar numa linha da lista de pendências navega para ela --
        # mesmo destino que os botões Anterior/Próximo alcançariam -- e
        # NÃO toca em nenhum campo do formulário (é só navegação).
        alvo_lista = min(1, len(pendentes_21b) - 1)
        app.tabela_revisao_lista.selection_set(str(alvo_lista))
        app._on_selecionar_pendencia_lista()
        app.update()
        assert app._revisao_posicao == alvo_lista, \
            "selecionar uma linha na lista de pendencias nao navegou para ela"
        _, registro_apos_clique = app._revisao_registro_atual()
        for chave, var in app.revisao_vars.items():
            assert var.get() == (registro_apos_clique.get(chave) or ""), (
                f"clicar na lista de pendencias alterou o campo {chave!r} do formulario"
            )
        app._revisao_ir_para(0)
        app.update()
        print("OK: Sub-fase 21b -- clicar na lista de pendencias navega sem alterar o formulario")

        # O campo bloqueante (e só ele) recebe destaque visual -- rótulo e
        # caixa em estilo "danger".
        explicacao_21b, _sinais_21b = app._explicacao_revisao_atual()
        for chave, widget in app.revisao_widgets.items():
            estilo = str(widget.cget("style"))
            if chave in explicacao_21b.campos_bloqueantes:
                assert "danger" in estilo, \
                    f"campo bloqueante {chave!r} sem destaque visual (estilo={estilo!r})"
            else:
                assert "danger" not in estilo, \
                    f"campo NAO bloqueante {chave!r} destacado por engano (estilo={estilo!r})"
        print("OK: Sub-fase 21b -- só o(s) campo(s) bloqueante(s) recebem destaque visual")

        # "Ver detalhes" começa fechado a cada registro (não pode dominar a
        # tela) e alternar não toca em `revisao_vars` nem no status.
        assert app._revisao_detalhes_expandido is False, \
            "o painel de detalhes deveria comecar fechado ao carregar um registro"
        antes_alternar = {k: v.get() for k, v in app.revisao_vars.items()}
        app._alternar_detalhes_revisao()
        assert app._revisao_detalhes_expandido is True
        app._alternar_detalhes_revisao()
        assert app._revisao_detalhes_expandido is False
        depois_alternar = {k: v.get() for k, v in app.revisao_vars.items()}
        assert antes_alternar == depois_alternar, \
            "expandir/recolher 'Ver detalhes' alterou o formulario"
        print("OK: Sub-fase 21b -- 'Ver detalhes' comeca fechado e alterna sem tocar no formulario")

        # A foto da folha é carregada quando a miniatura está disponível
        # (guardada por _worker_imagens/_worker_pdf durante o processamento).
        _, registro_com_foto = app._revisao_registro_atual()
        if registro_com_foto["pagina_origem"] in app._miniaturas_por_pagina:
            assert getattr(app, "_imagem_pil_revisao", None) is not None, \
                "havia miniatura para a pagina, mas a foto nao foi carregada na revisao"
            print("OK: Sub-fase 21b -- foto da folha carregada quando disponivel")

    # A proteção central (Fase 7/12): NENHUM lugar de ui/app.py pode
    # escrever "CONFIRMADO" à mão em registro["status"]/em um dict de
    # exportação -- toda atribuição tem que vir do RETORNO de
    # `classificar_registro` (via a variável `resultado`/`status`, nunca
    # um literal). Trava estrutural, não só comportamental: mesmo que
    # alguém adicione um atalho nunca exercitado pelos cenários acima, o
    # grep abaixo entra em pane.
    caminho_app = os.path.join(os.path.dirname(__file__), "..", "src",
                                "leitor_matriculas", "ui", "app.py")
    with open(caminho_app, encoding="utf-8") as _fh:
        codigo_app = _fh.read()
    import re as _re
    assert not _re.search(r'\["status"\]\s*=\s*"CONFIRMADO"', codigo_app), \
        "ui/app.py escreve 'CONFIRMADO' na marra em registro['status'] -- atalho proibido"
    assert not _re.search(r'"status"\s*:\s*"CONFIRMADO"', codigo_app), \
        "ui/app.py escreve 'CONFIRMADO' na marra num dict literal -- atalho proibido"
    # Os dois (e só os dois) caminhos legítimos que escrevem o status de um
    # registro: a classificação automática (_adicionar_registros, monta o
    # dict a partir da variável `status`) e `_revisao_confirmar`
    # (reatribui a partir de `resultado.status`). Um terceiro caminho
    # aparecendo aqui quebra esta trava de propósito, para ser notado.
    reatribuicoes = _re.findall(r'registro\["status"\]\s*=(?!=)\s*([^\n]+)', codigo_app)
    assert reatribuicoes == ["resultado.status"], (
        f"esperava exatamente 1 reatribuicao de registro['status'] (em "
        f"_revisao_confirmar, vinda de resultado.status); encontrado: {reatribuicoes}"
    )
    # Só os dicts que MONTAM um registro (têm "pagina_origem" ao lado) --
    # não os de layout (CABECALHOS_TABELA/LARGURAS_TABELA, que também têm
    # a chave "status", mas para largura/rótulo de coluna).
    dicts_de_registro = _re.findall(r'"pagina_origem":[^\n]*"status":\s*(\w+|"ERRO")', codigo_app)
    assert sorted(dicts_de_registro) == sorted(["status", '"ERRO"']), (
        f"esperava exatamente os 2 dicts de registro conhecidos (classificacao "
        f"automatica com 'status': status, e a linha ERRO de falha de pagina); "
        f"encontrado: {dicts_de_registro}"
    )
    print("OK: Sub-fase 21b -- _revisao_confirmar continua o UNICO caminho para "
          "sair de REVISAO (nenhum atalho grava 'CONFIRMADO' na marra)")

    shutil.rmtree(tmp, ignore_errors=True)
    app.destroy()

shutil.rmtree(_tmp_dir_img, ignore_errors=True)
shutil.rmtree(_tmp_dir_correcoes, ignore_errors=True)
print("TESTE DE INTEGRACAO UI COMPLETO: OK")
