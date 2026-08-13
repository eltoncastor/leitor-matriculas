"""
ui/estilos.py

Sub-fase 21c: design tokens da interface -- tipografia, espaçamento e o
VOCABULÁRIO DE STATUS (ícone + rótulo + cor semântica de CONFIRMADO/
REVISAO/ERRO), num só lugar em vez de espalhados como tuplas/strings
soltas em `ui/app.py`.

POR QUE UM MÓDULO SEPARADO, e não mais constantes soltas em `ui/app.py`:
o vocabulário de status já era usado em mais de um lugar antes desta
sub-fase (a tabela principal tinha `_rotulo_status`/`_tag_status`
próprios) e a auditoria da 21c achou o mesmo texto/ícone reimplementado
com pequenas variações ("✓ CONFIRMADO" vs. o que a Fase 12/18 mostravam
em prosa). Um módulo dedicado, puro (não importa Tkinter), garante que
"o que é um REVISAO" -- ícone, palavra, cor -- só é decidido aqui, e é
testável sem abrir janela nenhuma, mesma razão de `ui/mensagens.py` e
`validacao/explicacao_revisao.py` (que morava em `ui/` até a Fase 24c).

NÃO é um "componente" nem um motor de temas: não decide layout, não
substitui `ttkbootstrap`, só nomeia os valores que `ui/app.py` já usava
(tamanhos de fonte, espaçamentos, cores) para que o mesmo número/cor não
precise ser copiado de cabeça em cada tela nova.

---------------------------------------------------------------------
Sub-fase 22a (Fase 22 -- redesign visual): FUNDAÇÃO. Esta sub-fase
ESTENDE este módulo com paleta de cores, o resto da hierarquia
tipográfica, raio de borda e vocabulário de ícones -- os tokens que as
sub-fases 22b/22c/22d vão aplicar nas telas. NENHUM token novo é
aplicado em `ui/app.py` nesta sub-fase (ver `saida/avaliacao_fase22_
redesign.md`, seção "Sub-fase 22a", para a auditoria completa que
motivou os valores escolhidos); os tokens existem e são testados, mas a
aparência do programa continua idêntica ao fim da Fase 21d.

Os valores de cor "fortes" (COR_ACCENT/COR_SUCESSO/COR_ATENCAO/
COR_ERRO) NÃO são inventados -- são os mesmos que `ttkbootstrap`
resolve para o tema de base já em uso (`Style().colors.primary` etc.),
só nomeados aqui para o resto da paleta (fundo/superfície/texto, que o
tema não define) poder ser pensado ao lado deles sem duas fontes de
verdade divergentes.

---------------------------------------------------------------------
Sub-fase 22e: TEMA VISUAL DE BASE e alternância clara/escura.

Correção de rumo recebida do usuário ao final da 22d: as sub-fases
22a-22d nomearam as cores que o tema `cosmo` (`ttkbootstrap`) já
produzia, mas o TEMA em si nunca foi reavaliado -- boa parte da mudança
visual das sub-fases anteriores era, na prática, o mesmo tema com
padding/tipografia ajustados. Esta sub-fase troca o tema de base
(`TEMA_CLARO`/`TEMA_ESCURO`, usados por `ui/app.py` -- ver `TEMA` lá) e
faz os tokens de cor deste módulo PARARAM DE SER CONSTANTES FIXAS: viram
valores que `aplicar_paleta()` atualiza IN-PLACE quando o modo muda. Os
outros módulos continuam acessando `estilos.COR_FUNDO` etc. exatamente
como antes (nenhuma chamada em `ui/app.py` precisou mudar de forma só
por causa disto) -- o que muda é que agora esses nomes podem valer
coisas diferentes ao longo da execução, não só na importação.

ESCOLHA DOS TEMAS (medida, não por preferência -- ver avaliação
completa em `saida/avaliacao_fase22_redesign.md`, seção 22e):
`flatly` (claro) e `darkly` (escuro) são um PAR do mesmo desenhista
(Bootswatch) -- `warning`/`danger` saem no MESMO hexadecimal nos dois
temas, e `success` é quase idêntico (`#18bc9c` vs. `#00bc8c`). Isso
satisfaz diretamente o critério pedido ("as cores semânticas continuam
claramente diferenciáveis nos dois") sem precisar escolher cores à
parte para cada modo -- são a MESMA cor. `primary` (`#2c3e50`, um azul-
ardósia escuro) foge do azul genérico de "SaaS dashboard" que o
preâmbulo original da Fase 22 pediu para evitar.

O que É derivado do tema em tempo real (`aplicar_paleta(escura,
cores_tema)`, chamada com `Style().colors` já carregado): `COR_ACCENT`/
`COR_SUCESSO`/`COR_ATENCAO`/`COR_ERRO` -- sempre as cores reais do tema
ativo, nunca hexadecimais soltos. O que é uma escolha DESTE módulo (as
duas paletas `_PALETA["clara"]`/`_PALETA["escura"]`, abaixo): fundo,
superfície, bordas, texto e os tons de status/tipo-de-pendência da
tabela -- porque nem `flatly` nem `darkly` definem um "fundo de tela"
diferente de um "fundo de cartão" (mesmo problema que a 22a achou no
`cosmo`), e os tons PASTEL de status (`STATUS_VOCABULARIO[...][
"cor_fundo_tabela"]`) precisam ser tons ESCUROS com a MESMA tinta no
modo escuro -- um verde-pastel claro por trás de texto branco seria
ilegível.
"""

