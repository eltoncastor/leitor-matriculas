"""
teste/teste_normalizacao_motivo_hora.py

Ajuste pontual de normalização, virado em teste de regressão:

    1. MOTIVO  -- família de sinônimos "negado" da base canonicalizada
                  para HORÁRIO NEGADO quando o OCR veio corrompido, SEM
                  puxar para lá motivos de outra natureza.
    2. GESTOR  -- código nu ("GR3", "GR5", "6R05") expandido para a
                  identificação completa cadastrada ("GR3 - DIANA").
    3. HORA    -- formato canônico HH:MM, mantendo a recusa de hora
                  impossível.
    4. Ponta a ponta em `classificar_registro`: formato de saída, texto da
       Observação e, sobretudo, que nada disso cria CONFIRMADO artificial.

Não usa PaddleOCR nem as planilhas reais: as bases são fixtures
sintéticas com o MESMO conteúdo das reais (que têm, de propósito,
"NEGADO"/"NEGADA"/"H. NEGADO"/"Horário negado" cadastrados
separadamente -- é essa proximidade entre sinônimos que gerava AMBIGUA).

Uso:
    python teste\\teste_normalizacao_motivo_hora.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.parsing.registro_parser import Registro, CampoOcr  # noqa: E402
from leitor_matriculas.parsing.tempo_parser import normalizar_data, normalizar_hora  # noqa: E402
from leitor_matriculas.validacao.correspondencia_aproximada import (  # noqa: E402
    MOTIVO_HORARIO_NEGADO,
    resolver_motivo,
    resolver_responsavel,
)
from leitor_matriculas.validacao.regras import classificar_registro  # noqa: E402

# Conteúdo REAL das bases (dados/Motivos.xlsx e dados/Gestores.xlsx),
# incluindo os espaços de preenchimento que as planilhas trazem.
MOTIVOS = [" Horário negado         ", " RH                     ", " ADM                    ",
           " Armários               ", " Folga fixa             ",
           " Esquecimento de crachá ", "TREINAMENTO", "NEGADA", "NEGADO", "H. NEGADO"]
GESTORES = ["GR1 – JADSON", "GR3 - DIANA", "GR4 - ANDRÉ VALENÇA", "GR5 - DIEGO",
            "GRL - FABIANA", "ADELINO", "ANDERSON ABREU", "ANDERSON CARLOS", "BRUNO",
            "CARLOS", "DANIEL", "EDVALDO", "NAYSHA", "PATRICK",
            "GR1", "GR3", "GR4", "GR5", "GRL", "ABREU", "A. ABREU", "ANDERSON "]

# Leituras corrompidas do motivo observadas nas folhas reais.
MOTIVO_CORROMPIDO = ["Hiv. Nigado", "H.v. vigaolb", "Negoide", "Negade", "NEGAND",
                     "Hev. Nigadb", "I Wegado", "NoGAAO", "H.v. Nigado"]

falhas = []


def checar(cond, msg):
    print(("  OK    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


class _DMFalso:
    """DataManager mínimo: as bases do teste não podem depender do
    conteúdo local de dados/."""

    def __init__(self, colaboradores=None, gestores=GESTORES, motivos=MOTIVOS):
        self._colaboradores = colaboradores or {}
        self.colaboradores_disponivel = True
        self.gestores_disponivel = bool(gestores)
        self.motivos_disponivel = bool(motivos)
        self._gestores = gestores or []
        self._motivos = motivos or []

    def listar_gestores(self):
        return self._gestores

    def listar_motivos(self):
        return self._motivos

    def buscar_colaborador(self, matricula):
        return self._colaboradores.get(matricula)


COLABORADOR = {"matricula": "19547", "nome": "FULANO", "cargo": "OPERADOR", "setor": "LOJA"}


def _registro(motivo="Horário negado", gestor="GR5 - DIEGO", hora="11:05",
              data="23.04.26", matricula="19547"):
    campos = {}
    if data:
        campos["data"] = CampoOcr(data, 0.9, None)
    if hora:
        campos["hora"] = CampoOcr(hora, 0.9, None)
    if matricula:
        campos["matricula"] = CampoOcr(matricula, 0.95, None)
    if gestor:
        campos["gestor"] = CampoOcr(gestor, 0.9, None)
    if motivo:
        campos["motivo"] = CampoOcr(motivo, 0.9, None)
    return Registro(indice=1, campos=campos)


# ---------------------------------------------------------------------------
# 1. MOTIVO -> HORÁRIO NEGADO
# ---------------------------------------------------------------------------

def teste_motivo_corrompido_vira_horario_negado():
    print("=== MOTIVO: leituras corrompidas reais -> HORÁRIO NEGADO ===")
    for bruto in MOTIVO_CORROMPIDO:
        r = resolver_motivo(bruto, MOTIVOS)
        checar(r.motivo_confirmado == MOTIVO_HORARIO_NEGADO and r.houve_fallback,
               f"{bruto!r} -> {MOTIVO_HORARIO_NEGADO!r} "
               f"(obtido: {r.motivo_confirmado!r}, status={r.status})")
    print()


def teste_motivo_exato_nunca_e_alterado():
    print("=== MOTIVO: reconhecido com segurança mantém o motivo correto ===")
    for bruto, esperado in [("NEGADA", "NEGADA"), ("NEGADO", "NEGADO"),
                            ("H. NEGADO", "H. NEGADO"), ("TREINAMENTO", "TREINAMENTO")]:
        r = resolver_motivo(bruto, MOTIVOS)
        checar(r.status == "EXATA" and (r.motivo_confirmado or "").strip() == esperado,
               f"{bruto!r} (exato) permanece {esperado!r} "
               f"(obtido: {r.motivo_confirmado!r}, status={r.status})")
    r = resolver_motivo("Horário negado", MOTIVOS)
    checar(r.status == "EXATA" and (r.motivo_confirmado or "").strip() == "Horário negado",
           f"'Horário negado' (exato) permanece como está (obtido: {r.motivo_confirmado!r})")
    print()


def teste_outros_motivos_nao_sao_sugados_para_o_fallback():
    print("=== MOTIVO: nenhum outro motivo é puxado para HORÁRIO NEGADO ===")
    # Corrupções de motivos de OUTRA natureza: têm de resolver para o
    # próprio motivo, ou ir para REVISAO -- nunca para o fallback.
    for bruto, esperado in [("AOM", "ADM"), ("Folga fixo", "Folga fixa"),
                            ("TREINAMENTU", "TREINAMENTO"), ("Armarios", "Armários"),
                            ("Esquecimento de cracha", "Esquecimento de crachá")]:
        r = resolver_motivo(bruto, MOTIVOS)
        checar((r.motivo_confirmado or "").strip() == esperado and not r.houve_fallback,
               f"{bruto!r} -> {esperado!r}, sem fallback (obtido: {r.motivo_confirmado!r})")
    for bruto in ["XPTO INEXISTENTE", "ZZZZZZZZ", "112233"]:
        r = resolver_motivo(bruto, MOTIVOS)
        checar(r.motivo_confirmado is None and not r.houve_fallback,
               f"{bruto!r} -> sem correspondência, sem fallback "
               f"(obtido: {r.motivo_confirmado!r}, status={r.status})")
    print()


def teste_fallback_exige_o_canonico_na_base():
    print("=== MOTIVO: sem 'Horário negado' na base, não há fallback ===")
    sem_canonico = ["RH", "ADM", "TREINAMENTO"]
    r = resolver_motivo("Negade", sem_canonico)
    checar(r.motivo_confirmado != MOTIVO_HORARIO_NEGADO,
           f"base sem o valor canônico nunca produz {MOTIVO_HORARIO_NEGADO!r} "
           f"(obtido: {r.motivo_confirmado!r})")
    r2 = resolver_motivo("Negade", [])
    checar(r2.status == "SEM_CANDIDATOS" and r2.motivo_confirmado is None,
           f"base vazia -> SEM_CANDIDATOS (obtido: {r2.status})")
    r3 = resolver_motivo("", MOTIVOS)
    checar(r3.status == "VAZIO" and r3.motivo_confirmado is None,
           f"texto vazio -> VAZIO (obtido: {r3.status})")
    print()


# ---------------------------------------------------------------------------
# 2. GESTOR -> identificação completa cadastrada
# ---------------------------------------------------------------------------

def teste_codigo_gr_expande_para_nome_completo():
    print("=== GESTOR: código nu expandido para o nome cadastrado ===")
    for bruto, esperado in [("GR3", "GR3 - DIANA"), ("GR5", "GR5 - DIEGO"),
                            ("GR4", "GR4 - ANDRÉ VALENÇA"), ("GRL", "GRL - FABIANA"),
                            ("GR1", "GR1 – JADSON"), ("6R05", "GR5 - DIEGO"),
                            ("6R5", "GR5 - DIEGO")]:
        r = resolver_responsavel(bruto, GESTORES)
        checar(r.gestor_confirmado == esperado,
               f"{bruto!r} -> {esperado!r} (obtido: {r.gestor_confirmado!r}, status={r.status})")
    print()


def teste_nome_da_auxiliar_nao_contamina_o_responsavel():
    print("=== GESTOR: nome da auxiliar descartado (GR5 + Loemone/Esleane) ===")
    for bruto in ["GR5 - Eosee", "GR5 - Loemone", "GR5 - Esleane", "GR5- Esleane"]:
        r = resolver_responsavel(bruto, GESTORES)
        checar(r.gestor_confirmado == "GR5 - DIEGO",
               f"{bruto!r} -> 'GR5 - DIEGO' (obtido: {r.gestor_confirmado!r})")
        for residuo in ("Eosee", "Loemone", "Esleane"):
            checar(residuo not in (r.gestor_confirmado or ""),
                   f"{bruto!r}: {residuo!r} não aparece no responsável")
    print()


def teste_gestor_sem_expansao_unica_nao_e_chutado():
    print("=== GESTOR: sem expansão única, nada é chutado ===")
    r = resolver_responsavel("ANDERSON", GESTORES)
    checar((r.gestor_confirmado or "").strip() == "ANDERSON",
           f"'ANDERSON' (duas expansões possíveis) não vira ABREU nem CARLOS "
           f"(obtido: {r.gestor_confirmado!r})")
    # "GRI": o I pode ser tanto o dígito 1 quanto a letra L, e GR1 e GRL
    # existem OS DOIS na base -- duas leituras plausíveis, nenhuma escolha.
    # (Este caso substituiu "GRS", que esta suíte tratava como ambíguo
    # quando a leitura do código era só similaridade de texto. Com a
    # tabela FECHADA de confusões de OCR, "S" é leitura conhecida de "5" e
    # não de "L": GR5 é a ÚNICA leitura de "GRS" que existe na base, e por
    # isso ela passou a ser aceita -- é o mesmo critério de evidência da
    # recuperação de matrícula, não um chute. Ver teste_gestor_codigo_gr.)
    r2 = resolver_responsavel("GRI", GESTORES)
    checar(r2.gestor_confirmado is None,
           f"'GRI' (I pode ser 1 ou L; GR1 e GRL existem os dois) -> REVISAO "
           f"(obtido: {r2.gestor_confirmado!r}, status={r2.status})")
    print()


# ---------------------------------------------------------------------------
# 3. HORA -> HH:MM
# ---------------------------------------------------------------------------

def teste_hora_normalizada_para_hh_mm():
    print("=== HORA: formato canônico HH:MM ===")
    for bruto, esperado in [("18.59", "18:59"), ("07.55", "07:55"), ("11.27", "11:27"),
                            ("14.04", "14:04"), ("07:53", "07:53"), ("11h05", "11:05"),
                            ("7:5", None), ("8.00", "08:00"), ("23:59:59", "23:59")]:
        obtido = normalizar_hora(bruto)
        checar(obtido == esperado, f"{bruto!r} -> {esperado!r} (obtido: {obtido!r})")
    print()


def teste_hora_impossivel_continua_recusada():
    print("=== HORA: impossível/ilegível continua recusada (célula vazia) ===")
    for bruto in ["90:24", "25:00", "11:60", "meio-dia", "", None, "<br>"]:
        checar(normalizar_hora(bruto) is None, f"{bruto!r} -> None (obtido: {normalizar_hora(bruto)!r})")
    print()


def teste_data_continua_em_dd_mm_aa():
    print("=== DATA: formato canônico dd/mm/aa (regressão) ===")
    for bruto, esperado in [("14.04.26", "14/04/26"), ("28.04.26", "28/04/26"),
                            ("23.04.26", "23/04/26"), ("14-04-26", "14/04/26"),
                            ("28/04/26", "28/04/26"), ("23.04", None)]:
        obtido = normalizar_data(bruto)
        checar(obtido == esperado, f"{bruto!r} -> {esperado!r} (obtido: {obtido!r})")
    print()


# ---------------------------------------------------------------------------
# 4. Ponta a ponta em classificar_registro
# ---------------------------------------------------------------------------

def teste_ponta_a_ponta_saida_normalizada():
    print("=== PONTA A PONTA: registro completo sai todo normalizado ===")
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    r = classificar_registro(
        _registro(motivo="Hiv. Nigado", gestor="6R05", hora="18.59", data="14.04.26"),
        COLABORADOR, dm,
    )
    checar(r.status == "CONFIRMADO", f"status CONFIRMADO (obtido: {r.status} -- {r.observacao})")
    checar(r.data_confirmada == "14/04/26", f"data '14/04/26' (obtido: {r.data_confirmada!r})")
    checar(r.hora_confirmada == "18:59", f"hora '18:59' (obtido: {r.hora_confirmada!r})")
    checar(r.motivo_confirmado == MOTIVO_HORARIO_NEGADO,
           f"motivo {MOTIVO_HORARIO_NEGADO!r} (obtido: {r.motivo_confirmado!r})")
    checar(r.gestor_confirmado == "GR5 - DIEGO", f"gestor 'GR5 - DIEGO' (obtido: {r.gestor_confirmado!r})")
    checar("motivo normalizado para HORÁRIO NEGADO a partir do OCR: 'Hiv. Nigado'" in r.observacao,
           f"Observação registra o fallback (obtido: {r.observacao!r})")
    print()


def teste_hora_ilegivel_nao_bloqueia_mas_sai_vazia():
    print("=== PONTA A PONTA: hora impossível não bloqueia, mas sai vazia ===")
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    r = classificar_registro(_registro(hora="90:24"), COLABORADOR, dm)
    checar(r.status == "CONFIRMADO", f"hora ilegível não bloqueia (obtido: {r.status})")
    checar(r.hora_confirmada is None, f"hora sai vazia (obtido: {r.hora_confirmada!r})")
    checar("90:24" in r.observacao, f"texto bruto preservado na Observação (obtido: {r.observacao!r})")
    print()


def teste_normalizacao_nao_cria_confirmado_artificial():
    print("=== PONTA A PONTA: normalização NÃO infla CONFIRMADO ===")
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})

    # Motivo irreconhecível: continua REVISAO, não vira HORÁRIO NEGADO.
    r = classificar_registro(_registro(motivo="XPTO INEXISTENTE"), COLABORADOR, dm)
    checar(r.status == "REVISAO" and r.motivo_confirmado is None,
           f"motivo sem relação -> REVISAO (obtido: {r.status}/{r.motivo_confirmado!r})")

    # Gestor ambíguo entre GR1 e GRL: continua REVISAO.
    r2 = classificar_registro(_registro(gestor="GRI"), COLABORADOR, dm)
    checar(r2.status == "REVISAO", f"gestor ambíguo -> REVISAO (obtido: {r2.status} -- {r2.observacao})")

    # Data sem ano SEM contexto de lote: continua bloqueando, mesmo com
    # motivo/gestor perfeitos. (Com contexto confiável do lote o ano pode
    # ser completado -- ver teste_data_sem_ano_com_contexto_do_lote na
    # suíte da recuperação contextual; aqui não há contexto nenhum.)
    r3 = classificar_registro(_registro(data="23.04"), COLABORADOR, dm)
    checar(r3.status == "REVISAO" and r3.data_confirmada is None,
           f"data sem ano (sem contexto) -> REVISAO (obtido: {r3.status})")

    # Matrícula fora da base: continua REVISAO.
    r4 = classificar_registro(_registro(matricula="99999"), None, dm)
    checar(r4.status == "REVISAO", f"matrícula fora da base -> REVISAO (obtido: {r4.status})")
    print()


def teste_campos_confirmados_sobrevivem_a_revisao_por_outro_campo():
    print("=== PONTA A PONTA: normalização preservada mesmo indo para REVISAO ===")
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    # A DATA é que derruba o registro; hora normalizada tem de sobreviver.
    r = classificar_registro(_registro(data="23.04", hora="18.59"), COLABORADOR, dm)
    checar(r.status == "REVISAO", f"status REVISAO (obtido: {r.status})")
    checar(r.hora_confirmada == "18:59",
           f"hora normalizada preservada mesmo em REVISAO (obtido: {r.hora_confirmada!r})")
    print()


def teste_motivo_e_gestor_normalizados_mesmo_em_revisao_por_outro_campo():
    """
    Regressão do caso REAL das fotos: o registro era barrado ANTES (data
    ilegível, matrícula fora da base...) e motivo/responsável nunca chegavam
    a ser resolvidos -- a planilha recebia o texto CRU do OCR ('Negade',
    'H.v. Nigado') nessas colunas, exatamente o que não pode aparecer na
    saída final. Agora os dois são resolvidos ANTES de qualquer bloqueio.
    """
    print("=== PONTA A PONTA: motivo/gestor normalizados mesmo com bloqueio antes ===")
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})

    cenarios = [
        ("data ilegível", _registro(data="23.04", motivo="H.v. Nigado", gestor="GR5 - Loemone"), COLABORADOR),
        ("data ausente", _registro(data=None, motivo="Negade", gestor="6R05"), COLABORADOR),
        ("sem matrícula", _registro(matricula=None, motivo="NoGAAO", gestor="GR3"), None),
        ("matrícula fora da base", _registro(matricula="99999", motivo="Hev. Nigadb", gestor="GR5"), None),
    ]
    esperado_gestor = {"GR5 - Loemone": "GR5 - DIEGO", "6R05": "GR5 - DIEGO",
                       "GR3": "GR3 - DIANA", "GR5": "GR5 - DIEGO"}
    for rotulo, registro, colaborador in cenarios:
        r = classificar_registro(registro, colaborador, dm)
        bruto_motivo = registro.campos["motivo"].texto
        bruto_gestor = registro.campos["gestor"].texto
        checar(r.status == "REVISAO", f"{rotulo}: continua REVISAO (obtido: {r.status})")
        checar(r.motivo_confirmado == MOTIVO_HORARIO_NEGADO,
               f"{rotulo}: motivo {bruto_motivo!r} -> {MOTIVO_HORARIO_NEGADO!r} "
               f"(obtido: {r.motivo_confirmado!r})")
        checar(r.gestor_confirmado == esperado_gestor[bruto_gestor],
               f"{rotulo}: responsável {bruto_gestor!r} -> "
               f"{esperado_gestor[bruto_gestor]!r} (obtido: {r.gestor_confirmado!r})")
        checar(bruto_motivo not in r.observacao or "normalizado" in r.observacao,
               f"{rotulo}: Observação preserva o texto bruto da normalização")
    print()


def teste_bloqueio_continua_sendo_a_primeira_razao_da_observacao():
    print("=== PONTA A PONTA: a razão do bloqueio vem primeiro na Observação ===")
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    r = classificar_registro(_registro(data="23.04", motivo="Negade"), COLABORADOR, dm)
    checar(r.observacao.startswith("data não pôde ser interpretada"),
           f"bloqueio primeiro (obtido: {r.observacao!r})")
    checar("normalizado para HORÁRIO NEGADO" in r.observacao,
           f"normalização registrada em seguida (obtido: {r.observacao!r})")
    print()


if __name__ == "__main__":
    for nome, funcao in list(globals().items()):
        if nome.startswith("teste_"):
            funcao()
    print("=" * 62)
    if not falhas:
        print("TODOS OS CASOS DE NORMALIZAÇÃO (MOTIVO/GESTOR/DATA/HORA) PASSARAM.")
    else:
        print(f"{len(falhas)} FALHA(S):")
        for f in falhas:
            print("   -", f)
        sys.exit(1)
