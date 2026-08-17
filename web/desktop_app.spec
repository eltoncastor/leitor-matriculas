# -*- mode: python ; coding: utf-8 -*-
"""
web/desktop_app.spec

Sub-fase 25b (empacotamento do app web em .exe portátil com PyInstaller,
ver CLAUDE.md e saida/avaliacao_fase25_exe.md). Empacota web/desktop_app.py
(Sub-fase 25a: processo único, backend + frontend buildado + janela nativa)
num executável/pasta portátil.

Rodar (a partir da raiz do projeto, com o venv ativo):
    pyinstaller web/desktop_app.spec --distpath dist_exe --workpath build_exe --noconfirm

Por que um .spec em vez da linha de comando padrão do PyInstaller
(`pyinstaller web/desktop_app.py`): PaddleOCR/PaddleX têm hidden imports e
arquivos de dados (configs YAML, etc.) que a análise estática do
PyInstaller não descobre sozinha -- padrão conhecido desses pacotes,
citado no pedido desta sub-fase. A ferramenta CERTA para isso é
`collect_all()` (do próprio PyInstaller, `PyInstaller.utils.hooks`), que
coleta hidden imports + datas + binaries de um pacote inteiro de uma vez
-- é o padrão documentado para frameworks de ML grandes e dinâmicos como
este, não uma lista adivinhada por tentativa-e-erro. `pyinstaller-hooks-
contrib` (instalado junto) já cobre `cv2`, `openpyxl`, `shapely`,
`skimage`, `uvicorn` e `webview` -- só paddle/paddleocr/paddlex e pymupdf
não têm hook nenhum (nem no PyInstaller nem no hooks-contrib), daí o
`collect_all` explícito só para esses quatro abaixo.
"""
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

# SPECPATH (injetado pelo PyInstaller) já É a pasta que contém o .spec
# (web/), não o caminho do arquivo -- achado real: a primeira tentativa
# aplicava `os.path.dirname` em cima disso de novo, subindo um nível a
# mais e apontando para fora do repositório inteiro ("script ... não
# encontrado", apontando para Projetos/web/ em vez de Projetos/
# leitor_matriculas/web/). Corrigido para só ".." uma vez a partir de
# SPECPATH.
RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821

# ----------------------------------------------------------------------
# Sub-fase 25b, seção 2 do pedido: investigação de tamanho -- pandas/
# modelscope/networkx são transitivos de paddleocr/paddlex (medidos na
# 25a: 101 MB somados) e não são importados em nenhuma linha de
# src/leitor_matriculas/ ou web/. Testados aqui via `excludes`, um de cada
# vez, com o fluxo real (OCR de verdade, `entrada/pdf/teste.pdf`) --
# MEDIDO, não assumido. RESULTADO: os TRÊS são genuinamente necessários
# em tempo de execução, nenhum pôde ser excluído:
#   - `modelscope`: QUEBROU -- `paddlex/inference/utils/official_models.
#     py` faz `import modelscope` incondicional no topo do módulo.
#   - `pandas`: QUEBROU -- `paddlex/inference/utils/io/readers.py` faz
#     `import pandas as pd` incondicional no topo do módulo (leitores de
#     dados genéricos do PaddleX, carregados na cadeia de import mesmo só
#     usando OCR de texto).
#   - `networkx`: QUEBROU -- `paddlex.utils.deps.require_extra("ocr", ...)`
#     verifica a presença de `networkx` como parte da checagem de
#     dependências do extra "ocr" ANTES de criar o pipeline (`RuntimeError:
#     A dependency error occurred during pipeline creation`), mesmo o
#     código deste projeto nunca importando `networkx` diretamente.
# Os três voltaram a fazer parte do bundle -- `EXCLUSOES_INVESTIGADAS`
# fica vazia de propósito (não apagada), documentando que a investigação
# ACONTECEU e não achou nada seguro para cortar, não que ela nunca foi
# tentada. Detalhe completo em saida/avaliacao_fase25_exe.md, seção 25b.
# ----------------------------------------------------------------------
EXCLUSOES_INVESTIGADAS = []

hiddenimports = []
datas = []
binaries = []

# Achado real, não hipotético: a primeira tentativa de `collect_all
# ("paddle")` MATOU o subprocesso isolado do PyInstaller (access
# violation nativo, exit code 3221225477 = 0xC0000005) ao tentar
# IMPORTAR `paddle.jit.sot` só para enumerar os submódulos dele --
# `paddle.tensorrt` também falha (com um AttributeError mais benigno,
# sobrevive como warning) na mesma tentativa, porque este ambiente não
# tem GPU/TensorRT. Nenhum dos dois é usado por `ocr/engine.py`
# (`PaddleOCR(...).predict()`, CPU, sem JIT/sot nem TensorRT) -- por isso
# `filter_submodules` os exclui da ENUMERAÇÃO (nunca chega a importar,
# então nunca chega a crashar), em vez de eu tentar capturar a exceção
# depois (um access violation mata o processo antes de qualquer
# try/except em Python rodar).
_PADDLE_SUBMODULOS_A_EVITAR = ("paddle.jit.sot", "paddle.tensorrt")


def _filtro_submodulos_paddle(nome):
    return not nome.startswith(_PADDLE_SUBMODULOS_A_EVITAR)


