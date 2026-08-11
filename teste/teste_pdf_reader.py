"""
teste/teste_pdf_reader.py

Testes de pdf_reader.py usando PDFs SINTÉTICOS, criados na hora com o
próprio PyMuPDF (não são folhas reais — servem só para validar a lógica
de leitura: contagem de páginas, geração de imagem por página, tratamento
de arquivo ausente/corrompido, e recuperação quando uma página específica
falha ao renderizar).

Uso:
    python teste\\teste_pdf_reader.py
"""

import os
import sys
import shutil
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pdf_reader  # noqa: E402
from pdf_reader import contar_paginas, iterar_paginas, PaginaPdf  # noqa: E402

try:
    import pymupdf as fitz
except ImportError:
    import fitz


def _criar_pdf_sintetico(caminho: str, n_paginas: int, largura=600, altura=800):
    """Cria um PDF sintético com N páginas, cada uma com um texto simples."""
    documento = fitz.open()
    for i in range(n_paginas):
        pagina = documento.new_page(width=largura, height=altura)
        pagina.insert_text((50, 50), f"Pagina sintetica {i + 1}", fontsize=14)
    documento.save(caminho)
    documento.close()


def teste_contar_paginas():
    print("=== Teste 1: contar_paginas ===")
    tmp = tempfile.mkdtemp()
    try:
        caminho = os.path.join(tmp, "teste_5paginas.pdf")
        _criar_pdf_sintetico(caminho, 5)
        assert contar_paginas(caminho) == 5
        print("  OK: PDF de 5 páginas -> contar_paginas() == 5")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()