# ---------------------------------------------------------------------
# Tipografia -- a escala que já existia espalhada em `ui/app.py` (tuplas
# `font=("", N, "bold")` repetidas), agora nomeada por PAPEL do texto, não
# por tamanho. O corpo de texto (rótulos comuns, valores de campo) usa a
# fonte padrão do tema ttkbootstrap e não precisa de token -- só o que se
# destaca ganha um.
# ---------------------------------------------------------------------
FONTE_TITULO_PAGINA = ("", 19, "bold")     # título de uma aba inteira (ex.: "Leitor de Matrículas" na Início)
FONTE_TITULO_CARTAO = ("", 15, "bold")     # título de um cartão dentro de uma aba
FONTE_TITULO_SECAO = ("", 13, "bold")      # título de uma subseção dentro de um cartão
FONTE_DESTAQUE_NUMERO = ("", 24, "bold")   # números grandes (contagens do resultado)
FONTE_TITULO_CABECALHO = ("", 12, "bold")  # título compacto na barra superior (persistente em toda tela)
FONTE_ROTULO_FORTE = ("", 11, "bold")      # cabeçalho compacto de contexto (ex.: posição atual na revisão)
FONTE_ROTULO_MEDIO = ("", 10, "bold")      # destaque de uma linha (ex.: resumo do bloqueio na revisão)

# Sub-fase 22a: o resto da hierarquia, que a 21c tinha deixado implícita
# ("a fonte padrão do tema", sem nome próprio). A auditoria da 22a achou
# essas quatro funções de texto já em uso -- subtítulo descritivo abaixo
# de um H1, corpo, texto secundário (hoje só uma cor via
# `bootstyle="secondary"`, nunca um tamanho próprio) e legenda de apoio
# de campo -- mas nenhuma tinha um nome para outra tela reutilizar sem
# copiar o tamanho de cabeça. Não existe "título de aplicação" à parte:
# `FONTE_TITULO_PAGINA` já cumpre esse papel hoje (é o que renderiza
# "Leitor de Matrículas" como H1 da Início) e `FONTE_TITULO_CABECALHO` é
# a versão compacta e persistente do mesmo nome na barra superior --
# duplicar um terceiro tamanho não resolvido geraria um token morto.
#
# `FONTE_CORPO` e `FONTE_TEXTO_SECUNDARIO` têm o MESMO tamanho (9, igual
# à fonte padrão do tema `cosmo`, Segoe UI 9 -- verificado consultando
# `tkinter.font.nametofont("TkDefaultFont")` com o tema carregado): a
# distinção entre os dois nunca foi de tamanho, é de COR
# (`COR_TEXTO_SECUNDARIO`, definida abaixo). Os dois tokens existem
# separados mesmo assim para que o nome no código diga a intenção
# ("isto é corpo" vs. "isto é secundário") em vez de repetir o mesmo
# `font=("", 9)` sem contexto.
FONTE_SUBTITULO = ("", 11, "normal")       # linha descritiva abaixo de um título de página/cartão
FONTE_CORPO = ("", 9, "normal")            # texto corrido padrão -- mesmo tamanho da fonte base do tema
FONTE_TEXTO_SECUNDARIO = ("", 9, "normal")  # mesmo tamanho do corpo; usar com COR_TEXTO_SECUNDARIO
FONTE_LEGENDA = ("", 8, "normal")          # texto de apoio pequeno (ex.: a explicação de formato sob um campo)

