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

_RAIZ_PROJETO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Mesmo raciocínio de `web/backend/main.py`: rodando como `python
# web/desktop_app.py`, o Python só coloca `web/` no sys.path
# automaticamente (o diretório do próprio script) -- sem a RAIZ aqui,
# `import web.backend.main` abaixo falharia. `src/` também é inserido
# aqui, embora `web.backend.main` já faça o mesmo ao ser importado --
# inofensivo repetir (sys.path aceita entradas duplicadas sem efeito
# colateral), e deixa este arquivo correto por si só, sem depender da
# ordem de import.
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

    janela = webview.create_window(
        "Leitor de Matrículas",
        f"http://{HOST}:{PORTA}/",
        width=1440,
        height=900,
        min_size=(1024, 700),
    )

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
    sys.exit(main())
