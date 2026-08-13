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

FLUXO PRINCIPAL (Fase 21a): a janela abria direto numa tabela vazia de 12
colunas — a primeira tela do programa não respondia "o que eu faço
agora?", só mostrava um gabarito em branco. Foi acrescentada a aba
**Início**, que é o fluxo guiado do trabalho:

    Escolher folhas -> Conferir a seleção -> Processar -> Resultado

São três cartões alternados dentro da mesma aba (`_cartao_pronto`,
`_cartao_selecao`, `_cartao_processando`), nunca dois ao mesmo tempo: em
cada etapa existe UMA ação principal evidente e o próximo passo é o botão
destacado. A escolha do arquivo deixou de disparar o processamento na
hora — passa por uma etapa de conferência, que é onde o operador vê o que
selecionou, quantas folhas são e (para PDF) quantas páginas o arquivo
tem, antes de gastar ~40 s de OCR por folha.

Nada disso toca o motor: os workers, a fila, a classificação, o parser, a
exportação e a revisão são os mesmos. O que a fase acrescentou à fila foi
a mensagem ("etapa", texto), puramente informativa, para a tela poder
dizer em que passo a folha está em vez de só "Processando...".
"""

import io
import logging
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import cv2
import numpy as np
import ttkbootstrap as tb
from PIL import Image, ImageTk
from ttkbootstrap.dialogs import Messagebox

from leitor_matriculas.ocr.engine import get_ocr_engine
from leitor_matriculas.dados.data_manager import DataManager
from leitor_matriculas.parsing.registro_parser import verificar_contagem_posicoes
from leitor_matriculas.parsing.contexto_lote import ContextoLote
# Fase 24a (Web MVP): "rodar o pipeline sobre uma folha" (pré-processamento
# -> OCR -> parser -> reparo DATA+HORA -> classificação) e "confirmar uma
# revisão manual" deixaram de ser lógica desta classe -- viraram funções
# neutras em `pipeline.py`/`validacao/confirmacao.py` para que o backend
# web (que não pode instanciar `App`, que abre uma janela) chame as MESMAS
# funções em vez de duplicar a decisão. `ui/app.py` a partir daqui só
# COORDENA: lê os campos dos widgets, chama a função, atualiza o que é
# tela (tabela, contador, fila, navegação).
from leitor_matriculas import pipeline
from leitor_matriculas.validacao.confirmacao import NAO_ENCONTRADO, confirmar_revisao_manual
from leitor_matriculas.ui import explicacao_revisao
from leitor_matriculas.ui import mensagens
from leitor_matriculas.ui import estilos
from leitor_matriculas.ui import preferencias
from leitor_matriculas.ocr import pdf_reader
from leitor_matriculas.exportacao import xlsx_exporter

EXTENSOES_IMAGEM = [("Imagens", "*.jpg *.jpeg *.png *.webp"), ("Todos", "*.*")]
EXTENSOES_PDF = [("PDF", "*.pdf")]

# Sub-fase 22e: `cosmo` nunca tinha sido reavaliado -- ver a auditoria em
# `saida/avaliacao_fase22_redesign.md` (seção 22e) e a explicação em
# `ui/estilos.py` (por que `flatly`/`darkly` foram escolhidos como o par
# claro/escuro). O nome do tema ATIVO nesta sessão (`self._tema_atual`,
# em `App`) pode ser um dos dois -- esta constante é só o padrão de
# abertura.
TEMA = estilos.TEMA_CLARO

# NAO_ENCONTRADO (placeholder de Nome/Cargo/Setor quando a matrícula não
# pôde ser associada a um colaborador da base) mudou de dono na Fase 24a:
# agora vem de `validacao/confirmacao.py` (importado acima), porque tanto
# o Tkinter quanto o backend web precisam mostrar exatamente o mesmo
# texto -- duas cópias da mesma constante um dia divergiriam.

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
#
# Sub-fase 21c: "status" cresceu (116→190) para caber o vocabulário
# completo ("✕ Erro no processamento", o mais longo dos três -- ver
# `ui/estilos.py`) sem cortar texto; a diferença saiu de três colunas
# secundárias/técnicas (setor, cargo, confiança), que continuam legíveis
# e mantêm a soma igual à de antes -- a tabela continua cabendo na janela
# no tamanho padrão.
LARGURAS_TABELA = {
    "pagina": 46, "status": 190, "data": 74, "hora": 56, "matricula": 84,
    "nome": 172, "setor": 104, "motivo": 122, "gestor": 128, "cargo": 80,
    "confianca": 56, "observacao": 280,
}
# Altura das linhas da tabela. O padrão do ttk aperta demais as linhas para
# uma tabela que se lê durante uma hora de lote.
ALTURA_LINHA_TABELA = 26
# Colunas que ficam alinhadas à esquerda por serem texto corrido; as demais
# (números, códigos, status) ficam centradas.
COLUNAS_A_ESQUERDA = {"nome", "setor", "cargo", "observacao"}

FILTROS_TABELA = ("Todos", "Confirmados", "Em revisão", "Com erro")

# Sub-fase 21b (aba Revisão): uma cor de TEXTO (não de fundo -- "sem
# exagerar em cores", pedido explícito do escopo) por campo, usada tanto na
# lista de pendências quanto no rótulo do campo em destaque no formulário.
# É só apresentação -- os nomes das chaves são os mesmos de
# `explicacao_revisao.ROTULOS`. Sub-fase 22e: os valores moraram para
# `ui/estilos.py` (`CORES_TIPO_PENDENCIA`/`COR_TIPO_PENDENCIA_PADRAO`),
# que `aplicar_paleta()` atualiza IN-PLACE ao trocar de tema -- este
# nome continua existindo aqui como ALIAS do MESMO dicionário (não uma
# cópia), então nada que já lia `CORES_TIPO_PENDENCIA` precisou mudar.
CORES_TIPO_PENDENCIA = estilos.CORES_TIPO_PENDENCIA

# Sub-fase 21d: filtro por tipo de pendência na lista de Revisão. O rótulo
# mostrado no Combobox é o mesmo de `explicacao_revisao.ROTULOS`
# ("Responsável", "Data", ...); este dicionário faz o caminho inverso
# (rótulo -> chave do campo) para comparar contra `campos_bloqueantes`.
FILTRO_REVISAO_TODAS = "Todas"
ROTULOS_REVISAO_INVERTIDO = {v: k for k, v in explicacao_revisao.ROTULOS.items()}
# Texto de apoio (placeholder) do campo de busca -- ttk não tem
# placeholder nativo, então o texto é escrito/apagado manualmente
# conforme o campo ganha/perde foco (ver `_ativar_placeholder_busca_revisao`).
PLACEHOLDER_BUSCA_REVISAO = "Buscar por matrícula, responsável, motivo ou página..."

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


# Fase 24a: movida para `pipeline.reparar_data_hora_mescladas`. O ALIAS
# abaixo existe só para não quebrar `from leitor_matriculas.ui.app import
# _reparar_data_hora_mescladas`, que `teste_extracao_fase1.py` já fazia
# antes desta fase (o teste continua válido -- a função é a mesma, só
# mudou de arquivo).
_reparar_data_hora_mescladas = pipeline.reparar_data_hora_mescladas


class App(tb.Window):
    def __init__(self):
        # Sub-fase 22e: abre no tema salvo da última sessão (se houver
        # -- `preferencias.py`, nunca lança, devolve claro por padrão).
        # `self._tema_escuro` é o estado de VERDADE a partir daqui;
        # `TEMA`/`estilos.TEMA_CLARO` só decidem o padrão de abertura.
        self._tema_escuro = preferencias.carregar_tema_escuro()
        tema_inicial = estilos.TEMA_ESCURO if self._tema_escuro else estilos.TEMA_CLARO
        super().__init__(themename=tema_inicial)
        # As cores fortes (`COR_ACCENT`/`COR_SUCESSO`/`COR_ATENCAO`/
        # `COR_ERRO`) e a paleta de fundo/texto deste módulo já podem ser
        # calculadas: o `Style()` do `ttkbootstrap` acabou de carregar o
        # tema `tema_inicial` na linha acima. Precisa vir ANTES de
        # `_montar_layout()`, que já lê `estilos.COR_*` para montar os
        # widgets.
        estilos.aplicar_paleta(self._tema_escuro, self.style.colors)
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

        # Fase 21a (fluxo principal). Estado APENAS de apresentação: em que
        # etapa do fluxo a aba Início está, o que foi selecionado mas ainda
        # não processado, e o que medir para mostrar progresso honesto.
        # Nada aqui participa de nenhuma decisão de negócio.
        self._etapa_fluxo = "pronto"          # pronto | selecao | processando
        self._selecao_pendente = None         # {"tipo", "caminhos", "descricao", "total"}
        self._etapa_atual = ""                # em que passo a folha corrente está
        self._instante_inicio_lote = None     # time.monotonic() do início da leva
        self._lote_concluido = False          # houve uma leva que terminou nesta sessão
        self._ticker_processando = None       # id do after() que atualiza o tempo decorrido

        # Foto de cada página (JPEG comprimido), para a aba de Revisão.
        self._miniaturas_por_pagina = {}
        # Estado da aba de Revisão.
        self._revisao_indices = []   # índices em _registros_exportacao, na ordem física
        self._revisao_posicao = 0    # posição atual dentro de _revisao_indices
        self._revisao_zoom = 1.0
        self._foto_revisao = None    # referência viva do PhotoImage (senão o Tk descarta)
        # Sub-fase 21b: quantas correções foram CONFIRMADAS nesta sessão de
        # revisão (não é o mesmo que "quantas ainda faltam" -- essa conta já
        # existe em `_indices_pendentes_revisao`). É o numerador do contador
        # "N de M revisados"; o denominador é `resolvidos + pendentes_atuais`,
        # recalculado ao vivo (nunca guardado como total fixo), para que
        # processar folhas novas no meio de uma revisão aumente o total sem
        # exigir nenhum código extra. Puramente informativo -- não participa
        # de nenhuma decisão e é zerado junto com "Limpar resultados".
        self._revisao_resolvidos_sessao = 0
        # Se o painel de detalhes (Fase 18, "Por que está em revisão") está
        # expandido. Fecha por padrão a cada registro novo, para não dominar
        # a tela (pedido explícito do escopo da 21b).
        self._revisao_detalhes_expandido = False
        # Sub-fase 22c: item da lista de pendências sob o cursor (hover
        # visual, puramente cosmético -- não participa de nenhuma decisão
        # nem da seleção real, que continua sendo `tabela_revisao_lista.
        # selection()`). `None` quando o cursor não está sobre a lista.
        self._hover_item_revisao = None

        self._montar_layout()
        # Sincroniza a tabela já vazia para que o estado vazio (Fase 21a)
        # apareça desde a abertura, em vez de uma grade em branco.
        self._sincronizar_tabela_principal()
        self._atualizar_status()
        self._atualizar_avisos()
        self._atualizar_painel_revisao()
        self._ir_para_etapa("pronto")

    # ==================================================================
    # LAYOUT
    # ==================================================================
    def _montar_layout(self):
        self._montar_estilos_visuais()
        self._montar_cabecalho()

        self.abas = ttk.Notebook(self)
        self.abas.pack(side="top", fill="both", expand=True, padx=12, pady=(0, 8))
        # Fase 21a: Início é a PRIMEIRA aba porque é onde o trabalho começa.
        # Antes o programa abria em Registros, isto é, na tabela de saída de
        # um trabalho que ainda não tinha sido feito.
        self._montar_aba_inicio()
        self._montar_aba_registros()
        self._montar_aba_revisao()
        self._montar_aba_avisos()

        self._montar_rodape()

        # Sub-fase 22e: idempotente na montagem inicial (mesmos valores
        # que cada `_montar_aba_*` já aplicou) -- existe aqui, num único
        # lugar, para ser exatamente o que `_alternar_tema()` chama de
        # novo depois de trocar de tema.
        self._aplicar_cores_dinamicas_tabelas()
        self._atualizar_texto_botao_tema()

    # ------------------------------------------------------------------
    def _montar_estilos_visuais(self):
        """
        Sub-fase 22b (Fase 22 -- redesign visual): registra os estilos
        `ttk` derivados dos tokens de `ui/estilos.py` que a Home e o
        cabeçalho passam a usar. Só isto -- nenhuma regra de negócio.

        Sub-fase 22e: chamado DUAS vezes por sessão, no mínimo -- uma vez
        na montagem inicial (`_montar_layout`) e de novo a cada
        `_alternar_tema()`, depois que `estilos.aplicar_paleta(...)` já
        atualizou os tokens `estilos.COR_*` para o modo novo. Como os
        widgets referenciam os estilos por NOME (`style="Card.TFrame"`
        etc.), reconfigurar o mesmo nome aqui é o que os redesenha --
        nenhum widget individual precisa ser tocado.

        A CORREÇÃO CENTRAL que estes estilos existem para viabilizar (ver
        achados 1/2 da auditoria da 22a em `saida/avaliacao_fase22_
        redesign.md`): o tema `cosmo` nunca separou fundo de TELA de
        fundo de CARTÃO -- os dois eram a mesma cor branca, e por isso
        cada agrupamento só se distinguia do resto por uma borda de
        `ttk.LabelFrame`. `Canvas.TFrame`/`Canvas.TLabel` (cor de fundo
        `estilos.COR_FUNDO`, o cinza-azulado claro) pintam o CONTEÚDO de
        uma aba; `Card.TFrame` (branco, `estilos.COR_SUPERFICIE`) pinta
        os agrupamentos que antes eram `ttk.Labelframe` -- a mesma cor
        que o `TFrame` padrão do tema já usava, mas nomeada explicitamente
        em vez de depender de uma coincidência entre o tema e o token
        (se `COR_SUPERFICIE` mudar um dia, o estilo muda junto; contando
        com o padrão do tema, não mudaria).

        `SecaoTitulo.TLabel` substitui o texto que o `Labelframe` cavalgava
        na própria borda (`text="O que você quer fazer?"`) por um título
        comum ACIMA do cartão, na cor do canvas -- é a técnica que troca
        borda por espaço/contraste, o critério escrito em `ui/estilos.py`.

        Escopo da 22b: cabeçalho, rodapé, abas (Notebook) e a aba Início.
        Sub-fase 22c ESTENDEU este mesmo método (não criou um segundo) com
        os estilos que a aba Revisão passou a usar: `PosicaoRevisao.
        TLabel`/`ResumoRevisao.TLabel`/`ResultadoRevisaoErro.TLabel` (as
        três únicas cores que a Revisão trocava dinamicamente via
        `bootstyle`, e que precisavam de um fundo próprio -- `bootstyle`
        sozinho não define fundo, só a cor do texto, e o fundo branco
        padrão do tema ficaria como uma mancha sobre o canvas cinza), o
        realce da linha selecionada/em hover da lista de pendências
        (`Treeview` com a tag "revisao_lista", `COR_SELECAO_LISTA`) e o
        fundo do `TPanedwindow` (a área entre os três painéis).

        Sub-fase 22d ESTENDEU de novo com o estilo `"Treeview"` PLANO
        (cabeçalho, fundo, seleção) -- o que Registros e Avisos usam.
        Também é aqui, não mais num bloco solto em `_montar_layout`, que
        `rowheight=ALTURA_LINHA_TABELA` é aplicado (consolidado: era a
        única configuração de estilo que ainda vivia fora deste método).
        Como o estilo `"light.Treeview"` da lista de pendências (22c) é
        um BUCKET SEPARADO (`ttkbootstrap` cria um por `bootstyle`), mexer
        em `"Treeview"` aqui não vaza para a Revisão -- só os dois únicos
        outros widgets que usam o estilo plano (`self.tabela`/`self.
        tabela_avisos`) são afetados, de propósito.
        """
        try:
            estilo = tb.Style()

            # A janela raiz é um `tk.Tk` puro por baixo do `tb.Window`; o
            # que sobra fora de qualquer `ttk.Frame` (as margens do
            # `Notebook`, por exemplo) mostra esta cor.
            self.configure(background=estilos.COR_FUNDO)

            estilo.configure("Canvas.TFrame", background=estilos.COR_FUNDO)
            estilo.configure(
                "Canvas.TLabel", background=estilos.COR_FUNDO, foreground=estilos.COR_TEXTO_PRIMARIO,
            )
            estilo.configure(
                "CanvasSecundario.TLabel", background=estilos.COR_FUNDO, foreground=estilos.COR_TEXTO_SECUNDARIO,
            )
            estilo.configure(
                "SecaoTitulo.TLabel", background=estilos.COR_FUNDO,
                foreground=estilos.COR_TEXTO_PRIMARIO, font=estilos.FONTE_TITULO_SECAO,
            )
            estilo.configure("Card.TFrame", background=estilos.COR_SUPERFICIE)
            estilo.configure(
                "HeaderTitulo.TLabel", background=estilos.COR_SUPERFICIE, foreground=estilos.COR_TEXTO_PRIMARIO,
                font=estilos.FONTE_TITULO_CABECALHO,
            )
            # Sub-fase 22e: cabeçalho e rodapé usavam `ttk.Frame` SEM
            # estilo -- em `cosmo`/`flatly` (fundo padrão branco) isso
            # coincidia com `COR_SUPERFICIE` por acaso; a troca de tema
            # revelou a armadilha real dessa coincidência: alternando
            # para `darkly`, PARTE do cabeçalho ficava clara e parte
            # escura (um problema de repintura de um `TFrame` sem nome
            # próprio, não só de cor errada -- confirmado inspecionando
            # pixels da captura, não só olhando por cima). `Header.
            # TFrame`, com fundo nomeado explicitamente, garante que
            # `_montar_estilos_visuais` (chamado de novo a cada troca)
            # realmente repinta a área inteira.
            estilo.configure("Header.TFrame", background=estilos.COR_SUPERFICIE)
            estilo.configure(
                "Header.TLabel", background=estilos.COR_SUPERFICIE, foreground=estilos.COR_TEXTO_PRIMARIO,
            )
            estilo.configure(
                "HeaderSecundario.TLabel", background=estilos.COR_SUPERFICIE, foreground=estilos.COR_TEXTO_SECUNDARIO,
            )
            # Linha de 1px -- separa o cabeçalho/rodapé (brancos) do resto
            # da janela (cinza), no lugar de uma borda ao redor de tudo.
            estilo.configure("Separador.TFrame", background=estilos.COR_BORDA)

            # Notebook (abas): aba ativa na cor de cartão, inativas na cor
            # de canvas -- o mesmo contraste de fundo aplicado à navegação.
            estilo.configure("TNotebook", background=estilos.COR_FUNDO, borderwidth=0)
            estilo.configure("TNotebook.Tab", padding=(estilos.ESPACO_LG, estilos.ESPACO_SM), font=estilos.FONTE_ROTULO_MEDIO)
            estilo.map(
                "TNotebook.Tab",
                background=[("selected", estilos.COR_SUPERFICIE), ("!selected", estilos.COR_FUNDO)],
                foreground=[("selected", estilos.COR_TEXTO_PRIMARIO), ("!selected", estilos.COR_TEXTO_SECUNDARIO)],
            )

            # Sub-fase 22c (aba Revisão): três rótulos que trocavam de cor
            # dinamicamente via `bootstyle` ("warning"/"danger") e ficaram
            # diretamente sobre o canvas cinza -- `bootstyle` só define a
            # cor do TEXTO, nunca o fundo, então sem um estilo próprio cada
            # um apareceria como uma mancha branca (a cor de fundo padrão
            # do tema) sobre o cinza. Cada um usa a cor FORTE correspondente
            # da paleta da 22a (`COR_ATENCAO`/`COR_ERRO`), nunca inventada.
            estilo.configure(
                "PosicaoRevisao.TLabel", background=estilos.COR_FUNDO,
                foreground=estilos.COR_TEXTO_PRIMARIO, font=estilos.FONTE_ROTULO_FORTE,
            )
            estilo.configure(
                "ResumoRevisao.TLabel", background=estilos.COR_FUNDO,
                foreground=estilos.COR_ATENCAO, font=estilos.FONTE_ROTULO_MEDIO,
            )
            estilo.configure(
                "ResultadoRevisaoErro.TLabel", background=estilos.COR_FUNDO, foreground=estilos.COR_ERRO,
            )

            # (O ajuste da cor de seleção da lista de pendências --
            # "light.Treeview" -- fica em `_montar_aba_revisao`, logo após
            # criar o widget: o `ttkbootstrap` só REGISTRA o estilo
            # "light.Treeview" na hora em que o primeiro widget com
            # `bootstyle="light"` é construído; ajustar aqui, antes disso
            # existir, seria sobrescrito pelo próprio `ttkbootstrap` quando
            # ele constrói o estilo em seguida.)

            # A faixa entre os três painéis (o "sash" arrastável) mostrando
            # a mesma cor do canvas, em vez do cinza genérico do tema.
            estilo.configure("TPanedwindow", background=estilos.COR_FUNDO)

            # Sub-fase 22d: tabelas de Registros e Avisos -- estilo
            # `"Treeview"` PLANO (ver nota no docstring sobre por que isto
            # não afeta a lista de pendências, que usa outro estilo).
            # Linha mais alta (Fase 10, só consolidada aqui), fundo/campo
            # na cor de cartão (nomeado, em vez de coincidir com o padrão
            # do tema), cabeçalho discreto (texto secundário, sem o baixo-
            # relevo pesado do tema padrão) e a MESMA técnica de seleção
            # da lista de pendências -- para as tabelas pararem de parecer
            # widgets soltos de temas diferentes.
            estilo.configure(
                "Treeview", rowheight=ALTURA_LINHA_TABELA,
                background=estilos.COR_SUPERFICIE, fieldbackground=estilos.COR_SUPERFICIE,
            )
            estilo.configure(
                "Treeview.Heading", background=estilos.COR_SUPERFICIE, foreground=estilos.COR_TEXTO_SECUNDARIO,
                font=estilos.FONTE_ROTULO_MEDIO, relief="flat",
            )
            # Sem "foreground" no mapa: as tags de status (CONFIRMADO/
            # REVISAO/ERRO, `estilos.cor_fundo_tabela_status`) continuam
            # decidindo o fundo das linhas NÃO selecionadas -- só a
            # SELECIONADA usa o tom pastel de accent.
            #
            # `bordercolor`/`lightcolor`/`darkcolor` fixados (não deixados
            # herdar do construtor de Treeview do `ttkbootstrap`, que mapeia
            # esses três para a cor de accent quando o widget tem foco --
            # um contorno azul grosso em volta da tabela inteira ao clicar
            # nela, sem nenhuma relação com o resto do app). Fixá-los aqui
            # sobrepõe esse mapa padrão sem alterar a MOLDURA em si.
            estilo.map(
                "Treeview",
                background=[("selected", estilos.COR_SELECAO_LISTA)],
                foreground=[("selected", estilos.COR_TEXTO_PRIMARIO)],
                bordercolor=[("focus", estilos.COR_BORDA), ("!focus", estilos.COR_BORDA)],
                lightcolor=[("focus", estilos.COR_SUPERFICIE), ("!focus", estilos.COR_SUPERFICIE)],
                darkcolor=[("focus", estilos.COR_SUPERFICIE), ("!focus", estilos.COR_SUPERFICIE)],
            )
        except Exception:
            logging.exception("Falha ao registrar os estilos visuais novos (apenas cosmético)")

    # ------------------------------------------------------------------
    def _separador_horizontal(self, mestre=None, lado="top"):
        """Linha fina de 1px (`Separador.TFrame`) para trocar borda por
        contraste discreto entre duas faixas de cor diferentes (ex.:
        cabeçalho branco sobre o canvas cinza). `lado="bottom"` para o
        rodapé, onde a linha precisa ficar presa à borda inferior da
        janela, não ao topo do que sobrou da área de empacotamento."""
        linha = ttk.Frame(mestre if mestre is not None else self, style="Separador.TFrame", height=1)
        linha.pack(side=lado, fill="x")
        return linha

    # ------------------------------------------------------------------
    def _aplicar_selecao_lista_revisao(self):
        """
        Sobrescreve a cor de fundo E de texto da linha SELECIONADA da
        lista de pendências (Sub-fase 22c/22e). Extraído para método
        próprio (era código embutido em `_montar_aba_revisao` até a
        22e) porque a alternância de tema precisa REPETIR exatamente
        isto depois de `self.style.theme_use(...)`: o `ttkbootstrap`
        reconstrói o estilo `"light.Treeview"` para o tema novo (com o
        cinza/branco padrão dele, não com `COR_SELECAO_LISTA`) sempre
        que o tema muda -- esta sobreposição precisa ser refeita, não
        só feita uma vez na montagem inicial.

        Widget-alvo isolado do resto da aplicação: `"light.Treeview"` só
        é usado por `self.tabela_revisao_lista` (ver o comentário em
        `_montar_aba_revisao` sobre por que `bootstyle="light"`, não
        `style=`, foi o jeito de conseguir um estilo próprio).
        """
        try:
            tb.Style().map(
                "light.Treeview",
                background=[("selected", estilos.COR_SELECAO_LISTA)],
                foreground=[("selected", estilos.COR_TEXTO_PRIMARIO)],
            )
        except Exception:
            logging.exception("Falha ao ajustar a cor de seleção da lista de pendências (apenas cosmético)")

    # ------------------------------------------------------------------
    def _aplicar_cores_dinamicas_tabelas(self):
        """
        Sub-fase 22e: reaplica todas as cores que foram fixadas via
        `tag_configure`/`.map()` em vez de um estilo `ttk` nomeado --
        `self.style.theme_use(...)` NÃO atualiza essas sozinho (ele só
        redesenha widgets que usam um estilo por NOME; uma tag de
        Treeview é um valor literal preso no momento em que foi
        configurada). Chamado uma vez ao fim de `_montar_layout` (idem-
        potente -- mesmos valores que a montagem inicial já usou) e de
        novo a cada `_alternar_tema()`.
        """
        for status in ("CONFIRMADO", "REVISAO", "ERRO"):
            self.tabela.tag_configure(
                estilos.tag_status(status),
                background=estilos.cor_fundo_tabela_status(status),
            )
        for campo, cor in CORES_TIPO_PENDENCIA.items():
            self.tabela_revisao_lista.tag_configure(campo, foreground=cor)
        self.tabela_revisao_lista.tag_configure("outro", foreground=estilos.COR_TIPO_PENDENCIA_PADRAO)
        self.tabela_revisao_lista.tag_configure("hover", background=estilos.COR_FUNDO)
        self._aplicar_selecao_lista_revisao()
        self.tabela_avisos.tag_configure("hover", background=estilos.COR_FUNDO)

    # ------------------------------------------------------------------
    def _alternar_tema(self):
        """
        Sub-fase 22e: alterna entre `estilos.TEMA_CLARO`/`TEMA_ESCURO`
        em tempo de execução -- o único controle de preferência real do
        programa (ver `ui/preferencias.py`). Só camada de apresentação:
        não toca em `_registros_exportacao`, `_data_manager` nem em
        nenhum estado de negócio.
        """
        self._tema_escuro = not self._tema_escuro
        novo_tema = estilos.TEMA_ESCURO if self._tema_escuro else estilos.TEMA_CLARO
        try:
            self.style.theme_use(novo_tema)
        except Exception:
            logging.exception("Falha ao trocar de tema (interface pode continuar no tema anterior)")
            self._tema_escuro = not self._tema_escuro  # desfaz a intenção -- a troca não aconteceu
            return
        # `self.style.theme_use` já trocou o tema; `self.style.colors`
        # agora reflete o tema NOVO -- é esse `colors` que alimenta
        # `COR_ACCENT`/`COR_SUCESSO`/`COR_ATENCAO`/`COR_ERRO`.
        estilos.aplicar_paleta(self._tema_escuro, self.style.colors)
        self._montar_estilos_visuais()
        self._aplicar_cores_dinamicas_tabelas()
        self._atualizar_texto_botao_tema()
        preferencias.salvar_tema_escuro(self._tema_escuro)

    def _atualizar_texto_botao_tema(self):
        if not hasattr(self, "btn_alternar_tema"):
            return
        if self._tema_escuro:
            self.btn_alternar_tema.config(text=f"{estilos.ICONE_TEMA_CLARO} Claro")
        else:
            self.btn_alternar_tema.config(text=f"{estilos.ICONE_TEMA_ESCURO} Escuro")

    # ------------------------------------------------------------------
    def _montar_cabecalho(self):
        # Sub-fase 22b: o cabeçalho passou a ser uma SUPERFÍCIE (fundo
        # branco, `estilos.COR_SUPERFICIE` -- que já é o padrão do tema,
        # ver `_montar_estilos_visuais`) separada do resto da janela (o
        # canvas cinza) por uma linha de 1px em vez de nenhuma fronteira
        # visual, que era o caso antes (cabeçalho e corpo eram a mesma
        # cor branca, sem nenhuma pista de que são áreas diferentes).
        cabecalho = ttk.Frame(self, padding=(estilos.ESPACO_LG, estilos.ESPACO_MD), style="Header.TFrame")
        cabecalho.pack(side="top", fill="x")

        # Ações de ENTRADA à esquerda; a ação de SAÍDA ("Gerar planilha")
        # fica destacada à direita. Antes todos os botões tinham exatamente
        # o mesmo peso visual, então a ação que encerra o trabalho parecia
        # tão importante quanto "Ver avisos".
        #
        # Fase 21a: o cabeçalho deixou de ser o único lugar por onde o
        # trabalho começa -- a aba Início passou a ter as ações principais,
        # em tamanho e com explicação. Estes botões continuam existindo como
        # ATALHO (chegar às mesmas ações de dentro de qualquer aba), e por
        # isso ficaram todos com peso visual menor: quem carrega a ação
        # principal agora é a tela, não a barra. "Gerar planilha" é a única
        # exceção, porque é a ação que encerra o trabalho e não tem
        # equivalente em nenhuma outra aba.
        entrada = ttk.Frame(cabecalho, style="Header.TFrame")
        entrada.pack(side="left")

        ttk.Label(entrada, text="Leitor de Matrículas", style="HeaderTitulo.TLabel").pack(
            side="left", padx=(0, estilos.ESPACO_SM)
        )
        # Sub-fase 22e: o único controle de preferência real do programa
        # (ver `ui/preferencias.py` -- a 21a/21d já auditaram e não
        # acharam nenhuma outra opção de usuário real para expor, por
        # isso isto é um botão discreto perto do título, não uma tela de
        # "Configurações" inventada). O texto inicial é ajustado por
        # `_atualizar_texto_botao_tema()`, chamado ao fim de
        # `_montar_layout` -- aqui só precisa existir o widget.
        self.btn_alternar_tema = ttk.Button(
            entrada, text="", bootstyle="link", command=self._alternar_tema, width=9,
        )
        self.btn_alternar_tema.pack(side="left", padx=(0, estilos.ESPACO_LG))

        self.btn_imagem = ttk.Button(
            entrada, text="Fotos das folhas", bootstyle="primary-outline",
            command=self._on_selecionar_imagem, width=18,
        )
        self.btn_imagem.pack(side="left", padx=(0, 6))
        self.btn_pdf = ttk.Button(
            entrada, text="Arquivo PDF", bootstyle="primary-outline",
            command=self._on_selecionar_pdf, width=14,
        )
        self.btn_pdf.pack(side="left", padx=(0, 6))
        self.btn_limpar = ttk.Button(
            entrada, text="Limpar resultados", bootstyle="secondary-outline",
            command=self._on_limpar, width=18,
        )
        self.btn_limpar.pack(side="left")

        saida = ttk.Frame(cabecalho, style="Header.TFrame")
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

        # Fronteira visual entre o cabeçalho (branco) e o resto da janela
        # (canvas cinza) -- ver `_montar_estilos_visuais`.
        self._separador_horizontal()

    # ==================================================================
    # ABA INÍCIO -- o fluxo principal do trabalho (Fase 21a)
    #
    # Três cartões ocupam o mesmo lugar e só um aparece por vez, conforme
    # `_etapa_fluxo`. A troca é feita SÓ por `_ir_para_etapa`, pelo mesmo
    # motivo que `_sincronizar_tabela_principal` é o único ponto que
    # escreve na tabela: com dois caminhos para mudar de estado, a tela
    # acaba mostrando dois estados ao mesmo tempo.
    # ==================================================================
    def _montar_aba_inicio(self):
        # Sub-fase 22b: a aba passou a ser CANVAS (`Canvas.TFrame`, o
        # cinza-azulado de `estilos.COR_FUNDO`) para que os cartões
        # brancos abaixo (`Card.TFrame`) apareçam por CONTRASTE DE FUNDO,
        # não só por borda -- ver `_montar_estilos_visuais`. Qualquer
        # texto que fique diretamente sobre esta aba (não dentro de um
        # cartão) precisa do estilo `Canvas*` correspondente, senão herda
        # o fundo branco padrão do `TLabel` e aparece como uma mancha
        # clara sobre o cinza.
        aba = ttk.Frame(self.abas, padding=(24, 18), style="Canvas.TFrame")
        self.abas.add(aba, text="Início")
        self._aba_inicio = aba

        ttk.Label(
            aba, text="Leitor de Matrículas", font=estilos.FONTE_TITULO_PAGINA, style="Canvas.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            aba,
            text="Transforma as folhas de liberação — fotografadas ou em PDF — numa planilha conferida.",
            style="CanvasSecundario.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        self._container_fluxo = ttk.Frame(aba, style="Canvas.TFrame")
        self._container_fluxo.pack(side="top", fill="both", expand=True)

        self._montar_cartao_pronto()
        self._montar_cartao_selecao()
        self._montar_cartao_processando()

    # ------------------------------------------------------------------
    def _montar_cartao_pronto(self):
        """Etapa 1 (e também a tela de resultado): o que dá para fazer agora."""
        cartao = ttk.Frame(self._container_fluxo, style="Canvas.TFrame")
        self._cartao_pronto = cartao

        # Faixa de conclusão -- só aparece logo depois de uma leva terminar.
        # É o que responde "acabou?" sem o operador ter de reparar que uma
        # barra sumiu ou que uma palavra mudou no rodapé. Fica sobre o
        # canvas (fora de qualquer cartão), daí o estilo `Canvas.TLabel`
        # -- a cor de sucesso vem de `bootstyle`, que continua funcionando
        # junto com `style` (um dá a cor do texto, o outro o fundo/fonte).
        self.lbl_inicio_concluido = ttk.Label(
            cartao, text="", bootstyle="success", font=estilos.FONTE_TITULO_SECAO, style="Canvas.TLabel",
        )

        # Sub-fase 22b: título comum (fora do cartão, na cor do canvas)
        # substituindo o rótulo que o `ttk.Labelframe` cavalgava na
        # própria borda -- é a troca de borda por espaço/contraste que
        # `ui/estilos.py` documenta como critério.
        titulo_acoes = ttk.Label(cartao, text="O que você quer fazer?", style="SecaoTitulo.TLabel")
        titulo_acoes.pack(side="top", anchor="w", pady=(0, estilos.ESPACO_SM))
        # Guardado porque a faixa de conclusão é empacotada com `before=`
        # ele -- assim ela aparece e some sem reordenar o resto do cartão
        # (tem que ficar ACIMA do título, não colada entre título e cartão).
        self._moldura_acoes_inicio = titulo_acoes
        acoes = ttk.Frame(cartao, style="Card.TFrame", padding=estilos.ESPACO_LG)
        acoes.pack(side="top", fill="x")
        linha_botoes = ttk.Frame(acoes)
        linha_botoes.pack(side="top", fill="x")
        self.btn_inicio_imagens = ttk.Button(
            linha_botoes, text="Fotos das folhas", bootstyle="primary",
            command=self._on_selecionar_imagem, width=22,
        )
        self.btn_inicio_imagens.pack(side="left")
        self.btn_inicio_pdf = ttk.Button(
            linha_botoes, text="Arquivo PDF", bootstyle="primary-outline",
            command=self._on_selecionar_pdf, width=22,
        )
        self.btn_inicio_pdf.pack(side="left", padx=(10, 0))
        ttk.Label(
            acoes,
            text="Escolha as fotos das folhas do dia (pode selecionar várias de uma vez) "
                 "ou o arquivo PDF do mês.",
            bootstyle="secondary", wraplength=760, justify="left",
        ).pack(side="top", anchor="w", pady=(10, 0))

        # Resultado do que já foi processado nesta sessão. O título fica
        # sempre visível (packed aqui, na construção) porque o cartão
        # abaixo dele também é sempre mostrado (mesmo vazio, com
        # `lbl_resultado_vazio`) -- só o CONTEÚDO do cartão muda com o
        # resultado, nunca a moldura em si (ver `_atualizar_cartao_pronto`).
        ttk.Label(cartao, text="Último processamento", style="SecaoTitulo.TLabel").pack(
            side="top", anchor="w", pady=(estilos.ESPACO_XL, estilos.ESPACO_SM),
        )
        self.moldura_resultado = ttk.Frame(cartao, style="Card.TFrame", padding=estilos.ESPACO_LG)

        self.lbl_resultado_vazio = ttk.Label(
            self.moldura_resultado, text=mensagens.VAZIO_SEM_PROCESSAMENTO, bootstyle="secondary",
        )

        self.frame_numeros = ttk.Frame(self.moldura_resultado)
        self._numeros_resultado = {}
        for coluna, (chave, rotulo, estilo) in enumerate([
            ("folhas", "folhas lidas", "secondary"),
            ("total", "registros", "primary"),
            ("confirmados", "confirmados", "success"),
            ("revisao", "para revisar", "warning"),
            ("erros", "folhas com erro", "danger"),
        ]):
            bloco = ttk.Frame(self.frame_numeros)
            bloco.grid(row=0, column=coluna, sticky="w", padx=(0, 34))
            valor = ttk.Label(bloco, text="0", font=estilos.FONTE_DESTAQUE_NUMERO, bootstyle=estilo)
            valor.pack(anchor="w")
            ttk.Label(bloco, text=rotulo, bootstyle="secondary").pack(anchor="w")
            self._numeros_resultado[chave] = valor
        # O bloco de erros só aparece quando houver erro: um "0" permanente
        # em vermelho treina o olho a ignorar justamente o número que
        # precisa ser notado quando deixar de ser zero.
        self._bloco_erros = self._numeros_resultado["erros"].master

        self.lbl_resultado_proximo = ttk.Label(
            self.moldura_resultado, text="", wraplength=760, justify="left",
        )

        acoes_resultado = ttk.Frame(self.moldura_resultado)
        self._acoes_resultado = acoes_resultado
        self.btn_inicio_revisar = ttk.Button(
            acoes_resultado, text="Revisar pendências", bootstyle="warning",
            command=self._abrir_revisao, width=26,
        )
        self.btn_inicio_revisar.pack(side="left")
        self.btn_inicio_salvar = ttk.Button(
            acoes_resultado, text="Gerar planilha", bootstyle="success",
            command=self._on_salvar, width=20,
        )
        self.btn_inicio_salvar.pack(side="left", padx=(10, 0))
        self.btn_inicio_registros = ttk.Button(
            acoes_resultado, text="Ver registros", bootstyle="secondary-outline",
            command=lambda: self._selecionar_aba(self._aba_registros), width=16,
        )
        self.btn_inicio_registros.pack(side="left", padx=(10, 0))
        self.btn_inicio_avisos = ttk.Button(
            acoes_resultado, text="Ver avisos", bootstyle="secondary-outline",
            command=lambda: self._selecionar_aba(self._aba_avisos), width=16,
        )

    # ------------------------------------------------------------------
    def _montar_cartao_selecao(self):
        """
        Etapa 2: conferir o que foi selecionado ANTES de começar.

        Antes da Fase 21a esta etapa não existia -- escolher o arquivo já
        disparava o OCR. Num lote real isso significa descobrir que
        selecionou a pasta errada depois de ~40 s por folha já gastos, e
        com as folhas erradas já misturadas aos resultados (que se
        ACUMULAM, ver `_on_limpar`).
        """
        cartao = ttk.Frame(self._container_fluxo, style="Canvas.TFrame")
        self._cartao_selecao = cartao

        ttk.Label(cartao, text="Confira antes de processar", style="SecaoTitulo.TLabel").pack(
            side="top", anchor="w", pady=(0, estilos.ESPACO_SM),
        )
        moldura = ttk.Frame(cartao, style="Card.TFrame", padding=estilos.ESPACO_LG)
        moldura.pack(side="top", fill="x")

        self.lbl_selecao_titulo = ttk.Label(moldura, text="", font=estilos.FONTE_TITULO_CARTAO)
        self.lbl_selecao_titulo.pack(anchor="w")
        self.lbl_selecao_detalhe = ttk.Label(
            moldura, text="", bootstyle="secondary", wraplength=780, justify="left",
        )
        self.lbl_selecao_detalhe.pack(anchor="w", pady=(4, 0))
        # Aviso de acumulação: só quando já houver resultados na sessão.
        self.lbl_selecao_acumulo = ttk.Label(
            moldura, text="", bootstyle="info", wraplength=780, justify="left",
        )

        acoes = ttk.Frame(moldura)
        acoes.pack(side="top", fill="x", pady=(16, 0))
        self.btn_selecao_processar = ttk.Button(
            acoes, text="Processar", bootstyle="success",
            command=self._processar_selecao_pendente, width=26,
        )
        self.btn_selecao_processar.pack(side="left")
        self.btn_selecao_trocar = ttk.Button(
            acoes, text="Escolher outros arquivos", bootstyle="secondary-outline",
            command=self._trocar_selecao, width=24,
        )
        self.btn_selecao_trocar.pack(side="left", padx=(10, 0))
        self.btn_selecao_cancelar = ttk.Button(
            acoes, text="Cancelar", bootstyle="secondary-outline",
            command=self._cancelar_selecao, width=14,
        )
        self.btn_selecao_cancelar.pack(side="left", padx=(10, 0))

        ttk.Label(
            moldura,
            text="A leitura leva cerca de 40 segundos por folha. Enquanto ela corre, "
                 "as folhas já lidas vão aparecendo na aba Registros.",
            bootstyle="secondary", wraplength=780, justify="left",
        ).pack(anchor="w", pady=(12, 0))

    # ------------------------------------------------------------------
    def _montar_cartao_processando(self):
        """Etapa 3: o que está acontecendo agora, e há quanto tempo."""
        cartao = ttk.Frame(self._container_fluxo, style="Canvas.TFrame")
        self._cartao_processando = cartao

        ttk.Label(cartao, text="Processando", style="SecaoTitulo.TLabel").pack(
            side="top", anchor="w", pady=(0, estilos.ESPACO_SM),
        )
        moldura = ttk.Frame(cartao, style="Card.TFrame", padding=estilos.ESPACO_LG)
        moldura.pack(side="top", fill="x")

        self.lbl_proc_titulo = ttk.Label(moldura, text="", font=estilos.FONTE_TITULO_CARTAO)
        self.lbl_proc_titulo.pack(anchor="w")

        self.barra_proc_inicio = ttk.Progressbar(
            moldura, mode="determinate", maximum=100, value=0, bootstyle="primary-striped",
        )
        self.barra_proc_inicio.pack(side="top", fill="x", pady=(12, 6))

        self.lbl_proc_etapa = ttk.Label(moldura, text="", wraplength=780, justify="left")
        self.lbl_proc_etapa.pack(anchor="w")
        # Tempo DECORRIDO e média MEDIDA. Nenhuma previsão de término: o
        # tempo por folha varia com a foto, e um "faltam 3 min" que erra é
        # pior que não ter estimativa nenhuma.
        self.lbl_proc_tempo = ttk.Label(moldura, text="", bootstyle="secondary")
        self.lbl_proc_tempo.pack(anchor="w", pady=(4, 0))

        ttk.Label(
            moldura,
            text="Pode acompanhar as folhas já lidas na aba Registros — o programa "
                 "continua respondendo enquanto lê.",
            bootstyle="secondary", wraplength=780, justify="left",
        ).pack(anchor="w", pady=(12, 0))

    # ------------------------------------------------------------------
    # Máquina de estados da aba Início
    # ------------------------------------------------------------------
    def _selecionar_aba(self, aba):
        try:
            self.abas.select(aba)
        except Exception:
            logging.exception("Falha ao trocar de aba (apenas navegação)")

    def _ir_para_etapa(self, etapa):
        """Mostra o cartão da etapa pedida e esconde os outros."""
        self._etapa_fluxo = etapa
        cartoes = {
            "pronto": self._cartao_pronto,
            "selecao": self._cartao_selecao,
            "processando": self._cartao_processando,
        }
        for nome, cartao in cartoes.items():
            try:
                if nome == etapa:
                    cartao.pack(side="top", fill="both", expand=True)
                else:
                    cartao.pack_forget()
            except Exception:
                logging.exception("Falha ao alternar o cartão do fluxo (apenas cosmético)")
        if etapa == "pronto":
            self._atualizar_cartao_pronto()
        elif etapa == "processando":
            self._atualizar_cartao_processando()

    def _atualizar_cartao_pronto(self):
        """Preenche a tela de resultado a partir do que já foi processado."""
        total = len(self._registros_exportacao)

        if self._lote_concluido:
            self.lbl_inicio_concluido.config(text="✓ Processamento concluído")
            self.lbl_inicio_concluido.pack(
                side="top", anchor="w", pady=(0, 12), before=self._moldura_acoes_inicio,
            )
        else:
            self.lbl_inicio_concluido.pack_forget()

        # Sem pady extra aqui: o espaçamento acima já vem do título
        # ("Último processamento", packed em `_montar_cartao_pronto`),
        # que é sempre visível junto com este cartão.
        self.moldura_resultado.pack(side="top", fill="x")

        if not total:
            self.frame_numeros.pack_forget()
            self.lbl_resultado_proximo.pack_forget()
            self._acoes_resultado.pack_forget()
            self.lbl_resultado_vazio.pack(side="top", anchor="w")
            return

        self.lbl_resultado_vazio.pack_forget()

        confirmados = sum(1 for r in self._registros_exportacao if r["status"] == "CONFIRMADO")
        pendentes = len(self._indices_pendentes_revisao())
        erros = sum(1 for r in self._registros_exportacao if r["status"] == "ERRO")

        self._numeros_resultado["folhas"].config(text=str(self._paginas_processadas))
        self._numeros_resultado["total"].config(text=str(total))
        self._numeros_resultado["confirmados"].config(text=str(confirmados))
        self._numeros_resultado["revisao"].config(text=str(pendentes))
        self._numeros_resultado["erros"].config(text=str(erros))
        if erros:
            self._bloco_erros.grid()
        else:
            self._bloco_erros.grid_remove()
        self.frame_numeros.pack(side="top", fill="x", anchor="w")

        # O PRÓXIMO PASSO, dito com todas as letras -- é a pergunta que a
        # tela de conclusão precisa responder, e que antes ficava por conta
        # do operador deduzir de quais botões tinham acendido.
        if pendentes:
            proximo = (
                f"Próximo passo: {pendentes} registro(s) precisam da sua conferência "
                "antes de virarem planilha."
            )
        else:
            proximo = "Tudo conferido. Próximo passo: gerar a planilha."
        if erros:
            proximo += f" {erros} folha(s) falharam e precisam ser processadas de novo — veja em Avisos."
        self.lbl_resultado_proximo.config(text=proximo)
        self.lbl_resultado_proximo.pack(side="top", anchor="w", pady=(14, 0))

        # A ação principal do momento é a que fica destacada: revisar
        # enquanto houver pendência, gerar planilha quando não houver mais.
        if pendentes:
            self.btn_inicio_revisar.config(
                text=f"Revisar pendências ({pendentes})", bootstyle="warning", state="normal",
            )
            self.btn_inicio_salvar.config(bootstyle="success-outline")
        else:
            self.btn_inicio_revisar.config(
                text="Revisar pendências (0)", bootstyle="secondary-outline", state="disabled",
            )
            self.btn_inicio_salvar.config(bootstyle="success")
        self.btn_inicio_salvar.config(state="disabled" if self._processando else "normal")
        if erros:
            self.btn_inicio_avisos.pack(side="left", padx=(10, 0))
        else:
            self.btn_inicio_avisos.pack_forget()
        self._acoes_resultado.pack(side="top", fill="x", pady=(14, 0))

    def _atualizar_cartao_processando(self):
        total = self._total_paginas_lote
        feitas = self._paginas_processadas_lote
        if total:
            atual = min(feitas + 1, total)
            self.lbl_proc_titulo.config(text=f"Lendo a folha {atual} de {total}")
            pct = 100.0 * feitas / total
            self.barra_proc_inicio.config(mode="determinate", value=pct)
        else:
            # Uma folha só: não há denominador, e inventar um seria mentir.
            self.lbl_proc_titulo.config(text="Lendo a folha selecionada")
            self.barra_proc_inicio.config(value=0)

        self.lbl_proc_etapa.config(text=self._etapa_atual or "Preparando...")
        self.lbl_proc_tempo.config(text=self._texto_tempo_decorrido())

    def _texto_tempo_decorrido(self):
        if self._instante_inicio_lote is None:
            return ""
        decorrido = time.monotonic() - self._instante_inicio_lote
        texto = f"Tempo decorrido: {mensagens.duracao_legivel(decorrido)}"
        # A média só é dita depois que existe alguma folha medida -- antes
        # disso seria um número tirado do nada.
        if self._paginas_processadas_lote:
            media = decorrido / self._paginas_processadas_lote
            texto += f"  ·  média medida: {mensagens.duracao_legivel(media)} por folha"
        return texto

    def _tick_processando(self):
        """Mantém o tempo decorrido vivo mesmo entre duas folhas (o OCR de
        uma folha leva ~40 s; sem isto o relógio ficaria parado o tempo
        todo e a tela pareceria travada)."""
        self._ticker_processando = None
        if not self._processando:
            return
        try:
            # Fechar a janela no meio de um lote deixa este callback
            # agendado sobre widgets que já não existem -- mostrar o tempo
            # decorrido nunca pode ser motivo de erro na saída do programa.
            if not self.winfo_exists():
                return
            if self._etapa_fluxo == "processando":
                self.lbl_proc_tempo.config(text=self._texto_tempo_decorrido())
            self._ticker_processando = self.after(1000, self._tick_processando)
        except Exception:
            logging.exception("Falha ao atualizar o tempo decorrido (apenas informativo)")

    # ------------------------------------------------------------------
    def _montar_aba_registros(self):
        # Sub-fase 22d: mesma técnica canvas+cartão das demais abas -- a
        # tabela (já era o elemento mais "de produto" da interface, achado
        # 8 da auditoria 22a) ganha uma moldura de cartão branco sobre o
        # canvas cinza, em vez de ficar solta contra o fundo da aba.
        aba = ttk.Frame(self.abas, padding=estilos.ESPACO_MD, style="Canvas.TFrame")
        self.abas.add(aba, text="Registros")
        self._aba_registros = aba

        filtros = ttk.Frame(aba, style="Canvas.TFrame")
        filtros.pack(side="top", fill="x", pady=(0, estilos.ESPACO_SM))
        ttk.Label(filtros, text="Mostrar:", style="Canvas.TLabel").pack(side="left", padx=(0, 6))
        self.filtro_var = tk.StringVar(value=FILTROS_TABELA[0])
        self.combo_filtro = ttk.Combobox(
            filtros, textvariable=self.filtro_var, values=list(FILTROS_TABELA),
            state="readonly", width=14,
        )
        self.combo_filtro.pack(side="left")
        self.combo_filtro.bind("<<ComboboxSelected>>", lambda _e: self._sincronizar_tabela_principal())
        self.lbl_contagem_tabela = ttk.Label(filtros, text="", style="CanvasSecundario.TLabel")
        self.lbl_contagem_tabela.pack(side="left", padx=12)

        # Estado vazio (Fase 21a): uma grade de 12 colunas em branco não
        # diz que não há nada A FAZER ali -- parece um formulário que o
        # operador deveria estar preenchendo. O texto ocupa o lugar da
        # tabela enquanto não houver linha nenhuma e diz para onde ir.
        self.lbl_tabela_vazia = ttk.Label(
            aba, text=mensagens.VAZIO_TABELA, style="CanvasSecundario.TLabel",
            justify="center", anchor="center",
        )

        moldura = ttk.Frame(aba, style="Card.TFrame", padding=estilos.ESPACO_SM)
        self._moldura_tabela = moldura
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
        # e legível, sem depender só da cor (o rótulo de status também diz,
        # em texto -- ver `_rotulo_status`/`ui/estilos.py`). As três cores
        # vêm do mesmo vocabulário que decide o texto, para nunca haver uma
        # linha "revisão" com a cor de "erro" por engano.
        for status in ("CONFIRMADO", "REVISAO", "ERRO"):
            self.tabela.tag_configure(
                estilos.tag_status(status),
                background=estilos.cor_fundo_tabela_status(status),
            )

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
        """
        Sub-fase 21b: a revisão passou a ter TRÊS áreas lado a lado, na
        ordem em que o operador raciocina sobre uma linha pendente --
        "o que falta revisar" (lista), "o que a folha realmente diz" (a
        foto), "o que eu decido e como confirmo" (formulário, com o campo
        bloqueante em destaque). Antes eram só foto + formulário: não
        havia nenhuma visão do conjunto, só do item atual -- então navegar
        entre pendências era só "próximo", nunca "vou direto na linha 9
        porque é matrícula, que eu sei resolver rápido".

        Nada disto substitui `_revisao_confirmar` (Fase 7/12): esta função
        só monta widgets, nenhum deles decide nada.

        Sub-fase 22c: as três áreas ganharam a mesma linguagem visual da
        22b (título + `Card.TFrame` sobre `Canvas.TFrame`, no lugar de
        `ttk.Labelframe`) -- a aba inteira passou a ser canvas cinza, com
        cada área como um cartão branco flutuando dentro do seu painel do
        `PanedWindow`. Nenhuma mudança de ESTRUTURA de informação: mesmas
        três áreas, mesma ordem, mesmos widgets com os mesmos nomes.
        """
        aba = ttk.Frame(self.abas, padding=estilos.ESPACO_MD, style="Canvas.TFrame")
        self.abas.add(aba, text="Revisão")
        self._aba_revisao = aba

        # Estado vazio (mesmo padrão da aba Registros -- Fase 21a): a
        # revisão pode estar vazia por dois motivos BEM diferentes ("ainda
        # não processei nada" x "processei e não sobrou pendência", que é
        # a boa notícia), então o texto muda conforme o caso em
        # `_atualizar_estado_vazio_revisao`.
        self.lbl_revisao_vazio = ttk.Label(
            aba, text="", style="CanvasSecundario.TLabel", anchor="center", justify="center",
        )

        painel = ttk.PanedWindow(aba, orient="horizontal")
        self._moldura_revisao_painel = painel
        painel.pack(side="top", fill="both", expand=True)

        # ---- área 1: lista de pendências -------------------------------
        # Um nível a mais que antes (painel_lista envolve título + cartão)
        # -- é o mesmo padrão de `_montar_cartao_pronto` (22b): o painel do
        # PanedWindow é canvas cinza, o título fica sobre ele, e só o
        # cartão abaixo é branco.
        painel_lista = ttk.Frame(painel, style="Canvas.TFrame", padding=(0, 0, estilos.ESPACO_SM, 0))
        painel.add(painel_lista, weight=2)
        ttk.Label(painel_lista, text="Pendências", style="SecaoTitulo.TLabel").pack(
            side="top", anchor="w", pady=(0, estilos.ESPACO_SM)
        )
        moldura_lista = ttk.Frame(painel_lista, style="Card.TFrame", padding=estilos.ESPACO_MD)
        moldura_lista.pack(side="top", fill="both", expand=True)

        self.lbl_revisao_progresso = ttk.Label(
            moldura_lista, text="", bootstyle="secondary", justify="left", wraplength=210,
        )
        self.lbl_revisao_progresso.pack(side="top", fill="x", pady=(0, 6))

        # Sub-fase 21d: filtro por tipo de pendência + busca textual --
        # necessidade real medida nas Fases 9/16/18 (Responsável é o maior
        # grupo de pendência real, 10-11 de 21 linhas nas 5 folhas reais) e
        # confirmada de novo pela 21b (13 das 21 linhas do lote real têm
        # sinal de contexto de Responsável). Um lote de 50 folhas pode
        # facilmente passar de 100 pendências -- revisar "todas as de
        # Responsável em sequência" (ou achar a matrícula 27325 sem rolar a
        # lista à mão) é produtividade real, não especulação. Os dois só
        # controlam o que APARECE e pode ser CLICADO nesta lista -- nunca
        # alteram `_indices_pendentes_revisao()` nem o que
        # Anterior/Próximo percorrem (ver `_atualizar_lista_revisao_pendencias`).
        controles_lista = ttk.Frame(moldura_lista)
        controles_lista.pack(side="top", fill="x", pady=(0, 6))
        ttk.Label(controles_lista, text="Tipo:", bootstyle="secondary").grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        self.revisao_filtro_tipo_var = tk.StringVar(value=FILTRO_REVISAO_TODAS)
        valores_filtro = [FILTRO_REVISAO_TODAS] + list(explicacao_revisao.ROTULOS.values())
        self.combo_revisao_filtro_tipo = ttk.Combobox(
            controles_lista, textvariable=self.revisao_filtro_tipo_var,
            values=valores_filtro, state="readonly", width=13,
        )
        self.combo_revisao_filtro_tipo.grid(row=0, column=1, sticky="ew")
        self.combo_revisao_filtro_tipo.bind(
            "<<ComboboxSelected>>", lambda _e: self._atualizar_lista_revisao_pendencias()
        )
        controles_lista.columnconfigure(1, weight=1)

        self.revisao_busca_var = tk.StringVar()
        self.entrada_revisao_busca = ttk.Entry(
            controles_lista, textvariable=self.revisao_busca_var,
        )
        self.entrada_revisao_busca.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        # Placeholder simples (ttk não tem placeholder nativo): o texto de
        # apoio some assim que o operador clicar dentro do campo.
        self._revisao_busca_placeholder_ativo = False
        self._ativar_placeholder_busca_revisao()
        self.entrada_revisao_busca.bind("<FocusIn>", self._on_foco_busca_revisao)
        self.entrada_revisao_busca.bind("<FocusOut>", self._on_saida_busca_revisao)
        # Esc limpa a busca -- convenção segura e bem conhecida (nunca
        # confirma nada, só descarta o texto de filtro).
        self.entrada_revisao_busca.bind("<Escape>", self._on_escape_busca_revisao)
        self.revisao_busca_var.trace_add("write", lambda *_a: self._atualizar_lista_revisao_pendencias())

        self.lbl_revisao_lista_contagem = ttk.Label(
            moldura_lista, text="", bootstyle="secondary",
        )
        self.lbl_revisao_lista_contagem.pack(side="top", fill="x", pady=(0, 4))

        moldura_lista_tabela = ttk.Frame(moldura_lista)
        moldura_lista_tabela.pack(side="top", fill="both", expand=True)
        # `bootstyle="light"` (não `style=`) de propósito: o `ttkbootstrap`
        # intercepta a CONSTRUÇÃO de todo widget `ttk` e recusa um nome de
        # estilo customizado que não reconheça como uma de suas cores --
        # `style="RevisaoLista.Treeview"` foi tentado e ignorado em
        # silêncio (a Treeview voltava ao estilo `"Treeview"` plano,
        # PARTILHADO com a tabela de Registros). `bootstyle="light"` é uma
        # cor que o `ttkbootstrap` reconhece e usa para gerar um estilo
        # PRÓPRIO ("light.Treeview"), isolado da tabela de Registros --
        # é esse nome que `_montar_estilos_visuais` ajusta depois, só a
        # cor da linha SELECIONADA (ver comentário lá).
        self.tabela_revisao_lista = ttk.Treeview(
            moldura_lista_tabela, columns=("pagina", "matricula", "pendencia"),
            show="headings", selectmode="browse", bootstyle="light",
        )
        for coluna, titulo, largura in [
            ("pagina", "Pág.", 40), ("matricula", "Matrícula", 70), ("pendencia", "Pendência", 100),
        ]:
            self.tabela_revisao_lista.heading(coluna, text=titulo)
            self.tabela_revisao_lista.column(coluna, width=largura, anchor="w", stretch=(coluna == "pendencia"))
        # Cor de TEXTO por tipo de campo -- não de fundo, para não "exagerar
        # em cores" (pedido explícito do escopo). É o mesmo vocabulário de
        # `explicacao_revisao.ROTULOS`.
        for campo, cor in CORES_TIPO_PENDENCIA.items():
            self.tabela_revisao_lista.tag_configure(campo, foreground=cor)
        # `estilos.COR_TIPO_PENDENCIA_PADRAO` (atributo, não import direto
        # -- é uma string, `aplicar_paleta()` REBINDA o nome no módulo,
        # e só o acesso por atributo enxerga o valor novo depois disso).
        self.tabela_revisao_lista.tag_configure("outro", foreground=estilos.COR_TIPO_PENDENCIA_PADRAO)
        # Sub-fase 22c: realce sutil sob o cursor (hover), só de fundo --
        # nunca muda a cor de texto por tipo de campo, que continua vindo
        # das tags acima. Puramente cosmético: não participa da seleção
        # real (`tabela.selection()`), só do que o olho segue no mouse.
        self.tabela_revisao_lista.tag_configure("hover", background=estilos.COR_FUNDO)
        self._aplicar_selecao_lista_revisao()
        vsb_lista = ttk.Scrollbar(moldura_lista_tabela, orient="vertical", command=self.tabela_revisao_lista.yview)
        self.tabela_revisao_lista.configure(yscrollcommand=vsb_lista.set)
        self.tabela_revisao_lista.grid(row=0, column=0, sticky="nsew")
        vsb_lista.grid(row=0, column=1, sticky="ns")
        moldura_lista_tabela.rowconfigure(0, weight=1)
        moldura_lista_tabela.columnconfigure(0, weight=1)
        # Clicar numa pendência da lista vai direto para ela -- a mesma
        # ação que "Próximo"/"Anterior" fazem, só que por escolha, não em
        # sequência.
        self.tabela_revisao_lista.bind("<<TreeviewSelect>>", self._on_selecionar_pendencia_lista)
        # Sub-fase 22c: hover sutil -- só troca a tag "hover" da linha sob o
        # cursor, nunca a seleção real nem `revisao_vars`. `<Leave>` limpa
        # ao sair da lista inteira.
        self.tabela_revisao_lista.bind("<Motion>", self._on_hover_lista_revisao)
        self.tabela_revisao_lista.bind("<Leave>", self._limpar_hover_lista_revisao)
        # Sub-fase 21d: ← → como atalho de "Anterior"/"Próximo" -- só
        # ativo quando a LISTA tem o foco (não o formulário), então nunca
        # interfere com o cursor de texto dentro de Data/Hora/Matrícula
        # (onde ← → precisam continuar movendo o cursor normalmente). ↑ ↓
        # já navegam por padrão do próprio Treeview (mudam a seleção, que
        # já dispara `_on_selecionar_pendencia_lista`) -- não precisou de
        # binding novo. Nunca confirma nada: só chama a mesma
        # `_revisao_navegar` que os botões já chamam.
        self.tabela_revisao_lista.bind("<Left>", self._on_seta_esquerda_revisao)
        self.tabela_revisao_lista.bind("<Right>", self._on_seta_direita_revisao)

        # ---- área 2: a foto da folha ------------------------------------
        # Mesmo padrão de título + Card da área 1. Padding do cartão menor
        # de propósito (ESPACO_SM, não ESPACO_MD como as demais seções): é
        # a foto que precisa do espaço, não a moldura ao redor dela.
        painel_foto = ttk.Frame(painel, style="Canvas.TFrame", padding=(estilos.ESPACO_SM, 0))
        painel.add(painel_foto, weight=4)
        ttk.Label(painel_foto, text="Folha digitalizada", style="SecaoTitulo.TLabel").pack(
            side="top", anchor="w", pady=(0, estilos.ESPACO_SM)
        )
        moldura_foto = ttk.Frame(painel_foto, style="Card.TFrame", padding=estilos.ESPACO_SM)
        moldura_foto.pack(side="top", fill="both", expand=True)

        controles_foto = ttk.Frame(moldura_foto)
        controles_foto.pack(side="top", fill="x", pady=(0, 6))
        ttk.Button(controles_foto, text=estilos.ICONE_ZOOM_DIMINUIR, width=3, bootstyle="secondary-outline",
                   command=lambda: self._ajustar_zoom(0.8)).pack(side="left")
        ttk.Button(controles_foto, text=estilos.ICONE_ZOOM_AUMENTAR, width=3, bootstyle="secondary-outline",
                   command=lambda: self._ajustar_zoom(1.25)).pack(side="left", padx=(4, 0))
        ttk.Button(controles_foto, text="Ajustar", bootstyle="secondary-outline",
                   command=self._ajustar_zoom_para_caber).pack(side="left", padx=(4, 0))
        self.lbl_pagina_foto = ttk.Label(controles_foto, text="", bootstyle="secondary")
        self.lbl_pagina_foto.pack(side="right")

        moldura_canvas = ttk.Frame(moldura_foto)
        moldura_canvas.pack(side="top", fill="both", expand=True)
        # Moldura de 1px ao redor do visor -- um "passe-partout" claro
        # (COR_FUNDO) delimitado por uma borda discreta (COR_BORDA), em vez
        # de a foto encostar direto na borda do cartão branco.
        self.canvas_foto = tk.Canvas(
            moldura_canvas, background=estilos.COR_FUNDO,
            highlightthickness=1, highlightbackground=estilos.COR_BORDA,
        )
        vsb_foto = ttk.Scrollbar(moldura_canvas, orient="vertical", command=self.canvas_foto.yview)
        hsb_foto = ttk.Scrollbar(moldura_canvas, orient="horizontal", command=self.canvas_foto.xview)
        self.canvas_foto.configure(yscrollcommand=vsb_foto.set, xscrollcommand=hsb_foto.set)
        self.canvas_foto.grid(row=0, column=0, sticky="nsew")
        vsb_foto.grid(row=0, column=1, sticky="ns")
        hsb_foto.grid(row=1, column=0, sticky="ew")
        moldura_canvas.rowconfigure(0, weight=1)
        moldura_canvas.columnconfigure(0, weight=1)

        # ---- área 3: o que decidir e como confirmar ----------------------
        # Canvas cinza (mesmo padrão das áreas 1/2) -- as três seções
        # abaixo ("Por que está em revisão", "Campos lidos da folha",
        # "Obtido da base pela matrícula") viram título + Card sobre ele.
        moldura_form = ttk.Frame(painel, padding=(estilos.ESPACO_MD, 0, 0, 0), style="Canvas.TFrame")
        painel.add(moldura_form, weight=3)

        topo = ttk.Frame(moldura_form, style="Canvas.TFrame")
        topo.pack(side="top", fill="x")
        self.lbl_revisao_posicao = ttk.Label(topo, text="", style="PosicaoRevisao.TLabel")
        self.lbl_revisao_posicao.pack(side="left")

        # Resumo do bloqueio: SEMPRE visível, uma frase curta ("A dúvida
        # está em: Data"), para o operador nunca precisar abrir nada só
        # para saber o que está em jogo nesta linha. `ResumoRevisao.TLabel`
        # usa `COR_ATENCAO` (a mesma cor forte de "warning" do tema, só
        # com fundo compatível com o canvas -- ver `_montar_estilos_visuais`).
        self.lbl_revisao_resumo = ttk.Label(
            moldura_form, text="", style="ResumoRevisao.TLabel", wraplength=430, justify="left",
        )
        self.lbl_revisao_resumo.pack(side="top", fill="x", pady=(8, 2))

        # "Por que preciso revisar? [Ver detalhes]" -- Fase 18 continua
        # gerando a cadeia inteira de evidência (o que o OCR leu, a
        # normalização, o que a base respondeu); aqui ela só deixou de
        # aparecer sempre aberta, para não dominar a tela. Nunca expõe
        # nome de estrutura interna (DossieRegistro/Evidencia/limiar) --
        # `explicacao_revisao` já entrega só linguagem de operador. É a
        # ação TERCIÁRIA da tela (bootstyle "link", sem peso de botão).
        self.btn_revisao_detalhes = ttk.Button(
            moldura_form, text=f"Ver detalhes {estilos.ICONE_EXPANDIR}", bootstyle="link",
            command=self._alternar_detalhes_revisao, padding=0,
        )
        self.btn_revisao_detalhes.pack(side="top", anchor="w", pady=(0, 4))

        # `self.moldura_revisao_explicacao` continua sendo o widget que
        # `_atualizar_visibilidade_detalhes_revisao` mostra/esconde -- só
        # que agora é o GRUPO inteiro (título + cartão), não um
        # `Labelframe` sozinho. O comportamento de expandir/recolher não
        # mudou uma linha.
        self.moldura_revisao_explicacao = ttk.Frame(moldura_form, style="Canvas.TFrame")
        ttk.Label(
            self.moldura_revisao_explicacao, text="Por que está em revisão", style="SecaoTitulo.TLabel",
        ).pack(side="top", anchor="w", pady=(0, estilos.ESPACO_SM))
        _card_explicacao = ttk.Frame(self.moldura_revisao_explicacao, style="Card.TFrame", padding=estilos.ESPACO_MD)
        _card_explicacao.pack(side="top", fill="x")
        self.lbl_revisao_explicacao = ttk.Label(
            _card_explicacao, text="", wraplength=420, justify="left",
        )
        self.lbl_revisao_explicacao.pack(side="top", fill="x", anchor="w")
        # Os sinais de contexto (Fase 16/18 -- gestores do lote, ordem
        # cronológica) passaram a aparecer COLADOS ao campo a que se
        # referem (ver `_destacar_campos_revisao`), não mais soltos aqui:
        # é literalmente "a sugestão que o sistema já produziu, perto do
        # campo bloqueante", que é o pedido da 21b.

        # `self.moldura_revisao_campos` continua sendo a âncora do
        # `before=` que insere o painel de detalhes ACIMA desta seção
        # (ver `_atualizar_visibilidade_detalhes_revisao`) -- por isso
        # aponta para o GRUPO (título + cartão), não só o cartão.
        campos_grupo = ttk.Frame(moldura_form, style="Canvas.TFrame")
        campos_grupo.pack(side="top", fill="x")
        self.moldura_revisao_campos = campos_grupo
        ttk.Label(campos_grupo, text="Campos lidos da folha", style="SecaoTitulo.TLabel").pack(
            side="top", anchor="w", pady=(0, estilos.ESPACO_SM)
        )
        campos = ttk.Frame(campos_grupo, style="Card.TFrame", padding=estilos.ESPACO_MD)
        campos.pack(side="top", fill="x")

        self.revisao_vars = {}
        self.revisao_widgets = {}
        self.revisao_rotulos = {}
        self.revisao_dicas = {}
        # Sub-fase 22c: o texto ORIGINAL de cada rótulo (sem o ícone de
        # alerta), para `_destacar_campos_revisao` poder reconstruí-lo a
        # cada troca de registro sem acumular ícone repetido.
        self._revisao_rotulos_texto = {}
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
            linha_campo = 2 * i
            self._revisao_rotulos_texto[chave] = rotulo
            rotulo_widget = ttk.Label(campos, text=rotulo)
            rotulo_widget.grid(row=linha_campo, column=0, sticky="w", pady=(4, 0), padx=(0, 10))
            var = tk.StringVar()
            if tipo == "combo":
                try:
                    valores = sorted({str(v).strip() for v in (fonte_valores() or []) if str(v).strip()})
                except Exception:
                    valores = []
                widget = ttk.Combobox(campos, textvariable=var, values=valores, width=32)
            else:
                widget = ttk.Entry(campos, textvariable=var, width=34)
            widget.grid(row=linha_campo, column=1, sticky="ew", pady=(4, 0))
            self.revisao_vars[chave] = var
            self.revisao_widgets[chave] = widget
            self.revisao_rotulos[chave] = rotulo_widget
            # Linha da "sugestão que o sistema já produziu" para este campo
            # (Fase 16/18: só contexto medido -- nunca um candidato novo
            # buscado aqui). Some quando não há nada a mostrar; nunca
            # pré-seleciona nem escreve em `revisao_vars`.
            dica_widget = ttk.Label(
                campos, text="", bootstyle="info", wraplength=380, justify="left",
            )
            dica_widget.grid(row=linha_campo + 1, column=0, columnspan=2, sticky="w", padx=(0, 0), pady=(0, 2))
            dica_widget.grid_remove()
            self.revisao_dicas[chave] = dica_widget
        campos.columnconfigure(1, weight=1)

        ttk.Label(
            campos,
            text="Data em DD/MM/AA e hora em HH:MM. A hora é opcional;\n"
                 "a matrícula só pode conter dígitos.",
            bootstyle="secondary", justify="left",
        ).grid(row=2 * len(linhas), column=0, columnspan=2, sticky="w", pady=(8, 0))

        derivados_grupo = ttk.Frame(moldura_form, style="Canvas.TFrame")
        derivados_grupo.pack(side="top", fill="x", pady=(10, 0))
        ttk.Label(derivados_grupo, text="Obtido da base pela matrícula", style="SecaoTitulo.TLabel").pack(
            side="top", anchor="w", pady=(0, estilos.ESPACO_SM)
        )
        derivados = ttk.Frame(derivados_grupo, style="Card.TFrame", padding=estilos.ESPACO_MD)
        derivados.pack(side="top", fill="x")
        self.lbl_revisao_nome = ttk.Label(derivados, text="—", wraplength=430, justify="left")
        self.lbl_revisao_nome.pack(side="top", anchor="w")
        self.lbl_revisao_setor = ttk.Label(derivados, text="—", bootstyle="secondary", wraplength=430, justify="left")
        self.lbl_revisao_setor.pack(side="top", anchor="w", pady=(2, 0))

        # Erro de confirmação ("Ainda não é possível confirmar: ...") --
        # `style` fixo em vez de `bootstyle="danger"` dinâmico (ver
        # `_revisao_confirmar`): o texto SEMPRE que aparece aqui é erro, e
        # `bootstyle` sozinho não define o fundo (ficaria uma mancha branca
        # sobre o canvas cinza -- ver `_montar_estilos_visuais`).
        self.lbl_revisao_resultado = ttk.Label(
            moldura_form, text="", style="ResultadoRevisaoErro.TLabel", wraplength=430, justify="left",
        )
        self.lbl_revisao_resultado.pack(side="top", fill="x", pady=(10, 0))

        # Hierarquia de ações: PRINCIPAL (Confirmar, sólida/success, a que
        # encerra a decisão desta linha) à direita; SECUNDÁRIA (Anterior/
        # Próximo, outline, navegação sem decisão) agrupada à esquerda.
        # Já era essa a hierarquia desde a 21b -- aqui só os tokens de
        # ícone/espaçamento da 22a entraram no lugar de texto/pixel soltos.
        acoes = ttk.Frame(moldura_form, style="Canvas.TFrame")
        acoes.pack(side="bottom", fill="x", pady=(12, 0))
        self.btn_revisao_anterior = ttk.Button(
            acoes, text=f"{estilos.ICONE_ANTERIOR} Anterior", bootstyle="secondary-outline",
            command=lambda: self._revisao_navegar(-1), width=12,
        )
        self.btn_revisao_anterior.pack(side="left")
        self.btn_revisao_proximo = ttk.Button(
            acoes, text=f"Próximo {estilos.ICONE_PROXIMO}", bootstyle="secondary-outline",
            command=lambda: self._revisao_navegar(1), width=12,
        )
        self.btn_revisao_proximo.pack(side="left", padx=(estilos.ESPACO_SM, 0))
        # "Confirmar e próximo": o nome descreve o que acontece de fato --
        # `_revisao_confirmar` (Fase 7/12, intocada) já avança para a
        # próxima pendência sozinha quando a linha sai de REVISAO, porque a
        # lista de pendentes encolhe. Continua sendo o ÚNICO caminho para
        # sair de REVISAO.
        self.btn_revisao_confirmar = ttk.Button(
            acoes, text="Confirmar e próximo", bootstyle="success",
            command=self._revisao_confirmar, width=20,
        )
        self.btn_revisao_confirmar.pack(side="right")

    # ------------------------------------------------------------------
    def _montar_aba_avisos(self):
        aba = ttk.Frame(self.abas, padding=estilos.ESPACO_MD, style="Canvas.TFrame")
        self.abas.add(aba, text="Avisos")
        self._aba_avisos = aba

        ttk.Label(
            aba,
            text="Nada aqui bloqueia o processamento — são apontamentos para conferência no papel.",
            style="CanvasSecundario.TLabel",
        ).pack(side="top", anchor="w", pady=(0, estilos.ESPACO_SM))

        moldura = ttk.Frame(aba, style="Card.TFrame", padding=estilos.ESPACO_SM)
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
        # Sub-fase 22d: hover sutil, mesma técnica da lista de pendências
        # (22c) -- só faz sentido aqui porque as linhas de Avisos não têm
        # cor de fundo própria (ao contrário de Registros, que já usa o
        # fundo para dizer o status -- ver decisão registrada no relatório
        # sobre não sobrepor hover a essa cor).
        self.tabela_avisos.tag_configure("hover", background=estilos.COR_FUNDO)
        self.tabela_avisos.bind("<Motion>", self._on_hover_generico(self.tabela_avisos))
        self.tabela_avisos.bind("<Leave>", self._limpar_hover_generico(self.tabela_avisos))
        vsb = ttk.Scrollbar(moldura, orient="vertical", command=self.tabela_avisos.yview)
        self.tabela_avisos.configure(yscrollcommand=vsb.set)
        self.tabela_avisos.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        moldura.rowconfigure(0, weight=1)
        moldura.columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    def _montar_rodape(self):
        rodape = ttk.Frame(self, padding=(12, 0, 12, 10), style="Header.TFrame")
        rodape.pack(side="bottom", fill="x")
        # Mesma fronteira visual do cabeçalho (ver `_montar_cabecalho`),
        # do lado de baixo -- precisa ser packed DEPOIS do rodapé para
        # ficar entre ele e o canvas (pack empilha lados "bottom" na
        # ordem em que são chamados, do mais próximo da borda em diante).
        self._separador_horizontal(lado="bottom")

        self.lbl_status = ttk.Label(rodape, text="Nenhum arquivo selecionado.", style="Header.TLabel")
        self.lbl_status.pack(side="left")

        # Prefixo "Bases:" para que os três números do rodapé se leiam como
        # o que são -- o conteúdo das planilhas de referência carregadas --
        # e não como mais um contador do lote em andamento.
        self.lbl_bases = ttk.Label(
            rodape, text=f"Bases: {self._data_manager.resumo_status()}", style="HeaderSecundario.TLabel",
        )
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

        # Fase 21a: escolher o arquivo NÃO começa mais o processamento --
        # leva à etapa de conferência. O que dispara o OCR é o botão
        # "Processar" de lá (`_processar_selecao_pendente`), que reexecuta
        # exatamente o código que estava aqui antes, sem nenhuma mudança de
        # comportamento: só deixou de ser automático.
        nomes = [os.path.basename(c) for c in caminhos]
        self._registrar_selecao({
            "tipo": "imagens",
            "caminhos": caminhos,
            "total": len(caminhos),
            "titulo": mensagens.folhas_selecionadas(len(caminhos)),
            "detalhe": self._descrever_arquivos(nomes, caminhos[0]),
        })

    def _on_selecionar_pdf(self):
        if self._processando:
            return
        path = filedialog.askopenfilename(title="Selecione o PDF do mês", filetypes=EXTENSOES_PDF)
        if not path:
            return

        # Contar as páginas aqui responde "quantas folhas são?" ANTES de
        # gastar ~40 s de OCR por folha, e é também onde um PDF ilegível é
        # descoberto de imediato -- antes essa falha só aparecia depois de a
        # tela já ter entrado em "Processando...". `contar_paginas` é a
        # mesma função que o worker já usava; nada novo é lido do arquivo.
        try:
            total = pdf_reader.contar_paginas(path)
        except Exception as exc:
            logging.exception("Falha ao abrir o PDF selecionado")
            self._mostrar_falha("pdf", exc)
            return

        self._registrar_selecao({
            "tipo": "pdf",
            "caminho": path,
            "total": total,
            "titulo": f"{os.path.basename(path)} — {mensagens.plural_folhas(total)}",
            "detalhe": f"Pasta: {os.path.dirname(os.path.abspath(path))}",
        })

    @staticmethod
    def _descrever_arquivos(nomes, primeiro_caminho):
        """Lista curta dos arquivos escolhidos + a pasta de origem. Mostrar
        50 nomes não ajuda ninguém a conferir; mostrar os primeiros e a
        pasta, sim."""
        visiveis = ", ".join(nomes[:4])
        if len(nomes) > 4:
            visiveis += f" e mais {len(nomes) - 4}"
        return f"{visiveis}\nPasta: {os.path.dirname(os.path.abspath(primeiro_caminho))}"

    def _registrar_selecao(self, selecao):
        """Guarda o que foi escolhido e mostra a etapa de conferência."""
        self._selecao_pendente = selecao
        self.lbl_selecao_titulo.config(text=selecao["titulo"])
        self.lbl_selecao_detalhe.config(text=selecao["detalhe"])
        self.btn_selecao_processar.config(
            text=f"Processar {mensagens.plural_folhas(selecao['total'])}"
        )

        # Os resultados se ACUMULAM na mesma tabela até "Limpar resultados"
        # (comportamento antigo, mantido). Isso é útil -- é como se juntam
        # fotos avulsas ao PDF do mês -- mas é uma surpresa desagradável
        # quando não era a intenção, e até agora nada na tela avisava.
        if self._registros_exportacao:
            self.lbl_selecao_acumulo.config(
                text=f"ⓘ Estas folhas serão ACRESCENTADAS aos {len(self._registros_exportacao)} "
                     "registro(s) já processados. Para começar do zero, use “Limpar resultados”."
            )
            self.lbl_selecao_acumulo.pack(side="top", anchor="w", pady=(10, 0))
        else:
            self.lbl_selecao_acumulo.pack_forget()

        self._ir_para_etapa("selecao")
        self._selecionar_aba(self._aba_inicio)
        self.lbl_status.config(text=f"{selecao['titulo']} — confira e clique em “Processar”.")

    def _trocar_selecao(self):
        """Reabre o seletor do MESMO tipo já escolhido."""
        selecao = self._selecao_pendente
        self._cancelar_selecao()
        if selecao and selecao["tipo"] == "pdf":
            self._on_selecionar_pdf()
        else:
            self._on_selecionar_imagem()

    def _cancelar_selecao(self):
        self._selecao_pendente = None
        self._ir_para_etapa("pronto")
        self._atualizar_status(concluido=self._lote_concluido)

    def _processar_selecao_pendente(self):
        """
        Dispara o processamento do que foi conferido na etapa de seleção.

        O corpo é o mesmo que estava em `_on_selecionar_imagem` /
        `_on_selecionar_pdf` antes da Fase 21a -- mesmos workers, mesma
        fila, mesmo isolamento por página. A única diferença é QUANDO ele
        roda: depois de o operador confirmar, não no clique do seletor.
        """
        if self._processando or not self._selecao_pendente:
            return
        selecao = self._selecao_pendente
        self._selecao_pendente = None

        if selecao["tipo"] == "pdf":
            caminho = selecao["caminho"]
            self._arquivo_atual = os.path.basename(caminho)
            self._iniciar_processamento(f"Abrindo {self._arquivo_atual} ...")
            threading.Thread(target=self._worker_pdf, args=(caminho,), daemon=True).start()
            self.after(100, self._verificar_fila)
            return

        caminhos = selecao["caminhos"]
        if len(caminhos) == 1:
            path = caminhos[0]
            try:
                imagem = _ler_imagem(path)
            except Exception as exc:
                logging.exception("Falha ao abrir a foto selecionada")
                self._mostrar_falha("imagem", exc)
                self._ir_para_etapa("pronto")
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

    def _mostrar_falha(self, categoria, excecao=None, detalhe=""):
        """
        Único ponto por onde uma falha chega ao operador (Fase 21a).

        Traduz para linguagem operacional via `ui/mensagens.py` -- o que
        aconteceu, o que fazer, e só então o texto técnico. Antes o que
        aparecia era o `str(exc)` cru, que responde a pergunta do
        programador e nenhuma das duas do operador.
        """
        texto_tecnico = detalhe or (str(excecao) if excecao is not None else "")
        titulo, corpo = mensagens.descrever_falha(categoria, texto_tecnico)
        self.lbl_status.config(text=f"Erro: {titulo}")
        # Sub-fase 22d: `Messagebox` (ttkbootstrap), não `tkinter.
        # messagebox` -- achado 7 da auditoria 22a ("o ponto de maior
        # ruptura visual"): o diálogo nativo do SO não tem nenhuma relação
        # com o tema da aplicação. `Messagebox` desenha no mesmo tema
        # `cosmo`, com os mesmos ícones/botões do resto do app. A
        # microcopy (`titulo`/`corpo`, vinda de `ui/mensagens.py`) não
        # muda -- só a moldura em volta dela. Ordem dos argumentos
        # invertida em relação ao `tkinter.messagebox` (mensagem primeiro,
        # título depois).
        Messagebox.show_error(corpo, titulo, parent=self)

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

        # Fase 21a: entra na tela de acompanhamento e liga o relógio do
        # tempo decorrido. Continua sendo chamado direto pelos testes com
        # um texto de status qualquer -- por isso tudo aqui é tolerante a
        # ser chamado fora do fluxo da aba Início.
        self._etapa_atual = "Preparando..."
        self._instante_inicio_lote = time.monotonic()
        self._lote_concluido = False
        self._alternar_acoes_inicio(habilitado=False)
        self._ir_para_etapa("processando")
        if self._ticker_processando is None:
            self._ticker_processando = self.after(1000, self._tick_processando)

    def _finalizar_processamento(self):
        self._processando = False
        self.btn_imagem.config(state="normal")
        self.btn_pdf.config(state="normal")
        self.btn_limpar.config(state="normal")
        if self._registros_exportacao:
            self.btn_salvar.config(state="normal")
        self._etapa_atual = ""
        if self._ticker_processando is not None:
            try:
                self.after_cancel(self._ticker_processando)
            except Exception:
                pass
            self._ticker_processando = None
        self._alternar_acoes_inicio(habilitado=True)

    def _alternar_acoes_inicio(self, habilitado):
        """As ações de entrada da aba Início seguem as do cabeçalho: durante
        o processamento não faz sentido abrir outro seletor de arquivos."""
        estado = "normal" if habilitado else "disabled"
        for botao in (getattr(self, "btn_inicio_imagens", None), getattr(self, "btn_inicio_pdf", None)):
            try:
                if botao is not None:
                    botao.config(state=estado)
            except Exception:
                pass

    def _informar_etapa(self, texto):
        """
        Chamado DA THREAD WORKER: nunca toca em widget, só põe uma mensagem
        na fila -- o mesmo canal (e a mesma regra) que os resultados já
        usam desde sempre. É informação de acompanhamento; não participa de
        nenhuma decisão.
        """
        try:
            self._fila_resultados.put(("etapa", texto))
        except Exception:
            logging.exception("Falha ao informar a etapa atual (apenas informativo)")

    # ==================================================================
    # Workers (thread separada -- nunca tocam no Tkinter diretamente)
    # ==================================================================
    def _processar_uma_pagina(self, imagem_bgr):
        """Devolve (imagem_processada, registros, erro). Nunca levanta exceção.

        Fase 24a: o corpo do pipeline (pré-processar -> OCR -> parser ->
        reparo DATA+HORA) morou aqui até esta fase; agora é
        `pipeline.processar_uma_pagina`, para que o backend web chame a
        MESMA função sem precisar instanciar `App` (que abre uma janela).
        O que continua sendo responsabilidade DESTA classe é só o cache do
        engine (`self._ocr_engine`, reaproveitado entre páginas da mesma
        sessão) -- o backend web mantém o seu próprio cache, do jeito que
        fizer sentido para um processo sem Tkinter.

        Efeito colateral cosmético desta extração, registrado por
        completude: a mensagem "Iniciando o leitor de texto (só na
        primeira folha)" passa a aparecer ANTES de "Preparando a imagem da
        folha" na primeira página (antes vinha depois -- ver `saida/
        avaliacao_fase24_web.md`, seção 24a). `_informar_etapa` é
        puramente informativo -- não participa de nenhuma decisão -- então
        a ordem das duas frases não muda nenhum resultado.
        """
        if self._ocr_engine is None:
            self._informar_etapa("Iniciando o leitor de texto (só na primeira folha)")
            try:
                self._ocr_engine = get_ocr_engine("paddleocr")
            except ImportError as exc:
                return None, [], f"PaddleOCR não instalado: {exc}"

        return pipeline.processar_uma_pagina(
            imagem_bgr, self._ocr_engine, informar_etapa=self._informar_etapa
        )

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
            # Fase 21a: a categoria vem do título que o worker já produzia
            # ("Erro ao abrir o PDF", "Erro inesperado processando a
            # imagem"), então o protocolo da fila não mudou. O texto da
            # exceção continua na mensagem -- só deixou de ser tudo o que
            # o operador recebe (ver ui/mensagens.py).
            self._mostrar_falha(mensagens.categoria_da_origem(titulo), detalhe=mensagem)
            self._ir_para_etapa("pronto")
            return

        if tipo == "etapa":
            # Puramente informativo (Fase 21a): em que passo a folha está.
            self._etapa_atual = item[1]
            if self._etapa_fluxo == "processando":
                self.lbl_proc_etapa.config(text=self._etapa_atual)
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
            self._lote_concluido = True
            self._atualizar_status(concluido=True)
            self._atualizar_painel_revisao()
            # Fase 21a: terminar o lote leva de volta à tela de resultado,
            # que é onde estão os números e o próximo passo. Antes o único
            # sinal de conclusão era a palavra "Concluído" no rodapé e a
            # barra de progresso sumindo -- dois sinais discretos demais
            # para o fim de um trabalho de uma hora.
            self._ir_para_etapa("pronto")
            self._selecionar_aba(self._aba_inicio)
            return

    def _atualizar_status(self, concluido=False):
        # Fase 7 (operação em lote): enquanto processando, mostra
        # progresso "X/Y" da leva atual quando o total é conhecido (PDF,
        # ou seleção múltipla de imagens) -- um lote de ~50 folhas reais
        # leva bem mais de meia hora, e não ter nenhum indício de quanto
        # falta é o tipo de incerteza que leva o operador a fechar o
        # programa achando que travou, perdendo tudo que já tinha sido
        # processado (nada é salvo em disco até "Gerar planilha").
        # Fase 21a: com nada processado e nada rodando, a barra dizia
        # "Processando... Páginas: 0 | Confirmados: 0 | Revisão: 0" -- era
        # a PRIMEIRA frase que o programa mostrava ao abrir, e era falsa.
        # A causa é que o prefixo vinha de `concluido`, e não de estar ou
        # não processando (o construtor chama este método com
        # concluido=False).
        if not self._processando and not self._registros_exportacao:
            self.lbl_status.config(
                text="Pronto. Escolha as fotos das folhas ou o PDF do mês na aba Início."
            )
            self._atualizar_progresso(concluido)
            self._atualizar_rotulos_abas()
            return

        if self._processando and self._total_paginas_lote:
            rotulo_paginas = f"Folha {self._paginas_processadas_lote}/{self._total_paginas_lote}"
        else:
            rotulo_paginas = f"Folhas lidas: {self._paginas_processadas}"
        partes = [
            rotulo_paginas,
            f"Confirmados: {self._contador_confirmados}",
            f"Para revisar: {self._contador_revisao}",
        ]
        if self._paginas_com_erro:
            partes.append(f"Folhas com erro: {self._paginas_com_erro}")
        if self._processando:
            prefixo = "Processando... "
        elif concluido or self._lote_concluido:
            prefixo = "Concluído — "
        else:
            prefixo = ""
        self.lbl_status.config(text=prefixo + " | ".join(partes))

        self._atualizar_progresso(concluido)
        self._atualizar_rotulos_abas()
        # A tela do fluxo acompanha os mesmos números da barra de estado.
        if self._etapa_fluxo == "processando":
            self._atualizar_cartao_processando()
        elif self._etapa_fluxo == "pronto":
            self._atualizar_cartao_pronto()

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
            # Identificados pelo WIDGET, não por índice: a Fase 21a inseriu
            # a aba Início na frente, e um índice fixo passaria a rotular a
            # aba errada a cada nova aba acrescentada.
            self.abas.tab(self._aba_registros, text=f"Registros ({len(self._registros_exportacao)})")
            pendentes = len(self._indices_pendentes_revisao())
            self.abas.tab(self._aba_revisao, text=f"Revisão ({pendentes})" if pendentes else "Revisão")
            total_avisos = (
                len(self._erros_paginas) + len(self._avisos_contagem)
                + len(self._avisos_descarte) + len(self._data_manager.avisos)
            )
            self.abas.tab(self._aba_avisos, text=f"Avisos ({total_avisos})" if total_avisos else "Avisos")
        except Exception:
            logging.exception("Falha ao atualizar os rótulos das abas (apenas cosmético)")

    # ==================================================================
    # Registros -> tabela + lista de exportação
    # ==================================================================
    def _registro_erro_pagina(self, numero_pagina, mensagem):
        return pipeline.registro_erro_pagina(numero_pagina, mensagem)

    def _adicionar_registros(self, numero_pagina, registros):
        """
        Fase 24a: a classificação por registro (matrícula -> base -> `clas-
        sificar_registro` -> dict de exportação) morou aqui até esta fase;
        agora é `pipeline.montar_registro_exportacao`, chamada idêntica
        tanto daqui quanto do backend web -- só o que é ESTADO DE TELA
        (contadores, `_avisos_descarte`, a lista `_registros_exportacao`
        em si, redesenhar a tabela) continua sendo responsabilidade desta
        classe.
        """
        # Contexto do lote ANTES de classificar: as datas completas desta
        # página também valem como evidência para as linhas dela que vieram
        # sem ano. Só entram datas que se interpretam por completo (ver
        # ContextoLote.registrar_data) -- uma data recuperada por contexto
        # nunca realimenta o contexto.
        for registro in registros:
            campo_data = registro.campos.get("data")
            self._contexto_lote.registrar_data(campo_data.texto if campo_data else "")

        for registro in registros:
            registro_exportacao, aviso_sem_matricula = pipeline.montar_registro_exportacao(
                registro, numero_pagina, self._data_manager, self._contexto_lote,
            )
            if registro_exportacao["status"] == "CONFIRMADO":
                self._contador_confirmados += 1
            else:
                self._contador_revisao += 1

            # Aviso explícito de linha sem matrícula identificável. O
            # registro NÃO é descartado (vai para REVISAO com o que tem --
            # perder uma liberação real seria pior), mas o operador
            # precisa saber que ela existe e por quê: é a linha que ele
            # terá de conferir no papel.
            if aviso_sem_matricula:
                self._avisos_descarte.append({"pagina": numero_pagina, "mensagem": aviso_sem_matricula})

            self._registros_exportacao.append(registro_exportacao)

        self._sincronizar_tabela_principal()
        self._atualizar_botao_revisao()

    # ==================================================================
    # Tabela principal
    # ==================================================================
    @staticmethod
    def _rotulo_status(status: str, observacao: str = "") -> str:
        """Rótulo curto da coluna Status. A razão (observação) tem coluna
        própria desde a Fase 10 -- juntar as duas espremia o texto que o
        operador precisa ler.

        Sub-fase 21c: o texto/ícone vêm de `ui/estilos.STATUS_VOCABULARIO`
        -- vocabulário único ("✓ Confirmado" / "⚠ Precisa de revisão" /
        "✕ Erro no processamento"), para nunca reimplementar o mesmo
        status com palavras diferentes em telas diferentes."""
        return estilos.texto_status(status)

    @staticmethod
    def _tag_status(status: str) -> str:
        return estilos.tag_status(status)

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
        total = len(self._registros_exportacao)
        if hasattr(self, "lbl_contagem_tabela"):
            texto = f"{mostrados} de {total} registro(s)" if total else "nenhum registro ainda"
            self.lbl_contagem_tabela.config(text=texto)
        self._atualizar_estado_vazio_tabela(mostrados, total)
        self._atualizar_rotulos_abas()

    def _atualizar_estado_vazio_tabela(self, mostrados, total):
        """Troca a tabela pelo texto de estado vazio quando não há linha a
        mostrar -- distinguindo "ainda não processou nada" de "o filtro
        atual não deixa nada aparecer", que são problemas diferentes e têm
        saídas diferentes."""
        if not hasattr(self, "lbl_tabela_vazia"):
            return
        try:
            if mostrados:
                self.lbl_tabela_vazia.pack_forget()
                if not self._moldura_tabela.winfo_ismapped():
                    self._moldura_tabela.pack(side="top", fill="both", expand=True)
                return
            self._moldura_tabela.pack_forget()
            if total:
                texto = mensagens.VAZIO_TABELA_FILTRADA.format(filtro=self.filtro_var.get())
            else:
                texto = mensagens.VAZIO_TABELA
            self.lbl_tabela_vazia.config(text=texto)
            self.lbl_tabela_vazia.pack(side="top", fill="both", expand=True, pady=(60, 0))
        except Exception:
            logging.exception("Falha ao alternar o estado vazio da tabela (apenas cosmético)")

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
        # A reconstrução apaga todos os itens -- o iid em hover (se algum,
        # ver `_on_hover_generico`) deixou de existir junto.
        self.tabela_avisos._hover_item = None
        for aviso in self._data_manager.avisos:
            self.tabela_avisos.insert("", "end", values=("Base de dados", "—", aviso))
        for e in self._erros_paginas:
            self.tabela_avisos.insert("", "end", values=("Erro de página", e["pagina"], e["mensagem"]))
        for a in self._avisos_contagem:
            self.tabela_avisos.insert("", "end", values=("Contagem de posições", a["pagina"], a["mensagem"]))
        for a in self._avisos_descarte:
            self.tabela_avisos.insert("", "end", values=("Linha sem matrícula", a["pagina"], a["mensagem"]))
        # Estado vazio (Fase 21a): uma tabela de avisos em branco pode ser
        # lida como "ainda não verificou" quando na verdade quer dizer
        # "verificou e não há nada" -- que é a boa notícia.
        if not self.tabela_avisos.get_children():
            self.tabela_avisos.insert("", "end", values=("—", "—", mensagens.VAZIO_AVISOS))
        self._atualizar_rotulos_abas()

    # Mantidos: o fluxo por diálogo continua disponível (e é o que os
    # testes de regressão exercitam), agora além da aba consolidada.
    # Sub-fase 22d: `Messagebox` no lugar de `tkinter.messagebox` -- ver
    # nota em `_mostrar_falha`; mesma microcopy, mesma ordem de chamada
    # invertida (mensagem, título).
    def _mostrar_avisos_bases(self):
        if not self._data_manager.avisos:
            return
        msg = "\n\n".join(self._data_manager.avisos)
        msg += "\n\nColoque os arquivos em dados/ e reabra o programa."
        Messagebox.show_warning(msg, "Avisos sobre as bases de dados", parent=self)

    def _mostrar_erros_paginas(self):
        if not self._erros_paginas:
            return
        msg = "\n\n".join(f"Página {e['pagina']}: {e['mensagem']}" for e in self._erros_paginas)
        Messagebox.show_warning(msg, "Erros de página", parent=self)

    def _mostrar_avisos_contagem(self):
        if not self._avisos_contagem:
            return
        msg = "\n\n".join(f"Página {a['pagina']}: {a['mensagem']}" for a in self._avisos_contagem)
        Messagebox.show_warning(msg, "Avisos de contagem de posições", parent=self)

    def _mostrar_avisos_descarte(self):
        if not self._avisos_descarte:
            return
        msg = "\n\n".join(f"Página {a['pagina']}: {a['mensagem']}" for a in self._avisos_descarte)
        Messagebox.show_warning(msg, "Linhas sem matrícula identificável", parent=self)

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
        # Sub-fase 21b: o contador "N de M revisados" é da SESSÃO de
        # revisão em torno do lote atual -- limpo junto, senão a próxima
        # leva começaria contando como se já tivesse revisado algo.
        self._revisao_resolvidos_sessao = 0
        self._revisao_detalhes_expandido = False
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
        # Fase 21a: limpar devolve o fluxo ao começo -- inclusive a faixa de
        # "concluído" e uma seleção que tivesse ficado pendente, que senão
        # continuariam anunciando um lote que não existe mais.
        self._lote_concluido = False
        self._selecao_pendente = None
        self._instante_inicio_lote = None
        self._ir_para_etapa("pronto")
        self.lbl_status.config(
            text="Resultados limpos. Escolha as fotos das folhas ou o PDF do mês na aba Início."
        )

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
            Messagebox.show_warning("Ainda não há registros processados.", "Nada para salvar", parent=self)
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
            # A causa real e frequente aqui é a planilha estar aberta no
            # Excel -- e "Permission denied: [Errno 13]" não diz isso a
            # ninguém (ver ui/mensagens.py).
            logging.exception("Falha ao salvar a planilha")
            self._mostrar_falha("salvar", exc)
            return

        pendentes = len(self._indices_pendentes_revisao())
        aviso_pendentes = (
            f"\n\nAtenção: {pendentes} registro(s) ainda estão marcados para revisão "
            "e foram exportados assim, na aba “Revisão” da planilha."
            if pendentes else ""
        )
        Messagebox.show_info(
            f"{len(self._registros_exportacao)} registro(s) de "
            f"{mensagens.plural_folhas(self._paginas_processadas)} foram salvos em:\n{path}"
            f"{aviso_pendentes}",
            "Planilha gerada",
            parent=self,
        )
        self.lbl_status.config(text=f"Planilha gerada: {os.path.basename(path)}")
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
                Messagebox.show_info(
                    "Não há registros em revisão manual.\n\n"
                    f"Há {len(self._erros_paginas)} página(s) com ERRO de processamento — "
                    "veja a aba \"Avisos\" (essas páginas precisam ser "
                    "reprocessadas, não corrigidas campo a campo).",
                    "Revisão",
                    parent=self,
                )
            else:
                Messagebox.show_info("Não há registros pendentes de revisão.", "Revisão", parent=self)
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
        """Recarrega a lista de pendências, o formulário e a foto a partir
        do registro atual. Ponto único que sincroniza as três áreas da
        aba -- mesmo espírito de `_sincronizar_tabela_principal` (Fase 10):
        com mais de um lugar escrevendo nos mesmos widgets, as três áreas
        acabam divergindo entre si."""
        pendentes = self._indices_pendentes_revisao()
        self._atualizar_lista_revisao_pendencias(pendentes)
        self._atualizar_texto_progresso(pendentes)

        if not self._atualizar_estado_vazio_revisao(pendentes):
            self._atualizar_rotulos_abas()
            return

        habilitado = "normal" if pendentes else "disabled"
        for widget in list(self.revisao_widgets.values()) + [
            self.btn_revisao_anterior, self.btn_revisao_proximo, self.btn_revisao_confirmar
        ]:
            try:
                widget.config(state=habilitado)
            except Exception:
                pass

        # Fecha o painel de detalhes a cada registro novo -- ver o campo
        # `_revisao_detalhes_expandido` no __init__.
        self._revisao_detalhes_expandido = False

        _indice, registro = self._revisao_registro_atual()
        posicao = self._revisao_posicao + 1
        self.lbl_revisao_posicao.config(
            text=f"Pendente {posicao} de {len(pendentes)}  ·  página {registro['pagina_origem']}"
        )
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

    def _atualizar_estado_vazio_revisao(self, pendentes):
        """
        Troca o painel de três áreas pelo texto de estado vazio quando não
        há pendência nenhuma -- distinguindo "ainda não processei nada" de
        "processei e não sobrou pendência" (a boa notícia), mesmo padrão
        de `_atualizar_estado_vazio_tabela` (Fase 21a). Devolve True
        quando o painel normal deve continuar sendo preenchido.
        """
        try:
            if pendentes:
                self.lbl_revisao_vazio.pack_forget()
                if not self._moldura_revisao_painel.winfo_ismapped():
                    self._moldura_revisao_painel.pack(side="top", fill="both", expand=True)
                return True
            self._moldura_revisao_painel.pack_forget()
            texto = (
                mensagens.VAZIO_REVISAO_TUDO_CONFIRMADO if self._registros_exportacao
                else mensagens.VAZIO_REVISAO_SEM_PROCESSAMENTO
            )
            self.lbl_revisao_vazio.config(text=texto)
            self.lbl_revisao_vazio.pack(side="top", fill="both", expand=True, pady=(60, 0))
        except Exception:
            logging.exception("Falha ao alternar o estado vazio da revisão (apenas cosmético)")
        return False

    def _texto_progresso_revisao(self, pendentes):
        """
        'N de M revisados': N é quanto já foi CONFIRMADO nesta sessão de
        revisão (`_revisao_resolvidos_sessao`, só incrementado por
        `_revisao_confirmar`); M é `N + pendentes agora`, recalculado ao
        vivo -- não um total fixo -- para que processar folhas novas no
        meio de uma revisão aumente M sem exigir nenhum estado extra.
        Puramente informativo.
        """
        resolvidos = self._revisao_resolvidos_sessao
        total = resolvidos + len(pendentes)
        if total == 0:
            return ""
        return f"{resolvidos} de {total} revisados"

    def _atualizar_texto_progresso(self, pendentes):
        texto = self._texto_progresso_revisao(pendentes)
        sufixo = f"\n{len(pendentes)} pendente(s) agora" if pendentes else ""
        self.lbl_revisao_progresso.config(text=(texto + sufixo) if texto else "")

    def _texto_busca_revisao(self) -> str:
        """O texto de busca digitado, ou '' quando o campo só mostra o
        placeholder (nunca trata o placeholder como termo de busca)."""
        if not hasattr(self, "revisao_busca_var") or self._revisao_busca_placeholder_ativo:
            return ""
        return self.revisao_busca_var.get().strip()

    def _registro_passa_filtro_revisao(self, registro, campos_bloqueantes, termo_busca: str) -> bool:
        """
        Sub-fase 21d: filtro de TIPO (campo bloqueante) + busca textual --
        os dois só decidem o que APARECE nesta lista. Nunca tocam
        `_indices_pendentes_revisao()`, nunca mudam status, nunca alteram
        o que Anterior/Próximo percorrem (ver o comentário no ponto onde
        os controles são montados).
        """
        if hasattr(self, "revisao_filtro_tipo_var"):
            rotulo_filtro = self.revisao_filtro_tipo_var.get()
            if rotulo_filtro != FILTRO_REVISAO_TODAS:
                campo_filtro = ROTULOS_REVISAO_INVERTIDO.get(rotulo_filtro)
                if campo_filtro not in campos_bloqueantes:
                    return False

        if termo_busca:
            alvo = " ".join(str(registro.get(chave) or "") for chave in
                             ("matricula", "gestor", "motivo", "pagina_origem", "nome"))
            if termo_busca.lower() not in alvo.lower():
                return False

        return True

    def _atualizar_lista_revisao_pendencias(self, pendentes=None):
        """Reconstrói a lista de pendências (área 1) a partir de
        `_registros_exportacao` -- a mesma fonte de verdade da tabela
        principal. Cada linha mostra a página, a matrícula (quando lida) e
        o(s) campo(s) que bloqueiam, coloridos por tipo.

        Sub-fase 21d: o filtro de tipo e a busca textual (se ativos) só
        decidem quais dessas linhas são INSERIDAS na tabela -- o `iid` de
        cada linha continua sendo a posição REAL em `pendentes` (a lista
        completa, nunca a filtrada), então clicar numa linha visível ainda
        resolve certo em `_on_selecionar_pendencia_lista`, e
        Anterior/Próximo continuam percorrendo TODAS as pendências, não só
        as que passam no filtro -- combinar as duas coisas exigiria
        redefinir o que "próximo" significa, fora do que um filtro de
        apresentação pode fazer."""
        if pendentes is None:
            pendentes = self._indices_pendentes_revisao()
        tabela = self.tabela_revisao_lista
        tabela.delete(*tabela.get_children())
        # A reconstrução apaga todos os itens -- o iid em hover (se algum)
        # deixou de existir junto.
        self._hover_item_revisao = None
        termo_busca = self._texto_busca_revisao()
        mostradas = 0
        for posicao, indice in enumerate(pendentes):
            registro = self._registros_exportacao[indice]
            try:
                explicacao = explicacao_revisao.explicar(
                    registro.get("evidencias"), registro.get("observacao") or ""
                )
                campos = explicacao.campos_bloqueantes
            except Exception:
                campos = []
            if not self._registro_passa_filtro_revisao(registro, campos, termo_busca):
                continue
            if campos:
                pendencia = ", ".join(explicacao_revisao.ROTULOS.get(c, c) for c in campos)
                tag = campos[0]
            else:
                pendencia = "revisão"
                tag = "outro"
            matricula = registro.get("matricula") or "—"
            tabela.insert(
                "", "end", iid=str(posicao),
                values=(registro.get("pagina_origem"), matricula, pendencia),
                tags=(tag,),
            )
            mostradas += 1

        if hasattr(self, "lbl_revisao_lista_contagem"):
            if mostradas == len(pendentes):
                self.lbl_revisao_lista_contagem.config(text="")
            else:
                self.lbl_revisao_lista_contagem.config(
                    text=f"{mostradas} de {len(pendentes)} pendência(s) mostradas"
                )

        iid_atual = str(self._revisao_posicao)
        if tabela.exists(iid_atual):
            tabela.selection_set(iid_atual)
            tabela.see(iid_atual)

    # ------------------------------------------------------------------
    # Placeholder e atalhos do campo de busca (Sub-fase 21d)
    # ------------------------------------------------------------------
    def _ativar_placeholder_busca_revisao(self):
        """Escreve o texto de apoio em cinza -- nunca um termo de busca de
        verdade (ver `_texto_busca_revisao`)."""
        self._revisao_busca_placeholder_ativo = True
        self.revisao_busca_var.set(PLACEHOLDER_BUSCA_REVISAO)
        try:
            self.entrada_revisao_busca.config(bootstyle="secondary")
        except Exception:
            pass

    def _on_foco_busca_revisao(self, _evento=None):
        if self._revisao_busca_placeholder_ativo:
            self._revisao_busca_placeholder_ativo = False
            self.revisao_busca_var.set("")
            try:
                self.entrada_revisao_busca.config(bootstyle="default")
            except Exception:
                pass

    def _on_saida_busca_revisao(self, _evento=None):
        if not self.revisao_busca_var.get().strip():
            self._ativar_placeholder_busca_revisao()

    def _on_escape_busca_revisao(self, _evento=None):
        """Esc limpa a busca -- convenção segura: só descarta texto de
        filtro, nunca confirma nem altera nenhum registro. Tira o foco do
        campo (dispara `_on_saida_busca_revisao`, que reescreve o
        placeholder) em vez de reescrevê-lo aqui também."""
        self.revisao_busca_var.set("")
        self.tabela_revisao_lista.focus_set()

    def _on_selecionar_pendencia_lista(self, _evento=None):
        """Clicar numa linha da lista de pendências navega direto para
        ela -- mesma ação de `_revisao_ir_para`, só que por escolha do
        operador em vez de sequência."""
        selecao = self.tabela_revisao_lista.selection()
        if not selecao:
            return
        try:
            posicao = int(selecao[0])
        except (TypeError, ValueError):
            return
        if posicao != self._revisao_posicao:
            self._revisao_ir_para(posicao)

    # Sub-fase 22c: hover sutil na lista de pendências -- puramente visual,
    # não participa da seleção real nem de nenhuma decisão. `_hover_item_
    # revisao` só existe para saber qual linha "desligar" quando o cursor
    # sai dela ou entra em outra.
    def _on_hover_lista_revisao(self, evento):
        try:
            item = self.tabela_revisao_lista.identify_row(evento.y)
        except Exception:
            return
        if item == self._hover_item_revisao:
            return
        self._limpar_hover_lista_revisao()
        if item:
            tags = list(self.tabela_revisao_lista.item(item, "tags"))
            if "hover" not in tags:
                tags.append("hover")
                self.tabela_revisao_lista.item(item, tags=tags)
            self._hover_item_revisao = item

    def _limpar_hover_lista_revisao(self, _evento=None):
        item = self._hover_item_revisao
        try:
            if item and self.tabela_revisao_lista.exists(item):
                tags = [t for t in self.tabela_revisao_lista.item(item, "tags") if t != "hover"]
                self.tabela_revisao_lista.item(item, tags=tags)
        except Exception:
            pass
        self._hover_item_revisao = None

    # Sub-fase 22d: versão GENÉRICA do mesmo hover, para tabelas que não
    # têm um atributo de instância dedicado como `_hover_item_revisao`
    # (hoje: a aba Avisos). Guarda o item em hover como atributo dinâmico
    # no próprio widget (`tabela._hover_item`) -- widgets `ttk` são
    # objetos Python comuns, aceitam atributo novo sem problema -- em vez
    # de um dicionário à parte em `self`, para cada Treeview cuidar do
    # próprio estado sem colidir com o de outra. Não reaproveitado pela
    # lista de pendências de propósito: `_on_hover_lista_revisao` já
    # existe, é testada por nome próprio, e trocar sua assinatura agora
    # seria mexer em algo que já funciona sem ganho nenhum.
    def _on_hover_generico(self, tabela):
        def _handler(evento):
            try:
                item = tabela.identify_row(evento.y)
            except Exception:
                return
            if item == getattr(tabela, "_hover_item", None):
                return
            self._limpar_hover_generico(tabela)()
            if item:
                tags = list(tabela.item(item, "tags"))
                if "hover" not in tags:
                    tags.append("hover")
                    tabela.item(item, tags=tags)
                tabela._hover_item = item
        return _handler

    def _limpar_hover_generico(self, tabela):
        def _handler(_evento=None):
            item = getattr(tabela, "_hover_item", None)
            try:
                if item and tabela.exists(item):
                    tags = [t for t in tabela.item(item, "tags") if t != "hover"]
                    tabela.item(item, tags=tags)
            except Exception:
                pass
            tabela._hover_item = None
        return _handler

    # Sub-fase 21d: atalhos ← → na lista de pendências. Métodos nomeados
    # (não lambdas) só para a ligação ficar identificável ao inspecionar o
    # binding do Tk -- o comportamento é exatamente `_revisao_navegar`, o
    # mesmo que os botões "Anterior"/"Próximo" já chamavam.
    def _on_seta_esquerda_revisao(self, _evento=None):
        self._revisao_navegar(-1)

    def _on_seta_direita_revisao(self, _evento=None):
        self._revisao_navegar(1)

    def _alternar_detalhes_revisao(self):
        """'Ver detalhes' -- só mostra/esconde o painel com a cadeia
        completa de evidência (Fase 17/18); não recalcula nada."""
        self._revisao_detalhes_expandido = not self._revisao_detalhes_expandido
        self._atualizar_visibilidade_detalhes_revisao()

    def _atualizar_visibilidade_detalhes_revisao(self):
        if self._revisao_detalhes_expandido:
            self.btn_revisao_detalhes.config(text=f"Ocultar detalhes {estilos.ICONE_RECOLHER}")
            self.moldura_revisao_explicacao.pack(
                side="top", fill="x", pady=(0, 10), before=self.moldura_revisao_campos
            )
        else:
            self.btn_revisao_detalhes.config(text=f"Ver detalhes {estilos.ICONE_EXPANDIR}")
            self.moldura_revisao_explicacao.pack_forget()

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
        """Escreve o resumo do bloqueio, o painel de detalhes (Fase 18), o
        destaque do campo bloqueante e as sugestões de contexto na tela.
        Só desenha -- não toca em `revisao_vars` nem em nada do registro,
        e não decide nada: os campos que bloqueiam vêm inteiramente de
        `explicacao_revisao.explicar`, que só lê o dossiê já gravado."""
        if registro is None:
            self.lbl_revisao_resumo.config(text="")
            self.lbl_revisao_explicacao.config(text="")
            self.btn_revisao_detalhes.pack_forget()
            self.moldura_revisao_explicacao.pack_forget()
            self._destacar_campos_revisao([], [])
            return

        try:
            explicacao, sinais = self._explicacao_revisao_atual()
        except Exception:
            # Explicar é conveniência: se falhar, a revisão continua
            # funcionando exatamente como antes da Fase 18.
            logging.exception("Falha ao montar a explicação da revisão")
            explicacao, sinais = explicacao_revisao.ExplicacaoRevisao(), []

        # Resumo curto, SEMPRE visível (pedido do escopo: o operador nunca
        # deve precisar expandir nada só para saber o que está em jogo).
        # Sem dossiê (sessão anterior à Fase 17), cai na observação bruta
        # que a validação já produzia -- comportamento antigo preservado.
        resumo = explicacao.titulo if not explicacao.vazia else (registro.get("observacao") or "")
        self.lbl_revisao_resumo.config(text=resumo)

        # O corpo detalhado (a cadeia OCR -> normalização -> base -> regra)
        # só aparece atrás do botão "Ver detalhes". Os sinais de contexto
        # (Fase 16/18) não entram aqui -- vão colados ao campo a que se
        # referem, via `_destacar_campos_revisao` logo abaixo.
        self.lbl_revisao_explicacao.config(text="\n".join(explicacao.detalhes))

        if explicacao.detalhes:
            self.btn_revisao_detalhes.pack(side="top", anchor="w", pady=(0, 4))
            self._atualizar_visibilidade_detalhes_revisao()
        else:
            self.btn_revisao_detalhes.pack_forget()
            self.moldura_revisao_explicacao.pack_forget()

        self._destacar_campos_revisao(explicacao.campos_bloqueantes, sinais)

    def _destacar_campos_revisao(self, campos_bloqueantes, sinais):
        """
        Dá destaque visual ao(s) campo(s) que bloqueiam a linha e mostra,
        colada ao campo, a sugestão de contexto que o sistema já tinha
        produzido -- nunca um candidato novo calculado aqui, nunca
        pré-selecionado no campo (`revisao_vars` não é tocado por este
        método).

        Sub-fase 22c: refinado para não "pintar a tela inteira de
        vermelho" (pedido do escopo) -- antes rótulo E caixa ficavam
        vermelhos ao mesmo tempo. Agora só a CAIXA (`revisao_widgets`,
        bootstyle "danger" -- convenção padrão de campo inválido em
        formulário, e o que o teste estrutural da 21b trava) continua
        vermelha; o RÓTULO ganha o ícone de alerta (`ICONE_REVISAO`) e
        fica em negrito, na cor normal de texto -- ainda inconfundível
        (ícone + negrito + a caixa vermelha ao lado), com uma única cor
        de alerta na linha em vez de duas.
        """
        dicas_por_campo = {}
        for sinal in sinais:
            texto = f"{estilos.ICONE_INFO} {sinal.motivo}"
            if sinal.valor_observado:
                texto += f"\n    {sinal.valor_observado}"
            dicas_por_campo.setdefault(sinal.campo, []).append(texto)

        for chave in self.revisao_rotulos:
            bloqueado = chave in campos_bloqueantes
            texto_base = self._revisao_rotulos_texto.get(chave, chave)
            try:
                rotulo_widget = self.revisao_rotulos[chave]
                if bloqueado:
                    rotulo_widget.config(
                        text=f"{estilos.ICONE_REVISAO} {texto_base}", font=estilos.FONTE_ROTULO_MEDIO,
                    )
                else:
                    rotulo_widget.config(text=texto_base, font=("", 9, "normal"))
                self.revisao_widgets[chave].config(bootstyle=("danger" if bloqueado else "default"))
            except Exception:
                pass
            dica_widget = self.revisao_dicas[chave]
            texto_dica = "\n".join(dicas_por_campo.get(chave, []))
            if texto_dica:
                dica_widget.config(text=texto_dica)
                dica_widget.grid()
            else:
                dica_widget.config(text="")
                dica_widget.grid_remove()

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

        Fase 24a: a decisão em si (reconstruir o Registro sintético, rodar
        a MESMA `classificar_registro` do fluxo automático, decidir se sai
        de REVISAO) deixou de morar aqui -- é `validacao.confirmacao.
        confirmar_revisao_manual` agora, chamada IDÊNTICA tanto pelo
        Tkinter quanto pelo backend web. O que sobra aqui é só Tkinter
        puro: ler os campos digitados, chamar a função, e atualizar
        widget/contador/navegação a partir do resultado.
        """
        indice, registro = self._revisao_registro_atual()
        if registro is None:
            return

        resultado = confirmar_revisao_manual(
            registro,
            data=self.revisao_vars["data"].get(),
            hora=self.revisao_vars["hora"].get(),
            matricula=self.revisao_vars["matricula"].get(),
            gestor=self.revisao_vars["gestor"].get(),
            motivo=self.revisao_vars["motivo"].get(),
            data_manager=self._data_manager,
            contexto_lote=self._contexto_lote,
        )

        if resultado.confirmou_agora:
            self._contador_revisao -= 1
            self._contador_confirmados += 1
            # Sub-fase 21b: numerador do contador "N de M revisados" (área
            # de pendências). Só cresce aqui -- é a mesma condição que já
            # decide se a linha realmente saiu de REVISAO.
            self._revisao_resolvidos_sessao += 1

        self._sincronizar_tabela_principal()
        self._atualizar_botao_revisao()
        self._atualizar_status(concluido=not self._processando)

        if registro["status"] == "CONFIRMADO":
            # A linha saiu da lista de pendentes: a posição atual passa a
            # apontar para a PRÓXIMA pendente sozinha (a lista encolheu),
            # que é o comportamento desejado ao revisar em sequência.
            pendentes = self._indices_pendentes_revisao()
            if pendentes:
                self._revisao_posicao = min(self._revisao_posicao, len(pendentes) - 1)
            self._atualizar_painel_revisao()
            if not pendentes:
                # Sub-fase 22d: `Messagebox` no lugar de `tkinter.
                # messagebox` (ver nota em `_mostrar_falha`) -- única linha
                # tocada dentro de `_revisao_confirmar` por esta sub-fase,
                # puramente cosmética, mesmo texto.
                Messagebox.show_info("Todos os registros pendentes foram revisados.", "Revisão", parent=self)
        else:
            # Ainda não pôde ser confirmado -- permanece na lista, com a
            # observação atualizada, em vez de desaparecer como se
            # tivesse sido resolvido.
            self._atualizar_painel_revisao()
            # Sub-fase 22c: o estilo (cor de erro + fundo compatível com o
            # canvas) já vem fixado na construção do label -- ver
            # `_montar_aba_revisao`. Nenhuma mudança de comportamento: o
            # texto é o mesmo que já era escrito aqui.
            self.lbl_revisao_resultado.config(
                text=f"Ainda não é possível confirmar: {resultado.observacao_classificacao}",
            )

    # Nome anterior mantido: o fluxo de correção manual é o mesmo.
    _confirmar = _revisao_confirmar