# ---------------------------------------------------------------------
# Espaçamento -- escala de 4 em 4px. Usada nos paddings/pady/padx que
# marcam limite de CARTÃO/SEÇÃO (não em todo micro-ajuste interno de
# grade, que continua sendo decidido widget a widget).
# ---------------------------------------------------------------------
ESPACO_XS = 4
ESPACO_SM = 8
ESPACO_MD = 12
ESPACO_LG = 16
ESPACO_XL = 24

# ---------------------------------------------------------------------
# Paleta de cores (Sub-fase 22a; dinâmica desde a 22e -- ver docstring).
#
# O QUE A AUDITORIA ACHOU (ver relatório completo em
# `saida/avaliacao_fase22_redesign.md`): o tema de base do ttkbootstrap
# nunca definiu fundo de tela e fundo de cartão como coisas diferentes
# -- as duas são a mesma cor. É por isso que cada agrupamento da
# Início/Revisão só se separa do resto pela BORDA do `ttk.LabelFrame`
# (um contorno cinza fino com o rótulo cavalgando a linha) -- o efeito
# "caixa de formulário Win32" que o preâmbulo pede para evitar.
# `COR_FUNDO` (tela) e `COR_SUPERFICIE` (cartão) existem para resolver
# isso por CONTRASTE DE FUNDO em vez de mais linha.
TEMA_CLARO = "flatly"
TEMA_ESCURO = "darkly"

# Duas paletas COMPLETAS -- fundo, bordas, texto e os tons de tabela que
# nem `flatly` nem `darkly` definem sozinhos. `COR_ACCENT`/`COR_SUCESSO`/
# `COR_ATENCAO`/`COR_ERRO` NÃO estão aqui: são lidas do tema ativo em
# tempo real por `aplicar_paleta()`, nunca hexadecimais fixos.
_PALETA = {
    "clara": {
        "COR_FUNDO": "#ECF0F1",             # = Style().colors.light do tema flatly
        "COR_SUPERFICIE": "#FFFFFF",        # = Style().colors.bg
        "COR_SUPERFICIE_ELEVADA": "#FFFFFF",
        "COR_BORDA": "#CED4DA",             # = Style().colors.border
        "COR_BORDA_FORTE": "#ADB5BD",
        "COR_TEXTO_PRIMARIO": "#212529",    # = Style().colors.fg
        "COR_TEXTO_SECUNDARIO": "#6C757D",
        "COR_TEXTO_DESABILITADO": "#ADB5BD",
        "COR_SELECAO_LISTA": "#E9ECEF",
        "STATUS_FUNDO_TABELA": {"CONFIRMADO": "#EAF6EC", "REVISAO": "#FDF4E3", "ERRO": "#FBE9E7"},
        "CORES_TIPO_PENDENCIA": {
            "data": "#5C6BC0", "hora": "#00897B", "matricula": "#8E24AA",
            "motivo": "#EF6C00", "gestor": "#C2185B",
        },
        "COR_TIPO_PENDENCIA_PADRAO": "#495057",
    },
    "escura": {
        # `COR_SUPERFICIE` = Style().colors.inputbg do tema darkly (a cor
        # que o próprio tema já usa para "superfície elevada" -- campo de
        # entrada -- reaproveitada para cartão, em vez de inventada).
        "COR_FUNDO": "#1B1B1B",
        "COR_SUPERFICIE": "#2A2A2A",
        "COR_SUPERFICIE_ELEVADA": "#333333",
        "COR_BORDA": "#3F3F3F",
        "COR_BORDA_FORTE": "#5A5A5A",
        "COR_TEXTO_PRIMARIO": "#F5F5F5",
        "COR_TEXTO_SECUNDARIO": "#ADB5BD",  # = Style().colors.light do tema darkly (papel de "texto suave" no escuro)
        "COR_TEXTO_DESABILITADO": "#6C757D",
        "COR_SELECAO_LISTA": "#33465A",
        # Tons ESCUROS com a mesma tinta -- um pastel claro (modo claro)
        # por trás de texto BRANCO (modo escuro) seria ilegível.
        "STATUS_FUNDO_TABELA": {"CONFIRMADO": "#1E3B2A", "REVISAO": "#3D3319", "ERRO": "#3D1F1D"},
        "CORES_TIPO_PENDENCIA": {
            "data": "#8C9EFF", "hora": "#4DD0C4", "matricula": "#CE93D8",
            "motivo": "#FFB74D", "gestor": "#F06292",
        },
        "COR_TIPO_PENDENCIA_PADRAO": "#ADB5BD",
    },
}

