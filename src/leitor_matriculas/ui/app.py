"""
ui/app.py

Interface gráfica. Coordena: seleção de imagem/PDF -> pré-processamento
(image_processor) -> OCR (ocr_engine) -> parser espacial (registro_parser)
-> validação (validacao) -> revisão/edição -> exportação XLSX
(xlsx_exporter). Toda a lógica de negócio vive nos outros módulos; a UI só
chama e apresenta.

OCR roda em thread separada (threading.Thread); a comunicação de volta usa
queue.Queue consumida só pela thread principal via self.after — a worker
thread NUNCA chama métodos do Tkinter diretamente.

BASE VISUAL (Fase 10): `ttkbootstrap`, que é ttk por baixo — os widgets
continuam sendo `ttk.*` (inclusive o Treeview, que é o centro deste app) e
por isso a troca não exigiu reescrever a interface, só re-hospedá-la. O que
ele acrescenta é tema, variantes de botão (`bootstyle`) e cores de estado.

LAYOUT (Fase 10): a janela é dividida em cabeçalho (ações + progresso),
um Notebook com três abas e uma barra de estado:

    Registros -- a tabela de acompanhamento, com cor por status e filtro.
    Revisão   -- a foto da folha ao lado do formulário de edição.
    Avisos    -- tudo que antes eram messagebox soltas em quatro botões.

REVISÃO (Fase 10): deixou de ser uma janela separada e passou a ser uma
aba, porque revisar ~50 folhas em sequência numa caixa de diálogo modal é
o oposto de um fluxo. Além disso agora edita DATA e HORA, que antes não
tinham campo nenhum — uma linha barrada pela data era literalmente
impossível de resolver dentro do programa (o próprio código avisava isso
ao operador e mandava conferir no papel). O que NÃO mudou é a regra: o
botão continua sem poder "marcar como confirmado". Ele reconstrói um
Registro com os valores digitados e roda a MESMA `classificar_registro`
do fluxo automático; só sai de REVISAO o que a validação aceitar.
"""

import io
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
import ttkbootstrap as tb
from PIL import Image, ImageTk

from leitor_matriculas.ocr.image_processor import preprocess_image
from leitor_matriculas.ocr.engine import get_ocr_engine, normalizar_matricula
from leitor_matriculas.dados.data_manager import DataManager
from leitor_matriculas.parsing.registro_parser import (
    CampoOcr,
    Registro,
    parse_registros,
    verificar_contagem_posicoes,
)
from leitor_matriculas.parsing.contexto_lote import ContextoLote
from leitor_matriculas.parsing.tempo_parser import tentar_separar_data_hora_mesclada
from leitor_matriculas.validacao.regras import classificar_registro
from leitor_matriculas.validacao.recuperacao_matricula import resolver_matricula
from leitor_matriculas.ui import explicacao_revisao
from leitor_matriculas.ocr import pdf_reader
from leitor_matriculas.exportacao import xlsx_exporter

EXTENSOES_IMAGEM = [("Imagens", "*.jpg *.jpeg *.png *.webp"), ("Todos", "*.*")]
EXTENSOES_PDF = [("PDF", "*.pdf")]

TEMA = "cosmo"

# Placeholder explícito para Nome/Cargo/Setor quando a matrícula não pôde
# ser associada a um colaborador da base — nunca deixamos a célula "vazia
# aparentemente válida" (requisito funcional definitivo): quem olhar a
# planilha precisa ver que aquele dado é "não confirmado", não "em branco".
NAO_ENCONTRADO = "(não encontrado)"

# Ordem de exibição na tabela ao vivo (a ordem obrigatória da planilha
# final — Data/Hora/Matrícula/Nome/Setor/Motivo/Responsável — é aplicada
# em xlsx_exporter.py; aqui a tabela de acompanhamento prioriza Página/
# Status para leitura rápida durante o processamento).
#
# A Observação ganhou COLUNA PRÓPRIA (Fase 10). Antes ela era concatenada
# dentro da célula de Status ("⚠ REVISÃO — matrícula não encontrada; motivo
# normalizado..."), o que espremia o motivo real da revisão numa coluna de
# 220px e truncava exatamente a informação de que o operador precisa.
COLUNAS_TABELA = (
    "pagina", "status", "data", "hora", "matricula", "nome", "setor",
    "motivo", "gestor", "cargo", "confianca", "observacao",
)
CABECALHOS_TABELA = {
    "pagina": "Pág.", "status": "Status",
    "data": "Data", "hora": "Hora", "matricula": "Matrícula",
    "nome": "Nome", "setor": "Setor", "motivo": "Motivo",
    "gestor": "Responsável", "cargo": "Cargo", "confianca": "Confiança",
    "observacao": "Observação",
}
# Somadas, estas larguras cabem na janela no tamanho padrão -- senão a
# Observação, que é a ÚLTIMA coluna e justamente a que diz por que a linha
# precisa de revisão, nasce fora da tela e só aparece se o operador rolar
# na horizontal (foi o que aconteceu na primeira versão desta tela).
LARGURAS_TABELA = {
    "pagina": 46, "status": 116, "data": 74, "hora": 56, "matricula": 84,
    "nome": 172, "setor": 124, "motivo": 122, "gestor": 128, "cargo": 118,
    "confianca": 72, "observacao": 280,
}
# Altura das linhas da tabela. O padrão do ttk aperta demais as linhas para
# uma tabela que se lê durante uma hora de lote.
ALTURA_LINHA_TABELA = 26
# Colunas que ficam alinhadas à esquerda por serem texto corrido; as demais
# (números, códigos, status) ficam centradas.
COLUNAS_A_ESQUERDA = {"nome", "setor", "cargo", "observacao"}

FILTROS_TABELA = ("Todos", "Confirmados", "Em revisão", "Com erro")

# Maior dimensão guardada da foto de cada página para a aba de Revisão.
# A foto é guardada JÁ COMPRIMIDA em JPEG (bytes), não como matriz: um
# lote real de ~50 folhas em matriz numpy passaria de 1 GB de RAM, enquanto
# em JPEG reduzido fica na casa de dezenas de MB. A decodificação sob
# demanda custa milissegundos, contra ~65 s de OCR por página.
LARGURA_MAXIMA_MINIATURA = 1500
QUALIDADE_MINIATURA = 85


def _ler_imagem(path: str) -> np.ndarray:
    dados = np.fromfile(path, dtype=np.uint8)
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError(f"Não foi possível abrir a imagem: {path}")
    return imagem


def _comprimir_para_miniatura(imagem_bgr):
    """
    Reduz e comprime a foto da página para guardá-la em memória durante o
    lote (ver LARGURA_MAXIMA_MINIATURA). Devolve bytes JPEG ou None se a
    compressão falhar — a foto é uma comodidade da revisão, nunca um dado:
    falhar aqui não pode derrubar o processamento.
    """
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


def _texto_campo(registro, nome_campo: str) -> str:
    campo = registro.campos.get(nome_campo)
    return campo.texto if campo else ""


def _reparar_data_hora_mescladas(registros):
    """
    PROBLEMA 5 (Fase 1 de precisão da extração): corrige o caso real em que
    o próprio detector de texto do OCR colou DATA e HORA em uma única caixa
    (ex.: "14.04 26 20:24" -- visto em teste.jpg). Só age quando exatamente
    um dos dois campos está ausente; `tentar_separar_data_hora_mesclada`
    (tempo_parser.py) só aceita a separação se ambos os pedaços validarem
    de verdade -- nunca inventa. Sem separação segura, o registro segue
    sem alteração (campo ausente -> REVISAO, como já era o caso).
    """
    for registro in registros:
        tem_data = "data" in registro.campos
        tem_hora = "hora" in registro.campos
        if tem_data == tem_hora:
            continue  # ambos presentes ou ambos ausentes: nada a reparar aqui

        campo_fonte = registro.campos["data"] if tem_data else registro.campos["hora"]
        resultado = tentar_separar_data_hora_mesclada(campo_fonte.texto)
        if resultado is None:
            continue

        texto_data, texto_hora = resultado
        registro.campos["data"] = CampoOcr(texto=texto_data, confianca=campo_fonte.confianca, box=campo_fonte.box)
        # `texto_hora` vem None quando a caixa mesclada tinha uma hora
        # impossível ("14.04 -26 90:24"): a DATA legível é aproveitada e a
        # HORA (opcional) continua ausente -- o texto impossível nunca vai
        # para o campo, só para o registro de auditoria logo abaixo.
        if texto_hora is None:
            registro.campos.pop("hora", None)
        else:
            registro.campos["hora"] = CampoOcr(texto=texto_hora, confianca=campo_fonte.confianca, box=campo_fonte.box)
        # Preserva o texto mesclado original para auditoria (nunca some).
        registro.nao_associados.append(
            CampoOcr(texto=f"[data/hora mescladas no OCR: {campo_fonte.texto!r}]", confianca=campo_fonte.confianca, box=campo_fonte.box)
        )


