"""
web/desktop_app.py

Sub-fase 25a (retomada da Fase 25 -- empacotamento da versão WEB num .exe
portátil, ver CLAUDE.md e `saida/avaliacao_fase25_exe.md`). Processo Python
ÚNICO: sobe o backend (`web/backend/main.py`, que desde esta sub-fase
também serve o build de produção do frontend -- ver esse módulo) numa
THREAD interna -- nunca como um `uvicorn`/`node` separado via
`subprocess`/janela de terminal -- e abre uma janela nativa (`pywebview`)
apontando para ele. Fechar a janela precisa encerrar TUDO; não pode haver
nada "por fora" deste processo que sobreviva a ele.

Este é o alvo INTERMEDIÁRIO da Fase 25: ainda roda via `python
web/desktop_app.py`, não é o `.exe` (isso é a Sub-fase 25b, empacotamento
com PyInstaller). O que esta sub-fase prova é que a aplicação inteira
(API + interface) já cabe num processo Python só, controlado por uma
janela nativa em vez de um navegador -- pré-requisito para empacotar.

Pré-requisito: o build de produção do frontend precisa existir --
    cd web/frontend && npm run build
Sem ele, `web/backend/main.py` continua funcionando (só como API, ver o
próprio módulo), mas esta janela mostraria uma resposta de API pura em vez
da aplicação -- por isso este script verifica e avisa antes de abrir a
janela, em vez de deixar o operador descobrir isso olhando uma tela em
branco.

Rodar (a partir da raiz do projeto, com o venv ativo):
    python web\\desktop_app.py
"""
import os
import sys

if getattr(sys, "frozen", False):
    # Sub-fase 25b (empacotamento com PyInstaller) -- achado real, não
    # hipotético: o SCRIPT DE ENTRADA (este arquivo) recebe um `__file__`
    # congelado que aponta para a pasta do PRÓPRIO `.exe`
    # (`dist_exe/LeitorDeMatriculas/desktop_app.py`, um caminho sintético
    # que nem chega a existir como arquivo real) -- DIFERENTE de como um
    # módulo IMPORTADO (como `web.backend.main`, importado abaixo) tem seu
    # `__file__` resolvido, que preserva o caminho do pacote dentro de
    # `sys._MEIPASS` (`_internal/web/backend/main.pyc`). A primeira versão
    # deste arquivo usava `os.path.dirname(__file__)` sem essa distinção e
    # calculava a pasta ERRADA (a pasta do `.exe`, sem o `_internal` no
    # meio) -- resultado: "build de produção não encontrado" mesmo com o
    # build de verdade presente, só em local diferente do calculado.
    # `sys._MEIPASS` é a forma OFICIAL e documentada do PyInstaller para
    # um app congelado achar os próprios dados empacotados -- correta nos
    # dois modos (`--onedir` E `--onefile`), ao contrário de calcular a
    # partir de `__file__`.
    _RAIZ_PROJETO = sys._MEIPASS
else:
    _RAIZ_PROJETO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # Mesmo raciocínio de `web/backend/main.py`: rodando como `python
    # web/desktop_app.py`, o Python só coloca `web/` no sys.path
    # automaticamente (o diretório do próprio script) -- sem a RAIZ aqui,
    # `import web.backend.main` abaixo falharia. `src/` também é inserido
    # aqui, embora `web.backend.main` já faça o mesmo ao ser importado --
    # inofensivo repetir (sys.path aceita entradas duplicadas sem efeito
    # colateral), e deixa este arquivo correto por si só, sem depender da
    # ordem de import. Fora de um build congelado só -- dentro de um
    # `.exe`, os módulos já vêm resolvidos pelo importer do PyInstaller,
    # manipular `sys.path` não tem efeito nem faz falta.
    sys.path.insert(0, _RAIZ_PROJETO)
    sys.path.insert(0, os.path.join(_RAIZ_PROJETO, "src"))

import pathlib  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

import uvicorn  # noqa: E402
import webview  # noqa: E402

from web.backend.main import app  # noqa: E402

# 127.0.0.1, não 0.0.0.0: este modo é uma janela NATIVA rodando na MESMA
# máquina -- o motor de renderização do pywebview fala com o servidor
# localmente, nunca por rede. Não tem relação com o ajuste do Tailscale
# (esse é sobre `web/backend/main.py` rodando como servidor autônomo,
# acessado por OUTRA máquina/navegador -- um modo diferente, que continua
# existindo e inalterado). Uma porta diferente da 8000 "de sempre" evita
# colidir com uma instância do modo servidor (`python web/backend/main.py`)
# que porventura já esteja rodando na máquina.
HOST = "127.0.0.1"
PORTA = 8765

_DIST_INDEX = pathlib.Path(_RAIZ_PROJETO) / "web" / "frontend" / "dist" / "index.html"


