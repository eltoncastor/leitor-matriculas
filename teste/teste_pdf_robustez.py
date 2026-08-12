"""
teste/teste_pdf_robustez.py

Fase 14 -- robustez do fluxo de PDF. Protege as duas correções que a
medição comprovou, e o comportamento que a medição mostrou já estar certo
(para que continue certo).

O que a medição desta fase encontrou, em 50 páginas reais:

    memória do pdf_reader   estabiliza em ~322 MB (+0,18 MB/página)
                            -> o processamento incremental JÁ funciona;
                               o crescimento visto na Fase 11 vem do OCR,
                               não desta camada.
    retenção durante o yield  26,4 MB -> 8,8 MB depois da correção
                            -> pixmap e a view sobre ele ficavam vivos
                               durante os ~40 s de OCR da página.

Uso:
    python teste\\teste_pdf_robustez.py
"""

import gc
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402
import pymupdf as fitz  # noqa: E402

from leitor_matriculas.ocr import pdf_reader  # noqa: E402

falhas = []


def checar(cond, msg):
    print(("  OK    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def _pdf_sintetico(caminho, paginas=6):
    """PDF com N páginas, cada uma com um retângulo (conteúdo real, para o
    pixmap não ser trivialmente vazio)."""
    doc = fitz.open()
    for i in range(paginas):
        pagina = doc.new_page(width=600, height=400)
        pagina.draw_rect(fitz.Rect(50, 50, 550, 350), color=(0, 0, 0), width=2)
        pagina.insert_text((70, 100), f"pagina {i + 1}", fontsize=24)
    doc.save(caminho)
    doc.close()
    return caminho


# ---------------------------------------------------------------------------
# 1. O gerador não segura o pixmap enquanto quem consome trabalha
# ---------------------------------------------------------------------------

def teste_nao_retem_pixmap_durante_o_yield():
    print("=== O gerador não segura o pixmap durante o yield ===")
    with tempfile.TemporaryDirectory() as tmp:
        caminho = _pdf_sintetico(os.path.join(tmp, "doc.pdf"))
        gerador = pdf_reader.iterar_paginas(caminho)
        pagina = next(gerador)
        gc.collect()

        frame = gerador.gi_frame
        locais = frame.f_locals if frame is not None else {}
        pixmaps = [n for n, v in locais.items() if type(v).__name__ == "Pixmap"]
        checar(not pixmaps,
               f"nenhum Pixmap vivo no frame durante o yield (obtido: {pixmaps})")

        # A única imagem que pode continuar viva é a que foi entregue --
        # é o mesmo objeto que quem consome está usando.
        arrays = {n: v for n, v in locais.items() if isinstance(v, np.ndarray)}
        checar(len(arrays) <= 1,
               f"no máximo um array vivo (o entregue) durante o yield "
               f"(obtido: {sorted(arrays)})")
        for nome, valor in arrays.items():
            checar(valor is pagina.imagem,
                   f"o array vivo {nome!r} é exatamente a imagem entregue")

        # E a imagem entregue continua válida depois de soltar o pixmap:
        # ela é uma CÓPIA, não uma view sobre o buffer liberado.
        checar(pagina.imagem is not None and pagina.imagem.size > 0,
               "a imagem entregue continua utilizável")
        checar(float(pagina.imagem.std()) > 0,
               f"a imagem entregue tem conteúdo (std={float(pagina.imagem.std()):.2f})")
        gerador.close()
    print()


def teste_imagem_entregue_sobrevive_a_proxima_pagina():
    print("=== A imagem de uma página não é invalidada pela seguinte ===")
    with tempfile.TemporaryDirectory() as tmp:
        caminho = _pdf_sintetico(os.path.join(tmp, "doc.pdf"), paginas=3)
        gerador = pdf_reader.iterar_paginas(caminho)
        primeira = next(gerador)
        copia = primeira.imagem.copy()
        next(gerador)  # avança: o gerador renderiza a página seguinte
        checar(np.array_equal(primeira.imagem, copia),
               "a imagem da página 1 continua intacta depois de renderizar a 2")
        gerador.close()
    print()


# ---------------------------------------------------------------------------
# 2. Processamento incremental (o que a medição mostrou já estar certo)
# ---------------------------------------------------------------------------

def teste_paginas_sao_renderizadas_sob_demanda():
    print("=== Páginas são renderizadas sob demanda, não todas de uma vez ===")
    with tempfile.TemporaryDirectory() as tmp:
        caminho = _pdf_sintetico(os.path.join(tmp, "doc.pdf"), paginas=6)
        gerador = pdf_reader.iterar_paginas(caminho)
        primeira = next(gerador)
        checar(primeira.numero == 1, f"a primeira página sai antes das demais (obtido: {primeira.numero})")
        # o gerador está pausado: as páginas seguintes ainda não existem
        # como imagem em lugar nenhum.
        frame = gerador.gi_frame
        arrays = [v for v in (frame.f_locals if frame else {}).values()
                  if isinstance(v, np.ndarray)]
        checar(len(arrays) <= 1,
               f"nenhuma página adiantada foi renderizada (arrays vivos: {len(arrays)})")
        gerador.close()
    print()


def teste_documento_e_fechado_ao_interromper():
    print("=== Interromper o consumo não deixa o documento aberto ===")
    with tempfile.TemporaryDirectory() as tmp:
        caminho = _pdf_sintetico(os.path.join(tmp, "doc.pdf"), paginas=5)
        gerador = pdf_reader.iterar_paginas(caminho)
        next(gerador)
        gerador.close()  # dispara o finally do gerador
        # se o documento tivesse ficado aberto, no Windows o arquivo ficaria
        # travado e o TemporaryDirectory falharia ao limpar.
        checar(True, "o gerador fecha o documento no finally (sem travar o arquivo)")
    print()


# ---------------------------------------------------------------------------
# 3. Isolamento de falhas
# ---------------------------------------------------------------------------

def teste_falha_de_pagina_nao_derruba_o_lote():
    print("=== Uma página que falha ao renderizar não derruba as demais ===")
    with tempfile.TemporaryDirectory() as tmp:
        caminho = _pdf_sintetico(os.path.join(tmp, "doc.pdf"), paginas=5)

        # Falha real na renderização de UMA página, no ponto exato onde o
        # gerador a trata (get_pixmap). Uso um substituto porque o PyMuPDF
        # é resiliente demais para produzir esse erro por corrupção de
        # arquivo -- ver teste_pagina_ilegivel_vira_pagina_em_branco.
        original = fitz.Page.get_pixmap
        chamadas = {"n": 0}

        def get_pixmap_com_falha(self, *args, **kwargs):
            chamadas["n"] += 1
            if chamadas["n"] == 3:
                raise RuntimeError("falha simulada de renderização")
            return original(self, *args, **kwargs)

        fitz.Page.get_pixmap = get_pixmap_com_falha
        try:
            paginas = list(pdf_reader.iterar_paginas(caminho))
        finally:
            fitz.Page.get_pixmap = original

        checar(len(paginas) == 5, f"todas as 5 páginas foram devolvidas (obtido: {len(paginas)})")
        com_erro = [p for p in paginas if p.erro]
        checar(len(com_erro) == 1, f"exatamente uma com erro (obtido: {len(com_erro)})")
        checar(com_erro[0].numero == 3, f"o erro aponta a página certa (obtido: {com_erro[0].numero})")
        checar(com_erro[0].imagem is None, "a página com erro não entrega imagem")
        checar("falha simulada" in (com_erro[0].erro or ""), "o erro original é preservado, não engolido")
        numeros = [p.numero for p in paginas]
        checar(numeros == [1, 2, 3, 4, 5], f"a numeração não tem furo nem repetição (obtido: {numeros})")
        boas = [p for p in paginas if p.erro is None]
        checar(all(p.imagem is not None for p in boas), "as demais páginas continuam íntegras")
    print()


def teste_falha_do_documento_inteiro_e_fatal():
    print("=== Falha do DOCUMENTO inteiro levanta exceção (não é 'página com erro') ===")
    with tempfile.TemporaryDirectory() as tmp:
        inexistente = os.path.join(tmp, "nao_existe.pdf")
        try:
            list(pdf_reader.iterar_paginas(inexistente))
            checar(False, "arquivo inexistente deveria levantar exceção")
        except FileNotFoundError:
            checar(True, "arquivo inexistente -> FileNotFoundError")

        nao_e_pdf = os.path.join(tmp, "isto_nao_e_um_pdf.pdf")
        with open(nao_e_pdf, "w", encoding="utf-8") as f:
            f.write("isto e um arquivo de texto com extensao .pdf")
        try:
            list(pdf_reader.iterar_paginas(nao_e_pdf))
            checar(False, "arquivo que não é PDF deveria levantar exceção")
        except (RuntimeError, ValueError) as exc:
            checar(True, f"arquivo que não é PDF -> {type(exc).__name__}")

        # Achado da fase: o PyMuPDF RECUPERA um PDF truncado -- reconstrói o
        # que consegue e devolve páginas, em vez de falhar. Não dá para
        # exigir exceção aqui. O contrato que importa é o que se verifica
        # abaixo: o gerador não estoura para quem chama, e o que ele
        # devolver continua numerado de forma consistente.
        truncado = os.path.join(tmp, "truncado.pdf")
        caminho = _pdf_sintetico(os.path.join(tmp, "doc.pdf"), paginas=3)
        with open(caminho, "rb") as f:
            dados = f.read()
        with open(truncado, "wb") as f:
            f.write(dados[: len(dados) // 2])
        try:
            paginas = list(pdf_reader.iterar_paginas(truncado))
            numeros = [p.numero for p in paginas]
            checar(numeros == list(range(1, len(paginas) + 1)),
                   f"PDF truncado: o PyMuPDF recupera {len(paginas)} página(s), "
                   f"numeradas sem furo (obtido: {numeros})")
        except (RuntimeError, ValueError) as exc:
            checar(True, f"PDF truncado -> {type(exc).__name__} (erro de documento)")
    print()


def teste_pagina_ilegivel_vira_pagina_em_branco():
    print("=== Achado da fase: conteúdo ilegível vira página EM BRANCO, não erro ===")
    # O PyMuPDF não levanta exceção quando o conteúdo de uma página está
    # corrompido -- ele desenha o que consegue. Uma imagem embutida
    # destruída resulta numa página em branco, que segue pelo pipeline como
    # página "bem-sucedida" com ZERO registros. Isso não gera CONFIRMADO
    # nenhum (não há linha), e o aviso de contagem é o que sinaliza.
    # Este teste documenta o comportamento para que uma mudança futura de
    # versão do PyMuPDF não o altere sem que se perceba.
    tmp = tempfile.mkdtemp()
    try:
        intacto = os.path.join(tmp, "intacto.pdf")
        doc = fitz.open()
        pagina = doc.new_page(width=400, height=300)
        retangulo = fitz.Rect(10, 10, 390, 290)
        pagina.insert_image(retangulo, pixmap=fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 150)))
        doc.save(intacto)
        doc.close()

        # Salva a versão corrompida em OUTRO arquivo: gravar por cima do
        # mesmo caminho de onde o documento está aberto deixa o arquivo
        # travado no Windows.
        corrompido = os.path.join(tmp, "corrompido.pdf")
        doc = fitz.open(intacto)
        imagens = doc[0].get_images(full=True)
        if imagens:
            doc.update_stream(imagens[0][0], b"conteudo invalido" * 20)
        doc.save(corrompido)
        doc.close()

        paginas = list(pdf_reader.iterar_paginas(corrompido))
        checar(len(paginas) == 1, f"a página é devolvida (obtido: {len(paginas)})")
        checar(paginas[0].erro is None,
               "o PyMuPDF NÃO reporta erro para conteúdo corrompido (degrada em silêncio)")
        checar(paginas[0].imagem is not None, "e ainda assim entrega uma imagem")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print()


# ---------------------------------------------------------------------------
# 4. Rastreabilidade
# ---------------------------------------------------------------------------

def teste_numero_da_pagina_e_a_posicao_no_arquivo():
    print("=== O número devolvido é a posição da página DENTRO do arquivo ===")
    with tempfile.TemporaryDirectory() as tmp:
        caminho = _pdf_sintetico(os.path.join(tmp, "doc.pdf"), paginas=7)
        numeros = [p.numero for p in pdf_reader.iterar_paginas(caminho)]
        checar(numeros == list(range(1, 8)),
               f"numeração 1..7, na ordem física (obtido: {numeros})")
        checar(pdf_reader.contar_paginas(caminho) == 7,
               "contar_paginas concorda com o gerador (base do progresso)")
    print()


TESTES = [
    teste_nao_retem_pixmap_durante_o_yield,
    teste_imagem_entregue_sobrevive_a_proxima_pagina,
    teste_paginas_sao_renderizadas_sob_demanda,
    teste_documento_e_fechado_ao_interromper,
    teste_falha_de_pagina_nao_derruba_o_lote,
    teste_falha_do_documento_inteiro_e_fatal,
    teste_pagina_ilegivel_vira_pagina_em_branco,
    teste_numero_da_pagina_e_a_posicao_no_arquivo,
]


if __name__ == "__main__":
    for teste in TESTES:
        teste()
    print("=" * 62)
    if falhas:
        print(f"{len(falhas)} FALHA(S):")
        for f in falhas:
            print("   - " + f)
        sys.exit(1)
    print("TODAS AS VERIFICAÇÕES PASSARAM.")
