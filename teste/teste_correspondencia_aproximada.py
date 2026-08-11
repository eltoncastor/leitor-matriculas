"""
teste/teste_correspondencia_aproximada.py

Testes do fuzzy matching CONTROLADO (correspondencia_aproximada.py), usado
pela Fase 1 de precisão da extração para os campos MOTIVO (PROBLEMA 3) e
RESPONSÁVEL PELA AUTORIZAÇÃO (PROBLEMA 4). Fixtures sintéticas, sem
dependência de OCR real.

Uso:
    python teste\\teste_correspondencia_aproximada.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.validacao.correspondencia_aproximada import buscar_correspondencia, resolver_responsavel  # noqa: E402


# ---------------------------------------------------------------------------
# MOTIVOS
# ---------------------------------------------------------------------------

# Base simplificada correspondendo literalmente ao exemplo do requisito
# funcional (evita a ambiguidade real entre "NEGADA"/"NEGADO" da base de
# produção -- essa ambiguidade real tem teste dedicado mais abaixo).
MOTIVOS_EXEMPLO = ["NEGADO", "HORÁRIO NEGADO", "OUTROS MOTIVOS"]


def teste_motivo_correspondencia_exata():
    r = buscar_correspondencia("NEGADO", MOTIVOS_EXEMPLO)
    assert r.status == "EXATA" and r.valor_sugerido == "NEGADO"
    r2 = buscar_correspondencia("negado", MOTIVOS_EXEMPLO)  # minúsculo -- ainda exata após normalização
    assert r2.status == "EXATA" and r2.valor_sugerido == "NEGADO"
    print("OK: motivo com correspondência exata (inclusive ignorando maiúscula)")


def teste_motivo_erro_simples_neegadho():
    r = buscar_correspondencia("neegadho", MOTIVOS_EXEMPLO)
    assert r.status == "APROXIMADA" and r.valor_sugerido == "NEGADO", r
    assert r.houve_normalizacao
    assert r.texto_original == "neegadho"  # original preservado para diagnóstico
    print("OK: 'neegadho' -> 'NEGADO' por aproximação")


def teste_motivo_erro_simples_negaoda():
    r = buscar_correspondencia("negaoda", MOTIVOS_EXEMPLO)
    assert r.status == "APROXIMADA" and r.valor_sugerido == "NEGADO", r
    print("OK: 'negaoda' -> 'NEGADO' por aproximação")


def teste_motivo_hr_negad_para_horario_negado():
    # Numa base onde "HORÁRIO NEGADO" não compete de perto com nenhum outro
    # candidato parecido, "hr negad" reconhece sem ambiguidade.
    base_sem_concorrente_proximo = ["HORÁRIO NEGADO", "OUTROS MOTIVOS"]
    r = buscar_correspondencia("hr negad", base_sem_concorrente_proximo)
    assert r.status == "APROXIMADA" and r.valor_sugerido == "HORÁRIO NEGADO", r
    print("OK: 'hr negad' -> 'HORÁRIO NEGADO' (a base contém esse motivo, sem concorrente próximo)")


def teste_motivo_hr_negad_ambiguo_quando_negado_tambem_existe():
    # Achado real (Fase 1): com "NEGADO" e "HORÁRIO NEGADO" nos MESMOS
    # candidatos (como MOTIVOS_EXEMPLO acima), "hr negad" fica perto demais
    # dos dois -- corretamente vai para REVISAO em vez de decidir sozinho
    # qual delas a pessoa quis dizer. Documentado de propósito, não
    # escondido (ver relatório da Fase 1).
    r = buscar_correspondencia("hr negad", MOTIVOS_EXEMPLO)
    assert r.status == "AMBIGUA" and r.valor_sugerido is None, r
    print("OK: 'hr negad' com 'NEGADO' e 'HORÁRIO NEGADO' ambos na base -> AMBIGUA (REVISAO)")


def teste_motivo_similaridade_insuficiente():
    r = buscar_correspondencia("xyz completamente diferente", MOTIVOS_EXEMPLO)
    assert r.status == "SEM_CORRESPONDENCIA" and r.valor_sugerido is None, r
    print("OK: texto sem nada a ver com a base -> SEM_CORRESPONDENCIA (REVISAO)")


def teste_motivo_candidatos_ambiguos():
    # "PORTARIA X" fica exatamente a meio caminho de dois candidatos que só
    # diferem entre si na mesma posição (substituição simétrica de 1
    # caractere) -- similaridade empatada, não deve escolher nenhum sozinho.
    candidatos = ["PORTARIA A", "PORTARIA B"]
    r = buscar_correspondencia("PORTARIA X", candidatos)
    assert r.status == "AMBIGUA" and r.valor_sugerido is None, r
    print("OK: dois candidatos igualmente próximos -> AMBIGUA (REVISAO), nunca um chute")


def teste_motivo_base_vazia():
    r = buscar_correspondencia("qualquer coisa", [])
    assert r.status == "SEM_CANDIDATOS" and r.valor_sugerido is None
    print("OK: base de motivos vazia -> SEM_CANDIDATOS, comportamento seguro (não derruba nada)")


def teste_motivo_texto_vazio():
    r = buscar_correspondencia("", MOTIVOS_EXEMPLO)
    assert r.status == "VAZIO" and r.valor_sugerido is None
    print("OK: texto OCR vazio -> VAZIO, comportamento seguro")


def teste_motivo_base_real_negada_negado_e_ambigua():
    # Achado real (Fase 1): a base real Motivos.xlsx tem "NEGADA" E
    # "NEGADO" como motivos DISTINTOS. Um erro de OCR que fica a meio
    # caminho dos dois (ex.: "Negade.") deve ir para REVISAO em vez de
    # escolher um dos dois no chute -- é exatamente o cenário para o qual
    # a checagem de ambiguidade existe. Documentado aqui de propósito
    # (ver relatório da Fase 1) em vez de escondido.
    motivos_reais = ["NEGADA", "NEGADO", "H. NEGADO", "Horário negado", "RH", "ADM"]
    r = buscar_correspondencia("Negade.", motivos_reais)
    assert r.status == "AMBIGUA", r
    print("OK: 'Negade.' contra base real com NEGADA/NEGADO -> AMBIGUA (REVISAO), não inventa o gênero")


# ---------------------------------------------------------------------------
# RESPONSÁVEIS (GESTOR)
# ---------------------------------------------------------------------------

GESTORES_EXEMPLO = ["JOÃO PAULO", "MARIA EDUARDA", "CARLOS ALBERTO"]


def teste_gestor_correspondencia_exata():
    r = buscar_correspondencia("JOÃO PAULO", GESTORES_EXEMPLO)
    assert r.status == "EXATA" and r.valor_sugerido == "JOÃO PAULO"
    print("OK: responsável com correspondência exata")


def teste_gestor_erro_simples_de_ocr():
    r = buscar_correspondencia("JOAO PAUL0", GESTORES_EXEMPLO)  # zero no lugar do O, sem acento
    assert r.status == "APROXIMADA" and r.valor_sugerido == "JOÃO PAULO", r
    print("OK: 'JOAO PAUL0' -> 'JOÃO PAULO' por aproximação")


def teste_gestor_nome_com_acento():
    r = buscar_correspondencia("Joao Paulo", GESTORES_EXEMPLO)  # sem os acentos
    assert r.status in ("EXATA", "APROXIMADA") and r.valor_sugerido == "JOÃO PAULO", r
    print("OK: nome sem acento ainda reconhece o candidato correto")


def teste_gestor_erro_de_caractere():
    r = buscar_correspondencia("CARLOS ALBERT0", GESTORES_EXEMPLO)
    assert r.status == "APROXIMADA" and r.valor_sugerido == "CARLOS ALBERTO", r
    print("OK: erro de caractere isolado -> aproximação correta")


def teste_gestor_candidato_ambiguo():
    candidatos = ["MARCELO TORRES", "MARCELO SOUZA"]
    r = buscar_correspondencia("MARCELO", candidatos)
    assert r.status == "AMBIGUA" and r.valor_sugerido is None, r
    print("OK: 'MARCELO' sozinho, com dois sobrenomes parecidos na base -> AMBIGUA (REVISAO)")


def teste_gestor_candidato_insuficiente():
    r = buscar_correspondencia("Supervisor de Prevenção de Perdas", GESTORES_EXEMPLO)
    assert r.status == "SEM_CORRESPONDENCIA" and r.valor_sugerido is None, r
    print("OK: texto sem relação com a base de gestores -> SEM_CORRESPONDENCIA (REVISAO)")


def teste_gestor_base_vazia():
    r = buscar_correspondencia("Qualquer Nome", [])
    assert r.status == "SEM_CANDIDATOS" and r.valor_sugerido is None
    print("OK: base de gestores vazia -> SEM_CANDIDATOS, comportamento seguro")


# ---------------------------------------------------------------------------
# RESPONSÁVEL (resolver_responsavel)
#
# O nome do Auxiliar de Prevenção de Perdas, quando anotado junto ao
# gestor (ex.: "GR3 - BEATRIZ - LORENA"), NÃO é reconhecido nem faz parte
# do resultado -- não é usado na planilha final. O texto residual depois
# do gestor só é usado internamente para não contaminar a identificação
# do GESTOR; o valor em si é descartado (ver correspondencia_aproximada.py).
# ---------------------------------------------------------------------------

# Base real de Gestores.xlsx (nomes compostos, códigos "GRx - NOME",
# códigos sozinhos e possíveis aliases -- ver correspondencia_aproximada.py).
GESTORES_REAIS = [
    "GR1 - TEODORO", "GR3 - BEATRIZ", "GR4 - RENATO GUIMARÃES", "GR5 - OTAVIO", "GRL - LUCIA",
    "ROBERTO", "MARCELO TORRES", "MARCELO SOUZA", "HELIO", "SOUZA", "MARTIM", "NORBERTO",
    "TAMIRES", "VICENTE", "GR1", "GR3", "GR4", "GR5", "GRL", "TORRES", "M TORRES", "MARCELO",
]


def teste_responsavel_codigo_nome_e_identificacao_unica():
    # Hífen NÃO separa gestor/texto residual por padrão -- "GR3 - BEATRIZ" é
    # uma identificação única e existe assim, inteira, na base.
    r = resolver_responsavel("GR3 - BEATRIZ", GESTORES_REAIS)
    assert r.status == "EXATA" and r.gestor_confirmado == "GR3 - BEATRIZ", r
    print("OK: 'GR3 - BEATRIZ' -> gestor único, sem dividir por hífen")


def teste_responsavel_codigo_nome_composto():
    r = resolver_responsavel("GR4 - RENATO GUIMARÃES", GESTORES_REAIS)
    assert r.status == "EXATA" and r.gestor_confirmado == "GR4 - RENATO GUIMARÃES", r
    print("OK: 'GR4 - RENATO GUIMARÃES' -> gestor único (nome composto preservado)")


def teste_responsavel_nome_composto_sem_codigo():
    r1 = resolver_responsavel("MARCELO TORRES", GESTORES_REAIS)
    assert r1.status == "EXATA" and r1.gestor_confirmado == "MARCELO TORRES", r1
    r2 = resolver_responsavel("MARCELO SOUZA", GESTORES_REAIS)
    assert r2.status == "EXATA" and r2.gestor_confirmado == "MARCELO SOUZA", r2
    print("OK: 'MARCELO TORRES'/'MARCELO SOUZA' -> nomes compostos não divididos por espaço")


def teste_responsavel_alias_curto():
    r = resolver_responsavel("TORRES", GESTORES_REAIS)
    assert r.status == "EXATA" and r.gestor_confirmado == "TORRES", r
    print("OK: 'TORRES' -> reconhece o alias curto exatamente como está na base")


def teste_responsavel_alias_com_erro_de_ocr():
    r = resolver_responsavel("M. TORRES", GESTORES_REAIS)
    assert r.status == "APROXIMADA" and r.gestor_confirmado == "M TORRES", r
    print("OK: 'M. TORRES' -> aproximado de 'M TORRES' (ponto do OCR não confunde com 'TORRES')")


def teste_responsavel_com_texto_residual_codigo_nome():
    # "GR3 - BEATRIZ - LORENA": o gestor é identificado normalmente; o
    # texto depois dele ("LORENA") é só descartado, não aparece no
    # resultado.
    r = resolver_responsavel("GR3 - BEATRIZ - LORENA", GESTORES_REAIS)
    assert r.status == "EXATA", r
    assert r.gestor_confirmado == "GR3 - BEATRIZ", r
    print("OK: 'GR3 - BEATRIZ - LORENA' -> gestor='GR3 - BEATRIZ' (texto residual descartado, não aparece no resultado)")


def teste_responsavel_com_texto_residual_nome_composto():
    r = resolver_responsavel("MARCELO TORRES - LORENA", GESTORES_REAIS)
    assert r.status == "EXATA", r
    assert r.gestor_confirmado == "MARCELO TORRES", r
    print("OK: 'MARCELO TORRES - LORENA' -> gestor='MARCELO TORRES' (texto residual descartado)")


def teste_responsavel_ambiguo_entre_dois_andersons():
    # Sem o alias "MARCELO" sozinho na base (cenário onde só existem os
    # dois nomes completos), "MARCELO" sozinho é genuinamente ambíguo --
    # nunca escolhe entre "MARCELO TORRES" e "MARCELO SOUZA" no chute.
    gestores_sem_alias = [g for g in GESTORES_REAIS if g != "MARCELO"]
    r = resolver_responsavel("MARCELO", gestores_sem_alias)
    assert r.status == "AMBIGUA" and r.gestor_confirmado is None, r
    print("OK: 'MARCELO' sem alias inequívoco, com dois nomes completos parecidos -> AMBIGUA (REVISAO)")


def teste_responsavel_erro_de_ocr_corrigivel():
    r = resolver_responsavel("MARCELO TORNES", GESTORES_REAIS)  # "M" no lugar de "N"
    assert r.status == "APROXIMADA" and r.gestor_confirmado == "MARCELO TORRES", r
    print("OK: 'MARCELO TORNES' (erro de OCR) -> corrigido para 'MARCELO TORRES'")


def teste_responsavel_ocr_degradado_com_codigo_e_nome_curto():
    # Achado real (teste.jpg): o OCR real produziu "GR3 - Loreno" e
    # "Martim - coseeone" -- o texto inteiro não bate com confiança
    # suficiente, mas o PREFIXO (código/nome já cadastrado sozinho na
    # base) bate; como "GR3" tem uma única expansão mais específica na
    # base ("GR3 - BEATRIZ"), o gestor confirmado já vem na forma completa.
    # O restante ("Loreno"/"coseeone") é só descartado -- não faz parte do
    # resultado.
    r1 = resolver_responsavel("GR3 - Loreno", GESTORES_REAIS)
    assert r1.gestor_confirmado == "GR3 - BEATRIZ", r1

    # "MARTIM" já é a forma mais completa (não é um código com expansão) --
    # fica como está.
    r2 = resolver_responsavel("Martim - coseeone", GESTORES_REAIS)
    assert r2.status == "EXATA" and r2.gestor_confirmado == "MARTIM", r2
    print("OK: 'GR3 - Loreno'/'Martim - coseeone' -> gestor identificado corretamente, texto residual descartado")


def teste_responsavel_hifen_sem_espaco_antes():
    # Achado real (teste.jpg): o OCR às vezes produz "GR4- Cosecone" (sem
    # espaço antes do hífen) -- o corte não pode depender de " - " literal.
    r = resolver_responsavel("GR4- Cosecone", GESTORES_REAIS)
    assert r.gestor_confirmado == "GR4 - RENATO GUIMARÃES", r
    print("OK: 'GR4- Cosecone' (sem espaço antes do hífen) -> gestor='GR4 - RENATO GUIMARÃES'")


def teste_responsavel_gkl_codione_gestor_identificado_auxiliar_descartado():
    # CASO REAL (teste.jpg): "Gkl - Codione" -- "Gkl" é erro de OCR de
    # "GRL" (código da gestora LUCIA); "Codione" seria o auxiliar de
    # portaria, mas o nome do auxiliar não faz mais parte do resultado
    # (simplificação: eliminamos essa tentativa de reconhecimento, que
    # tinha risco real de erro -- o nome curto de um auxiliar sai parecido
    # demais com o de um gestor cadastrado e acaba sendo "corrigido" para
    # ele, ex.: um "Marto" manuscrito virando "MARTIM").
    r = resolver_responsavel("Gkl - Codione", GESTORES_REAIS)

    # A parte que importa continua funcionando: "Gkl" reconhece "GRL" por
    # aproximação controlada (erro de OCR num código curto) e expande para
    # a identificação completa e inequívoca "GRL - LUCIA".
    assert r.gestor_confirmado == "GRL - LUCIA", r
    print("OK: 'Gkl - Codione' -> gestor='GRL - LUCIA' (auxiliar não é mais reconhecido nem faz parte do resultado)")


def teste_responsavel_nao_inventa_sem_correspondencia():
    r = resolver_responsavel("Supervisor de Prevenção de Perdas", GESTORES_REAIS)
    assert r.status in ("SEM_CORRESPONDENCIA", "AMBIGUA") and r.gestor_confirmado is None, r
    print("OK: texto sem relação com a base -> não inventa gestor")


def teste_responsavel_base_vazia():
    r = resolver_responsavel("GR3 - BEATRIZ - LORENA", [])
    assert r.status == "SEM_CANDIDATOS" and r.gestor_confirmado is None
    print("OK: base de gestores vazia -> SEM_CANDIDATOS, comportamento seguro")


def teste_responsavel_sem_texto_residual_e_normal_e_valido():
    # A AUSÊNCIA de texto residual (só o gestor, sem nada depois) é o caso
    # mais comum -- registro totalmente válido, sem nenhum tratamento
    # especial.
    r1 = resolver_responsavel("GR3 - BEATRIZ", GESTORES_REAIS)
    assert r1.status == "EXATA" and r1.gestor_confirmado == "GR3 - BEATRIZ", r1
    r2 = resolver_responsavel("MARCELO TORRES", GESTORES_REAIS)
    assert r2.status == "EXATA" and r2.gestor_confirmado == "MARCELO TORRES", r2
    print("OK: 'GR3 - BEATRIZ'/'MARCELO TORRES' sem nada depois -> registro válido")


def teste_responsavel_resultado_nao_tem_mais_campo_de_auxiliar():
    # Simplificação: ResultadoResponsavel não expõe mais nome de auxiliar
    # nenhum -- confirma que o campo realmente não existe mais no objeto.
    r = resolver_responsavel("GR3 - BEATRIZ - LORENA", GESTORES_REAIS)
    assert not hasattr(r, "auxiliar_portaria"), r
    print("OK: ResultadoResponsavel não tem mais campo de auxiliar (eliminado do resultado)")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("teste_")]
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