class App(tb.Window):
    def __init__(self):
        super().__init__(themename=TEMA)
        self.title("Leitor de Planilhas by Elton Marques")
        self.geometry("1400x860")
        self.minsize(1120, 700)

        self._ocr_engine = None
        self._data_manager = DataManager()
        # Contexto acumulado do lote (hoje: o ano das datas já lidas), usado
        # para completar uma DATA que o OCR entregou sem ano. Vive junto com
        # os resultados: é zerado no "Limpar resultados", nunca atravessa
        # dois lotes diferentes.
        self._contexto_lote = ContextoLote()

        self._arquivo_atual = None

        self._processando = False
        self._fila_resultados: "queue.Queue" = queue.Queue()

        self._proximo_numero_pagina = 1
        self._registros_exportacao = []  # lista de dicts prontos p/ xlsx_exporter
        self._erros_paginas = []
        self._avisos_contagem = []  # PROBLEMA 2: páginas cuja contagem de posições divergiu do esperado
        self._avisos_descarte = []  # linhas sem matrícula identificável (nunca descartadas em silêncio)
        self._contador_confirmados = 0
        self._contador_revisao = 0
        self._paginas_processadas = 0
        self._paginas_com_erro = 0
        # Fase 7 (operação em lote): total esperado de páginas do lote em
        # andamento (quando conhecido) e quantas dessa leva específica já
        # foram processadas -- usados só para mostrar progresso "X/Y" na
        # barra de status durante lotes longos (~50 folhas reais). Nunca
        # usados para nenhuma decisão de negócio, só informativos.
        self._total_paginas_lote = None
        self._paginas_processadas_lote = 0

        # Foto de cada página (JPEG comprimido), para a aba de Revisão.
        self._miniaturas_por_pagina = {}
        # Estado da aba de Revisão.
        self._revisao_indices = []   # índices em _registros_exportacao, na ordem física
        self._revisao_posicao = 0    # posição atual dentro de _revisao_indices
        self._revisao_zoom = 1.0
        self._foto_revisao = None    # referência viva do PhotoImage (senão o Tk descarta)

        self._montar_layout()
        self._atualizar_status()
        self._atualizar_avisos()
        self._atualizar_painel_revisao()

    # ==================================================================
    # LAYOUT
    # ==================================================================
    def _montar_layout(self):
        # Linhas mais altas em TODAS as tabelas (ver ALTURA_LINHA_TABELA).
        try:
            estilo = tb.Style()
            estilo.configure("Treeview", rowheight=ALTURA_LINHA_TABELA)
        except Exception:
            logging.exception("Falha ao ajustar a altura das linhas (apenas cosmético)")

        self._montar_cabecalho()

        self.abas = ttk.Notebook(self)
        self.abas.pack(side="top", fill="both", expand=True, padx=12, pady=(0, 8))
        self._montar_aba_registros()
        self._montar_aba_revisao()
        self._montar_aba_avisos()

        self._montar_rodape()

    # ------------------------------------------------------------------
    def _montar_cabecalho(self):
        cabecalho = ttk.Frame(self, padding=(12, 12, 12, 8))
        cabecalho.pack(side="top", fill="x")

        # Ações de ENTRADA à esquerda; a ação de SAÍDA ("Gerar planilha")
        # fica destacada à direita. Antes todos os botões tinham exatamente
        # o mesmo peso visual, então a ação que encerra o trabalho parecia
        # tão importante quanto "Ver avisos".
        entrada = ttk.Frame(cabecalho)
        entrada.pack(side="left")

        self.btn_imagem = ttk.Button(
            entrada, text="Selecionar imagens", bootstyle="primary",
            command=self._on_selecionar_imagem, width=20,
        )
        self.btn_imagem.pack(side="left", padx=(0, 6))
        self.btn_pdf = ttk.Button(
            entrada, text="Selecionar PDF", bootstyle="primary-outline",
            command=self._on_selecionar_pdf, width=18,
        )
        self.btn_pdf.pack(side="left", padx=(0, 6))
        self.btn_limpar = ttk.Button(
            entrada, text="Limpar resultados", bootstyle="secondary-outline",
            command=self._on_limpar, width=18,
        )
        self.btn_limpar.pack(side="left")

        saida = ttk.Frame(cabecalho)
        saida.pack(side="right")
        self.btn_salvar = ttk.Button(
            saida, text="Gerar planilha", bootstyle="success",
            command=self._on_salvar, state="disabled", width=18,
        )
        self.btn_salvar.pack(side="right")
        # Mantido por compatibilidade de fluxo: leva para a aba de Revisão.
        self.btn_revisao = ttk.Button(
            saida, text="Revisar (0)", bootstyle="warning-outline",
            command=self._abrir_revisao, state="disabled", width=16,
        )
        self.btn_revisao.pack(side="right", padx=(0, 6))

        # Barra de progresso do lote. O "X/Y" já existia como texto desde a
        # Fase 7; faltava a leitura visual, que é o que responde "falta
        # muito?" sem o operador precisar ler número nenhum.
        #
        # Ela só aparece ENQUANTO há um lote rodando (ver
        # _mostrar_progresso). Parada em 100% ela ocupava a faixa inteira
        # do topo sem informar nada -- a barra de estado no rodapé já diz
        # "Concluído — Páginas: N | Confirmados: ... | Revisão: ...".
        self._frame_progresso = ttk.Frame(self, padding=(12, 0, 12, 8))
        self.barra_progresso = ttk.Progressbar(
            self._frame_progresso, mode="determinate", maximum=100, value=0, bootstyle="primary-striped",
        )
        self.barra_progresso.pack(side="left", fill="x", expand=True)
        self.lbl_progresso = ttk.Label(self._frame_progresso, text="", width=22, anchor="e")
        self.lbl_progresso.pack(side="left", padx=(10, 0))

    # ------------------------------------------------------------------
    def _montar_aba_registros(self):
        aba = ttk.Frame(self.abas, padding=10)
        self.abas.add(aba, text="Registros")
        self._aba_registros = aba

        filtros = ttk.Frame(aba)
        filtros.pack(side="top", fill="x", pady=(0, 8))
        ttk.Label(filtros, text="Mostrar:").pack(side="left", padx=(0, 6))
        self.filtro_var = tk.StringVar(value=FILTROS_TABELA[0])
        self.combo_filtro = ttk.Combobox(
            filtros, textvariable=self.filtro_var, values=list(FILTROS_TABELA),
            state="readonly", width=14,
        )
        self.combo_filtro.pack(side="left")
        self.combo_filtro.bind("<<ComboboxSelected>>", lambda _e: self._sincronizar_tabela_principal())
        self.lbl_contagem_tabela = ttk.Label(filtros, text="", bootstyle="secondary")
        self.lbl_contagem_tabela.pack(side="left", padx=12)

        moldura = ttk.Frame(aba)
        moldura.pack(side="top", fill="both", expand=True)
        # Sem bootstyle de cor nas tabelas: a moldura colorida do
        # ttkbootstrap desenha uma borda grossa em volta da tabela inteira,
        # que numa tela densa de dados compete com a informação. Quem
        # comunica o estado aqui é a cor de FUNDO de cada linha (ver as
        # tags abaixo) e o texto da coluna Status.
        self.tabela = ttk.Treeview(moldura, columns=COLUNAS_TABELA, show="headings")
        for coluna in COLUNAS_TABELA:
            self.tabela.heading(coluna, text=CABECALHOS_TABELA[coluna])
            self.tabela.column(
                coluna, width=LARGURAS_TABELA[coluna],
                anchor="w" if coluna in COLUNAS_A_ESQUERDA else "center",
                stretch=(coluna == "observacao"),
            )
        # Cor por status: o olho encontra a linha problemática antes de ler
        # qualquer texto. Tons claros de propósito -- o texto continua preto
        # e legível, sem depender só da cor (o rótulo de status também diz).
        self.tabela.tag_configure("confirmado", background="#eaf6ec")
        self.tabela.tag_configure("revisao", background="#fdf4e3")
        self.tabela.tag_configure("erro", background="#fbe9e7")

        vsb = ttk.Scrollbar(moldura, orient="vertical", command=self.tabela.yview)
        hsb = ttk.Scrollbar(moldura, orient="horizontal", command=self.tabela.xview)
        self.tabela.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tabela.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        moldura.rowconfigure(0, weight=1)
        moldura.columnconfigure(0, weight=1)

        # Duplo clique numa linha em revisão leva direto para ela na aba de
        # Revisão -- o caminho natural depois de encontrar o problema aqui.
        self.tabela.bind("<Double-1>", self._on_duplo_clique_tabela)

    # ------------------------------------------------------------------
    def _montar_aba_revisao(self):
        aba = ttk.Frame(self.abas, padding=10)
        self.abas.add(aba, text="Revisão")
        self._aba_revisao = aba

        painel = ttk.PanedWindow(aba, orient="horizontal")
        painel.pack(side="top", fill="both", expand=True)

        # ---- esquerda: a foto da folha --------------------------------
        moldura_foto = ttk.Labelframe(painel, text="Folha digitalizada", padding=8)
        painel.add(moldura_foto, weight=3)

        controles_foto = ttk.Frame(moldura_foto)
        controles_foto.pack(side="top", fill="x", pady=(0, 6))
        ttk.Button(controles_foto, text="−", width=3, bootstyle="secondary-outline",
                   command=lambda: self._ajustar_zoom(0.8)).pack(side="left")
        ttk.Button(controles_foto, text="+", width=3, bootstyle="secondary-outline",
                   command=lambda: self._ajustar_zoom(1.25)).pack(side="left", padx=(4, 0))
        ttk.Button(controles_foto, text="Ajustar", bootstyle="secondary-outline",
                   command=self._ajustar_zoom_para_caber).pack(side="left", padx=(4, 0))
        self.lbl_pagina_foto = ttk.Label(controles_foto, text="", bootstyle="secondary")
        self.lbl_pagina_foto.pack(side="right")

        moldura_canvas = ttk.Frame(moldura_foto)
        moldura_canvas.pack(side="top", fill="both", expand=True)
        self.canvas_foto = tk.Canvas(moldura_canvas, background="#f1f3f5", highlightthickness=0)
        vsb_foto = ttk.Scrollbar(moldura_canvas, orient="vertical", command=self.canvas_foto.yview)
        hsb_foto = ttk.Scrollbar(moldura_canvas, orient="horizontal", command=self.canvas_foto.xview)
        self.canvas_foto.configure(yscrollcommand=vsb_foto.set, xscrollcommand=hsb_foto.set)
        self.canvas_foto.grid(row=0, column=0, sticky="nsew")
        vsb_foto.grid(row=0, column=1, sticky="ns")
        hsb_foto.grid(row=1, column=0, sticky="ew")
        moldura_canvas.rowconfigure(0, weight=1)
        moldura_canvas.columnconfigure(0, weight=1)

        # ---- direita: o formulário ------------------------------------
        moldura_form = ttk.Frame(painel, padding=(12, 0, 0, 0))
        painel.add(moldura_form, weight=2)

        topo = ttk.Frame(moldura_form)
        topo.pack(side="top", fill="x")
        self.lbl_revisao_posicao = ttk.Label(topo, text="", font=("", 11, "bold"))
        self.lbl_revisao_posicao.pack(side="left")

        self.lbl_revisao_motivo = ttk.Label(
            moldura_form, text="", bootstyle="warning", wraplength=430, justify="left",
        )
        self.lbl_revisao_motivo.pack(side="top", fill="x", pady=(6, 10))

        # Fase 18: a explicação da dúvida, lida do dossiê da Fase 17. Entra
        # ACIMA do formulário porque é o que o operador precisa ler ANTES de
        # digitar. O rótulo de observação acima continua existindo (é o texto
        # que a validação sempre produziu); aqui vem a cadeia detalhada.
        self.moldura_revisao_explicacao = ttk.Labelframe(
            moldura_form, text="Por que está em revisão", padding=10,
        )
        self.lbl_revisao_explicacao = ttk.Label(
            self.moldura_revisao_explicacao, text="", wraplength=420, justify="left",
        )
        self.lbl_revisao_explicacao.pack(side="top", fill="x", anchor="w")
        # Sinais de contexto (Fase 16, medidos e aprovados só para EXIBIÇÃO).
        # Rótulo próprio e estilo próprio: contexto não pode ficar
        # indistinguível de dado confirmado.
        self.lbl_revisao_contexto = ttk.Label(
            self.moldura_revisao_explicacao, text="", bootstyle="info",
            wraplength=420, justify="left",
        )

        campos = ttk.Labelframe(moldura_form, text="Campos lidos da folha", padding=12)
        campos.pack(side="top", fill="x")
        # Guardado porque a moldura da explicação (Fase 18) é empacotada
        # com `before=` este frame -- ela aparece e some conforme houver ou
        # não o que explicar, sem reordenar o resto do formulário.
        self.moldura_revisao_campos = campos

        self.revisao_vars = {}
        self.revisao_widgets = {}
        # MOTIVO e RESPONSÁVEL viram lista fechada (Combobox) porque o valor
        # válido só pode ser um dos cadastrados -- digitar à mão aqui só
        # criaria um valor que a validação vai recusar em seguida. Ficam
        # editáveis (não "readonly") para o operador poder colar/ajustar,
        # mas com a lista à mão.
        linhas = [
            ("data", "Data", "entry", None),
            ("hora", "Hora", "entry", None),
            ("matricula", "Matrícula", "entry", None),
            ("motivo", "Motivo", "combo", self._data_manager.listar_motivos),
            ("gestor", "Responsável", "combo", self._data_manager.listar_gestores),
        ]
        for i, (chave, rotulo, tipo, fonte_valores) in enumerate(linhas):
            ttk.Label(campos, text=rotulo).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 10))
            var = tk.StringVar()
            if tipo == "combo":
                try:
                    valores = sorted({str(v).strip() for v in (fonte_valores() or []) if str(v).strip()})
                except Exception:
                    valores = []
                widget = ttk.Combobox(campos, textvariable=var, values=valores, width=32)
            else:
                widget = ttk.Entry(campos, textvariable=var, width=34)
            widget.grid(row=i, column=1, sticky="ew", pady=4)
            self.revisao_vars[chave] = var
            self.revisao_widgets[chave] = widget
        campos.columnconfigure(1, weight=1)

        ttk.Label(
            campos,
            text="Data em DD/MM/AA e hora em HH:MM. A hora é opcional;\n"
                 "a matrícula só pode conter dígitos.",
            bootstyle="secondary", justify="left",
        ).grid(row=len(linhas), column=0, columnspan=2, sticky="w", pady=(8, 0))

        derivados = ttk.Labelframe(moldura_form, text="Obtido da base pela matrícula", padding=12)
        derivados.pack(side="top", fill="x", pady=(10, 0))
        self.lbl_revisao_nome = ttk.Label(derivados, text="—", wraplength=430, justify="left")
        self.lbl_revisao_nome.pack(side="top", anchor="w")
        self.lbl_revisao_setor = ttk.Label(derivados, text="—", bootstyle="secondary", wraplength=430, justify="left")
        self.lbl_revisao_setor.pack(side="top", anchor="w", pady=(2, 0))

        self.lbl_revisao_resultado = ttk.Label(moldura_form, text="", wraplength=430, justify="left")
        self.lbl_revisao_resultado.pack(side="top", fill="x", pady=(10, 0))

        acoes = ttk.Frame(moldura_form)
        acoes.pack(side="bottom", fill="x", pady=(12, 0))
        self.btn_revisao_anterior = ttk.Button(
            acoes, text="◀ Anterior", bootstyle="secondary-outline",
            command=lambda: self._revisao_navegar(-1), width=12,
        )
        self.btn_revisao_anterior.pack(side="left")
        self.btn_revisao_proximo = ttk.Button(
            acoes, text="Próximo ▶", bootstyle="secondary-outline",
            command=lambda: self._revisao_navegar(1), width=12,
        )
        self.btn_revisao_proximo.pack(side="left", padx=(6, 0))
        self.btn_revisao_confirmar = ttk.Button(
            acoes, text="Confirmar correção", bootstyle="success",
            command=self._revisao_confirmar, width=20,
        )
        self.btn_revisao_confirmar.pack(side="right")

        self.lbl_revisao_vazio = ttk.Label(
            aba, text="", bootstyle="secondary", anchor="center", justify="center",
        )

    # ------------------------------------------------------------------
    def _montar_aba_avisos(self):
        aba = ttk.Frame(self.abas, padding=10)
        self.abas.add(aba, text="Avisos")
        self._aba_avisos = aba

        ttk.Label(
            aba,
            text="Nada aqui bloqueia o processamento — são apontamentos para conferência no papel.",
            bootstyle="secondary",
        ).pack(side="top", anchor="w", pady=(0, 8))

        moldura = ttk.Frame(aba)
        moldura.pack(side="top", fill="both", expand=True)
        self.tabela_avisos = ttk.Treeview(
            moldura, columns=("tipo", "pagina", "mensagem"), show="headings",
        )
        for coluna, titulo, largura, ancora in [
            ("tipo", "Tipo", 200, "w"), ("pagina", "Pág.", 60, "center"),
            ("mensagem", "Detalhe", 780, "w"),
        ]:
            self.tabela_avisos.heading(coluna, text=titulo)
            self.tabela_avisos.column(coluna, width=largura, anchor=ancora, stretch=(coluna == "mensagem"))
        vsb = ttk.Scrollbar(moldura, orient="vertical", command=self.tabela_avisos.yview)
        self.tabela_avisos.configure(yscrollcommand=vsb.set)
        self.tabela_avisos.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        moldura.rowconfigure(0, weight=1)
        moldura.columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    def _montar_rodape(self):
        rodape = ttk.Frame(self, padding=(12, 0, 12, 10))
        rodape.pack(side="bottom", fill="x")

        self.lbl_status = ttk.Label(rodape, text="Nenhum arquivo selecionado.")
        self.lbl_status.pack(side="left")

        self.lbl_bases = ttk.Label(rodape, text=self._data_manager.resumo_status(), bootstyle="secondary")
        self.lbl_bases.pack(side="right")

    # ==================================================================
    # Seleção de arquivo
    # ==================================================================
    def _on_selecionar_imagem(self):
        if self._processando:
            return
        # Fase 7 (operação em lote): seleção MÚLTIPLA -- selecionar um
        # arquivo de cada vez para ~50 fotos reais é operacionalmente
        # arriscado (esquecer um arquivo, clicar errado, cansaço do
        # operador), e é justamente o cenário real de amanhã. Um único
        # arquivo continua seguindo exatamente o caminho já testado
        # (carrega a imagem já na thread principal e usa _worker_imagem);
        # múltiplos arquivos vão para _worker_imagens, que isola cada
        # arquivo da mesma forma que _worker_pdf já isola cada página.
        caminhos = filedialog.askopenfilenames(title="Selecione a(s) foto(s) da(s) folha(s)", filetypes=EXTENSOES_IMAGEM)
        if not caminhos:
            return
        caminhos = list(caminhos)

        if len(caminhos) == 1:
            path = caminhos[0]
            try:
                imagem = _ler_imagem(path)
            except Exception as exc:
                messagebox.showerror("Erro ao abrir imagem", str(exc))
                return
            self._arquivo_atual = os.path.basename(path)
            self._iniciar_processamento(f"Processando {self._arquivo_atual} ...")
            threading.Thread(target=self._worker_imagem, args=(imagem,), daemon=True).start()
            self.after(100, self._verificar_fila)
            return

        self._arquivo_atual = f"{len(caminhos)} imagens selecionadas"
        self._iniciar_processamento(f"Processando 0/{len(caminhos)} imagens ...")
        threading.Thread(target=self._worker_imagens, args=(caminhos,), daemon=True).start()
        self.after(100, self._verificar_fila)

    def _on_selecionar_pdf(self):
        if self._processando:
            return
        path = filedialog.askopenfilename(title="Selecione o PDF do mês", filetypes=EXTENSOES_PDF)
        if not path:
            return
        self._arquivo_atual = os.path.basename(path)
        self._iniciar_processamento(f"Abrindo {self._arquivo_atual} ...")
        threading.Thread(target=self._worker_pdf, args=(path,), daemon=True).start()
        self.after(100, self._verificar_fila)

    def _iniciar_processamento(self, texto_status):
        self._processando = True
        self.btn_imagem.config(state="disabled")
        self.btn_pdf.config(state="disabled")
        self.btn_limpar.config(state="disabled")
        self.btn_salvar.config(state="disabled")
        self.lbl_status.config(text=texto_status)
        # Progresso é sempre reiniciado a cada nova leva (imagem única,
        # lote de imagens ou PDF) -- reflete o andamento DESTA leva, não
        # o acumulado de sessões anteriores (ver _atualizar_status).
        self._total_paginas_lote = None
        self._paginas_processadas_lote = 0
        self.barra_progresso.config(value=0)

    def _finalizar_processamento(self):
        self._processando = False
        self.btn_imagem.config(state="normal")
        self.btn_pdf.config(state="normal")
        self.btn_limpar.config(state="normal")
        if self._registros_exportacao:
            self.btn_salvar.config(state="normal")

    # ==================================================================
    # Workers (thread separada -- nunca tocam no Tkinter diretamente)
    # ==================================================================
    def _processar_uma_pagina(self, imagem_bgr):
        """Devolve (imagem_processada, registros, erro). Nunca levanta exceção."""
        try:
            imagem_processada = preprocess_image(imagem_bgr)
        except Exception as exc:
            return None, [], f"Erro no pré-processamento: {exc}"

        if self._ocr_engine is None:
            try:
                self._ocr_engine = get_ocr_engine("paddleocr")
            except ImportError as exc:
                return None, [], f"PaddleOCR não instalado: {exc}"

        try:
            resultados_ocr = self._ocr_engine.recognize(imagem_processada)
        except Exception as exc:
            return imagem_processada, [], f"Erro no OCR: {exc}"

        try:
            registros = parse_registros(resultados_ocr).registros
            _reparar_data_hora_mescladas(registros)
        except Exception as exc:
            return imagem_processada, [], f"Erro no parser espacial: {exc}"

        return imagem_processada, registros, None

    def _worker_imagem(self, imagem_bgr):
        # Ao contrário de _processar_uma_pagina (que já blinda cada etapa
        # internamente), este método rodava sem nenhum try/except: qualquer
        # exceção que escapasse dali (ex.: get_ocr_engine falhando por um
        # motivo diferente de ImportError) matava a thread em silêncio sem
        # nunca colocar ("fim", ...) na fila -- a UI ficava presa em
        # "Processando..." para sempre, com os botões desabilitados. Espelha
        # o mesmo padrão de captura/"erro_fatal" já usado em _worker_pdf.
        numero = self._proximo_numero_pagina
        try:
            imagem_processada, registros, erro = self._processar_uma_pagina(imagem_bgr)
            self._fila_resultados.put(("pagina", numero, imagem_bgr, imagem_processada, registros, erro))
            self._proximo_numero_pagina = numero + 1
            self._fila_resultados.put(("fim", 1))
        except Exception as exc:
            logging.exception("Falha inesperada processando imagem (página %s)", numero)
            self._fila_resultados.put(("erro_fatal", "Erro inesperado processando a imagem", str(exc)))

    def _worker_imagens(self, caminhos):
        """
        Processa uma LISTA de arquivos de imagem (seleção múltipla -- ex.:
        o lote de ~50 fotos do dia), com o MESMO isolamento de falha por
        página que _worker_pdf já usa para páginas de PDF: um arquivo que
        não abre (corrompido, formato inesperado, não é imagem) ou que
        falha em qualquer etapa interna de _processar_uma_pagina vira uma
        linha de ERRO para aquela página e o lote CONTINUA -- uma foto
        ruim nunca aborta as demais 49.
        """
        total = len(caminhos)
        self._fila_resultados.put(("total", total))
        try:
            for caminho in caminhos:
                numero = self._proximo_numero_pagina
                nome_arquivo = os.path.basename(caminho)
                try:
                    imagem_bgr = _ler_imagem(caminho)
                except Exception as exc:
                    self._fila_resultados.put(
                        ("pagina", numero, None, None, [], f"Falha ao abrir '{nome_arquivo}': {exc}")
                    )
                    self._proximo_numero_pagina = numero + 1
                    continue

                imagem_processada, registros, erro = self._processar_uma_pagina(imagem_bgr)
                if erro:
                    erro = f"'{nome_arquivo}': {erro}"
                self._fila_resultados.put(("pagina", numero, imagem_bgr, imagem_processada, registros, erro))
                self._proximo_numero_pagina = numero + 1
        except Exception as exc:
            logging.exception("Falha inesperada processando lote de imagens")
            self._fila_resultados.put(("erro_fatal", "Erro inesperado processando as imagens", str(exc)))
            return

        self._fila_resultados.put(("fim", total))

    def _worker_pdf(self, caminho_pdf):
        try:
            total = pdf_reader.contar_paginas(caminho_pdf)
        except Exception as exc:
            self._fila_resultados.put(("erro_fatal", "Erro ao abrir o PDF", str(exc)))
            return
        self._fila_resultados.put(("total", total))

        nome_pdf = os.path.basename(caminho_pdf)
        try:
            for pagina_pdf in pdf_reader.iterar_paginas(caminho_pdf):
                numero = self._proximo_numero_pagina
                # Fase 14 (rastreabilidade): DOIS números coexistem e não
                # podem ser confundidos -- `numero` é a posição da folha no
                # lote (o que vai para a coluna Página da planilha, e o que
                # preserva a ordem física), e `pagina_pdf.numero` é a página
                # DENTRO deste arquivo. Eles só coincidem quando o PDF é a
                # primeira coisa processada na sessão; a partir do segundo
                # arquivo divergem. A mensagem antes citava só o número
                # interno, então o operador via "página 3" numa linha
                # rotulada "página 8" e não tinha como saber qual folha
                # conferir. Agora a origem vem nomeada e completa.
                origem = f"página {pagina_pdf.numero} de '{nome_pdf}'"
                if pagina_pdf.erro:
                    self._fila_resultados.put(
                        ("pagina", numero, None, None, [],
                         f"Falha ao renderizar a {origem}: {pagina_pdf.erro}")
                    )
                else:
                    imagem_processada, registros, erro = self._processar_uma_pagina(pagina_pdf.imagem)
                    if erro:
                        erro = f"{origem}: {erro}"
                    self._fila_resultados.put(("pagina", numero, pagina_pdf.imagem, imagem_processada, registros, erro))
                self._proximo_numero_pagina = numero + 1
        except Exception as exc:
            self._fila_resultados.put(("erro_fatal", "Erro inesperado processando o PDF", str(exc)))
            return

        self._fila_resultados.put(("fim", total))

    # ==================================================================
    # Consumo da fila (thread principal)
    # ==================================================================
    def _verificar_fila(self):
        try:
            while True:
                item = self._fila_resultados.get_nowait()
                try:
                    self._processar_item(item)
                except Exception:
                    # Fase 8 (segurança do lote): antes, uma exceção
                    # inesperada processando UM item (ex.: um dado
                    # malformado vindo do worker) escapava daqui, e como
                    # isso acontece dentro de um callback agendado via
                    # self.after, o Tkinter só reporta no console e segue
                    # -- MAS o `self.after(100, self._verificar_fila)` lá
                    # embaixo nunca era reagendado, então o polling da
                    # fila parava para sempre. O worker continuava
                    # rodando e enfileirando páginas normalmente, só que
                    # ninguém mais as consumia: a UI parecia travada em
                    # "Processando...", sem nunca gerar a XLSX, com o
                    # lote inteiro (até ~50 páginas de OCR já feito)
                    # preso na fila em memória. Isola cada item da mesma
                    # forma que cada página já é isolada nos workers --
                    # um item ruim é só logado, e a fila continua.
                    logging.exception("Falha ao processar item da fila de resultados (item ignorado, lote continua)")
        except queue.Empty:
            pass
        if self._processando:
            self.after(100, self._verificar_fila)

    def _processar_item(self, item):
        tipo = item[0]

        if tipo == "erro_fatal":
            _, titulo, mensagem = item
            self._finalizar_processamento()
            self.lbl_status.config(text=f"Erro: {titulo}")
            messagebox.showerror(titulo, mensagem)
            return

        if tipo == "total":
            self._total_paginas_lote = item[1]
            self._atualizar_status()
            return

        if tipo == "pagina":
            _, numero, imagem_original, imagem_processada, registros, erro = item
            self._paginas_processadas += 1
            self._paginas_processadas_lote += 1
            if erro:
                self._paginas_com_erro += 1
                self._erros_paginas.append({"pagina": numero, "mensagem": erro})
                self._registros_exportacao.append(self._registro_erro_pagina(numero, erro))
            else:
                if imagem_original is not None and imagem_processada is not None:
                    # Fase 19: a imagem original (26,8 MB) e a processada
                    # (2,9 MB) NÃO ficam mais guardadas na App. Elas eram
                    # atribuídas a `self._imagem_original`/`_imagem_processada`
                    # desde antes da Fase 10, quando o topo da tela tinha as
                    # duas pré-visualizações; aquele redesenho removeu os
                    # painéis e as atribuições ficaram para trás -- eram
                    # escritas e nunca lidas. O efeito era reter 29,7 MB por
                    # página: durante o OCR da página seguinte a App ainda
                    # segurava as duas matrizes da anterior, e ao fim do lote
                    # as da última folha ficavam vivas pelo resto da sessão.
                    # O que a revisão usa é a miniatura JPEG logo abaixo.
                    # Guarda a foto desta página para a aba de Revisão: sem
                    # ela, o operador teria de abrir o arquivo por fora para
                    # conferir o que está escrito no papel.
                    miniatura = _comprimir_para_miniatura(imagem_original)
                    if miniatura is not None:
                        self._miniaturas_por_pagina[numero] = miniatura
                self._adicionar_registros(numero, registros)

                # PROBLEMA 2: 8 posições esperadas por folha, só como
                # restrição de validação -- nunca fabrica nem descarta
                # registro nenhum, só avisa quando a contagem diverge.
                aviso_contagem = verificar_contagem_posicoes(len(registros))
                if aviso_contagem:
                    self._avisos_contagem.append({"pagina": numero, "mensagem": aviso_contagem})

            # Fase 8 (segurança do lote): só em uma LEVA de verdade (PDF
            # ou seleção múltipla de imagens -- _total_paginas_lote
            # conhecido; uma imagem única não aciona isto, ver
            # _autosave_lote). Protege contra a perda TOTAL de ~50
            # páginas de OCR (quase 1h de trabalho) se o processo inteiro
            # morrer antes do operador clicar "Gerar planilha" -- algo
            # que nenhum try/except em Python evita (ex.: uma falha
            # nativa fora do interpretador).
            if self._total_paginas_lote:
                self._autosave_lote()

            self._atualizar_status()
            self._atualizar_avisos()
            return

        if tipo == "fim":
            self._finalizar_processamento()
            self._atualizar_status(concluido=True)
            self._atualizar_painel_revisao()
            return

    def _atualizar_status(self, concluido=False):
        # Fase 7 (operação em lote): enquanto processando, mostra
        # progresso "X/Y" da leva atual quando o total é conhecido (PDF,
        # ou seleção múltipla de imagens) -- um lote de ~50 folhas reais
        # leva bem mais de meia hora, e não ter nenhum indício de quanto
        # falta é o tipo de incerteza que leva o operador a fechar o
        # programa achando que travou, perdendo tudo que já tinha sido
        # processado (nada é salvo em disco até "Gerar planilha").
        if not concluido and self._total_paginas_lote:
            rotulo_paginas = f"Página {self._paginas_processadas_lote}/{self._total_paginas_lote}"
        else:
            rotulo_paginas = f"Páginas: {self._paginas_processadas}"
        partes = [
            rotulo_paginas,
            f"Confirmados: {self._contador_confirmados}",
            f"Revisão: {self._contador_revisao}",
        ]
        if self._paginas_com_erro:
            partes.append(f"Páginas com erro: {self._paginas_com_erro}")
        prefixo = "Concluído — " if concluido else "Processando... "
        self.lbl_status.config(text=prefixo + " | ".join(partes))

        self._atualizar_progresso(concluido)
        self._atualizar_rotulos_abas()

    def _mostrar_progresso(self, visivel):
        """A barra só ocupa espaço enquanto há lote rodando."""
        try:
            if visivel and not self._frame_progresso.winfo_ismapped():
                self._frame_progresso.pack(side="top", fill="x", before=self.abas)
            elif not visivel and self._frame_progresso.winfo_ismapped():
                self._frame_progresso.pack_forget()
        except Exception:
            logging.exception("Falha ao alternar a barra de progresso (apenas cosmético)")

    def _atualizar_progresso(self, concluido=False):
        if concluido or not self._processando:
            self._mostrar_progresso(False)
            return
        self._mostrar_progresso(True)
        if self._total_paginas_lote:
            pct = 100.0 * self._paginas_processadas_lote / self._total_paginas_lote
            self.barra_progresso.config(value=pct)
            self.lbl_progresso.config(
                text=f"{self._paginas_processadas_lote}/{self._total_paginas_lote} ({pct:.0f}%)"
            )
        else:
            # Total desconhecido (imagem única): sem denominador não há
            # percentual honesto a mostrar -- a barra vira indeterminada.
            self.barra_progresso.config(value=0)
            self.lbl_progresso.config(text="Processando...")

    def _atualizar_rotulos_abas(self):
        """Contadores nas abas: onde há trabalho pendente fica visível sem
        precisar entrar na aba."""
        try:
            self.abas.tab(0, text=f"Registros ({len(self._registros_exportacao)})")
            pendentes = len(self._indices_pendentes_revisao())
            self.abas.tab(1, text=f"Revisão ({pendentes})" if pendentes else "Revisão")
            total_avisos = (
                len(self._erros_paginas) + len(self._avisos_contagem)
                + len(self._avisos_descarte) + len(self._data_manager.avisos)
            )
            self.abas.tab(2, text=f"Avisos ({total_avisos})" if total_avisos else "Avisos")
        except Exception:
            logging.exception("Falha ao atualizar os rótulos das abas (apenas cosmético)")

    # ==================================================================
    # Registros -> tabela + lista de exportação
    # ==================================================================
    def _registro_erro_pagina(self, numero_pagina, mensagem):
        return {
            "data": "", "hora": "", "matricula": "", "nome": "", "cargo": "", "setor": "",
            "gestor": "", "motivo": "",
            "pagina_origem": numero_pagina, "status": "ERRO",
            "confianca_matricula": "", "confianca_gestor": "", "confianca_motivo": "",
            "observacao": mensagem, "texto_ocr_original": "",
        }

    def _adicionar_registros(self, numero_pagina, registros):
        # Contexto do lote ANTES de classificar: as datas completas desta
        # página também valem como evidência para as linhas dela que vieram
        # sem ano. Só entram datas que se interpretam por completo (ver
        # ContextoLote.registrar_data) -- uma data recuperada por contexto
        # nunca realimenta o contexto.
        for registro in registros:
            campo_data = registro.campos.get("data")
            self._contexto_lote.registrar_data(campo_data.texto if campo_data else "")

        for registro in registros:
            campo_matricula = registro.campos.get("matricula")
            texto_matricula = campo_matricula.texto if campo_matricula else ""
            # Primeiro as confusões já conhecidas (O->0, I->1, S->5, B->8,
            # só quando o texto já parece matrícula), depois a recuperação
            # contextual dos caracteres que sobraram (ex.: "+" -> 7), que
            # usa a base de colaboradores como evidência.
            matricula_normalizada = normalizar_matricula(texto_matricula) if texto_matricula else ""
            resultado_matricula = resolver_matricula(
                matricula_normalizada,
                existe_na_base=(
                    (lambda m: self._data_manager.buscar_colaborador(m) is not None)
                    if self._data_manager.colaboradores_disponivel else None
                ),
            )
            # A matrícula exibida/exportada é SEMPRE só dígitos (requisito
            # funcional): quando a recuperação não conseguiu chegar a uma
            # leitura só-dígitos, a célula sai VAZIA em vez de levar o
            # texto cru do OCR ("1954+", "195.4"). Nada se perde -- o texto
            # original continua na coluna técnica de OCR, na Observação e
            # no aviso "Linhas sem matrícula".
            matricula_normalizada = resultado_matricula.matricula or ""

            colaborador = None
            if registro.completo and resultado_matricula.status != "AMBIGUA":
                colaborador = self._data_manager.buscar_colaborador(matricula_normalizada)

            resultado_classificacao = classificar_registro(
                registro, colaborador, self._data_manager,
                resultado_matricula=resultado_matricula,
                contexto_lote=self._contexto_lote,
            )
            status, observacao = resultado_classificacao.status, resultado_classificacao.observacao
            if status == "CONFIRMADO":
                self._contador_confirmados += 1
            else:
                self._contador_revisao += 1

            nome = colaborador["nome"] if colaborador else NAO_ENCONTRADO
            cargo = colaborador["cargo"] if colaborador else NAO_ENCONTRADO
            setor = colaborador["setor"] if colaborador else NAO_ENCONTRADO
            # DATA sai sempre no formato canônico dd/mm/aa; quando não pôde
            # ser interpretada com segurança, a célula sai VAZIA (o registro
            # já está em REVISAO). Mesma regra da Hora, e pelo mesmo motivo:
            # escrever "23.04" ou "14.0.4.26" na coluna Data misturaria
            # formatos na planilha e o valor seria indistinguível de uma
            # data de verdade. O texto cru do OCR não se perde -- fica na
            # Observação (ver validacao.validar_data) e na coluna técnica.
            data_ = resultado_classificacao.data_confirmada or ""
            # HORA é campo OPCIONAL: só vai para a tabela/planilha quando
            # pôde ser interpretada com segurança. Ausente ou ilegível, sai
            # VAZIA -- nunca com o texto ilegível do OCR, que seria
            # indistinguível de uma hora real. O texto bruto não some: fica
            # registrado na Observação (ver validacao.avaliar_hora_opcional).
            hora = resultado_classificacao.hora_confirmada or ""
            # PROBLEMAS 3/4: quando a correspondência aproximada aceitou uma
            # correção (ver validacao.py/correspondencia_aproximada.py), usa
            # o valor normalizado na tabela/planilha; o texto bruto do OCR
            # continua disponível na Observação quando isso acontece, e como
            # fallback aqui quando não houve correção nenhuma.
            gestor = resultado_classificacao.gestor_confirmado or _texto_campo(registro, "gestor")
            motivo = resultado_classificacao.motivo_confirmado or _texto_campo(registro, "motivo")
            campo_gestor = registro.campos.get("gestor")
            campo_motivo = registro.campos.get("motivo")

            conf_matricula = campo_matricula.confianca if campo_matricula else None

            # Aviso explícito de linha sem matrícula identificável. O
            # registro NÃO é descartado (vai para REVISAO com o que tem --
            # perder uma liberação real seria pior), mas o operador
            # precisa saber que ela existe e por quê: é a linha que ele
            # terá de conferir no papel.
            if not resultado_matricula.matricula:
                self._avisos_descarte.append({
                    "pagina": numero_pagina,
                    "mensagem": (
                        f"linha sem matrícula identificável"
                        + (f" (OCR leu: '{texto_matricula}')" if texto_matricula else " (coluna vazia)")
                        + " -- mantida em REVISÃO, nenhuma matrícula foi inventada"
                    ),
                })

            self._registros_exportacao.append({
                "data": data_, "hora": hora,
                "matricula": matricula_normalizada,
                "nome": nome, "cargo": cargo, "setor": setor,
                "gestor": gestor, "motivo": motivo,
                "pagina_origem": numero_pagina, "status": status,
                "confianca_matricula": conf_matricula,
                "confianca_gestor": campo_gestor.confianca if campo_gestor else "",
                "confianca_motivo": campo_motivo.confianca if campo_motivo else "",
                "observacao": observacao,
                "texto_ocr_original": texto_matricula,
                # Texto que o OCR leu nesta linha e o parser não conseguiu
                # associar a coluna nenhuma. Guardado para a revisão manual
                # poder rodar a MESMA checagem de integridade do fluxo
                # automático (ver _revisao_confirmar). Chave técnica: o
                # xlsx_exporter só lê as colunas que conhece e ignora esta.
                "ocr_nao_associados": [
                    c.texto for c in (registro.nao_associados or []) if (c.texto or "").strip()
                ],
                # Fase 17 (motor de evidências): o dossiê do registro, em
                # dados puros. Mesma natureza de chave técnica que
                # `ocr_nao_associados` acima -- fica no dict de exportação
                # e FORA das COLUNAS do xlsx_exporter, portanto não aparece
                # na planilha. Esta fase não expõe evidência ao usuário
                # final: quem vai consumir isto é a Fase 18.
                "evidencias": resultado_classificacao.dossie.como_dicionarios(),
            })

        self._sincronizar_tabela_principal()
        self._atualizar_botao_revisao()

    # ==================================================================
    # Tabela principal
    # ==================================================================
    @staticmethod
    def _rotulo_status(status: str, observacao: str = "") -> str:
        """Rótulo curto da coluna Status. A razão (observação) tem coluna
        própria desde a Fase 10 -- juntar as duas espremia o texto que o
        operador precisa ler."""
        if status == "CONFIRMADO":
            return "✓ CONFIRMADO"
        if status == "ERRO":
            return "✗ ERRO"
        return "⚠ REVISÃO"

    @staticmethod
    def _tag_status(status: str) -> str:
        return {"CONFIRMADO": "confirmado", "ERRO": "erro"}.get(status, "revisao")

    def _registro_passa_no_filtro(self, registro) -> bool:
        filtro = self.filtro_var.get() if hasattr(self, "filtro_var") else "Todos"
        if filtro == "Confirmados":
            return registro["status"] == "CONFIRMADO"
        if filtro == "Em revisão":
            return registro["status"] == "REVISAO"
        if filtro == "Com erro":
            return registro["status"] == "ERRO"
        return True

    def _sincronizar_tabela_principal(self):
        """Reconstrói a tabela a partir de self._registros_exportacao,
        aplicando o filtro atual. É o único ponto que escreve na tabela --
        assim ela nunca fica fora de sincronia com os dados de exportação
        (que são a fonte da verdade e o que vai para a planilha)."""
        self.tabela.delete(*self.tabela.get_children())
        mostrados = 0
        for indice, r in enumerate(self._registros_exportacao):
            if not self._registro_passa_no_filtro(r):
                continue
            mostrados += 1
            conf = r.get("confianca_matricula")
            conf_str = f"{conf * 100:.0f}%" if isinstance(conf, (int, float)) else "N/D"
            self.tabela.insert(
                "", "end", iid=str(indice),
                values=(
                    r["pagina_origem"], self._rotulo_status(r["status"]), r["data"], r["hora"],
                    r["matricula"], r["nome"], r["setor"], r["motivo"], r["gestor"],
                    r["cargo"], conf_str, r["observacao"],
                ),
                tags=(self._tag_status(r["status"]),),
            )
        if hasattr(self, "lbl_contagem_tabela"):
            total = len(self._registros_exportacao)
            texto = f"{mostrados} de {total} registro(s)" if total else "nenhum registro ainda"
            self.lbl_contagem_tabela.config(text=texto)
        self._atualizar_rotulos_abas()

    def _on_duplo_clique_tabela(self, _evento=None):
        """Duplo clique numa linha em revisão abre exatamente aquela linha
        na aba de Revisão."""
        selecao = self.tabela.selection()
        if not selecao:
            return
        try:
            indice = int(selecao[0])
        except (TypeError, ValueError):
            return
        if self._registros_exportacao[indice]["status"] != "REVISAO":
            return
        pendentes = self._indices_pendentes_revisao()
        if indice in pendentes:
            self._abrir_revisao(posicao=pendentes.index(indice))

    def _atualizar_botao_revisao(self):
        if self._contador_revisao:
            self.btn_revisao.config(text=f"Revisar ({self._contador_revisao})", state="normal")
        else:
            self.btn_revisao.config(text="Revisar (0)", state="disabled")

    # ==================================================================
    # Avisos
    # ==================================================================
    def _atualizar_avisos(self):
        self.tabela_avisos.delete(*self.tabela_avisos.get_children())
        for aviso in self._data_manager.avisos:
            self.tabela_avisos.insert("", "end", values=("Base de dados", "—", aviso))
        for e in self._erros_paginas:
            self.tabela_avisos.insert("", "end", values=("Erro de página", e["pagina"], e["mensagem"]))
        for a in self._avisos_contagem:
            self.tabela_avisos.insert("", "end", values=("Contagem de posições", a["pagina"], a["mensagem"]))
        for a in self._avisos_descarte:
            self.tabela_avisos.insert("", "end", values=("Linha sem matrícula", a["pagina"], a["mensagem"]))
        self._atualizar_rotulos_abas()

    # Mantidos: o fluxo por messagebox continua disponível (e é o que os
    # testes de regressão exercitam), agora além da aba consolidada.
    def _mostrar_avisos_bases(self):
        if not self._data_manager.avisos:
            return
        msg = "\n\n".join(self._data_manager.avisos)
        msg += "\n\nColoque os arquivos em dados/ e reabra o programa."
        messagebox.showwarning("Avisos sobre as bases de dados", msg)

    def _mostrar_erros_paginas(self):
        if not self._erros_paginas:
            return
        msg = "\n\n".join(f"Página {e['pagina']}: {e['mensagem']}" for e in self._erros_paginas)
        messagebox.showwarning("Erros de página", msg)

    def _mostrar_avisos_contagem(self):
        if not self._avisos_contagem:
            return
        msg = "\n\n".join(f"Página {a['pagina']}: {a['mensagem']}" for a in self._avisos_contagem)
        messagebox.showwarning("Avisos de contagem de posições", msg)

    def _mostrar_avisos_descarte(self):
        if not self._avisos_descarte:
            return
        msg = "\n\n".join(f"Página {a['pagina']}: {a['mensagem']}" for a in self._avisos_descarte)
        messagebox.showwarning("Linhas sem matrícula identificável", msg)

    # ==================================================================
    # Limpar / salvar
    # ==================================================================
    def _on_limpar(self):
        if self._processando:
            return
        self._registros_exportacao = []
        self._erros_paginas = []
        self._avisos_contagem = []
        self._avisos_descarte = []
        self._contador_confirmados = 0
        self._contador_revisao = 0
        self._paginas_processadas = 0
        self._paginas_com_erro = 0
        self._total_paginas_lote = None
        self._paginas_processadas_lote = 0
        self._proximo_numero_pagina = 1
        self._miniaturas_por_pagina = {}
        self._revisao_indices = []
        self._revisao_posicao = 0
        # O contexto do lote é evidência das folhas que estavam na tabela:
        # limpar os resultados tem de limpá-lo junto, senão o ano de um lote
        # completaria datas do lote seguinte.
        self._contexto_lote = ContextoLote()
        self.btn_salvar.config(state="disabled")
        self._atualizar_botao_revisao()
        self._sincronizar_tabela_principal()
        self._atualizar_avisos()
        self._atualizar_painel_revisao()
        self.barra_progresso.config(value=0)
        self.lbl_progresso.config(text="")
        self.lbl_status.config(text="Resultados limpos. Nenhum arquivo selecionado.")

    @staticmethod
    def _pasta_saida_padrao() -> str:
        # app.py está em src/leitor_matriculas/ui/ -- a raiz do projeto
        # fica 3 níveis acima (ui -> leitor_matriculas -> src -> raiz),
        # mesmo cálculo já usado em dados/data_manager.py para achar a
        # pasta dados/ a partir de um módulo na mesma profundidade.
        raiz_projeto = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
        )
        return os.path.join(raiz_projeto, "saida")

    def _autosave_lote(self):
        """
        Fase 8 (segurança do lote): salva uma cópia de segurança de TUDO
        que já foi processado até agora, reaproveitando exatamente o
        mesmo xlsx_exporter.export_to_xlsx que "Gerar planilha" usa --
        mesmo formato, mesma ordem física, nenhuma dependência nova. Se
        o processo inteiro morrer no meio de um lote de ~50 páginas
        (quase 1h de OCR), o operador não perde tudo: reabre este
        arquivo, que tem tudo que já tinha sido processado até a última
        página antes da falha.

        Nunca pode interromper o processamento: qualquer falha aqui
        (arquivo aberto no Excel, disco cheio, pasta sem permissão) é só
        registrada no log -- o lote continua normalmente, exatamente
        como qualquer outro isolamento de falha já existente no projeto.
        """
        if not self._registros_exportacao:
            return
        try:
            pasta_saida = self._pasta_saida_padrao()
            os.makedirs(pasta_saida, exist_ok=True)
            caminho = os.path.join(pasta_saida, "Liberacoes_autosave.xlsx")
            xlsx_exporter.export_to_xlsx(
                self._registros_exportacao, caminho,
                paginas_processadas=self._paginas_processadas,
                paginas_com_erro=self._paginas_com_erro,
                paginas_com_contagem_divergente=len(self._avisos_contagem),
            )
        except Exception:
            logging.exception("Falha ao salvar cópia de segurança automática (lote continua normalmente)")

    def _on_salvar(self):
        if not self._registros_exportacao:
            messagebox.showwarning("Nada para salvar", "Ainda não há registros processados.")
            return
        path = filedialog.asksaveasfilename(
            title="Salvar planilha como", defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")], initialfile="Liberacoes.xlsx",
        )
        if not path:
            return
        try:
            xlsx_exporter.export_to_xlsx(
                self._registros_exportacao, path,
                paginas_processadas=self._paginas_processadas,
                paginas_com_erro=self._paginas_com_erro,
                paginas_com_contagem_divergente=len(self._avisos_contagem),
            )
        except Exception as exc:
            messagebox.showerror("Erro ao salvar XLSX", str(exc))
            return

        messagebox.showinfo("Salvo", f"Planilha salva em:\n{path}")
        pasta = os.path.dirname(os.path.abspath(path))
        if hasattr(os, "startfile"):  # só existe no Windows
            try:
                os.startfile(pasta)
            except Exception:
                pass

    # ==================================================================
    # REVISÃO (aba integrada)
    #
    # A API abaixo (_indices_pendentes_revisao / _revisao_ir_para /
    # _revisao_confirmar) é o contrato programático da revisão: é por ela
    # que o teste de integração dirige a aba, em vez de caçar widgets na
    # árvore do Tk. Isso mantém o teste verificando COMPORTAMENTO (o que
    # pode ou não virar CONFIRMADO) em vez de layout.
    # ==================================================================
    def _indices_pendentes_revisao(self):
        """
        Índices, em `_registros_exportacao`, das linhas que a revisão
        manual pode tratar -- na ordem física da folha.

        Fase 7 (PROBLEMA E): SÓ status REVISAO. Linhas ERRO (falha de
        página inteira: OCR não rodou, PDF não abriu) não têm nenhum campo
        de verdade para corrigir, e deixar o operador digitar valores do
        zero seria inventar dado sem nenhuma evidência de OCR por trás.
        Página com ERRO precisa ser reprocessada, não corrigida campo a
        campo (ver aba Avisos).
        """
        return [i for i, r in enumerate(self._registros_exportacao) if r["status"] == "REVISAO"]

    def _abrir_revisao(self, posicao=None):
        """Leva para a aba de Revisão (antes da Fase 10 isto abria uma
        janela Toplevel separada)."""
        pendentes = self._indices_pendentes_revisao()
        if not pendentes:
            if self._erros_paginas:
                messagebox.showinfo(
                    "Revisão",
                    "Não há registros em revisão manual.\n\n"
                    f"Há {len(self._erros_paginas)} página(s) com ERRO de processamento — "
                    "veja a aba \"Avisos\" (essas páginas precisam ser "
                    "reprocessadas, não corrigidas campo a campo).",
                )
            else:
                messagebox.showinfo("Revisão", "Não há registros pendentes de revisão.")
            return

        if posicao is not None:
            self._revisao_posicao = max(0, min(posicao, len(pendentes) - 1))
        self._atualizar_painel_revisao()
        try:
            self.abas.select(self._aba_revisao)
        except Exception:
            logging.exception("Falha ao selecionar a aba de Revisão")

    def _revisao_ir_para(self, posicao):
        """Posiciona a revisão no n-ésimo pendente e recarrega o
        formulário. Usado pela navegação e pelo teste de integração."""
        pendentes = self._indices_pendentes_revisao()
        if not pendentes:
            return
        self._revisao_posicao = max(0, min(int(posicao), len(pendentes) - 1))
        self._atualizar_painel_revisao()

    def _revisao_navegar(self, passo):
        pendentes = self._indices_pendentes_revisao()
        if not pendentes:
            return
        self._revisao_ir_para((self._revisao_posicao + passo) % len(pendentes))

    def _revisao_registro_atual(self):
        pendentes = self._indices_pendentes_revisao()
        if not pendentes:
            return None, None
        posicao = max(0, min(self._revisao_posicao, len(pendentes) - 1))
        indice = pendentes[posicao]
        return indice, self._registros_exportacao[indice]

    def _atualizar_painel_revisao(self):
        """Recarrega o formulário e a foto a partir do registro atual."""
        pendentes = self._indices_pendentes_revisao()
        habilitado = "normal" if pendentes else "disabled"
        for widget in list(self.revisao_widgets.values()) + [
            self.btn_revisao_anterior, self.btn_revisao_proximo, self.btn_revisao_confirmar
        ]:
            try:
                widget.config(state=habilitado)
            except Exception:
                pass

        if not pendentes:
            for var in self.revisao_vars.values():
                var.set("")
            self.lbl_revisao_posicao.config(text="Nenhum registro pendente de revisão")
            self.lbl_revisao_motivo.config(text="")
            self._mostrar_explicacao_revisao(None, None)
            self.lbl_revisao_nome.config(text="—")
            self.lbl_revisao_setor.config(text="")
            self.lbl_revisao_resultado.config(text="")
            self.lbl_pagina_foto.config(text="")
            self.canvas_foto.delete("all")
            self._foto_revisao = None
            self._atualizar_rotulos_abas()
            return

        _indice, registro = self._revisao_registro_atual()
        posicao = self._revisao_posicao + 1
        self.lbl_revisao_posicao.config(
            text=f"Pendente {posicao} de {len(pendentes)}  ·  página {registro['pagina_origem']}"
        )
        self.lbl_revisao_motivo.config(text=registro.get("observacao") or "")
        # Fase 18: a explicação é montada ANTES de preencher os campos, e é
        # só leitura -- `revisao_vars` continua recebendo exclusivamente o
        # valor JÁ apurado do registro. Nenhuma sugestão entra aqui: um
        # campo pré-preenchido com palpite viraria dado confirmado no
        # clique seguinte, que é exatamente o que esta fase não pode fazer.
        self._mostrar_explicacao_revisao(_indice, registro)
        for chave in ("data", "hora", "matricula", "motivo", "gestor"):
            self.revisao_vars[chave].set(registro.get(chave) or "")
        self._atualizar_derivados_revisao(registro)
        self.lbl_revisao_resultado.config(text="")
        self._mostrar_foto_pagina(registro["pagina_origem"])
        self._atualizar_rotulos_abas()

    def _explicacao_revisao_atual(self):
        """
        Contrato programático da Fase 18 (mesmo espírito de
        `_indices_pendentes_revisao`): devolve
        `(ExplicacaoRevisao, [Evidencia de contexto])` da linha em revisão,
        para o teste de integração verificar COMPORTAMENTO sem caçar
        widgets na árvore do Tk.
        """
        indice, registro = self._revisao_registro_atual()
        if registro is None:
            return explicacao_revisao.ExplicacaoRevisao(), []
        explicacao = explicacao_revisao.explicar(
            registro.get("evidencias"), registro.get("observacao") or ""
        )
        sinais = explicacao_revisao.sinais_de_contexto(self._registros_exportacao, indice)
        return explicacao, sinais

    def _mostrar_explicacao_revisao(self, indice, registro):
        """Escreve a explicação e os sinais de contexto na tela. Só desenha
        -- não toca em `revisao_vars` nem em nada do registro."""
        if registro is None:
            self.lbl_revisao_explicacao.config(text="")
            self.lbl_revisao_contexto.config(text="")
            self.moldura_revisao_explicacao.pack_forget()
            self.lbl_revisao_contexto.pack_forget()
            return

        try:
            explicacao, sinais = self._explicacao_revisao_atual()
        except Exception:
            # Explicar é conveniência: se falhar, a revisão continua
            # funcionando exatamente como antes da Fase 18.
            logging.exception("Falha ao montar a explicação da revisão")
            explicacao, sinais = explicacao_revisao.ExplicacaoRevisao(), []

        texto = explicacao.como_texto()
        self.lbl_revisao_explicacao.config(text=texto)

        # Contexto vem com prefixo próprio e estilo próprio para nunca se
        # confundir com o dado confirmado do registro.
        if sinais:
            partes = []
            for sinal in sinais:
                parte = f"ⓘ {sinal.motivo}"
                if sinal.valor_observado:
                    parte += f"\n    {sinal.valor_observado}"
                partes.append(parte)
            self.lbl_revisao_contexto.config(text="\n".join(partes))
            self.lbl_revisao_contexto.pack(side="top", fill="x", anchor="w", pady=(8, 0))
        else:
            self.lbl_revisao_contexto.config(text="")
            self.lbl_revisao_contexto.pack_forget()

        if texto or sinais:
            self.moldura_revisao_explicacao.pack(
                side="top", fill="x", pady=(0, 10), before=self.moldura_revisao_campos
            )
        else:
            self.moldura_revisao_explicacao.pack_forget()

    def _atualizar_derivados_revisao(self, registro):
        nome = registro.get("nome") or "—"
        setor = registro.get("setor") or ""
        cargo = registro.get("cargo") or ""
        self.lbl_revisao_nome.config(text=nome)
        detalhe = " · ".join(p for p in (setor, cargo) if p and p != NAO_ENCONTRADO)
        self.lbl_revisao_setor.config(text=detalhe or "")

    # ------------------------------------------------------------------
    # Foto da folha
    # ------------------------------------------------------------------
    def _mostrar_foto_pagina(self, numero_pagina):
        self.canvas_foto.delete("all")
        self._foto_revisao = None
        dados = self._miniaturas_por_pagina.get(numero_pagina)
        if dados is None:
            self.lbl_pagina_foto.config(text="(foto indisponível)")
            self.canvas_foto.create_text(
                12, 12, anchor="nw", fill="#868e96",
                text="A foto desta página não está disponível\n"
                     "(página com erro, ou resultados carregados sem imagem).",
            )
            return
        self.lbl_pagina_foto.config(text=f"página {numero_pagina}")
        self._imagem_pil_revisao = Image.open(io.BytesIO(dados))
        self._ajustar_zoom_para_caber()

    def _redesenhar_foto(self):
        imagem = getattr(self, "_imagem_pil_revisao", None)
        if imagem is None:
            return
        largura = max(1, int(imagem.width * self._revisao_zoom))
        altura = max(1, int(imagem.height * self._revisao_zoom))
        redimensionada = imagem.resize((largura, altura), Image.LANCZOS)
        self._foto_revisao = ImageTk.PhotoImage(redimensionada)
        self.canvas_foto.delete("all")
        self.canvas_foto.create_image(0, 0, anchor="nw", image=self._foto_revisao)
        self.canvas_foto.config(scrollregion=(0, 0, largura, altura))

    def _ajustar_zoom(self, fator):
        if getattr(self, "_imagem_pil_revisao", None) is None:
            return
        self._revisao_zoom = max(0.1, min(4.0, self._revisao_zoom * fator))
        self._redesenhar_foto()

    def _ajustar_zoom_para_caber(self):
        imagem = getattr(self, "_imagem_pil_revisao", None)
        if imagem is None:
            return
        self.canvas_foto.update_idletasks()
        largura_disponivel = max(1, self.canvas_foto.winfo_width())
        altura_disponivel = max(1, self.canvas_foto.winfo_height())
        # Antes de a janela ser desenhada, winfo_* devolve 1 -- nesse caso
        # um zoom "para caber" seria absurdo; usa 1.0 e deixa o operador
        # ajustar (ou o próximo clique em "Ajustar" já pega o tamanho real).
        if largura_disponivel <= 1 or altura_disponivel <= 1:
            self._revisao_zoom = 1.0
        else:
            self._revisao_zoom = min(
                largura_disponivel / imagem.width, altura_disponivel / imagem.height, 1.0
            )
        self._redesenhar_foto()

    # ------------------------------------------------------------------
    # Confirmação da correção
    # ------------------------------------------------------------------
    def _revisao_confirmar(self):
        """
        Fase 7 (PROBLEMAS C/D — segurança contra falso CONFIRMADO): esta
        função NÃO marca CONFIRMADO por o operador ter clicado o botão.
        Ela reconstrói um Registro com os valores digitados e roda a MESMA
        validação do fluxo automático (`classificar_registro`) -- reutiliza
        a regra existente, não cria nenhuma nova. Confiança 1.0 nos campos
        digitados: foram verificados por uma pessoa, deixaram de ser uma
        hipótese de OCR (não é um valor inventado).

        Fase 10: DATA e HORA passaram a ser editáveis aqui. Antes elas
        vinham fixas do registro, então uma linha barrada pela data era
        impossível de resolver dentro do programa.
        """
        indice, registro = self._revisao_registro_atual()
        if registro is None:
            return

        data_digitada = self.revisao_vars["data"].get().strip()
        hora_digitada = self.revisao_vars["hora"].get().strip()
        matricula_digitada = self.revisao_vars["matricula"].get().strip()
        gestor_digitado = self.revisao_vars["gestor"].get().strip()
        motivo_digitado = self.revisao_vars["motivo"].get().strip()

        # Mesmo tratamento do fluxo automático: a matrícula final só
        # pode conter dígitos, mesmo vinda de digitação manual.
        matricula_normalizada = normalizar_matricula(matricula_digitada) if matricula_digitada else ""
        resultado_matricula = resolver_matricula(
            matricula_normalizada,
            existe_na_base=(
                (lambda m: self._data_manager.buscar_colaborador(m) is not None)
                if self._data_manager.colaboradores_disponivel else None
            ),
        )
        matricula_normalizada = resultado_matricula.matricula or ""

        campos_sinteticos = {}
        if data_digitada:
            campos_sinteticos["data"] = CampoOcr(texto=data_digitada, confianca=1.0, box=None)
        if hora_digitada:
            campos_sinteticos["hora"] = CampoOcr(texto=hora_digitada, confianca=1.0, box=None)
        if matricula_normalizada:
            campos_sinteticos["matricula"] = CampoOcr(texto=matricula_normalizada, confianca=1.0, box=None)
        if gestor_digitado:
            campos_sinteticos["gestor"] = CampoOcr(texto=gestor_digitado, confianca=1.0, box=None)
        if motivo_digitado:
            campos_sinteticos["motivo"] = CampoOcr(texto=motivo_digitado, confianca=1.0, box=None)
        # A evidência de campo perdido detectada no processamento automático
        # (ver validacao/integridade.py) precisa SOBREVIVER à revisão
        # manual. Sem isto, o registro sintético nasceria sem
        # `nao_associados`, a checagem de integridade não teria o que ver, e
        # bastaria abrir a revisão e clicar em confirmar para transformar em
        # CONFIRMADO exatamente o registro que a Fase 12 passou a barrar --
        # uma porta dos fundos para o problema que ela existe para fechar.
        #
        # Isto NÃO prende o operador: a checagem só dispara quando o campo
        # continua VAZIO. Se ele digitar a hora que está no papel, o campo
        # passa a existir e a evidência deixa de bloquear.
        sobras = [
            CampoOcr(texto=texto, confianca=None, box=None)
            for texto in (registro.get("ocr_nao_associados") or [])
        ]
        registro_sintetico = Registro(indice=0, campos=campos_sinteticos, nao_associados=sobras)

        # PROBLEMA C: re-consulta a base pela matrícula corrigida --
        # Nome/Setor/Cargo têm que refletir a matrícula certa, nunca
        # ficar mostrando "(não encontrado)" para um registro que
        # acabou de ser confirmado com uma matrícula válida.
        colaborador = (
            self._data_manager.buscar_colaborador(matricula_normalizada) if matricula_normalizada else None
        )

        resultado = classificar_registro(
            registro_sintetico, colaborador, self._data_manager,
            resultado_matricula=resultado_matricula,
            contexto_lote=self._contexto_lote,
        )

        registro["matricula"] = matricula_normalizada
        registro["nome"] = colaborador["nome"] if colaborador else NAO_ENCONTRADO
        registro["cargo"] = colaborador["cargo"] if colaborador else NAO_ENCONTRADO
        registro["setor"] = colaborador["setor"] if colaborador else NAO_ENCONTRADO
        registro["data"] = resultado.data_confirmada or ""
        registro["hora"] = resultado.hora_confirmada or ""
        registro["gestor"] = resultado.gestor_confirmado or gestor_digitado
        registro["motivo"] = resultado.motivo_confirmado or motivo_digitado
        # O dossiê acompanha a REavaliação: depois de uma correção manual,
        # a evidência que vale é a da decisão que acabou de ser tomada, não
        # a da leitura original do OCR (que continua registrada dentro do
        # próprio dossiê, como `ocr_bruto`).
        registro["evidencias"] = resultado.dossie.como_dicionarios()
        if matricula_normalizada:
            registro["confianca_matricula"] = 1.0
        if gestor_digitado:
            registro["confianca_gestor"] = 1.0
        if motivo_digitado:
            registro["confianca_motivo"] = 1.0

        status_anterior = registro["status"]
        registro["status"] = resultado.status
        if resultado.status == "CONFIRMADO":
            registro["observacao"] = (
                "corrigido manualmente" if not resultado.observacao
                else f"corrigido manualmente; {resultado.observacao}"
            )
        else:
            registro["observacao"] = f"revisão manual incompleta -- {resultado.observacao}"

        if resultado.status == "CONFIRMADO" and status_anterior != "CONFIRMADO":
            self._contador_revisao -= 1
            self._contador_confirmados += 1

        self._sincronizar_tabela_principal()
        self._atualizar_botao_revisao()
        self._atualizar_status(concluido=not self._processando)

        if resultado.status == "CONFIRMADO":
            # A linha saiu da lista de pendentes: a posição atual passa a
            # apontar para a PRÓXIMA pendente sozinha (a lista encolheu),
            # que é o comportamento desejado ao revisar em sequência.
            pendentes = self._indices_pendentes_revisao()
            if pendentes:
                self._revisao_posicao = min(self._revisao_posicao, len(pendentes) - 1)
            self._atualizar_painel_revisao()
            if not pendentes:
                messagebox.showinfo("Revisão", "Todos os registros pendentes foram revisados.")
        else:
            # Ainda não pôde ser confirmado -- permanece na lista, com a
            # observação atualizada, em vez de desaparecer como se
            # tivesse sido resolvido.
            self._atualizar_painel_revisao()
            self.lbl_revisao_resultado.config(
                text=f"Ainda não é possível confirmar: {resultado.observacao}",
                bootstyle="danger",
            )

    # Nome anterior mantido: o fluxo de correção manual é o mesmo.
    _confirmar = _revisao_confirmar