def teste_iterar_paginas_basico():
    print("=== Teste 2: iterar_paginas devolve uma imagem BGR por página ===")
    tmp = tempfile.mkdtemp()
    try:
        caminho = os.path.join(tmp, "teste_3paginas.pdf")
        _criar_pdf_sintetico(caminho, 3, largura=400, altura=600)

        paginas = list(iterar_paginas(caminho, dpi=100))
        assert len(paginas) == 3

        for i, pagina in enumerate(paginas, start=1):
            assert isinstance(pagina, PaginaPdf)
            assert pagina.numero == i
            assert pagina.erro is None
            assert pagina.imagem is not None
            assert pagina.imagem.ndim == 3 and pagina.imagem.shape[2] == 3, pagina.imagem.shape
            # 100 dpi numa página de 400x600 pontos (72 dpi) -> ~555x833 px
            altura_esperada = round(600 * 100 / 72)
            largura_esperada = round(400 * 100 / 72)
            assert abs(pagina.imagem.shape[0] - altura_esperada) <= 1, pagina.imagem.shape
            assert abs(pagina.imagem.shape[1] - largura_esperada) <= 1, pagina.imagem.shape

        print(f"  OK: 3 páginas, cada uma virou uma imagem BGR de shape ~{paginas[0].imagem.shape}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()


def teste_arquivo_inexistente():
    print("=== Teste 3: arquivo PDF inexistente ===")
    try:
        contar_paginas("/caminho/que/nao/existe.pdf")
        raise AssertionError("Deveria ter levantado FileNotFoundError")
    except FileNotFoundError as exc:
        print(f"  OK: FileNotFoundError levantado corretamente -> {exc}")

    try:
        list(iterar_paginas("/caminho/que/nao/existe.pdf"))
        raise AssertionError("Deveria ter levantado FileNotFoundError")
    except FileNotFoundError as exc:
        print(f"  OK: iterar_paginas também levanta FileNotFoundError -> {exc}")
    print()


def teste_pdf_corrompido():
    print("=== Teste 4: PDF corrompido / inválido (arquivo existe, mas não é um PDF de verdade) ===")
    tmp = tempfile.mkdtemp()
    try:
        caminho = os.path.join(tmp, "nao_e_um_pdf.pdf")
        with open(caminho, "wb") as f:
            f.write(b"isto claramente nao e um arquivo PDF valido")

        try:
            contar_paginas(caminho)
            raise AssertionError("Deveria ter levantado RuntimeError para PDF corrompido")
        except RuntimeError as exc:
            print(f"  OK: RuntimeError levantado corretamente -> {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()


def teste_pdf_sem_paginas():
    print("=== Teste 5: PDF sem nenhuma página (defesa contra page_count == 0) ===")
    # O próprio PyMuPDF impede salvar um PDF com zero páginas de verdade
    # (`ValueError: cannot save with zero pages`), então não é possível
    # criar esse arquivo "de verdade" como fixture. Para ainda assim testar
    # a checagem defensiva em `_abrir_documento` (que existe para o caso de
    # algum PDF malformado abrir com 0 páginas), simulamos a situação
    # substituindo `page_count` por 0 num documento real via mock.
    tmp = tempfile.mkdtemp()
    try:
        caminho = os.path.join(tmp, "com_1_pagina.pdf")
        _criar_pdf_sintetico(caminho, 1)

        documento_real = fitz.open(caminho)

        class _DocumentoSimuladoSemPaginas:
            page_count = 0

            def close(self):
                documento_real.close()

        with patch.object(pdf_reader.fitz, "open", return_value=_DocumentoSimuladoSemPaginas()):
            try:
                contar_paginas(caminho)
                raise AssertionError("Deveria ter levantado ValueError para PDF sem páginas")
            except ValueError as exc:
                print(f"  OK: ValueError levantado corretamente -> {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()


def teste_erro_em_uma_pagina_especifica_nao_para_o_resto():
    print("=== Teste 6: erro ao renderizar UMA página específica não interrompe as outras ===")
    tmp = tempfile.mkdtemp()
    try:
        caminho = os.path.join(tmp, "teste_4paginas.pdf")
        _criar_pdf_sintetico(caminho, 4)

        original_get_pixmap = fitz.Page.get_pixmap

        def get_pixmap_com_falha_na_pagina_2(self, *args, **kwargs):
            # self.number é o índice 0-based da página; página 2 (número
            # humano) == índice 1.
            if self.number == 1:
                raise RuntimeError("falha simulada de renderização")
            return original_get_pixmap(self, *args, **kwargs)

        with patch.object(fitz.Page, "get_pixmap", get_pixmap_com_falha_na_pagina_2):
            paginas = list(iterar_paginas(caminho))

        assert len(paginas) == 4, "As 4 páginas deveriam continuar aparecendo no resultado"

        pagina_1, pagina_2, pagina_3, pagina_4 = paginas

        assert pagina_1.erro is None and pagina_1.imagem is not None
        assert pagina_2.erro is not None and pagina_2.imagem is None
        assert "falha simulada" in pagina_2.erro
        assert pagina_3.erro is None and pagina_3.imagem is not None
        assert pagina_4.erro is None and pagina_4.imagem is not None

        print("  OK: página 2 falhou e voltou com erro, mas páginas 1, 3 e 4 continuaram normalmente")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()


def teste_processamento_preguicoso():
    print("=== Teste 7: páginas são renderizadas sob demanda (não todas de uma vez) ===")
    tmp = tempfile.mkdtemp()
    try:
        caminho = os.path.join(tmp, "teste_6paginas.pdf")
        _criar_pdf_sintetico(caminho, 6)

        contador = {"chamadas": 0}
        original_get_pixmap = fitz.Page.get_pixmap

        def get_pixmap_contando(self, *args, **kwargs):
            contador["chamadas"] += 1
            return original_get_pixmap(self, *args, **kwargs)

        with patch.object(fitz.Page, "get_pixmap", get_pixmap_contando):
            gerador = iterar_paginas(caminho)
            assert contador["chamadas"] == 0, "Criar o gerador não deveria renderizar nada ainda"

            next(gerador)
            assert contador["chamadas"] == 1, "Pedir 1 página só deveria renderizar 1 página"

            next(gerador)
            assert contador["chamadas"] == 2, "Pedir a 2ª página só deveria renderizar mais 1"

            # Consome o restante
            list(gerador)
            assert contador["chamadas"] == 6

        print("  OK: páginas são renderizadas uma de cada vez, sob demanda (comportamento de gerador)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()


if __name__ == "__main__":
    testes = [
        teste_contar_paginas,
        teste_iterar_paginas_basico,
        teste_arquivo_inexistente,
        teste_pdf_corrompido,
        teste_pdf_sem_paginas,
        teste_erro_em_uma_pagina_especifica_nao_para_o_resto,
        teste_processamento_preguicoso,
    ]

    falhas = 0
    for teste in testes:
        try:
            teste()
        except AssertionError as exc:
            falhas += 1
            print(f"  FALHOU: {teste.__name__}: {exc}")
            print()

    print("=" * 60)
    if falhas == 0:
        print(f"TODOS OS {len(testes)} TESTES PASSARAM.")
    else:
        print(f"{falhas} de {len(testes)} TESTE(S) FALHARAM.")
        sys.exit(1)
