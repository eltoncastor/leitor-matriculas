"""
teste/teste_tempo_parser.py

Testes de tempo_parser.py: interpretação estruturada de data/hora, sempre
respeitando a regra de nunca inventar/corrigir um valor "provável".

Uso:
    python teste\\teste_tempo_parser.py
"""

import os
import sys
from datetime import date, datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.parsing.tempo_parser import (  # noqa: E402
    interpretar_data,
    interpretar_hora,
    interpretar_data_hora,
    validar_data,
    avaliar_hora_opcional,
)


def teste_data_formatos_validos():
    print("=== Teste 1: formatos de data válidos ===")
    assert interpretar_data("23/04/2026") == date(2026, 4, 23)
    assert interpretar_data("23.04.2026") == date(2026, 4, 23)
    assert interpretar_data("23-04-2026") == date(2026, 4, 23)
    assert interpretar_data("23/04/26") == date(2026, 4, 23)  # ano de 2 dígitos -> 20xx
    assert interpretar_data(" 05/01/2026 ") == date(2026, 1, 5)  # espaços nas pontas
    print("  OK")
    print()


def teste_data_sem_ano_nao_e_aceita():
    print("=== Teste 2: data sem ano nunca é aceita (nunca inventa o ano) ===")
    assert interpretar_data("23/04") is None
    assert interpretar_data("23.04") is None
    print("  OK")
    print()


def teste_data_impossivel():
    print("=== Teste 3: data impossível -> None ===")
    assert interpretar_data("31/04/2026") is None  # abril não tem dia 31
    assert interpretar_data("29/02/2027") is None  # 2027 não é bissexto
    assert interpretar_data("15/13/2026") is None  # mês 13 não existe
    assert interpretar_data("00/04/2026") is None  # dia 0 não existe
    print("  OK")
    print()


def teste_data_bissexto_valido():
    print("=== Teste 4: 29/02 em ano bissexto É válido (não é rejeitado por engano) ===")
    assert interpretar_data("29/02/2028") == date(2028, 2, 29)
    print("  OK")
    print()


def teste_data_formato_inesperado_ou_vazia():
    print("=== Teste 5: formato inesperado / vazio -> None ===")
    assert interpretar_data("") is None
    assert interpretar_data(None) is None
    assert interpretar_data("vinte e três de abril") is None
    assert interpretar_data("23/abril/2026") is None
    assert interpretar_data("23") is None
    print("  OK")
    print()


def teste_hora_formatos_validos():
    print("=== Teste 6: formatos de hora válidos ===")
    assert interpretar_hora("11:05") == time(11, 5)
    assert interpretar_hora("11.05") == time(11, 5)
    assert interpretar_hora("11h05") == time(11, 5)
    assert interpretar_hora("23:59:59") == time(23, 59, 59)
    assert interpretar_hora(" 08:00 ") == time(8, 0)
    print("  OK")
    print()


def teste_hora_impossivel_ou_invalida():
    print("=== Teste 7: hora impossível / inválida -> None ===")
    assert interpretar_hora("25:00") is None  # hora > 23
    assert interpretar_hora("11:60") is None  # minuto > 59
    assert interpretar_hora("") is None
    assert interpretar_hora(None) is None
    assert interpretar_hora("meio-dia") is None
    print("  OK")
    print()


def teste_interpretar_data_hora_combinado():
    print("=== Teste 8: interpretar_data_hora combina os dois, ou None se qualquer um falhar ===")
    assert interpretar_data_hora("23/04/2026", "11:05") == datetime(2026, 4, 23, 11, 5)
    assert interpretar_data_hora("23/04", "11:05") is None  # data inválida (sem ano)
    assert interpretar_data_hora("23/04/2026", "25:00") is None  # hora inválida
    assert interpretar_data_hora("", "") is None
    print("  OK")
    print()


def teste_validar_data_e_bloqueante():
    print("=== Teste 9: validar_data (DATA é obrigatória -> bloqueia) ===")
    assert validar_data("23/04/2026") is None  # válida -> sem observação

    msg_vazia = validar_data("")
    assert msg_vazia and "data" in msg_vazia.lower()

    msg_none = validar_data(None)
    assert msg_none and "data" in msg_none.lower()

    msg_impossivel = validar_data("31/04/2026")
    assert msg_impossivel is not None

    msg_sem_ano = validar_data("23/04")
    assert msg_sem_ano is not None

    msg_formato = validar_data("qualquer coisa")
    assert msg_formato is not None

    print("  OK: data ausente/impossível/sem ano/ilegível sempre devolve mensagem")
    print()


def teste_avaliar_hora_opcional_nunca_bloqueia():
    print("=== Teste 10: avaliar_hora_opcional (HORA é opcional -> nunca bloqueia) ===")
    # Hora AUSENTE é situação aceitável: nada a observar.
    assert avaliar_hora_opcional("") is None
    assert avaliar_hora_opcional(None) is None
    assert avaliar_hora_opcional("   ") is None

    # Hora VÁLIDA: nada a observar.
    assert avaliar_hora_opcional("11:05") is None
    assert avaliar_hora_opcional("11h05") is None

    # Hora PRESENTE mas ilegível/impossível: devolve AVISO (não erro), e o
    # aviso precisa carregar o texto bruto do OCR para auditoria.
    aviso_impossivel = avaliar_hora_opcional("25:99")
    assert aviso_impossivel and "25:99" in aviso_impossivel

    aviso_ilegivel = avaliar_hora_opcional("ilegivel")
    assert aviso_ilegivel and "ilegivel" in aviso_ilegivel

    print("  OK: ausente/válida -> sem aviso; presente e ilegível -> aviso com o texto bruto")
    print()


def teste_interpretar_data_hora_compara_datetime_real_nao_texto():
    print("=== Teste 11: interpretar_data_hora compara datetime real, não string ===")
    # Comparação lexicográfica de "9/1/2026" vs "10/1/2026" erraria (texto
    # "10..." < "9..."); com datetime real, 9 de janeiro vem antes.
    # NOTA: a planilha NÃO é mais ordenada cronologicamente (preserva a
    # ordem física da folha). Este teste cobre só a semântica da função.
    d1 = interpretar_data_hora("09/01/2026", "10:00")
    d2 = interpretar_data_hora("10/01/2026", "08:00")
    assert d1 < d2
    print("  OK: 09/01/2026 < 10/01/2026 mesmo com comparação de string enganosa")
    print()


if __name__ == "__main__":
    testes = [
        teste_data_formatos_validos,
        teste_data_sem_ano_nao_e_aceita,
        teste_data_impossivel,
        teste_data_bissexto_valido,
        teste_data_formato_inesperado_ou_vazia,
        teste_hora_formatos_validos,
        teste_hora_impossivel_ou_invalida,
        teste_interpretar_data_hora_combinado,
        teste_validar_data_e_bloqueante,
        teste_avaliar_hora_opcional_nunca_bloqueia,
        teste_interpretar_data_hora_compara_datetime_real_nao_texto,
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