# Sub-fase 21b, movidos para cá na 22e (precisavam existir num lugar que
# `aplicar_paleta()` pudesse atualizar por igual): cor de TEXTO por tipo
# de campo bloqueante na Revisão. Mutados IN-PLACE por `aplicar_paleta`
# (nunca reatribuídos) -- `ui/app.py` importa o DICT (`from .estilos
# import CORES_TIPO_PENDENCIA`) e continua vendo os valores novos porque
# é o MESMO objeto, só com conteúdo trocado.
CORES_TIPO_PENDENCIA = dict(_PALETA["clara"]["CORES_TIPO_PENDENCIA"])
COR_TIPO_PENDENCIA_PADRAO = _PALETA["clara"]["COR_TIPO_PENDENCIA_PADRAO"]

COR_FUNDO = _PALETA["clara"]["COR_FUNDO"]                        # tela/canvas por trás dos cartões
COR_SUPERFICIE = _PALETA["clara"]["COR_SUPERFICIE"]               # cartão/painel padrão sobre o fundo
# Mesma cor que COR_SUPERFICIE no modo claro (mas NÃO no escuro, desde a
# 22e -- ver `_PALETA["escura"]`): o Tk/ttk não desenha sombra, então uma
# "superfície elevada" (um cartão sobre outro cartão -- ex.: um menu
# suspenso, um popover) não tinha antes recurso de profundidade além de
# borda mais forte (COR_BORDA_FORTE). No modo escuro já dá pra usar um
# tom mais claro que o cartão comum -- convenção usual de UI escura.
COR_SUPERFICIE_ELEVADA = _PALETA["clara"]["COR_SUPERFICIE_ELEVADA"]
COR_BORDA = _PALETA["clara"]["COR_BORDA"]                         # borda discreta -- contorno de campo, separador fino
COR_BORDA_FORTE = _PALETA["clara"]["COR_BORDA_FORTE"]             # borda de elemento em foco, selecionado ou "elevado"

COR_TEXTO_PRIMARIO = _PALETA["clara"]["COR_TEXTO_PRIMARIO"]        # texto de leitura principal
COR_TEXTO_SECUNDARIO = _PALETA["clara"]["COR_TEXTO_SECUNDARIO"]    # rótulos de apoio, legendas, texto não-primário
COR_TEXTO_DESABILITADO = _PALETA["clara"]["COR_TEXTO_DESABILITADO"]  # texto/ícone de elemento inativo

