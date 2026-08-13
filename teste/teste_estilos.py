"""
teste/teste_estilos.py

Sub-fase 21c: testa o vocabulário de status de `ui/estilos.py` -- ícone,
texto e cor semântica de CONFIRMADO/REVISAO/ERRO. Função pura, sem
Tkinter: não abre janela nenhuma.

Uso:
    python teste\\teste_estilos.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.ui import estilos  # noqa: E402


def teste_texto_status_forma_longa():
    print("=== Teste 1: texto (forma longa) de cada status ===")
    assert estilos.texto_status("CONFIRMADO") == "✓ Confirmado"
    assert estilos.texto_status("REVISAO") == "⚠ Precisa de revisão"
    assert estilos.texto_status("ERRO") == "✕ Erro no processamento"
    print("  OK")
    print()


def teste_texto_status_forma_curta():
    print("=== Teste 2: texto (forma curta) de cada status ===")
    assert estilos.texto_status("CONFIRMADO", curto=True) == "✓ Confirmado"
    assert estilos.texto_status("REVISAO", curto=True) == "⚠ Revisão"
    assert estilos.texto_status("ERRO", curto=True) == "✕ Erro"
    print("  OK")
    print()


def teste_icone_e_bootstyle_nunca_dependem_so_de_cor():
    print("=== Teste 3: cada status tem ícone E palavra E cor -- nenhum dos três sozinho ===")
    for status in ("CONFIRMADO", "REVISAO", "ERRO"):
        icone = estilos.icone_status(status)
        texto = estilos.texto_status(status)
        estilo = estilos.bootstyle_status(status)
        assert icone, status
        assert texto.startswith(icone), (status, texto, icone)
        assert len(texto) > len(icone) + 1, "o texto nao pode ser so o icone"
        assert estilo in ("success", "warning", "danger"), estilo
    print("  OK")
    print()


def teste_tres_status_tem_tres_icones_e_tres_cores_distintas():
    print("=== Teste 4: os três status são visualmente distintos entre si ===")
    icones = {estilos.icone_status(s) for s in ("CONFIRMADO", "REVISAO", "ERRO")}
    estilos_boot = {estilos.bootstyle_status(s) for s in ("CONFIRMADO", "REVISAO", "ERRO")}
    cores_fundo = {estilos.cor_fundo_tabela_status(s) for s in ("CONFIRMADO", "REVISAO", "ERRO")}
    assert len(icones) == 3, f"icones repetidos entre status: {icones}"
    assert len(estilos_boot) == 3, f"cores semanticas repetidas entre status: {estilos_boot}"
    assert len(cores_fundo) == 3, f"cores de fundo repetidas entre status: {cores_fundo}"
    print("  OK")
    print()


def teste_tag_status_bate_com_o_vocabulario_da_tabela():
    print("=== Teste 5: tag do Treeview corresponde ao status ===")
    assert estilos.tag_status("CONFIRMADO") == "confirmado"
    assert estilos.tag_status("REVISAO") == "revisao"
    assert estilos.tag_status("ERRO") == "erro"
    print("  OK")
    print()


def teste_status_desconhecido_nao_estoura():
    print("=== Teste 6: um status desconhecido não derruba a interface (nunca inventa um status novo) ===")
    # Não deve acontecer na prática (só existem os 3 valores), mas a
    # função tem que degradar com segurança, não lançar exceção.
    texto = estilos.texto_status("ALGO_NOVO")
    assert texto  # não vazio
    tag = estilos.tag_status("ALGO_NOVO")
    assert tag == "revisao"  # cai no lado conservador -- nunca vira "confirmado" por engano
    print("  OK")
    print()


if __name__ == "__main__":
    teste_texto_status_forma_longa()
    teste_texto_status_forma_curta()
    teste_icone_e_bootstyle_nunca_dependem_so_de_cor()
    teste_tres_status_tem_tres_icones_e_tres_cores_distintas()
    teste_tag_status_bate_com_o_vocabulario_da_tabela()
    teste_status_desconhecido_nao_estoura()
    print("=" * 60)
    print("TESTE DE ESTILOS (SUB-FASE 21C): TUDO OK")
