"""
teste/teste_registro_parser.py

Testes do parser espacial (registro_parser.py), usando fixtures SINTÉTICAS
(coordenadas de bounding box inventadas à mão, não vêm de nenhuma folha
real) para simular diferentes situações da folha de liberações:

    - página normal (cabeçalho + N registros completos);
    - registros com pequenas variações de posição (linha "torta");
    - registro incompleto (faltando matrícula);
    - quantidade de registros diferente de 8;
    - elementos fora da ordem em que o OCR normalmente devolveria;
    - textos irrelevantes entre registros (título, texto solto).

Uso:
    python teste\\teste_registro_parser.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.ocr.engine import OCRResult  # noqa: E402
from leitor_matriculas.parsing.registro_parser import parse_registros, agrupar_em_linhas, ordenar_elementos, CampoOcr  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers de fixture
# ---------------------------------------------------------------------------

def _r(texto, x1, y1, x2, y2, confianca=0.95):
    """Atalho para criar um OCRResult de teste com box [x1,y1,x2,y2]."""
    return OCRResult(texto_original=texto, confianca=confianca, box=[x1, y1, x2, y2])


# Layout de colunas usado nas fixtures abaixo (posições x arbitrárias, só
# para simular uma tabela real com 7 colunas razoavelmente espaçadas):
#   DATA=60   HORA=160   NOME=280   MATRÍCULA=450   SETOR=560   MOTIVO=700   RESPONSÁVEL=880
COL_DATA, COL_HORA, COL_NOME, COL_MATRICULA, COL_SETOR, COL_MOTIVO, COL_GESTOR = (
    60, 160, 280, 450, 560, 700, 880,
)


def _linha_cabecalho(y1=10, y2=30):
    return [
        _r("DATA", COL_DATA - 20, y1, COL_DATA + 20, y2),
        _r("HORA", COL_HORA - 20, y1, COL_HORA + 20, y2),
        _r("NOME", COL_NOME - 25, y1, COL_NOME + 25, y2),
        _r("MATRÍCULA", COL_MATRICULA - 35, y1, COL_MATRICULA + 35, y2),
        _r("SETOR", COL_SETOR - 25, y1, COL_SETOR + 25, y2),
        _r("MOTIVO", COL_MOTIVO - 25, y1, COL_MOTIVO + 25, y2),
        _r("RESPONSÁVEL", COL_GESTOR - 40, y1, COL_GESTOR + 40, y2),
    ]


def _linha_registro(y1, y2, data, hora, nome, matricula, setor, motivo, gestor):
    """Monta uma linha de dados completa, alinhada às colunas do cabeçalho."""
    return [
        _r(data, COL_DATA - 15, y1, COL_DATA + 15, y2),
        _r(hora, COL_HORA - 15, y1, COL_HORA + 15, y2),
        _r(nome, COL_NOME - 25, y1, COL_NOME + 25, y2),
        _r(matricula, COL_MATRICULA - 20, y1, COL_MATRICULA + 20, y2),
        _r(setor, COL_SETOR - 20, y1, COL_SETOR + 20, y2),
        _r(motivo, COL_MOTIVO - 25, y1, COL_MOTIVO + 25, y2),
        _r(gestor, COL_GESTOR - 30, y1, COL_GESTOR + 30, y2),
    ]


def _pagina_normal(n_registros=8, y_inicial=40, altura_linha=30):
    """Página sintética com cabeçalho + N registros completos, bem alinhados."""
    elementos = list(_linha_cabecalho())
    for i in range(n_registros):
        y1 = y_inicial + i * altura_linha
        y2 = y1 + 20
        elementos += _linha_registro(
            y1, y2,
            data=f"0{(i % 9) + 1}.04",
            hora=f"11:{10 + i:02d}",
            nome=f"Colaborador {i+1}",
            matricula=f"{28000 + i}",
            setor="TI" if i % 2 == 0 else "RH",
            motivo="RH" if i % 2 == 0 else "ADM",
            gestor=f"Gestor {i % 3}",
        )
    return elementos


# ---------------------------------------------------------------------------
# Teste 1: página normal (cabeçalho + N registros completos)
# ---------------------------------------------------------------------------

def teste_pagina_normal():
    print("=== Teste 1: página normal (8 registros completos) ===")
    elementos = _pagina_normal(n_registros=8)
    resultado = parse_registros(elementos)

    assert resultado.cabecalho_detectado, "Deveria ter detectado o cabeçalho"
    # 5, não 7: nome/setor não são reconhecidos como campo (são derivados
    # da matrícula) -- ver requisito funcional definitivo em registro_parser.py.
    assert len(resultado.colunas_detectadas) == 5, resultado.colunas_detectadas
    assert len(resultado.registros) == 8, f"Esperava 8 registros, veio {len(resultado.registros)}"

    for registro in resultado.registros:
        assert registro.completo, f"Registro {registro.indice} deveria estar completo: {registro.campos}"
        assert not registro.campos_faltando(), registro.campos_faltando()
        assert "matricula" in registro.campos

    # Confere que o texto original foi preservado (não normalizado) e que a
    # confiança e o box também foram preservados.
    primeiro = resultado.registros[0]
    assert primeiro.campos["matricula"].texto == "28000"
    assert primeiro.campos["matricula"].confianca == 0.95
    assert primeiro.campos["matricula"].box == [430, 40, 470, 60]

    print(f"  Registros: {len(resultado.registros)} (todos completos)")
    print("  OK")
    print()


# ---------------------------------------------------------------------------
# Teste 2: ordenação espacial e elementos fora de ordem
# ---------------------------------------------------------------------------

def teste_ordenacao_e_fora_de_ordem():
    print("=== Teste 2: ordenação espacial (elementos fora da ordem do OCR) ===")
    elementos_em_ordem = _pagina_normal(n_registros=3)

    # Embaralha a lista para simular o OCR devolvendo tudo fora de ordem
    import random
    embaralhados = elementos_em_ordem[:]
    random.Random(42).shuffle(embaralhados)
    assert embaralhados != elementos_em_ordem  # garante que o embaralhamento de fato mudou a ordem

    resultado_ordem_normal = parse_registros(elementos_em_ordem)
    resultado_embaralhado = parse_registros(embaralhados)

    assert len(resultado_ordem_normal.registros) == len(resultado_embaralhado.registros) == 3

    # O resultado (quem foi parar em cada registro) deve ser o mesmo,
    # independente da ordem de entrada — só a posição espacial importa.
    for r1, r2 in zip(resultado_ordem_normal.registros, resultado_embaralhado.registros):
        assert r1.campos["matricula"].texto == r2.campos["matricula"].texto
        assert r1.campos["gestor"].texto == r2.campos["gestor"].texto

    # Testa também `ordenar_elementos` isoladamente: dado o cabeçalho
    # embaralhado, o resultado deve voltar para a ordem de leitura
    # (esquerda->direita dentro de cada linha). `ordenar_elementos` espera
    # `CampoOcr`, não `OCRResult` diretamente — por isso a conversão abaixo.
    cabecalho = [CampoOcr.de_ocr_result(r) for r in _linha_cabecalho()]
    cabecalho_embaralhado = cabecalho[:]
    random.Random(7).shuffle(cabecalho_embaralhado)
    ordenado = ordenar_elementos(cabecalho_embaralhado)
    textos_ordenados = [e.texto for e in ordenado]
    assert textos_ordenados == ["DATA", "HORA", "NOME", "MATRÍCULA", "SETOR", "MOTIVO", "RESPONSÁVEL"], textos_ordenados

    print("  OK: mesmo resultado independente da ordem de entrada")
    print("  OK: ordenar_elementos devolve ordem de leitura correta")
    print()


# ---------------------------------------------------------------------------
# Teste 3: pequenas variações de posição (linha "torta")
# ---------------------------------------------------------------------------

def teste_pequenas_variacoes_de_posicao():
    print("=== Teste 3: pequenas variações de posição (linha torta) ===")
    elementos = list(_linha_cabecalho())

    # Uma linha de dados com leve variação de y entre os elementos (como
    # aconteceria numa foto levemente torta), mas ainda claramente a MESMA
    # linha visualmente.
    y_base = 40
    elementos += [
        _r("23.04", COL_DATA - 15, y_base + 0, COL_DATA + 15, y_base + 20),
        _r("11:05", COL_HORA - 15, y_base + 2, COL_HORA + 15, y_base + 22),
        _r("Fulano", COL_NOME - 25, y_base - 3, COL_NOME + 25, y_base + 17),
        _r("28972", COL_MATRICULA - 20, y_base + 4, COL_MATRICULA + 20, y_base + 24),
        _r("TI", COL_SETOR - 20, y_base - 1, COL_SETOR + 20, y_base + 19),
        _r("RH", COL_MOTIVO - 25, y_base + 1, COL_MOTIVO + 25, y_base + 21),
        _r("Gestor X", COL_GESTOR - 30, y_base + 3, COL_GESTOR + 30, y_base + 23),
    ]

    # Segunda linha, claramente separada (mais abaixo) — não deve se
    # misturar com a primeira mesmo com a variação acima.
    y_base2 = 80
    elementos += _linha_registro(
        y_base2, y_base2 + 20,
        data="23.04", hora="11:10", nome="Beltrano", matricula="27331",
        setor="RH", motivo="ADM", gestor="Gestor Y",
    )

    resultado = parse_registros(elementos)
    assert resultado.cabecalho_detectado
    assert len(resultado.registros) == 2, f"Esperava 2 registros, veio {len(resultado.registros)}"

    r1, r2 = resultado.registros
    assert r1.completo and r2.completo
    assert r1.campos["matricula"].texto == "28972"
    assert r2.campos["matricula"].texto == "27331"
    # Garante que a variação de posição não fez elementos de uma linha
    # vazarem para os campos da outra.
    assert r1.campos["gestor"].texto == "Gestor X"
    assert r2.campos["gestor"].texto == "Gestor Y"

    print("  OK: linha com variação de poucos pixels continua sendo agrupada como 1 única linha")
    print("  OK: linhas claramente separadas continuam separadas")
    print()


# ---------------------------------------------------------------------------
# Teste 4: registro incompleto
# ---------------------------------------------------------------------------

def teste_registro_incompleto():
    print("=== Teste 4: registro incompleto (faltando matrícula) ===")
    elementos = list(_linha_cabecalho())

    # Registro 1: completo
    elementos += _linha_registro(
        40, 60, data="23.04", hora="11:05", nome="Fulano", matricula="28972",
        setor="TI", motivo="RH", gestor="Gestor X",
    )
    # Registro 2: SEM matrícula (o auxiliar não conseguiu ler / OCR falhou
    # totalmente naquele campo — nem chegou a existir um box para ele).
    y1, y2 = 70, 90
    elementos += [
        _r("23.04", COL_DATA - 15, y1, COL_DATA + 15, y2),
        _r("11:08", COL_HORA - 15, y1, COL_HORA + 15, y2),
        # (sem NOME também, propositalmente, pra testar múltiplos faltando)
        _r("RH", COL_SETOR - 20, y1, COL_SETOR + 20, y2),
        _r("ADM", COL_MOTIVO - 25, y1, COL_MOTIVO + 25, y2),
        _r("Gestor Y", COL_GESTOR - 30, y1, COL_GESTOR + 30, y2),
    ]

    resultado = parse_registros(elementos)
    assert len(resultado.registros) == 2

    completo, incompleto = resultado.registros
    assert completo.completo
    assert not incompleto.completo, "Registro sem matrícula deveria estar incompleto"
    faltando = incompleto.campos_faltando()
    assert "matricula" in faltando
    # "nome" não é mais um campo rastreado (é derivado da matrícula, não
    # reconhecido por OCR) -- por isso não aparece em campos_faltando().
    assert "nome" not in faltando
    assert "gestor" not in faltando  # esse campo, no exemplo, foi identificado

    print(f"  Registro 2 incompleto, faltando: {faltando}")
    print("  OK")
    print()


# ---------------------------------------------------------------------------
# Teste 5: quantidade de registros diferente de 8
# ---------------------------------------------------------------------------

def teste_quantidade_diferente_de_oito():
    print("=== Teste 5: quantidade de registros diferente de 8 ===")
    for quantidade in (1, 3, 5, 11, 14):
        elementos = _pagina_normal(n_registros=quantidade)
        resultado = parse_registros(elementos)
        assert len(resultado.registros) == quantidade, (
            f"Com {quantidade} registros na fixture, o parser encontrou {len(resultado.registros)}"
        )
        assert all(r.completo for r in resultado.registros)
        print(f"  {quantidade} registro(s) na fixture -> {len(resultado.registros)} encontrado(s): OK")
    print()


# ---------------------------------------------------------------------------
# Teste 6: textos irrelevantes entre/antes dos registros
# ---------------------------------------------------------------------------

def teste_textos_irrelevantes():
    print("=== Teste 6: textos irrelevantes (título antes do cabeçalho + texto solto entre registros) ===")
    elementos = []

    # Título/informação impressa ACIMA do cabeçalho — não é um registro.
    elementos.append(_r("Controle de Uso do Cartão Mestre", 200, -40, 500, -20))
    elementos.append(_r("Filial: Caruaru", 60, -15, 220, -1))

    elementos += _linha_cabecalho()

    # Registro 1 normal
    elementos += _linha_registro(
        40, 60, data="23.04", hora="11:05", nome="Fulano", matricula="28972",
        setor="TI", motivo="RH", gestor="Gestor X",
    )

    # Texto solto ENTRE os registros, longe de qualquer coluna conhecida
    # (ex.: uma rubrica ou marca d'água) — não deve ser confundido com
    # nenhum campo de verdade.
    elementos.append(_r("xxxxx", 1050, 65, 1090, 78))

    # Registro 2 normal
    elementos += _linha_registro(
        90, 110, data="23.04", hora="11:10", nome="Beltrano", matricula="27331",
        setor="RH", motivo="ADM", gestor="Gestor Y",
    )

    resultado = parse_registros(elementos)

    assert resultado.cabecalho_detectado
    # O título/filial (2 elementos, na mesma linha ou não) deve aparecer em
    # conteudo_antes_cabecalho, não como registro.
    textos_antes = {e.texto for e in resultado.conteudo_antes_cabecalho}
    assert "Controle de Uso do Cartão Mestre" in textos_antes
    assert "Filial: Caruaru" in textos_antes

    # PROBLEMA 1 (Fase 1 de precisão): uma linha sem NENHUM campo associado
    # a nenhuma coluna conhecida (o texto solto "xxxxx", longe de qualquer
    # coluna) não vira mais um Registro fantasma -- vai para
    # `linhas_ignoradas`, preservado para auditoria, mas fora da lista de
    # liberações. Só os 2 registros de verdade aparecem em `registros`.
    assert len(resultado.registros) == 2, f"Esperava 2 registros reais, veio {len(resultado.registros)}"

    r1, r2 = resultado.registros
    assert r1.completo and r1.campos["matricula"].texto == "28972"
    assert r2.completo and r2.campos["matricula"].texto == "27331"

    # O texto solto deve estar preservado em linhas_ignoradas (nunca
    # descartado em silêncio), não em registros nem em nenhuma coluna.
    textos_ignorados = {e.texto for linha in resultado.linhas_ignoradas for e in linha}
    assert "xxxxx" in textos_ignorados, textos_ignorados

    print("  OK: título antes do cabeçalho não vira registro")
    print("  OK: texto solto entre registros não vira registro fantasma (vai para linhas_ignoradas)")
    print("  OK: registros 1 e 2 continuam corretos, sem contaminação do texto solto")
    print()


# ---------------------------------------------------------------------------
# Teste 7: sem cabeçalho identificável (fallback seguro)
# ---------------------------------------------------------------------------

def teste_sem_cabecalho():
    print("=== Teste 7: nenhum cabeçalho identificável (fallback) ===")
    # Só linhas de dado, sem nenhuma linha de rótulos DATA/HORA/... —
    # simula um recorte de imagem que não capturou o cabeçalho da tabela.
    elementos = _linha_registro(
        40, 60, data="23.04", hora="11:05", nome="Fulano", matricula="28972",
        setor="TI", motivo="RH", gestor="Gestor X",
    )

    resultado = parse_registros(elementos)
    assert not resultado.cabecalho_detectado
    assert resultado.colunas_detectadas == {}
    assert len(resultado.registros) == 1

    registro = resultado.registros[0]
    # Sem cabeçalho, o parser NÃO deve adivinhar quais elementos são quais
    # campos — tudo fica em não_associados, e o registro fica incompleto.
    assert registro.campos == {}
    assert not registro.completo
    assert len(registro.nao_associados) == 7
    # Mas nada foi perdido: os 7 textos originais continuam preservados.
    textos = {e.texto for e in registro.nao_associados}
    assert textos == {"23.04", "11:05", "Fulano", "28972", "TI", "RH", "Gestor X"}

    print("  OK: sem cabeçalho, elementos ficam em não_associados (nada é inventado)")
    print("  OK: todos os textos originais continuam preservados")
    print()


# ---------------------------------------------------------------------------
# Teste 8: elementos sem box (posição desconhecida) não travam o parser
# ---------------------------------------------------------------------------

def teste_elementos_sem_box():
    print("=== Teste 8: elementos sem bounding box ===")
    elementos = _pagina_normal(n_registros=2)
    elementos.append(OCRResult(texto_original="???", confianca=0.3, box=None))

    resultado = parse_registros(elementos)
    assert len(resultado.registros) == 2  # o elemento sem box não virou registro nem quebrou nada
    assert len(resultado.elementos_sem_posicao) == 1
    assert resultado.elementos_sem_posicao[0].texto == "???"

    print("  OK: elemento sem box não trava o parser e fica separado em elementos_sem_posicao")
    print()


# ---------------------------------------------------------------------------
# Teste 9: preservação de texto/confiança/box (nada é normalizado aqui)
# ---------------------------------------------------------------------------

def teste_preservacao_de_dados():
    print("=== Teste 9: preservação do texto original, confiança e box ===")
    elementos = list(_linha_cabecalho())
    elementos += [
        _r("3O244", COL_DATA - 15, 40, COL_DATA + 15, 60, confianca=0.5123),  # propositalmente "errado", em qualquer coluna
        _r("11:05", COL_HORA - 15, 40, COL_HORA + 15, 60, confianca=0.999),
        _r("Costa", COL_NOME - 25, 40, COL_NOME + 25, 60, confianca=0.61),
        _r("3O244", COL_MATRICULA - 20, 40, COL_MATRICULA + 20, 60, confianca=0.9123),
        _r("TI", COL_SETOR - 20, 40, COL_SETOR + 20, 60, confianca=0.8),
        _r("RH", COL_MOTIVO - 25, 40, COL_MOTIVO + 25, 60, confianca=0.95),
        _r("Gestor X", COL_GESTOR - 30, 40, COL_GESTOR + 30, 60, confianca=0.7),
    ]

    resultado = parse_registros(elementos)
    registro = resultado.registros[0]

    campo_matricula = registro.campos["matricula"]
    # O texto NÃO deve ter sido normalizado (continua "3O244", não "30244")
    assert campo_matricula.texto == "3O244", campo_matricula.texto
    assert campo_matricula.confianca == 0.9123
    assert campo_matricula.box == [430, 40, 470, 60]

    # "nome" não é mais um campo reconhecido (é derivado da matrícula) --
    # o texto "Costa" continua preservado, só que em nao_associados, não
    # como campos["nome"].
    assert "nome" not in registro.campos
    textos_nao_associados = {e.texto for e in registro.nao_associados}
    assert "Costa" in textos_nao_associados, textos_nao_associados

    print("  OK: texto original preservado sem normalização (ex.: '3O244' continua '3O244')")
    print("  OK: confiança e box preservados exatamente como no OCRResult de entrada")
    print("  OK: 'nome' não é reconhecido como campo -- texto preservado em não_associados")
    print()


# ---------------------------------------------------------------------------
# Teste 10: linhas com células altas e espaçamento vertical apertado
# (agrupamento não pode "encadear" linhas distintas pela faixa acumulada)
# ---------------------------------------------------------------------------

def teste_linhas_altas_com_espacamento_apertado():
    """
    Achado real (entrada/pdf/teste.pdf, página 3): quando os boxes de OCR
    de uma linha são mais altos que o espaçamento vertical entre linhas
    (letra grande/manuscrita, ou -- como na folha real -- um box que juntou
    DATA+HORA+NOME numa única caixa), o agrupamento original podia
    "encadear" e colapsar várias linhas reais numa só: um elemento alto da
    linha 1 fazia a faixa acumulada crescer o bastante para engolir
    elementos da linha 2, mesmo sem nenhuma sobreposição direta entre os
    elementos de abertura das duas linhas.

    Reproduz isso sinteticamente: 3 linhas cujas células de DATA têm 45px
    de altura (uma célula "alta"), mas cujas linhas estão espaçadas por só
    30px de y1 -- exatamente o padrão da folha real (células mais altas que
    o espaçamento entre linhas).
    """
    print("=== Teste 10: linhas altas com espaçamento apertado (não pode encadear) ===")
    elementos = list(_linha_cabecalho())

    for i, (matricula, gestor) in enumerate([("28001", "Gestor A"), ("28002", "Gestor B"), ("28003", "Gestor C")]):
        y1 = 40 + i * 30  # linhas espaçadas por só 30px de y1...
        elementos += [
            _r(f"23.0{i}", COL_DATA - 15, y1, COL_DATA + 15, y1 + 45),  # ...mas células de 45px de altura
            _r("11:05", COL_HORA - 15, y1 + 5, COL_HORA + 15, y1 + 40),
            _r(matricula, COL_MATRICULA - 20, y1 + 8, COL_MATRICULA + 20, y1 + 42),
            _r("TI", COL_SETOR - 20, y1 + 3, COL_SETOR + 20, y1 + 38),
            _r("RH", COL_MOTIVO - 25, y1 + 6, COL_MOTIVO + 25, y1 + 41),
            _r(gestor, COL_GESTOR - 30, y1 + 4, COL_GESTOR + 30, y1 + 39),
        ]

    resultado = parse_registros(elementos)
    assert len(resultado.registros) == 3, (
        f"3 linhas reais deveriam continuar 3 registros (não colapsar numa só); veio {len(resultado.registros)}: "
        f"{[list(r.campos.keys()) for r in resultado.registros]}"
    )
    matriculas = {r.campos["matricula"].texto for r in resultado.registros if "matricula" in r.campos}
    assert matriculas == {"28001", "28002", "28003"}, matriculas
    for r in resultado.registros:
        assert r.completo, f"Registro {r.indice} deveria ter matrícula: {r.campos}"

    print("  OK: 3 linhas reais com células altas e espaçamento apertado continuam 3 registros distintos")
    print("  OK: nenhuma matrícula se perdeu (28001, 28002, 28003 todas presentes)")
    print()


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    testes = [
        teste_pagina_normal,
        teste_ordenacao_e_fora_de_ordem,
        teste_pequenas_variacoes_de_posicao,
        teste_registro_incompleto,
        teste_quantidade_diferente_de_oito,
        teste_textos_irrelevantes,
        teste_sem_cabecalho,
        teste_elementos_sem_box,
        teste_preservacao_de_dados,
        teste_linhas_altas_com_espacamento_apertado,
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