# Valores iniciais -- os mesmos que `Style().colors` resolve para
# `flatly` (o tema padrão, `TEMA_CLARO`). `App.__init__` chama
# `aplicar_paleta(...)` com o `Style()` já carregado logo na montagem
# do layout, então na prática estes literais nunca ficam "errados" por
# muito tempo -- existem para o módulo ter um valor válido mesmo se
# importado antes de qualquer `App` existir (ex.: os testes de
# `teste_estilos.py`, que não abrem janela).
COR_ACCENT = "#2C3E50"    # = Style().colors.primary do tema flatly
COR_SUCESSO = "#18BC9C"   # = Style().colors.success
COR_ATENCAO = "#F39C12"   # = Style().colors.warning
COR_ERRO = "#E74C3C"      # = Style().colors.danger

# Sub-fase 22c: tom PASTEL derivado de `COR_ACCENT`, mesma técnica já
# usada em `STATUS_VOCABULARIO["..."]["cor_fundo_tabela"]` (tons claros
# derivados das cores fortes, para preencher uma ÁREA sem competir com o
# texto em cima dela) -- usado só para a linha SELECIONADA de uma lista
# de navegação (hoje: a lista de pendências da Revisão), nunca para
# marcar dado nem status.
COR_SELECAO_LISTA = _PALETA["clara"]["COR_SELECAO_LISTA"]

_modo_atual = "clara"


def aplicar_paleta(escura: bool, cores_tema=None) -> None:
    """
    Sub-fase 22e: atualiza os tokens de cor deste módulo IN-PLACE para
    refletir o modo pedido -- chamada na montagem inicial da janela e de
    novo a cada alternância clara/escura (`ui/app.py`).

    `cores_tema` é o `Style().colors` do `ttkbootstrap` já carregado
    (com o tema certo -- `TEMA_CLARO`/`TEMA_ESCURO` -- ativo via
    `Style().theme_use(...)`); é dali que `COR_ACCENT`/`COR_SUCESSO`/
    `COR_ATENCAO`/`COR_ERRO` vêm, nunca de um hexadecimal solto aqui.
    Opcional (`None`) só para permitir chamar esta função em teste, sem
    `ttkbootstrap` carregado -- nesse caso as quatro cores fortes não
    mudam.
    """
    global _modo_atual
    global COR_FUNDO, COR_SUPERFICIE, COR_SUPERFICIE_ELEVADA, COR_BORDA, COR_BORDA_FORTE
    global COR_TEXTO_PRIMARIO, COR_TEXTO_SECUNDARIO, COR_TEXTO_DESABILITADO, COR_SELECAO_LISTA
    global COR_ACCENT, COR_SUCESSO, COR_ATENCAO, COR_ERRO, COR_TIPO_PENDENCIA_PADRAO

    _modo_atual = "escura" if escura else "clara"
    p = _PALETA[_modo_atual]

    COR_FUNDO = p["COR_FUNDO"]
    COR_SUPERFICIE = p["COR_SUPERFICIE"]
    COR_SUPERFICIE_ELEVADA = p["COR_SUPERFICIE_ELEVADA"]
    COR_BORDA = p["COR_BORDA"]
    COR_BORDA_FORTE = p["COR_BORDA_FORTE"]
    COR_TEXTO_PRIMARIO = p["COR_TEXTO_PRIMARIO"]
    COR_TEXTO_SECUNDARIO = p["COR_TEXTO_SECUNDARIO"]
    COR_TEXTO_DESABILITADO = p["COR_TEXTO_DESABILITADO"]
    COR_SELECAO_LISTA = p["COR_SELECAO_LISTA"]
    COR_TIPO_PENDENCIA_PADRAO = p["COR_TIPO_PENDENCIA_PADRAO"]

    if cores_tema is not None:
        COR_ACCENT = cores_tema.primary
        COR_SUCESSO = cores_tema.success
        COR_ATENCAO = cores_tema.warning
        COR_ERRO = cores_tema.danger

    # Mutação IN-PLACE (nunca reatribuição) -- é o que faz `ui/app.py`
    # ver os valores novos sem precisar reimportar nada.
    for status, cor in p["STATUS_FUNDO_TABELA"].items():
        STATUS_VOCABULARIO[status]["cor_fundo_tabela"] = cor
    CORES_TIPO_PENDENCIA.clear()
    CORES_TIPO_PENDENCIA.update(p["CORES_TIPO_PENDENCIA"])


