"""
main.py

Ponto de entrada do Leitor de Matrículas Manuscritas.

Rode com:
    python main.py

O código-fonte fica em `src/leitor_matriculas/` (organizado por
responsabilidade: ocr, parsing, validacao, dados, exportacao, ui). Como o
projeto roda direto do diretório, sem instalação via pip, este arquivo
acrescenta `src/` ao sys.path antes de importar o pacote — é o que
mantém `python main.py` funcionando sem nenhum passo extra de setup.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from leitor_matriculas.ui.app import App  # noqa: E402  (precisa vir depois do sys.path)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
