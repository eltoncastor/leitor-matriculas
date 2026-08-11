"""
teste/teste_extracao_fase1.py

Testes da Fase 1 de precisão da extração das 8 liberações por folha:
    PROBLEMA 1 — texto impresso não pode virar registro/dado;
    PROBLEMA 2 — 8 posições esperadas, como restrição de validação;
    PROBLEMA 5 — separação de DATA+HORA mescladas numa única caixa de OCR.

(PROBLEMAS 3/4 — fuzzy matching de motivo/responsável — têm teste dedicado
em teste_correspondencia_aproximada.py.)

Fixtures sintéticas, sem dependência de OCR real.

Uso:
    python teste\\teste_extracao_fase1.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.ocr.engine import OCRResult  # noqa: E402
from leitor_matriculas.parsing.registro_parser import (  # noqa: E402
    CampoOcr,
    POSICOES_ESPERADAS_POR_FOLHA,
    parse_registros,
    verificar_contagem_posicoes,
)
from leitor_matriculas.parsing.tempo_parser import tentar_separar_data_hora_mesclada  # noqa: E402
from leitor_matriculas.ui.app import _reparar_data_hora_mescladas  # noqa: E402


def _r(texto, x1, y1, x2, y2, confianca=0.9):
    return OCRResult(texto_original=texto, confianca=confianca, box=[x1, y1, x2, y2])


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
        _r("RESPONSÁVEL PELA AUTORIZAÇÃO", COL_GESTOR - 40, y1, COL_GESTOR + 40, y2),
    ]


def _linha_registro(y1, y2, data, hora, nome, matricula, setor, motivo, gestor):
    return [
        _r(data, COL_DATA - 15, y1, COL_DATA + 15, y2),
        _r(hora, COL_HORA - 15, y1, COL_HORA + 15, y2),
        _r(nome, COL_NOME - 25, y1, COL_NOME + 25, y2),
        _r(matricula, COL_MATRICULA - 20, y1, COL_MATRICULA + 20, y2),
        _r(setor, COL_SETOR - 20, y1, COL_SETOR + 20, y2),
        _r(motivo, COL_MOTIVO - 25, y1, COL_MOTIVO + 25, y2),
        _r(gestor, COL_GESTOR - 30, y1, COL_GESTOR + 30, y2),
    ]


# ---------------------------------------------------------------------------
# PROBLEMA 1 — texto impresso não pode virar registro
# ---------------------------------------------------------------------------

def teste_rodape_impresso_nao_vira_registro():
    """
    Reproduz o achado real em teste.jpg: linhas de rodapé impressas
    ("Supervisor de Prevenção de Perdas", código do formulário) caindo
    espacialmente perto das colunas DATA/HORA da tabela.
    """
    elementos = list(_linha_cabecalho())
    elementos += _linha_registro(
        40, 60, data="14.04.26", hora="18:23", nome="Fulano", matricula="18899",
        setor="TI", motivo="RH", gestor="Gestor X",
    )
    # Rodapé impresso, bem abaixo da tabela: um texto longo cai perto da
    # coluna DATA, outro perto da coluna HORA -- nenhum dos dois "tem cara"
    # de data/hora (sem dígitos em estrutura de data/hora).
    elementos.append(_r("Supervisor de Prevenção de Perdas", COL_DATA - 300, 500, COL_DATA + 300, 540))
    elementos.append(_r("FOR.PRP.0017", COL_HORA - 80, 600, COL_HORA + 80, 640))

    resultado = parse_registros(elementos)

    assert len(resultado.registros) == 1, (
        f"Texto impresso do rodapé não deveria virar registro; veio {len(resultado.registros)}"
    )
    assert resultado.registros[0].campos["matricula"].texto == "18899"

    textos_ignorados = {e.texto for linha in resultado.linhas_ignoradas for e in linha}
    assert "Supervisor de Prevenção de Perdas" in textos_ignorados
    assert "FOR.PRP.0017" in textos_ignorados
    print("OK: texto impresso de rodapé (sem cara de data/hora) não vira registro -- preservado em linhas_ignoradas")


def teste_rodape_no_campo_livre_gestor_nao_vira_registro():
    """
    Achado real em teste.jpg: um fragmento de rodapé impresso ("Última
    Revisão:") caiu, por coincidência de posição, dentro da coluna
    RESPONSÁVEL (texto livre, sem filtro de formato como data/hora têm) --
    virava uma 9ª "liberação" fantasma mesmo já existindo 8 reais. Uma
    linha cujo ÚNICO campo associado é motivo/gestor (nenhum campo
    estruturado -- matrícula/data/hora) não deve virar Registro.
    """
    elementos = list(_linha_cabecalho())
    for i in range(8):
        y1 = 40 + i * 30
        elementos += _linha_registro(
            y1, y1 + 20, data="14.04.26", hora=f"1{i}:00", nome="X",
            matricula=f"1000{i}", setor="TI", motivo="RH", gestor="Gestor X",
        )
    # Rodapé bem abaixo das 8 linhas reais: só cai perto da coluna GESTOR,
    # nenhum outro campo por perto -- sem nenhuma "cara" de data/hora/
    # matrícula, e sem filtro de formato pra barrar (motivo/gestor são
    # texto livre).
    elementos.append(_r("Última Revisão:", COL_GESTOR - 60, 500, COL_GESTOR + 60, 520))

    resultado = parse_registros(elementos)

    assert len(resultado.registros) == 8, (
        f"Rodapé no campo GESTOR não deveria virar uma 9ª liberação; veio {len(resultado.registros)}"
    )
    textos_ignorados = {e.texto for linha in resultado.linhas_ignoradas for e in linha}
    assert "Última Revisão:" in textos_ignorados
    print("OK: rodapé caindo só na coluna GESTOR (sem campo estruturado) não vira 9ª liberação fantasma")


def teste_texto_com_digitos_mas_sem_separador_nao_passa_no_filtro():
    """Um código como 'FOR.PRP.0017' tem dígitos, mas não tem a ESTRUTURA
    dígito-separador-dígito de data/hora -- não deve ser aceito na coluna
    DATA nem HORA mesmo que cheguem perto o suficiente."""
    elementos = list(_linha_cabecalho())
    elementos.append(_r("FOR.PRP.0017", COL_DATA - 10, 40, COL_DATA + 200, 70))
    resultado = parse_registros(elementos)
    # Sem outro conteúdo na linha, e sem passar no filtro de formato, a
    # linha fica sem nenhum campo associado -> vai para linhas_ignoradas.
    assert len(resultado.registros) == 0
    textos_ignorados = {e.texto for linha in resultado.linhas_ignoradas for e in linha}
    assert "FOR.PRP.0017" in textos_ignorados
    print("OK: 'FOR.PRP.0017' (dígitos sem separador de data/hora) não é aceito na coluna DATA")


# ---------------------------------------------------------------------------
# PROBLEMA 2 — 8 posições esperadas, restrição de validação
# ---------------------------------------------------------------------------

def teste_contagem_igual_ao_esperado():
    assert verificar_contagem_posicoes(POSICOES_ESPERADAS_POR_FOLHA) is None
    print("OK: 8 posições encontradas -> nenhum aviso")


def teste_contagem_menor_que_esperado():
    aviso = verificar_contagem_posicoes(6)
    assert aviso is not None and "8" in aviso and "6" in aviso, aviso
    print(f"OK: 6 < 8 -> aviso claro: {aviso!r}")


def teste_contagem_maior_que_esperado():
    aviso = verificar_contagem_posicoes(9)
    assert aviso is not None and "9" in aviso, aviso
    print(f"OK: 9 > 8 -> aviso claro: {aviso!r}")


def teste_contagem_nao_fabrica_nem_descarta_registro():
    """Com só 6 posições de verdade na página, o parser devolve 6 registros
    -- nunca 8 (nunca fabrica uma posição vazia para completar)."""
    elementos = list(_linha_cabecalho())
    for i in range(6):
        y1 = 40 + i * 30
        elementos += _linha_registro(
            y1, y1 + 20, data="14.04.26", hora=f"1{i}:00", nome="X",
            matricula=f"1000{i}", setor="TI", motivo="RH", gestor="Gestor X",
        )
    resultado = parse_registros(elementos)
    assert len(resultado.registros) == 6
    aviso = verificar_contagem_posicoes(len(resultado.registros))
    assert aviso is not None and "6" in aviso
    print("OK: com 6 posições reais, o sistema informa 6 (nunca fabrica as outras 2)")


def teste_registro_ilegivel_nao_fabrica_liberacao():
    """Uma linha ilegível (nenhum campo reconhecível) não vira uma 9ª
    liberação fantasma quando já existem 8 reais -- fica fora de
    `registros`, preservada para auditoria."""
    elementos = list(_linha_cabecalho())
    for i in range(8):
        y1 = 40 + i * 30
        elementos += _linha_registro(
            y1, y1 + 20, data="14.04.26", hora=f"1{i}:00", nome="X",
            matricula=f"1000{i}", setor="TI", motivo="RH", gestor="Gestor X",
        )
    # 9ª linha, mas sem nenhum elemento em cara de campo nenhum (ex.: uma
    # mancha/rubrica ilegível bem longe de qualquer coluna).
    elementos.append(_r("###", 2000, 300, 2050, 320))
    resultado = parse_registros(elementos)
    assert len(resultado.registros) == 8, f"Não deveria fabricar uma 9ª liberação; veio {len(resultado.registros)}"
    textos_ignorados = {e.texto for linha in resultado.linhas_ignoradas for e in linha}
    assert "###" in textos_ignorados
    print("OK: posição ilegível não gera uma liberação fantasma além das 8 reais")


# ---------------------------------------------------------------------------
# PROBLEMA 5 — DATA + HORA mescladas numa única caixa de OCR
# ---------------------------------------------------------------------------

def teste_separar_data_hora_mescladas_caso_real():
    # Caso real observado em teste.jpg.
    resultado = tentar_separar_data_hora_mesclada("14.04 26 20:24")
    assert resultado == ("14.04.26", "20:24"), resultado
    print("OK: '14.04 26 20:24' -> data='14.04.26', hora='20:24'")


def teste_separar_data_hora_mesclagem_invalida_nao_inventa():
    # "35.13 26" não é um dia/mês possível -- não deve aceitar a separação.
    resultado = tentar_separar_data_hora_mesclada("35.13 26 20:24")
    assert resultado is None, resultado
    print("OK: mesclagem com data impossível (35/13) -> None, não inventa")


def teste_separar_data_hora_sem_hora_no_texto():
    resultado = tentar_separar_data_hora_mesclada("14.04.26")
    assert resultado is None
    print("OK: texto só com data (sem hora nenhuma) -> None, não inventa hora")


def teste_separar_data_hora_texto_vazio():
    assert tentar_separar_data_hora_mesclada("") is None
    assert tentar_separar_data_hora_mesclada(None) is None
    print("OK: texto vazio/None -> None, comportamento seguro")


def teste_reparo_no_registro_preenche_data_e_hora():
    """Integração: um Registro com 'data' contendo o texto mesclado e SEM
    'hora' -- após _reparar_data_hora_mescladas (ui.py), os dois campos
    ficam corretos e o texto mesclado original continua auditável."""
    elementos = list(_linha_cabecalho())
    elementos += [
        _r("14.04 26 20:24", COL_DATA - 15, 40, COL_DATA + 60, 60),  # cai perto da coluna DATA
        _r("Fulano", COL_NOME - 25, 40, COL_NOME + 25, 60),
        _r("29306", COL_MATRICULA - 20, 40, COL_MATRICULA + 20, 60),
        _r("TI", COL_SETOR - 20, 40, COL_SETOR + 20, 60),
        _r("Negada", COL_MOTIVO - 25, 40, COL_MOTIVO + 25, 60),
        _r("Gestor X", COL_GESTOR - 30, 40, COL_GESTOR + 30, 60),
    ]
    resultado = parse_registros(elementos)
    assert len(resultado.registros) == 1
    registro = resultado.registros[0]
    assert "data" in registro.campos and "hora" not in registro.campos  # antes do reparo

    _reparar_data_hora_mescladas(resultado.registros)

    assert registro.campos["data"].texto == "14.04.26", registro.campos["data"].texto
    assert registro.campos["hora"].texto == "20:24", registro.campos["hora"].texto
    # O texto mesclado original continua acessível para auditoria.
    textos_nao_associados = " ".join(e.texto for e in registro.nao_associados)
    assert "14.04 26 20:24" in textos_nao_associados
    print("OK: reparo de mesclagem preenche data/hora corretamente e preserva o texto original mesclado")


def teste_reparo_nao_mexe_quando_ja_estao_separadas():
    elementos = list(_linha_cabecalho())
    elementos += _linha_registro(
        40, 60, data="14.04.26", hora="20:24", nome="Fulano", matricula="29306",
        setor="TI", motivo="Negada", gestor="Gestor X",
    )
    resultado = parse_registros(elementos)
    registro = resultado.registros[0]
    data_antes, hora_antes = registro.campos["data"].texto, registro.campos["hora"].texto
    _reparar_data_hora_mescladas(resultado.registros)
    assert registro.campos["data"].texto == data_antes
    assert registro.campos["hora"].texto == hora_antes
    print("OK: quando data e hora já estão corretas e separadas, o reparo não altera nada")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    testes = [
        teste_rodape_impresso_nao_vira_registro,
        teste_rodape_no_campo_livre_gestor_nao_vira_registro,
        teste_texto_com_digitos_mas_sem_separador_nao_passa_no_filtro,
        teste_contagem_igual_ao_esperado,
        teste_contagem_menor_que_esperado,
        teste_contagem_maior_que_esperado,
        teste_contagem_nao_fabrica_nem_descarta_registro,
        teste_registro_ilegivel_nao_fabrica_liberacao,
        teste_separar_data_hora_mescladas_caso_real,
        teste_separar_data_hora_mesclagem_invalida_nao_inventa,
        teste_separar_data_hora_sem_hora_no_texto,
        teste_separar_data_hora_texto_vazio,
        teste_reparo_no_registro_preenche_data_e_hora,
        teste_reparo_nao_mexe_quando_ja_estao_separadas,
    ]
    falhas = 0
    for t in testes:
        try:
            t()
        except AssertionError as exc:
            falhas += 1
            print(f"FALHOU: {t.__name__}: {exc}")
    print("=" * 60)
    if falhas == 0:
        print(f"TODOS OS {len(testes)} TESTES PASSARAM.")
    else:
        print(f"{len(testes) - falhas}/{len(testes)} passaram")
        sys.exit(1)