def modo_escuro_ativo() -> bool:
    return _modo_atual == "escura"

# ---------------------------------------------------------------------
# Bordas e raio (Sub-fase 22a) -- só o TOKEN é definido aqui; nenhuma
# tela usa `RAIO_PADRAO` ainda.
#
# POR QUE NÃO APLICADO: `ttk.Frame`/`ttk.LabelFrame`/`ttk.Entry` no Tk
# não têm uma propriedade de raio de borda -- não existe "border-radius"
# no `ttk.Style`. As formas de conseguir cantos arredondados de verdade
# (desenhar o retângulo num `tk.Canvas` atrás do conteúdo, ou compor uma
# imagem PNG pré-arredondada como plano de fundo do widget) são mudanças
# estruturais, não um valor de configuração -- avaliar isso é trabalho
# de 22b/22c, não desta sub-fase (ver preâmbulo: "não aplicar os tokens
# novos nas telas ainda").
#
# CRITÉRIO -- borda vs. espaço/contraste para agrupar visualmente (regra
# escrita, não um número): usar COR_BORDA num contorno completo só
# quando o elemento precisa de uma aresta dura contra um fundo que pode
# variar por baixo dele (campo de entrada, moldura de uma foto, o
# destaque vermelho de um campo bloqueante). Para agrupar conteúdo
# dentro de uma tela (um cartão, uma seção), preferir CONTRASTE DE FUNDO
# (COR_SUPERFICIE sobre COR_FUNDO) e ESPAÇO (ESPACO_LG/ESPACO_XL) em vez
# de um `ttk.LabelFrame` com borda no perímetro inteiro -- é exatamente
# essa troca que resolve o efeito "caixa de formulário" que a auditoria
# desta sub-fase documentou (ver relatório).
RAIO_PADRAO = 8   # px -- valor de referência para quando houver um jeito de aplicá-lo (ver nota acima)

# ---------------------------------------------------------------------
# Ícones (Sub-fase 22a) -- auditoria dos símbolos já em uso em
# `ui/app.py`, `ui/mensagens.py` e `validacao/explicacao_revisao.py`
# (que morava em `ui/` até a Fase 24c), reunidos aqui como vocabulário nomeado. Nenhum ícone NOVO foi introduzido: os
# nomes abaixo só apontam para os mesmos caracteres Unicode que o
# programa já desenha, para telas futuras reusarem o NOME em vez de
# copiar o glifo.
#
# DEPENDÊNCIA EXTERNA -- investigada e DESCARTADA: os glifos Unicode já
# em uso (símbolos monocromáticos: setas, ✓/⚠/✕, ▸/▾, ⓘ) cobrem a
# navegação, expansão/recolhimento, status e informação que a interface
# usa hoje, e renderizam de forma consistente (mesma família de traço,
# sem cor própria) com a fonte do sistema (Segoe UI / Segoe UI Symbol no
# Windows). Não há necessidade medida de uma biblioteca de ícones (ex.:
# um pacote de SVG/glifos) -- adicionar uma introduziria uma dependência
# nova (`requirements.txt`) sem um problema real que os glifos atuais
# não resolvam, o oposto do que o preâmbulo pede para decisões desse
# tipo.
#
# UMA INCONSISTÊNCIA REAL foi encontrada e fica registrada para 22b/22c
# corrigirem (não corrigida aqui -- seria "aplicar numa tela", fora do
# escopo desta sub-fase): `ui/mensagens.py` usa "🎉" (U+1F389, EMOJI de
# apresentação colorida) na mensagem de "nada pendente de revisão" --
# o único glifo colorido em toda a interface, destoando do resto do
# vocabulário, que é sempre monocromático. Ver relatório da auditoria.
ICONE_CONFIRMADO = "✓"        # = icone_status("CONFIRMADO"), repetido aqui só para o vocabulário ficar num lugar só
ICONE_REVISAO = "⚠"           # = icone_status("REVISAO")
ICONE_ERRO = "✕"              # = icone_status("ERRO")
ICONE_INFO = "ⓘ"              # nota informativa não-bloqueante (ex.: acúmulo de resultados, sinal de contexto)
ICONE_EXPANDIR = "▸"          # painel colapsável fechado ("Ver detalhes ▸")
ICONE_RECOLHER = "▾"          # painel colapsável aberto ("Ocultar detalhes ▾")
ICONE_ANTERIOR = "◀"          # navegação -- item anterior
ICONE_PROXIMO = "▶"           # navegação -- próximo item
ICONE_ZOOM_DIMINUIR = "−"     # controle de zoom da foto (Revisão)
ICONE_ZOOM_AUMENTAR = "+"     # controle de zoom da foto (Revisão)
# Sub-fase 22e: o botão de alternância de tema mostra o ícone do modo
# para o qual clicar LEVA (convenção comum -- o ícone descreve a ação,
# não o estado atual). "☀"/"☾" (U+2600/U+263E, bloco "Miscellaneous
# Symbols") de propósito, não os emojis de sol/lua (U+2600 tem uma
# variante emoji, mas nem essas nem "🌙" -- essa sim sempre colorida --
# entraram aqui: o vocabulário desta interface é monocromático, mesmo
# critério que já reprovou o "🎉" de `ui/mensagens.py` na auditoria 22a.
ICONE_TEMA_CLARO = "☀"
ICONE_TEMA_ESCURO = "☾"

