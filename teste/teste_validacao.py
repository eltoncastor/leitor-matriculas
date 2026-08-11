import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from registro_parser import Registro, CampoOcr  # noqa: E402
from validacao import classificar_registro  # noqa: E402
from data_manager import DataManager  # noqa: E402


class _DMFalso:
    def __init__(self, colaboradores_ok=True, gestores=None, motivos=None):
        self.colaboradores_disponivel = colaboradores_ok
        self.gestores_disponivel = bool(gestores)
        self.motivos_disponivel = bool(motivos)
        self._gestores = gestores or []
        self._motivos = motivos or []

    def listar_gestores(self):
        return self._gestores

    def listar_motivos(self):
        return self._motivos


def _campos_tempo_validos():
    return {
        "data": CampoOcr("23/04/2026", 0.9, None),
        "hora": CampoOcr("11:05", 0.9, None),
    }


def _reg(campos, com_tempo_valido=True):
    """
    Monta um Registro de teste. Por padrão, injeta data/hora válidas (para
    isolar, nos testes que não são sobre data/hora, a condição que
    realmente está sendo testada) -- passe com_tempo_valido=False e
    inclua "data"/"hora" em `campos` para testar cenários de data/hora.
    """
    base = _campos_tempo_validos() if com_tempo_valido else {}
    base.update(campos)
    return Registro(indice=1, campos=base)


def teste_sem_matricula():
    r = _reg({})
    status, obs = classificar_registro(r, None, _DMFalso())
    assert status == "REVISAO" and "não identificada" in obs
    print("OK: sem matrícula -> REVISAO")


def teste_matricula_nao_encontrada():
    r = _reg({"matricula": CampoOcr("28972", 0.95, None)})
    status, obs = classificar_registro(r, None, _DMFalso(colaboradores_ok=True))
    assert status == "REVISAO" and "não encontrada" in obs
    print("OK: matrícula não encontrada -> REVISAO")


def teste_base_indisponivel():
    r = _reg({"matricula": CampoOcr("28972", 0.95, None)})
    status, obs = classificar_registro(r, None, _DMFalso(colaboradores_ok=False))
    assert status == "REVISAO" and "indisponível" in obs
    print("OK: base indisponível -> REVISAO")


def teste_confianca_baixa():
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.5, None)})
    status, obs = classificar_registro(r, colaborador, _DMFalso())
    assert status == "REVISAO" and "confiança" in obs
    print("OK: confiança baixa -> REVISAO")


def teste_confirmado_sem_listas_gestor_motivo():
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "gestor": CampoOcr("Fulano", 0.9, None)})
    status, obs = classificar_registro(r, colaborador, _DMFalso())  # sem listas -> não penaliza
    assert status == "CONFIRMADO"
    print("OK: sem listas de gestor/motivo carregadas -> CONFIRMADO (não penaliza o que não pode validar)")


def teste_gestor_nao_reconhecido():
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "gestor": CampoOcr("Desconhecido", 0.9, None)})
    dm = _DMFalso(gestores=["Fulano de Tal"])
    status, obs = classificar_registro(r, colaborador, dm)
    # A observação agora usa o rótulo "responsável" (mesma renomeação já
    # aplicada na UI) -- "Desconhecido" x "Fulano de Tal" não passa nem por
    # correspondência aproximada (PROBLEMA 4), similaridade baixa demais.
    assert status == "REVISAO" and "responsável" in obs, obs
    print("OK: gestor fora da lista (mesmo com correspondência aproximada) -> REVISAO")


def teste_gestor_reconhecido_com_acento_maiuscula():
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "gestor": CampoOcr("JOSÉ", 0.9, None)})
    dm = _DMFalso(gestores=["José"])
    status, _ = classificar_registro(r, colaborador, dm)
    assert status == "CONFIRMADO"
    print("OK: comparação de gestor ignora acento/maiúscula -> CONFIRMADO")


def teste_motivo_nao_reconhecido():
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "motivo": CampoOcr("???", 0.9, None)})
    dm = _DMFalso(motivos=["RH", "ADM"])
    status, obs = classificar_registro(r, colaborador, dm)
    assert status == "REVISAO" and "motivo" in obs
    print("OK: motivo fora da lista -> REVISAO")


def teste_dm_real_sem_bases():
    # Integração leve com o DataManager de verdade (sem os XLSX ainda existindo)
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None)})
    dm = DataManager(pasta_dados="/caminho/que/nao/existe")
    status, obs = classificar_registro(r, colaborador, dm)
    assert status == "CONFIRMADO"  # sem gestores/motivos carregados, não penaliza
    print("OK: DataManager real sem bases + matrícula ok -> CONFIRMADO")


# ---------------------------------------------------------------------------
# Validação estruturada de data/hora (requisito funcional definitivo)
# ---------------------------------------------------------------------------

def teste_data_ausente():
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "hora": CampoOcr("11:05", 0.9, None)},
             com_tempo_valido=False)
    status, obs = classificar_registro(r, None, _DMFalso())
    assert status == "REVISAO" and "data" in obs.lower()
    print("OK: data ausente -> REVISAO")