def _criar_servidor() -> uvicorn.Server:
    config = uvicorn.Config(app, host=HOST, port=PORTA, log_level="warning")
    return uvicorn.Server(config)


def _esperar_servidor_pronto(timeout_s: float = 20.0) -> bool:
    """Faz polling em /saude até o servidor responder -- mesmo motivo de
    `PaginaLote.jsx` fazer polling de status em vez de assumir prontidão:
    o uvicorn leva um instante para terminar de subir, e abrir a janela
    cedo demais mostraria uma página de erro de conexão em vez de
    esperar."""
    url = f"http://{HOST}:{PORTA}/saude"
    inicio = time.monotonic()
    while time.monotonic() - inicio < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=1) as resposta:
                if resposta.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    # Achado real (botão "Baixar planilha" sem nenhum efeito no .exe): o
    # pywebview desabilita downloads por padrão desde a versão 4.4 -- o
    # link `<a href=... download>` de `Resultado.jsx` continua sendo um
    # link comum, mas o WebView2 engole o clique em silêncio (nenhum erro,
    # nenhum diálogo) até este `settings` ser ligado explicitamente. Tem
    # que vir ANTES de `create_window`, que é quando a janela/engine é
    # de fato instanciada.
    webview.settings["ALLOW_DOWNLOADS"] = True

    if not _DIST_INDEX.is_file():
        print(
            "AVISO: build de produção do frontend não encontrado em "
            f"{_DIST_INDEX}\n"
            "Rode primeiro:\n"
            "    cd web\\frontend\n"
            "    npm run build\n"
            "e tente de novo -- sem o build, esta janela mostraria a API "
            "pura, não a interface.",
            file=sys.stderr,
        )
        return 1

    servidor = _criar_servidor()
    # daemon=True: se por algum motivo o processo terminar sem passar pelo
    # caminho normal de encerramento abaixo (`_ao_fechar`), esta thread
    # nunca impede o processo Python de sair -- não sobra um "uvicorn
    # órfão" porque não existe um `uvicorn` separado nenhum, é só esta
    # thread dentro deste mesmo processo. Ver a verificação de "sem
    # processo órfão" no relatório desta sub-fase.
    thread_servidor = threading.Thread(target=servidor.run, daemon=True)
    thread_servidor.start()

    if not _esperar_servidor_pronto():
        print(f"ERRO: o servidor não respondeu em http://{HOST}:{PORTA}/saude a tempo.", file=sys.stderr)
        return 1

    # Sub-fase 25b -- achado medido, não hipotético: mesmo com o servidor
    # já respondendo (`_esperar_servidor_pronto` acima), a criação da
    # janela mostra uma tela BRANCA por ~4s antes do primeiro paint de
    # verdade -- é o próprio WebView2 inicializando/carregando a página,
    # não o servidor (o servidor já estava pronto quando a janela é
    # criada). `hidden=True` + revelar só no evento `loaded` (disparado
    # quando a página termina de carregar) troca "janela branca por
    # alguns segundos" por "nada aparece até estar pronto para aparecer" --
    # mais correto que sincronizar de novo com `/saude` (que já passou) ou
    # não fazer nada (a tela branca, medida, é desconfortável o bastante
    # pra justificar isto sem virar uma tela de carregamento elaborada).
    janela = webview.create_window(
        "Leitor de Matrículas",
        f"http://{HOST}:{PORTA}/",
        width=1440,
        height=900,
        min_size=(1024, 700),
        hidden=True,
    )
    janela.events.loaded += janela.show

    def _ao_fechar():
        # Sinaliza o `uvicorn.Server` para encerrar o próprio loop de
        # forma limpa (solta a porta, fecha conexões) em vez de só confiar
        # no processo inteiro morrer -- mais correto, mesmo a thread daemon
        # já garantindo que nada sobrevive ao processo de qualquer jeito.
        servidor.should_exit = True

    janela.events.closed += _ao_fechar

    # Bloqueia até a janela ser fechada -- é o "loop principal" da
    # aplicação desktop, equivalente ao `app.mainloop()` do Tkinter.
    webview.start()

    thread_servidor.join(timeout=5)
    return 0


if __name__ == "__main__":
    # Sub-fase 25b (empacotamento com PyInstaller): `freeze_support()` é
    # inofensivo fora de um `.exe` congelado (vira um no-op) e evita um
    # problema conhecido no Windows -- se QUALQUER dependência (paddle
    # inclusive) usar `multiprocessing` internamente, um `.exe` congelado
    # sem essa chamada pode reexecutar o programa inteiro do zero a cada
    # subprocesso, em vez de só rodar o worker esperado. Chamado logo no
    # início do bloco, antes de qualquer outra coisa, como a documentação
    # do `multiprocessing` recomenda.
    import multiprocessing

    multiprocessing.freeze_support()
    sys.exit(main())