# ---------------------------------------------------------------------
# Vocabulário de status. Um dicionário só, não um score, não uma cor
# isolada: ícone + palavra + cor semântica sempre juntos, porque o pedido
# explícito é "sem depender só de cor" -- a palavra tem que bastar sozinha.
#
# Duas variantes de rótulo por status:
#   - "curto": para onde o espaço é apertado mas ainda cabe o suficiente
#     para não depender só do ícone (a tabela de acompanhamento, Fase 10).
#   - "longo": a frase completa, para onde há espaço (cartões, avisos).
# ---------------------------------------------------------------------
STATUS_VOCABULARIO = {
    "CONFIRMADO": {
        "icone": "✓",
        "curto": "Confirmado",
        "longo": "Confirmado",
        "bootstyle": "success",
        "cor_fundo_tabela": "#eaf6ec",
    },
    "REVISAO": {
        "icone": "⚠",
        "curto": "Revisão",
        "longo": "Precisa de revisão",
        "bootstyle": "warning",
        "cor_fundo_tabela": "#fdf4e3",
    },
    "ERRO": {
        "icone": "✕",
        "curto": "Erro",
        "longo": "Erro no processamento",
        "bootstyle": "danger",
        "cor_fundo_tabela": "#fbe9e7",
    },
}
_PADRAO = STATUS_VOCABULARIO["REVISAO"]  # nunca deve ser usado de fato -- só evita estourar em status desconhecido


def _entrada(status: str) -> dict:
    return STATUS_VOCABULARIO.get(status, _PADRAO)


def texto_status(status: str, curto: bool = False) -> str:
    """'✓ Confirmado' / '⚠ Precisa de revisão' / '✕ Erro no processamento'
    (ou a forma curta, para colunas estreitas)."""
    entrada = _entrada(status)
    rotulo = entrada["curto"] if curto else entrada["longo"]
    return f"{entrada['icone']} {rotulo}"


def icone_status(status: str) -> str:
    return _entrada(status)["icone"]


def bootstyle_status(status: str) -> str:
    """Nome de estilo semântico do ttkbootstrap ('success'/'warning'/
    'danger') -- nunca usado sozinho para comunicar o status (o texto
    sempre acompanha), só para reforçar."""
    return _entrada(status)["bootstyle"]


def cor_fundo_tabela_status(status: str) -> str:
    return _entrada(status)["cor_fundo_tabela"]


def tag_status(status: str) -> str:
    """Nome da tag do Treeview (minúsculo, sem acento -- usado como chave
    de estilo, não como texto visível)."""
    return {"CONFIRMADO": "confirmado", "ERRO": "erro"}.get(status, "revisao")