def teste_hora_ausente_nao_impede_confirmacao():
    """
    REQUISITO FUNCIONAL DEFINITIVO: a HORA é opcional. Com data, matrícula,
    motivo e responsável confirmados, a ausência da hora NÃO impede o
    CONFIRMADO.
    """
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "data": CampoOcr("23/04/2026", 0.9, None)},
             com_tempo_valido=False)
    resultado = classificar_registro(r, colaborador, _DMFalso())
    assert resultado.status == "CONFIRMADO", resultado.observacao
    # Hora ausente é situação normal: não gera nem aviso nem valor.
    assert resultado.hora_confirmada is None
    assert "hora" not in resultado.observacao.lower()
    print("OK: hora ausente NÃO impede CONFIRMADO (campo opcional)")


def teste_hora_ausente_com_data_ausente_bloqueia_so_pela_data():
    """Sem data e sem hora, quem bloqueia é só a DATA -- a hora não entra."""
    r = _reg({"matricula": CampoOcr("28972", 0.95, None)}, com_tempo_valido=False)
    status, obs = classificar_registro(r, None, _DMFalso())
    assert status == "REVISAO" and "data" in obs.lower()
    assert "hora" not in obs.lower(), f"a hora não pode ser motivo de revisão: {obs}"
    print("OK: data e hora ausentes -> REVISAO apenas por causa da data")


def teste_hora_valida_e_preservada():
    """Quando a hora existe e é legível, é preservada normalmente."""
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None)})  # data/hora válidas por padrão
    resultado = classificar_registro(r, colaborador, _DMFalso())
    assert resultado.status == "CONFIRMADO"
    assert resultado.hora_confirmada == "11:05", resultado.hora_confirmada
    print("OK: hora válida é preservada em .hora_confirmada")


def teste_hora_preservada_mesmo_em_registro_de_revisao():
    """
    Uma hora legítima não pode ser perdida só porque o registro foi para
    REVISAO por outro motivo (ex.: matrícula não encontrada na base).
    """
    r = _reg({"matricula": CampoOcr("28972", 0.95, None)})
    resultado = classificar_registro(r, None, _DMFalso(colaboradores_ok=True))
    assert resultado.status == "REVISAO"
    assert resultado.hora_confirmada == "11:05", resultado.hora_confirmada
    print("OK: hora válida sobrevive a um REVISAO causado por outro campo")


def teste_data_impossivel():
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "data": CampoOcr("31/04/2026", 0.9, None),
              "hora": CampoOcr("11:05", 0.9, None)}, com_tempo_valido=False)
    status, obs = classificar_registro(r, None, _DMFalso())
    assert status == "REVISAO"
    print("OK: data impossível (31/04) -> REVISAO")


def teste_data_sem_ano():
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "data": CampoOcr("23/04", 0.9, None),
              "hora": CampoOcr("11:05", 0.9, None)}, com_tempo_valido=False)
    status, obs = classificar_registro(r, None, _DMFalso())
    assert status == "REVISAO"
    print("OK: data sem ano -> REVISAO (nunca inventa o ano)")


def teste_hora_impossivel_nao_impede_confirmacao():
    """
    REQUISITO FUNCIONAL DEFINITIVO: a ILEGIBILIDADE da hora também não
    impede o CONFIRMADO. A hora ilegível não vai para a planilha (seria
    indistinguível de uma hora real), mas o texto bruto é preservado na
    Observação -- nunca some em silêncio.
    """
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "data": CampoOcr("23/04/2026", 0.9, None),
              "hora": CampoOcr("25:99", 0.9, None)}, com_tempo_valido=False)
    resultado = classificar_registro(r, colaborador, _DMFalso())
    assert resultado.status == "CONFIRMADO", resultado.observacao
    # Não usa o valor impossível...
    assert resultado.hora_confirmada is None
    # ...mas registra o texto bruto na Observação, para auditoria.
    assert "25:99" in resultado.observacao, resultado.observacao
    print("OK: hora impossível (25:99) NÃO impede CONFIRMADO; texto bruto vai para a Observação")


def teste_data_hora_formato_inesperado():
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "data": CampoOcr("vinte e três de abril", 0.9, None),
              "hora": CampoOcr("11:05", 0.9, None)}, com_tempo_valido=False)
    status, obs = classificar_registro(r, None, _DMFalso())
    assert status == "REVISAO"
    print("OK: formato de data inesperado -> REVISAO")


def teste_data_hora_validas_nao_bloqueiam_confirmacao():
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None)})  # data/hora válidas por padrão
    status, obs = classificar_registro(r, colaborador, _DMFalso())
    assert status == "CONFIRMADO"
    print("OK: data/hora válidas não impedem CONFIRMADO")


def teste_data_com_ano_de_2_digitos():
    colaborador = {"matricula": "28972", "nome": "X", "cargo": "Y", "setor": "Z"}
    r = _reg({"matricula": CampoOcr("28972", 0.95, None), "data": CampoOcr("23/04/26", 0.9, None),
              "hora": CampoOcr("11:05", 0.9, None)}, com_tempo_valido=False)
    status, obs = classificar_registro(r, colaborador, _DMFalso())
    assert status == "CONFIRMADO"
    print("OK: ano com 2 dígitos (26 -> 2026) é aceito -> CONFIRMADO")


if __name__ == "__main__":
    testes = [v for k, v in list(globals().items()) if k.startswith("teste_")]
    falhas = 0
    for t in testes:
        try:
            t()
        except AssertionError as exc:
            falhas += 1
            print(f"FALHOU: {t.__name__}: {exc}")
    print("=" * 50)
    print(f"{len(testes) - falhas}/{len(testes)} passaram" if falhas else f"TODOS OS {len(testes)} TESTES PASSARAM.")
    if falhas:
        sys.exit(1)
