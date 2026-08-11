"""
teste/teste_normalizacao_ocr.py

Casos REAIS de erro recorrente do OCR observados nas folhas, virados em
teste de regressão: DATA (separadores/colagem), MATRÍCULA ("+" que é 7),
GESTOR (código com ruído de auxiliar) e MOTIVO ("H. NEGADO").

Não usa PaddleOCR nem as planilhas reais: as bases são fixtures
sintéticas, com o mesmo FORMATO das reais (matrículas só dígitos,
gestores com código nu + forma completa, motivos incluindo pares
propositalmente parecidos como NEGADO/NEGADA/H. NEGADO).

Uso:
    python teste\\teste_normalizacao_ocr.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.parsing.tempo_parser import interpretar_data, normalizar_data  # noqa: E402
from leitor_matriculas.validacao.recuperacao_matricula import resolver_matricula  # noqa: E402
from leitor_matriculas.validacao.correspondencia_aproximada import (  # noqa: E402
    buscar_correspondencia,
    resolver_responsavel,
)

# Bases sintéticas com o MESMO formato das reais.
GESTORES = ["GR1", "GR3", "GR4", "GR5", "GRL",
            "GR3 - BEATRIZ", "GR4 - RENATO GUIMARÃES", "GR5 - OTAVIO", "GRL - LUCIA",
            "MARTIM", "TAMIRES", "MARCELO TORRES", "MARCELO SOUZA"]
MOTIVOS = ["Horário negado", "RH", "ADM", "Armários", "Folga fixa",
           "Esquecimento de crachá", "TREINAMENTO", "NEGADA", "NEGADO", "H. NEGADO"]
# "19547" existe e "19544" não -> é isso que autoriza o "+"->7 em "1954+".
COLABORADORES = {"19547", "30874", "19160", "21491", "28972", "18899"}


def _existe(m):
    return m in COLABORADORES


falhas = []


def checar(cond, msg):
    print(("  OK    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------------------
# 1. DATA -> dd/mm/aa
# ---------------------------------------------------------------------------

def teste_data_normaliza_para_dd_mm_aa():
    print("=== DATA: variações reais normalizadas para dd/mm/aa ===")
    for bruto in ["14.04.26", "14-04-26", "14.04:26", "14.04 -26", "14/04/26", "14.04.2026"]:
        checar(normalizar_data(bruto) == "14/04/26", f"{bruto!r} -> '14/04/26' (obtido: {normalizar_data(bruto)!r})")
    checar(normalizar_data("23.0426") == "23/04/26",
           f"'23.0426' (separador mês/ano perdido) -> '23/04/26' (obtido: {normalizar_data('23.0426')!r})")
    checar(normalizar_data("23.042026") == "23/04/26", "'23.042026' (ano de 4 dígitos colado) -> '23/04/26'")
    print()


def teste_data_sem_ano_continua_recusada():
    print("=== DATA: sem ano continua REVISAO (nunca inventa o ano) ===")
    checar(normalizar_data("23.04") is None, "'23.04' -> None (não inventa o ano)")
    checar(normalizar_data("23-04") is None, "'23-04' -> None")
    checar(interpretar_data("23.04") is None, "interpretar_data('23.04') -> None")
    print()


def teste_data_impossivel_continua_recusada():
    print("=== DATA: calendário inválido continua recusado, mesmo com separador novo ===")
    checar(normalizar_data("31.04:26") is None, "'31.04:26' (31 de abril) -> None")
    checar(normalizar_data("14.13:26") is None, "'14.13:26' (mês 13) -> None")
    checar(normalizar_data("23.9926") is None, "'23.9926' (mês 99 colado) -> None")
    checar(normalizar_data("qualquer coisa") is None, "texto livre -> None")
    print()


# ---------------------------------------------------------------------------
# 2. MATRÍCULA
# ---------------------------------------------------------------------------

def teste_matricula_recupera_mais_como_sete():
    print("=== MATRÍCULA: '+' recuperado como 7 com evidência na base ===")
    r = resolver_matricula("1954+", _existe)
    checar(r.matricula == "19547", f"'1954+' -> '19547' (obtido: {r.matricula!r})")
    checar(r.status == "RECUPERADA", f"status RECUPERADA (obtido: {r.status})")
    checar(r.matricula.isdigit(), "resultado só com dígitos")

    r2 = resolver_matricula("308+4", _existe)
    checar(r2.matricula == "30874", f"'308+4' -> '30874' (obtido: {r2.matricula!r})")
    checar(r2.status == "RECUPERADA", f"status RECUPERADA (obtido: {r2.status})")
    print()


def teste_matricula_remove_ruido_de_separador():
    print("=== MATRÍCULA: ruído de traço/ponto removido ===")
    r = resolver_matricula("1.9160", _existe)
    checar(r.matricula == "19160", f"'1.9160' -> '19160' (obtido: {r.matricula!r})")
    checar(r.matricula.isdigit(), "resultado só com dígitos")
    r2 = resolver_matricula("19 160", _existe)
    checar(r2.matricula == "19160", f"'19 160' -> '19160' (obtido: {r2.matricula!r})")
    print()


def teste_matricula_nunca_deixa_caractere_nao_numerico():
    print("=== MATRÍCULA: saída nunca contém caractere não numérico ===")
    for bruto in ["1954+", "308+4", "1.9160", "19-160", "19547"]:
        r = resolver_matricula(bruto, _existe)
        checar(r.matricula.isdigit(), f"{bruto!r} -> {r.matricula!r} (só dígitos)")
    print()


def teste_matricula_ambigua_vai_para_revisao():
    print("=== MATRÍCULA: duas leituras existindo na base -> AMBIGUA (nunca escolhe) ===")
    # Base onde AS DUAS leituras de "+" existem: 19547 e 19544.
    ambos = {"19547", "19544"}
    r = resolver_matricula("1954+", lambda m: m in ambos)
    checar(r.status == "AMBIGUA", f"status AMBIGUA (obtido: {r.status})")
    checar(sorted(r.candidatos) == ["19544", "19547"], f"ambos os candidatos reportados: {r.candidatos}")
    print()


def teste_matricula_sem_correspondencia_nao_e_confirmada():
    print("=== MATRÍCULA: nenhuma leitura na base -> SEM_CORRESPONDENCIA (-> REVISAO) ===")
    r = resolver_matricula("1954+", lambda m: False)
    checar(r.status == "SEM_CORRESPONDENCIA", f"status SEM_CORRESPONDENCIA (obtido: {r.status})")
    checar(r.matricula.isdigit(), "ainda assim a saída é só dígitos (leitura preferida)")
    print()


def teste_matricula_vazia_nunca_e_inventada():
    print("=== MATRÍCULA: ausente nunca é inventada ===")
    for vazio in ["", "   ", None]:
        r = resolver_matricula(vazio, _existe)
        checar(r.status == "VAZIO" and r.matricula == "",
               f"{vazio!r} -> status VAZIO, matrícula '' (obtido: {r.status}/{r.matricula!r})")
    r = resolver_matricula("???", _existe)
    checar(r.status == "IRRECUPERAVEL" and r.matricula == "",
           f"'???' -> IRRECUPERAVEL, sem matrícula inventada (obtido: {r.status}/{r.matricula!r})")
    print()


# ---------------------------------------------------------------------------
# 3. GESTOR — código tem prioridade sobre o ruído do nome da auxiliar
# ---------------------------------------------------------------------------

def teste_gestor_codigo_tem_prioridade_sobre_ruido():
    print("=== GESTOR: código identificado apesar do ruído da auxiliar ===")
    for bruto in ["GR5 - Lorena", "GR5 - Eosee", "GR5 - Lorenne", "GR5- Lorena", "GR5 - XYZ"]:
        r = resolver_responsavel(bruto, GESTORES)
        checar(r.gestor_confirmado == "GR5 - OTAVIO",
               f"{bruto!r} -> 'GR5 - OTAVIO' (obtido: {r.gestor_confirmado!r}, status={r.status})")
    print()


def teste_gestor_usa_nome_oficial_da_base():
    print("=== GESTOR: nome oficial vem da base, nunca o da auxiliar ===")
    r = resolver_responsavel("GR3 - Loren", GESTORES)
    checar(r.gestor_confirmado == "GR3 - BEATRIZ",
           f"'GR3 - Loren' -> 'GR3 - BEATRIZ' (obtido: {r.gestor_confirmado!r})")
    checar("Loren" not in (r.gestor_confirmado or ""), "nome da auxiliar não contamina o gestor")
    r2 = resolver_responsavel("GRL - Coseeone", GESTORES)
    checar(r2.gestor_confirmado == "GRL - LUCIA",
           f"'GRL - Coseeone' -> 'GRL - LUCIA' (obtido: {r2.gestor_confirmado!r})")
    print()


def teste_gestor_ambiguo_continua_em_revisao():
    print("=== GESTOR: código sem expansão única não é chutado ===")
    # "MARCELO" tem DUAS expansões possíveis na base -> não expande.
    r = resolver_responsavel("MARCELO", GESTORES)
    checar(r.gestor_confirmado == "MARCELO" or r.status not in ("EXATA", "APROXIMADA"),
           f"'MARCELO' não vira TORRES nem SOUZA por chute (obtido: {r.gestor_confirmado!r})")
    r2 = resolver_responsavel("ZZZZZZ", GESTORES)
    checar(r2.gestor_confirmado is None, f"texto sem correspondência -> None (obtido: {r2.gestor_confirmado!r})")
    print()


# ---------------------------------------------------------------------------
# 4. MOTIVO — variações reais de "H. NEGADO"
# ---------------------------------------------------------------------------

def teste_motivo_h_negado_variacoes_reais():
    print("=== MOTIVO: variações reais de 'H. NEGADO' recuperadas ===")
    for bruto in ["Hiv. Nigado", "Hiv. vigado", "H.v. Nigado", "H.v. vegaco", "H.ve Negado"]:
        r = buscar_correspondencia(bruto, MOTIVOS)
        checar(r.valor_sugerido == "H. NEGADO" and r.status in ("EXATA", "APROXIMADA"),
               f"{bruto!r} -> 'H. NEGADO' (obtido: {r.valor_sugerido!r}, status={r.status})")
    print()


def teste_motivo_nao_vira_h_negado_indiscriminadamente():
    print("=== MOTIVO: texto sem relação NÃO vira 'H. NEGADO' ===")
    for bruto in ["TREINAMENTO", "Armários", "Folga fixa"]:
        r = buscar_correspondencia(bruto, MOTIVOS)
        checar(r.valor_sugerido != "H. NEGADO",
               f"{bruto!r} não vira 'H. NEGADO' (obtido: {r.valor_sugerido!r})")
    r = buscar_correspondencia("XPTO INEXISTENTE", MOTIVOS)
    checar(r.status in ("SEM_CORRESPONDENCIA", "AMBIGUA"),
           f"texto sem relação -> sem correspondência (obtido: {r.status})")
    print()


if __name__ == "__main__":
    for nome, funcao in list(globals().items()):
        if nome.startswith("teste_"):
            funcao()
    print("=" * 62)
    if not falhas:
        print("TODOS OS CASOS REAIS DE NORMALIZAÇÃO PASSARAM.")
    else:
        print(f"{len(falhas)} FALHA(S):")
        for f in falhas:
            print("   -", f)
        sys.exit(1)
