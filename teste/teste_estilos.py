"""
teste/teste_estilos.py

Sub-fase 21c: testa o vocabulário de status de `ui/estilos.py` -- ícone,
texto e cor semântica de CONFIRMADO/REVISAO/ERRO. Função pura, sem
Tkinter: não abre janela nenhuma.

Sub-fase 22a: acrescenta os testes dos tokens novos (paleta de cores,
resto da hierarquia tipográfica, raio de borda, vocabulário de ícones).
Mesma natureza dos testes da 21c -- só verifica que os valores existem,
têm o formato esperado (cor hex válida, tupla de fonte bem formada) e
são consistentes entre si (nenhuma cor duplicada disfarçando dois
conceitos diferentes). Não abre janela, não depende de `ttkbootstrap`
estar com tema carregado.

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


def _e_cor_hex_valida(valor):
    if not isinstance(valor, str) or not valor.startswith("#"):
        return False
    corpo = valor[1:]
    if len(corpo) not in (6, 8):
        return False
    try:
        int(corpo, 16)
    except ValueError:
        return False
    return True


def teste_paleta_de_cores_existe_e_e_hex_valida():
    print("=== Teste 7 (22a): paleta de cores -- todos os tokens são hex válidos ===")
    tokens = [
        estilos.COR_FUNDO, estilos.COR_SUPERFICIE, estilos.COR_SUPERFICIE_ELEVADA,
        estilos.COR_BORDA, estilos.COR_BORDA_FORTE,
        estilos.COR_TEXTO_PRIMARIO, estilos.COR_TEXTO_SECUNDARIO, estilos.COR_TEXTO_DESABILITADO,
        estilos.COR_ACCENT, estilos.COR_SUCESSO, estilos.COR_ATENCAO, estilos.COR_ERRO,
    ]
    for cor in tokens:
        assert _e_cor_hex_valida(cor), f"token de cor inválido: {cor!r}"
    print("  OK")
    print()


def teste_paleta_fundo_e_superficie_sao_distintos():
    print("=== Teste 8 (22a): COR_FUNDO e COR_SUPERFICIE são cores diferentes ===")
    # É exatamente o contraste que a auditoria da 22a apontou como
    # ausente no tema `cosmo` (fundo de tela == fundo de cartão, os dois
    # brancos) -- o token novo só faz sentido se as duas cores realmente
    # divergirem.
    assert estilos.COR_FUNDO != estilos.COR_SUPERFICIE
    print("  OK")
    print()


def teste_cores_fortes_batem_com_o_tema_padrao():
    print("=== Teste 9 (22a/22e): cores fortes replicam Style().colors do tema padrão (não são inventadas) ===")
    # Sub-fase 22e: o tema padrão trocou de `cosmo` para `estilos.
    # TEMA_CLARO` (`flatly`) -- os valores iniciais deste módulo (antes
    # de qualquer `App` chamar `aplicar_paleta` com o `Style()` de
    # verdade) são os mesmos que `Style().colors` resolve para `flatly`.
    assert estilos.COR_ACCENT.upper() == "#2C3E50"
    assert estilos.COR_SUCESSO.upper() == "#18BC9C"
    assert estilos.COR_ATENCAO.upper() == "#F39C12"
    assert estilos.COR_ERRO.upper() == "#E74C3C"
    print("  OK")
    print()


def teste_hierarquia_tipografica_completa_e_bem_formada():
    print("=== Teste 10 (22a): fontes novas (subtítulo/corpo/secundário/legenda) existem e são tuplas válidas ===")
    fontes = [
        estilos.FONTE_SUBTITULO, estilos.FONTE_CORPO,
        estilos.FONTE_TEXTO_SECUNDARIO, estilos.FONTE_LEGENDA,
    ]
    for fonte in fontes:
        assert isinstance(fonte, tuple) and len(fonte) == 3, fonte
        familia, tamanho, peso = fonte
        assert isinstance(tamanho, int) and tamanho > 0
        assert peso in ("normal", "bold")
    print("  OK")
    print()


def teste_hierarquia_tipografica_tamanhos_decrescem_do_titulo_a_legenda():
    print("=== Teste 11 (22a): a escala de tamanhos é monotônica (nenhum nível 'menor' fica maior que um 'maior') ===")
    # Não exige que cada par seja estritamente diferente (corpo ==
    # secundário em tamanho, de propósito -- ver comentário no módulo),
    # só que a ordem geral não se inverta.
    escala = [
        estilos.FONTE_TITULO_PAGINA[1],
        estilos.FONTE_TITULO_CARTAO[1],
        estilos.FONTE_TITULO_SECAO[1],
        estilos.FONTE_SUBTITULO[1],
        estilos.FONTE_ROTULO_FORTE[1],
        estilos.FONTE_ROTULO_MEDIO[1],
        estilos.FONTE_CORPO[1],
        estilos.FONTE_TEXTO_SECUNDARIO[1],
        estilos.FONTE_LEGENDA[1],
    ]
    assert escala == sorted(escala, reverse=True), escala
    print("  OK")
    print()


def teste_raio_padrao_e_um_numero_positivo():
    print("=== Teste 12 (22a): RAIO_PADRAO é um número positivo (token de referência, ainda não aplicado) ===")
    assert isinstance(estilos.RAIO_PADRAO, int) and estilos.RAIO_PADRAO > 0
    print("  OK")
    print()


def teste_vocabulario_de_icones_existe_e_bate_com_status():
    print("=== Teste 13 (22a): vocabulário de ícones existe e os de status batem com STATUS_VOCABULARIO ===")
    icones = [
        estilos.ICONE_CONFIRMADO, estilos.ICONE_REVISAO, estilos.ICONE_ERRO,
        estilos.ICONE_INFO, estilos.ICONE_EXPANDIR, estilos.ICONE_RECOLHER,
        estilos.ICONE_ANTERIOR, estilos.ICONE_PROXIMO,
        estilos.ICONE_ZOOM_DIMINUIR, estilos.ICONE_ZOOM_AUMENTAR,
    ]
    for icone in icones:
        assert isinstance(icone, str) and len(icone) == 1, icone
    assert estilos.ICONE_CONFIRMADO == estilos.icone_status("CONFIRMADO")
    assert estilos.ICONE_REVISAO == estilos.icone_status("REVISAO")
    assert estilos.ICONE_ERRO == estilos.icone_status("ERRO")
    print("  OK")
    print()


def teste_icones_de_navegacao_e_expansao_sao_todos_distintos():
    print("=== Teste 14 (22a): os ícones de navegação/expansão não se repetem entre si ===")
    icones = {
        estilos.ICONE_EXPANDIR, estilos.ICONE_RECOLHER,
        estilos.ICONE_ANTERIOR, estilos.ICONE_PROXIMO,
        estilos.ICONE_ZOOM_DIMINUIR, estilos.ICONE_ZOOM_AUMENTAR,
    }
    assert len(icones) == 6, "ícone de navegação repetido para dois papéis diferentes"
    print("  OK")
    print()


def teste_aplicar_paleta_alterna_entre_clara_e_escura():
    print("=== Teste 15 (22e): aplicar_paleta troca fundo/superfície/texto entre os dois modos ===")
    assert not estilos.modo_escuro_ativo()
    fundo_claro = estilos.COR_FUNDO
    superficie_clara = estilos.COR_SUPERFICIE
    texto_claro = estilos.COR_TEXTO_PRIMARIO

    estilos.aplicar_paleta(escura=True)
    assert estilos.modo_escuro_ativo()
    assert estilos.COR_FUNDO != fundo_claro
    assert estilos.COR_SUPERFICIE != superficie_clara
    assert estilos.COR_TEXTO_PRIMARIO != texto_claro
    # Modo escuro precisa continuar com fundo/superfície DIFERENTES entre
    # si -- a mesma correção que a 22a fez para o modo claro, agora
    # também no escuro (não é "trocar de cor", é continuar separando
    # canvas de cartão).
    assert estilos.COR_FUNDO != estilos.COR_SUPERFICIE

    estilos.aplicar_paleta(escura=False)
    assert not estilos.modo_escuro_ativo()
    assert estilos.COR_FUNDO == fundo_claro
    assert estilos.COR_SUPERFICIE == superficie_clara
    assert estilos.COR_TEXTO_PRIMARIO == texto_claro
    print("  OK")
    print()


def teste_aplicar_paleta_muta_status_vocabulario_e_cores_pendencia_in_place():
    print("=== Teste 16 (22e): aplicar_paleta muda STATUS_VOCABULARIO/CORES_TIPO_PENDENCIA no MESMO objeto ===")
    # Identidade do dicionário -- é o que garante que `ui/app.py`
    # (`CORES_TIPO_PENDENCIA = estilos.CORES_TIPO_PENDENCIA`) continua
    # vendo os valores novos sem reimportar nada.
    dict_pendencia_antes = estilos.CORES_TIPO_PENDENCIA
    fundo_tabela_claro = estilos.STATUS_VOCABULARIO["CONFIRMADO"]["cor_fundo_tabela"]
    cor_pendencia_clara = dict(estilos.CORES_TIPO_PENDENCIA)

    estilos.aplicar_paleta(escura=True)
    assert estilos.CORES_TIPO_PENDENCIA is dict_pendencia_antes, "aplicar_paleta não pode REBINDAR o dicionário"
    assert estilos.STATUS_VOCABULARIO["CONFIRMADO"]["cor_fundo_tabela"] != fundo_tabela_claro
    assert dict(estilos.CORES_TIPO_PENDENCIA) != cor_pendencia_clara

    estilos.aplicar_paleta(escura=False)
    assert estilos.STATUS_VOCABULARIO["CONFIRMADO"]["cor_fundo_tabela"] == fundo_tabela_claro
    assert dict(estilos.CORES_TIPO_PENDENCIA) == cor_pendencia_clara
    print("  OK")
    print()


def teste_aplicar_paleta_sem_cores_tema_nao_altera_cores_fortes():
    print("=== Teste 17 (22e): aplicar_paleta(cores_tema=None) não mexe em COR_ACCENT/SUCESSO/ATENCAO/ERRO ===")
    accent_antes = estilos.COR_ACCENT
    estilos.aplicar_paleta(escura=True, cores_tema=None)
    assert estilos.COR_ACCENT == accent_antes
    estilos.aplicar_paleta(escura=False, cores_tema=None)
    print("  OK")
    print()


def teste_temas_claro_e_escuro_sao_nomes_distintos():
    print("=== Teste 18 (22e): TEMA_CLARO e TEMA_ESCURO são temas ttkbootstrap distintos ===")
    assert isinstance(estilos.TEMA_CLARO, str) and estilos.TEMA_CLARO
    assert isinstance(estilos.TEMA_ESCURO, str) and estilos.TEMA_ESCURO
    assert estilos.TEMA_CLARO != estilos.TEMA_ESCURO
    print("  OK")
    print()


if __name__ == "__main__":
    teste_texto_status_forma_longa()
    teste_texto_status_forma_curta()
    teste_icone_e_bootstyle_nunca_dependem_so_de_cor()
    teste_tres_status_tem_tres_icones_e_tres_cores_distintas()
    teste_tag_status_bate_com_o_vocabulario_da_tabela()
    teste_status_desconhecido_nao_estoura()
    teste_paleta_de_cores_existe_e_e_hex_valida()
    teste_paleta_fundo_e_superficie_sao_distintos()
    teste_cores_fortes_batem_com_o_tema_padrao()
    teste_hierarquia_tipografica_completa_e_bem_formada()
    teste_hierarquia_tipografica_tamanhos_decrescem_do_titulo_a_legenda()
    teste_raio_padrao_e_um_numero_positivo()
    teste_vocabulario_de_icones_existe_e_bate_com_status()
    teste_icones_de_navegacao_e_expansao_sao_todos_distintos()
    teste_aplicar_paleta_alterna_entre_clara_e_escura()
    teste_aplicar_paleta_muta_status_vocabulario_e_cores_pendencia_in_place()
    teste_aplicar_paleta_sem_cores_tema_nao_altera_cores_fortes()
    teste_temas_claro_e_escuro_sao_nomes_distintos()
    print("=" * 60)
    print("TESTE DE ESTILOS (SUB-FASES 21C/22A/22E): TUDO OK")
