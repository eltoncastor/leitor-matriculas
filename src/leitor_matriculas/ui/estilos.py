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
`ui/explicacao_revisao.py`.

NÃO é um "componente" nem um motor de temas: não decide layout, não
substitui `ttkbootstrap`, só nomeia os valores que `ui/app.py` já usava
(tamanhos de fonte, espaçamentos, cores) para que o mesmo número/cor não
precise ser copiado de cabeça em cada tela nova.
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
