"""
ui.py

Interface gráfica (Tkinter). Coordena: seleção de imagem/PDF -> pré-
processamento (image_processor) -> OCR (ocr_engine) -> parser espacial
(registro_parser) -> validação (validacao) -> tabela/revisão -> exportação
XLSX (xlsx_exporter). Toda a lógica de negócio vive nos outros módulos; a
UI só chama e apresenta.

OCR roda em thread separada (threading.Thread); a comunicação de volta usa
queue.Queue consumida só pela thread principal via self.after — a worker
thread NUNCA chama métodos do Tkinter diretamente.
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from leitor_matriculas.ocr.image_processor import preprocess_image, to_display_rgb
from leitor_matriculas.ocr.engine import get_ocr_engine, normalizar_matricula
from leitor_matriculas.dados.data_manager import DataManager
from leitor_matriculas.parsing.registro_parser import (
    CampoOcr,
    Registro,
    parse_registros,
    verificar_contagem_posicoes,
)
from leitor_matriculas.parsing.tempo_parser import tentar_separar_data_hora_mesclada
from leitor_matriculas.validacao.regras import classificar_registro
from leitor_matriculas.validacao.recuperacao_matricula import resolver_matricula
from leitor_matriculas.ocr import pdf_reader
from leitor_matriculas.exportacao import xlsx_exporter

EXTENSOES_IMAGEM = [("Imagens", "*.jpg *.jpeg *.png *.webp"), ("Todos", "*.*")]
EXTENSOES_PDF = [("PDF", "*.pdf")]
TAMANHO_PREVIEW = (380, 380)

# Placeholder explícito para Nome/Cargo/Setor quando a matrícula não pôde
# ser associada a um colaborador da base — nunca deixamos a célula "vazia
# aparentemente válida" (requisito funcional definitivo): quem olhar a
# planilha precisa ver que aquele dado é "não confirmado", não "em branco".
NAO_ENCONTRADO = "(não encontrado)"

# Ordem de exibição na tabela ao vivo (a ordem obrigatória da planilha
# final — Data/Hora/Matrícula/Nome/Setor/Motivo/Responsável — é aplicada
# em xlsx_exporter.py; aqui a tabela de acompanhamento prioriza Página/
# Status para leitura rápida durante o processamento).
COLUNAS_TABELA = (
    "pagina", "status", "data", "hora", "matricula", "nome", "setor",
    "motivo", "gestor", "cargo", "confianca",
)
CABECALHOS_TABELA = {
    "pagina": "Pág.", "status": "Status",
    "data": "Data", "hora": "Hora", "matricula": "Matrícula",
    "nome": "Nome", "setor": "Setor", "motivo": "Motivo",
    "gestor": "Responsável", "cargo": "Cargo", "confianca": "Confiança",
}


def _ler_imagem(path: str) -> np.ndarray:
    dados = np.fromfile(path, dtype=np.uint8)
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError(f"Não foi possível abrir a imagem: {path}")
    return imagem


def _para_photoimage(imagem_rgb: np.ndarray, max_size=TAMANHO_PREVIEW) -> ImageTk.PhotoImage:
    pil_img = Image.fromarray(imagem_rgb)
    pil_img.thumbnail(max_size, Image.LANCZOS)
    return ImageTk.PhotoImage(pil_img)


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
        registro.campos["hora"] = CampoOcr(texto=texto_hora, confianca=campo_fonte.confianca, box=campo_fonte.box)
        # Preserva o texto mesclado original para auditoria (nunca some).
        registro.nao_associados.append(
            CampoOcr(texto=f"[data/hora mescladas no OCR: {campo_fonte.texto!r}]", confianca=campo_fonte.confianca, box=campo_fonte.box)
        )


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Leitor de Planilhas by Elton Marques")
        self.geometry("1180x780")
        self.minsize(1000, 640)

        self._ocr_engine = None
        self._data_manager = DataManager()

        self._imagem_original = None
        self._imagem_processada = None
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

        self._montar_layout()

    # ------------------------------------------------------------------
    def _montar_layout(self):
        barra = ttk.Frame(self, padding=10)
        barra.pack(side="top", fill="x")

        self.btn_imagem = ttk.Button(barra, text="Selecionar imagem", command=self._on_selecionar_imagem)
        self.btn_imagem.pack(side="left", padx=(0, 6))
        self.btn_pdf = ttk.Button(barra, text="Selecionar PDF", command=self._on_selecionar_pdf)
        self.btn_pdf.pack(side="left", padx=(0, 6))
        self.btn_limpar = ttk.Button(barra, text="Limpar resultados", command=self._on_limpar)
        self.btn_limpar.pack(side="left", padx=(0, 6))
        self.btn_revisao = ttk.Button(barra, text="Abrir revisão (0)", command=self._abrir_revisao, state="disabled")
        self.btn_revisao.pack(side="left", padx=(0, 6))
        self.btn_salvar = ttk.Button(barra, text="Gerar planilha", command=self._on_salvar, state="disabled")
        self.btn_salvar.pack(side="left")

        info = ttk.Frame(self, padding=(10, 0, 10, 6))
        info.pack(side="top", fill="x")
        self.lbl_status = ttk.Label(info, text="Nenhum arquivo selecionado.")
        self.lbl_status.pack(side="left")

        bases = ttk.Frame(self, padding=(10, 0, 10, 10))
        bases.pack(side="top", fill="x")
        self.lbl_bases = ttk.Label(bases, text=self._data_manager.resumo_status())
        self.lbl_bases.pack(side="left")
        if self._data_manager.avisos:
            ttk.Label(bases, text="  ⚠ dados/ incompleta", foreground="#b35900").pack(side="left", padx=8)
            ttk.Button(bases, text="Ver avisos", command=self._mostrar_avisos_bases).pack(side="left")
        self.btn_erros_pag = ttk.Button(bases, text="Erros de página (0)", command=self._mostrar_erros_paginas, state="disabled")
        self.btn_erros_pag.pack(side="left", padx=8)
        self.btn_avisos_contagem = ttk.Button(
            bases, text="Avisos de contagem (0)", command=self._mostrar_avisos_contagem, state="disabled"
        )
        self.btn_avisos_contagem.pack(side="left", padx=8)
        self.btn_avisos_descarte = ttk.Button(
            bases, text="Linhas sem matrícula (0)", command=self._mostrar_avisos_descarte, state="disabled"
        )
        self.btn_avisos_descarte.pack(side="left", padx=8)

        frame_imgs = ttk.Frame(self, padding=10)
        frame_imgs.pack(side="top", fill="x")
        col_o = ttk.LabelFrame(frame_imgs, text="Última página — original", padding=5)
        col_o.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.lbl_img_original = ttk.Label(col_o)
        self.lbl_img_original.pack()
        col_p = ttk.LabelFrame(frame_imgs, text="Última página — processada", padding=5)
        col_p.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.lbl_img_processada = ttk.Label(col_p)
        self.lbl_img_processada.pack()

        frame_res = ttk.LabelFrame(self, text="Registros", padding=10)
        frame_res.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 10))
        self.tabela = ttk.Treeview(frame_res, columns=COLUNAS_TABELA, show="headings", height=12)
        larguras = {"pagina": 45, "matricula": 90, "status": 220, "nome": 140, "cargo": 100,
                    "setor": 100, "data": 70, "hora": 60, "gestor": 120, "motivo": 120, "confianca": 80}
        for c in COLUNAS_TABELA:
            self.tabela.heading(c, text=CABECALHOS_TABELA[c])
            self.tabela.column(c, width=larguras[c], anchor="center")
        vsb = ttk.Scrollbar(frame_res, orient="vertical", command=self.tabela.yview)
        hsb = ttk.Scrollbar(frame_res, orient="horizontal", command=self.tabela.xview)
        self.tabela.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tabela.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame_res.rowconfigure(0, weight=1)
        frame_res.columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    # Seleção de arquivo
    # ------------------------------------------------------------------
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

    def _finalizar_processamento(self):
        self._processando = False
        self.btn_imagem.config(state="normal")
        self.btn_pdf.config(state="normal")
        self.btn_limpar.config(state="normal")
        if self._registros_exportacao:
            self.btn_salvar.config(state="normal")

    # ------------------------------------------------------------------
    # Workers (thread separada -- nunca tocam no Tkinter diretamente)
    # ------------------------------------------------------------------
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

        try:
            for pagina_pdf in pdf_reader.iterar_paginas(caminho_pdf):
                numero = self._proximo_numero_pagina
                if pagina_pdf.erro:
                    self._fila_resultados.put(
                        ("pagina", numero, None, None, [], f"Falha ao renderizar página {pagina_pdf.numero}: {pagina_pdf.erro}")
                    )
                else:
                    imagem_processada, registros, erro = self._processar_uma_pagina(pagina_pdf.imagem)
                    self._fila_resultados.put(("pagina", numero, pagina_pdf.imagem, imagem_processada, registros, erro))
                self._proximo_numero_pagina = numero + 1
        except Exception as exc:
            self._fila_resultados.put(("erro_fatal", "Erro inesperado processando o PDF", str(exc)))
            return

        self._fila_resultados.put(("fim", total))

    # ------------------------------------------------------------------
    # Consumo da fila (thread principal)
    # ------------------------------------------------------------------
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
                self.btn_erros_pag.config(text=f"Erros de página ({self._paginas_com_erro})", state="normal")
            else:
                if imagem_original is not None and imagem_processada is not None:
                    self._imagem_original = imagem_original
                    self._imagem_processada = imagem_processada
                    self._exibir_imagens()
                self._adicionar_registros(numero, registros)

                # PROBLEMA 2: 8 posições esperadas por folha, só como
                # restrição de validação -- nunca fabrica nem descarta
                # registro nenhum, só avisa quando a contagem diverge.
                aviso_contagem = verificar_contagem_posicoes(len(registros))
                if aviso_contagem:
                    self._avisos_contagem.append({"pagina": numero, "mensagem": aviso_contagem})
                    self.btn_avisos_contagem.config(
                        text=f"Avisos de contagem ({len(self._avisos_contagem)})", state="normal"
                    )

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
            return

        if tipo == "fim":
            self._finalizar_processamento()
            self._atualizar_status(concluido=True)
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

    # ------------------------------------------------------------------
    # Registros -> tabela + lista de exportação
    # ------------------------------------------------------------------
    def _registro_erro_pagina(self, numero_pagina, mensagem):
        return {
            "data": "", "hora": "", "matricula": "", "nome": "", "cargo": "", "setor": "",
            "gestor": "", "motivo": "",
            "pagina_origem": numero_pagina, "status": "ERRO",
            "confianca_matricula": "", "confianca_gestor": "", "confianca_motivo": "",
            "observacao": mensagem, "texto_ocr_original": "",
        }

    def _adicionar_registros(self, numero_pagina, registros):
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
            # no aviso "Linhas sem matrícula" logo abaixo.
            matricula_normalizada = resultado_matricula.matricula or ""

            colaborador = None
            if registro.completo and resultado_matricula.status != "AMBIGUA":
                colaborador = self._data_manager.buscar_colaborador(matricula_normalizada)

            resultado_classificacao = classificar_registro(
                registro, colaborador, self._data_manager,
                resultado_matricula=resultado_matricula,
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
            conf_str = f"{conf_matricula * 100:.0f}%" if conf_matricula is not None else "N/D"

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
                self.btn_avisos_descarte.config(
                    text=f"Linhas sem matrícula ({len(self._avisos_descarte)})", state="normal"
                )

            rotulo_status = self._rotulo_status(status, observacao)

            self.tabela.insert("", "end", values=(
                numero_pagina, rotulo_status, data_, hora,
                matricula_normalizada, nome, setor, motivo, gestor,
                cargo, conf_str,
            ))

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
            })

        if self._contador_revisao:
            self.btn_revisao.config(text=f"Abrir revisão ({self._contador_revisao})", state="normal")

    def _exibir_imagens(self):
        self._photo_original = _para_photoimage(to_display_rgb(self._imagem_original))
        self._photo_processada = _para_photoimage(to_display_rgb(self._imagem_processada))
        self.lbl_img_original.configure(image=self._photo_original)
        self.lbl_img_processada.configure(image=self._photo_processada)

    # ------------------------------------------------------------------
    # Ações auxiliares
    # ------------------------------------------------------------------
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

    def _on_limpar(self):
        if self._processando:
            return
        self.tabela.delete(*self.tabela.get_children())
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
        self.btn_salvar.config(state="disabled")
        self.btn_revisao.config(text="Abrir revisão (0)", state="disabled")
        self.btn_erros_pag.config(text="Erros de página (0)", state="disabled")
        self.btn_avisos_contagem.config(text="Avisos de contagem (0)", state="disabled")
        self.btn_avisos_descarte.config(text="Linhas sem matrícula (0)", state="disabled")
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

    # ------------------------------------------------------------------
    # Janela de revisão manual
    # ------------------------------------------------------------------
    def _abrir_revisao(self):
        # Fase 7 (PROBLEMA E): só registros REVISAO entram aqui -- linhas
        # ERRO (falha de página inteira: OCR não rodou, PDF não abriu
        # etc.) não têm nenhum campo de verdade para corrigir, e permitir
        # "confirmar" uma delas digitando valores do zero seria inventar
        # dado sem nenhuma evidência de OCR por trás. Página com ERRO
        # precisa ser reprocessada (nova foto/novo PDF), não corrigida
        # campo a campo -- ver botão "Erros de página". Isso também
        # elimina a dessincronia que existia entre este contador e
        # `self._contador_revisao` (que nunca contava ERRO).
        pendentes = [(i, r) for i, r in enumerate(self._registros_exportacao) if r["status"] == "REVISAO"]
        if not pendentes:
            if self._erros_paginas:
                messagebox.showinfo(
                    "Revisão",
                    "Não há registros em revisão manual.\n\n"
                    f"Há {len(self._erros_paginas)} página(s) com ERRO de processamento — "
                    "veja o botão \"Erros de página\" (essas páginas precisam ser "
                    "reprocessadas, não corrigidas campo a campo).",
                )
            else:
                messagebox.showinfo("Revisão", "Não há registros pendentes de revisão.")
            return

        janela = tk.Toplevel(self)
        janela.title(f"Revisão manual ({len(pendentes)} registro(s))")
        janela.geometry("780x480")

        colunas = ("pagina", "matricula", "gestor", "motivo", "observacao")
        tabela = ttk.Treeview(janela, columns=colunas, show="headings", height=12)
        for c, titulo, w in [("pagina", "Pág.", 50), ("matricula", "Matrícula", 90),
                              ("gestor", "Responsável", 140), ("motivo", "Motivo", 140),
                              ("observacao", "Motivo da revisão", 260)]:
            tabela.heading(c, text=titulo)
            tabela.column(c, width=w, anchor="center")
        tabela.pack(fill="both", expand=True, padx=10, pady=10)

        indices_por_item = {}
        for indice_original, registro in pendentes:
            item_id = tabela.insert("", "end", values=(
                registro["pagina_origem"], registro["matricula"], registro["gestor"],
                registro["motivo"], registro["observacao"],
            ))
            indices_por_item[item_id] = indice_original

        frame_edicao = ttk.LabelFrame(janela, text="Corrigir registro selecionado", padding=10)
        frame_edicao.pack(fill="x", padx=10, pady=(0, 10))

        campos_edicao = {}
        for i, (chave, rotulo) in enumerate([("matricula", "Matrícula"), ("gestor", "Responsável"), ("motivo", "Motivo")]):
            ttk.Label(frame_edicao, text=rotulo).grid(row=0, column=i * 2, sticky="w", padx=(0, 4))
            var = tk.StringVar()
            ttk.Entry(frame_edicao, textvariable=var, width=18).grid(row=0, column=i * 2 + 1, padx=(0, 10))
            campos_edicao[chave] = var

        def _ao_selecionar(_evt=None):
            sel = tabela.selection()
            if not sel:
                return
            registro = self._registros_exportacao[indices_por_item[sel[0]]]
            campos_edicao["matricula"].set(registro["matricula"])
            campos_edicao["gestor"].set(registro["gestor"])
            campos_edicao["motivo"].set(registro["motivo"])

        tabela.bind("<<TreeviewSelect>>", _ao_selecionar)

        def _confirmar():
            # Fase 7 (PROBLEMAS C/D — segurança contra falso CONFIRMADO):
            # esta função ANTES marcava CONFIRMADO incondicionalmente, só
            # por o operador ter clicado o botão, sem checar se a correção
            # realmente resolveu o problema, e sem nunca reconsultar a
            # base de colaboradores pela matrícula corrigida (Nome/Setor/
            # Cargo ficavam travados em "(não encontrado)" mesmo com a
            # matrícula certa). Agora reconstrói um Registro sintético com
            # os valores digitados e roda a MESMA validação do fluxo
            # automático (validacao.classificar_registro) -- reutiliza a
            # regra existente, não cria nenhuma nova. Confiança 1.0 nos
            # campos digitados: foram verificados por uma pessoa, deixaram
            # de ser uma hipótese de OCR (não é um valor inventado).
            sel = tabela.selection()
            if not sel:
                messagebox.showwarning("Revisão", "Selecione um registro na lista.")
                return
            item_id = sel[0]
            indice = indices_por_item[item_id]
            registro = self._registros_exportacao[indice]

            matricula_digitada = campos_edicao["matricula"].get().strip()
            gestor_digitado = campos_edicao["gestor"].get().strip()
            motivo_digitado = campos_edicao["motivo"].get().strip()
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
            if registro.get("data"):
                campos_sinteticos["data"] = CampoOcr(texto=registro["data"], confianca=1.0, box=None)
            if registro.get("hora"):
                campos_sinteticos["hora"] = CampoOcr(texto=registro["hora"], confianca=1.0, box=None)
            if matricula_normalizada:
                campos_sinteticos["matricula"] = CampoOcr(texto=matricula_normalizada, confianca=1.0, box=None)
            if gestor_digitado:
                campos_sinteticos["gestor"] = CampoOcr(texto=gestor_digitado, confianca=1.0, box=None)
            if motivo_digitado:
                campos_sinteticos["motivo"] = CampoOcr(texto=motivo_digitado, confianca=1.0, box=None)
            registro_sintetico = Registro(indice=0, campos=campos_sinteticos)

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
            )

            registro["matricula"] = matricula_normalizada
            registro["nome"] = colaborador["nome"] if colaborador else NAO_ENCONTRADO
            registro["cargo"] = colaborador["cargo"] if colaborador else NAO_ENCONTRADO
            registro["setor"] = colaborador["setor"] if colaborador else NAO_ENCONTRADO
            registro["hora"] = resultado.hora_confirmada or ""
            registro["gestor"] = resultado.gestor_confirmado or gestor_digitado
            registro["motivo"] = resultado.motivo_confirmado or motivo_digitado
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

            self._sincronizar_tabela_principal()

            if resultado.status == "CONFIRMADO":
                if status_anterior != "CONFIRMADO":
                    self._contador_revisao -= 1
                    self._contador_confirmados += 1
                tabela.delete(item_id)
                del indices_por_item[item_id]
                self.btn_revisao.config(text=f"Abrir revisão ({self._contador_revisao})",
                                         state="normal" if self._contador_revisao else "disabled")
                if not indices_por_item:
                    janela.destroy()
            else:
                # Ainda não pôde ser confirmado (ex.: o problema real era
                # a DATA, que este formulário não edita) -- permanece na
                # lista de pendentes, com a observação atualizada, em vez
                # de desaparecer como se tivesse sido resolvido.
                tabela.item(item_id, values=(
                    registro["pagina_origem"], registro["matricula"], registro["gestor"],
                    registro["motivo"], registro["observacao"],
                ))
                messagebox.showinfo(
                    "Revisão", f"Ainda não é possível confirmar este registro:\n\n{resultado.observacao}"
                )

            self._atualizar_status(concluido=True)

        ttk.Button(frame_edicao, text="Confirmar correção", command=_confirmar).grid(row=0, column=6, padx=(10, 0))

    @staticmethod
    def _rotulo_status(status: str, observacao: str) -> str:
        if status == "CONFIRMADO":
            return "✓ CONFIRMADO"
        if status == "ERRO":
            return "✗ ERRO — " + observacao
        return "⚠ REVISÃO — " + observacao

    def _sincronizar_tabela_principal(self):
        """Reconstrói a tabela principal a partir de self._registros_exportacao (após correção manual)."""
        self.tabela.delete(*self.tabela.get_children())
        for r in self._registros_exportacao:
            rotulo_status = self._rotulo_status(r["status"], r["observacao"])
            conf = r.get("confianca_matricula")
            conf_str = f"{conf * 100:.0f}%" if isinstance(conf, (int, float)) else "N/D"
            self.tabela.insert("", "end", values=(
                r["pagina_origem"], rotulo_status, r["data"], r["hora"], r["matricula"],
                r["nome"], r["setor"], r["motivo"], r["gestor"], r["cargo"], conf_str,
            ))