for pacote in ("paddle", "paddleocr", "paddlex", "pymupdf"):
    kwargs = {"filter_submodules": _filtro_submodulos_paddle} if pacote == "paddle" else {}
    _datas, _binaries, _hiddenimports = collect_all(pacote, **kwargs)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hiddenimports

# Achado real #2, numa tentativa POSTERIOR: com `modelscope` de volta na
# lista (obrigatório -- ver acima), `paddle.jit.sot.opcode_translator`
# voltou a crashar o subprocesso isolado do PyInstaller -- desta vez
# durante a fase de ANÁLISE dos hidden imports (`import_library()`), não
# durante o `collect_submodules` do `paddle` sozinho. Ou seja, o
# `filter_submodules` acima (que só se aplica à chamada `collect_all
# ("paddle")`) não é suficiente: o nome chega à lista de hiddenimports por
# OUTRO caminho -- provavelmente `modelscope` sondando `paddle.jit`
# internamente. A correção robusta é dupla: (1) remover qualquer entrada
# já coletada que comece com esses prefixos, não importa de qual dos 4
# `collect_all` ela veio; (2) declarar os mesmos prefixos em `excludes=`
# do `Analysis` abaixo, que é a camada AUTORITATIVA -- impede o
# PyInstaller de tentar importar esses módulos de novo por qualquer outro
# caminho de descoberta (inclusive um que eu não tenha antecipado).
hiddenimports = [
    nome for nome in hiddenimports if not nome.startswith(_PADDLE_SUBMODULOS_A_EVITAR)
]

# Achado real #3 (o que realmente resolveu o "DependencyError" que
# sobreviveu mesmo com pandas/modelscope/networkx todos de volta no
# bundle): `paddlex.utils.deps.require_extra("ocr", alt="ocr-core")`
# NÃO verifica se os módulos são IMPORTÁVEIS -- verifica se a METADATA de
# pacote instalado (`importlib.metadata.version(...)`) está presente e
# LEGÍVEL, lendo a própria pasta `.dist-info` de cada dependência. O
# PyInstaller (`collect_all`) empacota o CÓDIGO de um pacote, mas não
# duplica a pasta `.dist-info` das suas dependências por padrão -- por
# isso os módulos estavam todos lá (o ImportError sumiu), mas a checagem
# de metadata continuava falhando. `copy_metadata()` (a ferramenta CERTA
# do próprio PyInstaller para exatamente este padrão -- pacotes que usam
# `importlib.metadata`/`pkg_resources` pra checar capacidade em tempo de
# execução) resolve isso. Investigado com precisão, não em bloco: `alt=
# "ocr-core"` (não o "ocr" completo, mais pesado) é o que
# `paddleocr/_pipelines/base.py` realmente aceita, e a lista exata de
# dependências do extra "ocr-core" foi obtida direto de `paddlex.utils.
# deps.EXTRAS["ocr-core"]` (rodado neste venv), não adivinhada.
for pacote_metadata in (
    "paddlex", "paddleocr", "paddlepaddle",
    "imagesize", "opencv-contrib-python", "pyclipper",
    "pypdfium2", "python-bidi", "shapely",
):
    datas += copy_metadata(pacote_metadata)

# O build de produção do frontend (Sub-fase 25a) -- copiado para o MESMO
# caminho relativo (`web/frontend/dist`) que `web/backend/main.py` usa
# para calcular `_DIST_DIR` a partir do próprio `__file__`. O PyInstaller
# preserva a estrutura de pacote Python (`web/backend/main.pyc` etc.) sob
# `sys._MEIPASS`, então o cálculo "três níveis acima de __file__" que
# `main.py` já fazia sem mudança nenhuma continua resolvendo para
# `sys._MEIPASS` -- e é exatamente aí que este `datas` entry coloca o
# `dist/`. Verificado no build real (ver relatório) -- não é só teoria.
datas += [(os.path.join(RAIZ, "web", "frontend", "dist"), "web/frontend/dist")]

# `dados/` (Colaboradores/Gestores/Motivos.xlsx) DELIBERADAMENTE NÃO entra
# aqui -- ver `web/backend/estado.py::_pasta_dados_ao_lado_do_executavel`.
# São dados que o usuário edita sem reempacotar; ficam FORA do bundle, na
# mesma pasta do .exe final, nunca dentro do arquivo/pasta congelados.

a = Analysis(  # noqa: F821
    [os.path.join(RAIZ, "web", "desktop_app.py")],
    pathex=[RAIZ, os.path.join(RAIZ, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUSOES_INVESTIGADAS + list(_PADDLE_SUBMODULOS_A_EVITAR),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LeitorDeMatriculas",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True foi usado durante toda a depuração desta sub-fase
    # (deixou visíveis os tracebacks reais que levaram às correções
    # documentadas em saida/avaliacao_fase25_exe.md -- o crash do
    # `paddle.jit.sot`, o bug de caminho do `SPECPATH`, o `__file__`
    # sintético do script de entrada, os três `DependencyError` de
    # metadata). Só troca para False AQUI, depois de o fluxo completo já
    # ter sido verificado de ponta a ponta com console=True -- é o build
    # FINAL, sem janela de terminal atrás da janela nativa.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(RAIZ, "web", "frontend", "public", "favicon.ico")
    if os.path.isfile(os.path.join(RAIZ, "web", "frontend", "public", "favicon.ico"))
    else None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LeitorDeMatriculas",
)
