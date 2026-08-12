"""
teste/teste_integridade_captura.py

Fase 12 -- segurança da confirmação e detecção de CAMPO PERDIDO.

O caso que originou esta fase (medição da Fase 11, folha real, matrícula
26319): a hora `07:49` estava escrita e legível no papel, o OCR chegou a
lê-la como `07:4`, o parser não conseguiu associá-la à coluna HORA (o
filtro de formato exige dois dígitos depois do separador) e o registro
saiu **CONFIRMADO com a coluna Hora vazia**. O dado não estava ausente:
estava perdido, em silêncio.

O que se testa aqui é a DISTINÇÃO, não a obrigatoriedade:

    hora ausente na folha, sem vestígio  -> segue opcional, CONFIRMA
    hora com vestígio na linha           -> REVISAO ("não capturada")

Mais os campos que já bloqueavam (matrícula, data, motivo, responsável),
para garantir que continuam bloqueando, e a revisão manual, para garantir
que ela não vira uma porta dos fundos para confirmar o que o fluxo
automático barrou.

Não usa PaddleOCR nem as planilhas reais.

Uso:
    python teste\\teste_integridade_captura.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.parsing.registro_parser import Registro, CampoOcr  # noqa: E402
from leitor_matriculas.validacao.integridade import (  # noqa: E402
    detectar_campo_perdido,
    detectar_campos_perdidos,
)
from leitor_matriculas.validacao.regras import classificar_registro  # noqa: E402

MOTIVOS = ["HORÁRIO NEGADO", "RH", "ADM", "ARMÁRIOS", "FOLGA FIXA",
           "ESQUECEU CRACHÁ", "TREINAMENTO"]
GESTORES = ["GR3 - BEATRIZ", "GR5 - OTAVIO", "GRL - LUCIA", "TAMIRES", "MARTIM",
            "GR3", "GR5", "GRL"]
COLABORADOR = {"matricula": "26319", "nome": "FULANO DE TAL",
               "cargo": "ATENDENTE", "setor": "VENDAS"}

falhas = []


def checar(cond, msg):
    print(("  OK    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


class _DMFalso:
    colaboradores_disponivel = True
    gestores_disponivel = True
    motivos_disponivel = True

    def listar_gestores(self):
        return list(GESTORES)

    def listar_motivos(self):
        return list(MOTIVOS)

    def buscar_colaborador(self, matricula):
        return COLABORADOR if str(matricula) == "26319" else None


def _registro(data="14/04/26", hora="07:53", matricula="26319",
              motivo="HORÁRIO NEGADO", gestor="TAMIRES", sobras=()):
    """Registro sintético. `sobras` = texto que o OCR leu na linha e o
    parser não associou a coluna nenhuma (o `nao_associados` real)."""
    campos = {}
    if data:
        campos["data"] = CampoOcr(data, 0.9, None)
    if hora:
        campos["hora"] = CampoOcr(hora, 0.9, None)
    if matricula:
        campos["matricula"] = CampoOcr(matricula, 0.99, None)
    if motivo:
        campos["motivo"] = CampoOcr(motivo, 0.9, None)
    if gestor:
        campos["gestor"] = CampoOcr(gestor, 0.9, None)
    return Registro(
        indice=1, campos=campos,
        nao_associados=[CampoOcr(t, 0.9, None) for t in sobras],
    )


# ---------------------------------------------------------------------------
# 1. O CASO REAL: 26319
# ---------------------------------------------------------------------------

def teste_caso_real_26319_hora_perdida():
    print("=== CASO REAL 26319: hora lida pelo OCR e perdida pelo parser ===")
    dm = _DMFalso()
    # Exatamente o que o parser produziu na folha real: hora ausente do
    # campo, e o texto '07:4' sobrando na linha.
    registro = _registro(hora="", sobras=["07:4", "tiago", "Clubi Prot."])

    checar(detectar_campo_perdido(registro, "hora") == "07:4",
           f"a evidência é encontrada (obtido: {detectar_campo_perdido(registro, 'hora')!r})")

    resultado = classificar_registro(registro, COLABORADOR, dm)
    checar(resultado.status == "REVISAO",
           f"26319 com hora perdida NÃO é confirmado (obtido: {resultado.status})")
    checar("hora" in resultado.observacao and "07:4" in resultado.observacao,
           f"a Observação nomeia o campo e mostra o texto lido "
           f"(obtido: {resultado.observacao!r})")
    checar(resultado.hora_confirmada is None,
           "nenhuma hora é inventada para preencher a lacuna")
    print()


# ---------------------------------------------------------------------------
# 2. HORA -- os dois cenários NÃO são equivalentes
# ---------------------------------------------------------------------------

def teste_hora_realmente_ausente_continua_opcional():
    print("=== HORA: ausente de verdade continua sendo campo opcional ===")
    dm = _DMFalso()
    # Sem hora e sem nenhum vestígio numérico na linha: não há evidência de
    # perda, então a regra opcional de sempre continua valendo.
    registro = _registro(hora="", sobras=["Micaila", "Atend. Ferramentas"])
    checar(detectar_campo_perdido(registro, "hora") is None,
           "sem vestígio, nenhuma evidência de perda é inventada")
    resultado = classificar_registro(registro, COLABORADOR, dm)
    checar(resultado.status == "CONFIRMADO",
           f"hora ausente sem evidência NÃO bloqueia (obtido: {resultado.status} -- {resultado.observacao})")

    # E sem sobra nenhuma na linha (registro montado à mão, revisão etc.).
    resultado2 = classificar_registro(_registro(hora=""), COLABORADOR, dm)
    checar(resultado2.status == "CONFIRMADO",
           f"linha sem `nao_associados` continua confirmando (obtido: {resultado2.status})")
    print()


def teste_hora_ilegivel_continua_nao_bloqueando():
    print("=== HORA: presente mas ilegível continua sem bloquear ===")
    dm = _DMFalso()
    resultado = classificar_registro(_registro(hora="90:24"), COLABORADOR, dm)
    checar(resultado.status == "CONFIRMADO",
           f"hora impossível não bloqueia (obtido: {resultado.status})")
    checar(resultado.hora_confirmada is None and "90:24" in resultado.observacao,
           "célula sai vazia e o texto bruto fica na Observação")
    print()


def teste_variacoes_de_vestigio_de_hora():
    print("=== HORA: formas reais em que o vestígio aparece ===")
    # Casos observados nas 5 folhas reais.
    for sobra, esperado in [("07:4", True),              # minuto truncado
                            ("11:0s Card", True),         # dígito lido como letra
                            ("1108 fernamenta", True),    # separador comido, hora colada ao nome
                            ("Micaila", False),           # texto sem número
                            ("Manutencao", False),
                            ("exp", False)]:
        registro = _registro(hora="", sobras=[sobra])
        obtido = detectar_campo_perdido(registro, "hora") is not None
        checar(obtido == esperado,
               f"{sobra!r} -> evidência de hora perdida = {esperado} (obtido: {obtido})")

    # Guarda contra falso positivo: uma matrícula curta de 4 dígitos não
    # pode ser confundida com hora colada -- "3875" seria "38:75", que não
    # existe como hora.
    registro = _registro(hora="", matricula="", sobras=["3875"])
    checar(detectar_campo_perdido(registro, "hora") is None,
           "'3875' (matrícula de 4 dígitos) NÃO é lido como hora perdida")
    print()


# ---------------------------------------------------------------------------
# 3. OS CAMPOS QUE JÁ BLOQUEAVAM CONTINUAM BLOQUEANDO
# ---------------------------------------------------------------------------

def teste_campos_obrigatorios_continuam_bloqueando():
    print("=== Campos obrigatórios ausentes continuam impedindo CONFIRMADO ===")
    dm = _DMFalso()
    for rotulo, registro, trecho in [
        ("matrícula", _registro(matricula=""), "matrícula não identificada"),
        ("data", _registro(data=""), "data não identificada"),
        ("motivo", _registro(motivo=""), "motivo não identificado"),
        ("responsável", _registro(gestor=""), "responsável não identificado"),
    ]:
        resultado = classificar_registro(registro, COLABORADOR, dm)
        checar(resultado.status == "REVISAO" and trecho in resultado.observacao,
               f"{rotulo} ausente -> REVISAO nomeando o campo "
               f"(obtido: {resultado.status} -- {resultado.observacao})")
    print()


def teste_observacao_mostra_o_texto_perdido():
    print("=== Rastreabilidade: a Observação mostra o que o OCR chegou a ler ===")
    dm = _DMFalso()
    # Caso real da folha 4: a matrícula saiu grudada no setor e o parser
    # não a associou -- o bloqueio já existia, faltava dizer ao operador
    # que o número ESTÁ na folha.
    registro = _registro(matricula="", sobras=["Riam", "28972 tente de Lga"])
    resultado = classificar_registro(registro, None, dm)
    checar(resultado.status == "REVISAO", f"continua REVISAO (obtido: {resultado.status})")
    checar("28972" in resultado.observacao,
           f"a Observação mostra o texto perdido (obtido: {resultado.observacao!r})")

    # Caso real da folha 1: a data "13|04|26" saiu como '13104126'.
    registro_data = _registro(data="", sobras=["13104126", "Idalo", "Eletro"])
    resultado_data = classificar_registro(registro_data, COLABORADOR, dm)
    checar("13104126" in resultado_data.observacao,
           f"idem para a data (obtido: {resultado_data.observacao!r})")
    print()


def teste_deteccao_conjunta():
    print("=== detectar_campos_perdidos devolve todos os campos com evidência ===")
    registro = _registro(hora="", data="", sobras=["07:4", "13104126", "Idalo"])
    perdidos = detectar_campos_perdidos(registro)
    checar(perdidos.get("hora") == "07:4" and perdidos.get("data") == "13104126",
           f"hora e data detectadas juntas (obtido: {perdidos})")
    checar(detectar_campos_perdidos(_registro()) == {},
           "registro completo não acusa perda nenhuma")
    print()


def teste_anotacao_interna_nao_vira_evidencia():
    print("=== Anotação interna do pipeline não pode virar evidência ===")
    # `_reparar_data_hora_mescladas` deixa esta marca em `nao_associados`
    # para auditoria. Ela contém data E hora: se contasse como evidência,
    # o detector dispararia sozinho em toda linha reparada.
    registro = _registro(hora="", sobras=["[data/hora mescladas no OCR: '28.04.26 14:24']"])
    checar(detectar_campo_perdido(registro, "hora") is None,
           "a marca entre colchetes é ignorada")
    resultado = classificar_registro(registro, COLABORADOR, _DMFalso())
    checar(resultado.status == "CONFIRMADO",
           f"e não bloqueia o registro (obtido: {resultado.status} -- {resultado.observacao})")
    print()


# ---------------------------------------------------------------------------
# 4. A REVISÃO MANUAL NÃO PODE SER UMA PORTA DOS FUNDOS
# ---------------------------------------------------------------------------

def teste_revisao_manual_nao_contorna_a_integridade():
    print("=== Revisão manual: a mesma validação, sem atalho ===")
    dm = _DMFalso()
    sobras = ["07:4", "tiago"]

    # O operador abre a revisão e confirma SEM preencher a hora: a
    # evidência continua valendo e o registro continua em REVISAO.
    ainda_sem_hora = Registro(
        indice=0,
        campos={
            "data": CampoOcr("14/04/26", 1.0, None),
            "matricula": CampoOcr("26319", 1.0, None),
            "motivo": CampoOcr("HORÁRIO NEGADO", 1.0, None),
            "gestor": CampoOcr("TAMIRES", 1.0, None),
        },
        nao_associados=[CampoOcr(t, None, None) for t in sobras],
    )
    resultado = classificar_registro(ainda_sem_hora, COLABORADOR, dm)
    checar(resultado.status == "REVISAO",
           f"confirmar sem preencher a hora NÃO resolve (obtido: {resultado.status})")

    # O operador olha a foto e digita a hora: aí sim confirma.
    com_hora = Registro(
        indice=0,
        campos=dict(ainda_sem_hora.campos, hora=CampoOcr("07:49", 1.0, None)),
        nao_associados=[CampoOcr(t, None, None) for t in sobras],
    )
    resultado2 = classificar_registro(com_hora, COLABORADOR, dm)
    checar(resultado2.status == "CONFIRMADO" and resultado2.hora_confirmada == "07:49",
           f"com a hora digitada, confirma (obtido: {resultado2.status}/{resultado2.hora_confirmada!r})")
    print()


def teste_revisao_manual_nao_aceita_valor_fora_da_base():
    print("=== Revisão manual: valor incompatível com a base continua em REVISAO ===")
    dm = _DMFalso()
    # Mesmo digitado por uma pessoa, um responsável que não existe na base
    # não pode ser confirmado (o lote real teve um responsável errado
    # introduzido justamente nesta etapa).
    registro = _registro(gestor="NOME QUE NAO EXISTE NA BASE")
    resultado = classificar_registro(registro, COLABORADOR, dm)
    checar(resultado.status == "REVISAO",
           f"responsável fora da base -> REVISAO (obtido: {resultado.status} -- {resultado.observacao})")

    registro_mat = _registro(matricula="00000")
    resultado_mat = classificar_registro(registro_mat, None, dm)
    checar(resultado_mat.status == "REVISAO",
           f"matrícula fora da base -> REVISAO (obtido: {resultado_mat.status})")
    print()


TESTES = [
    teste_caso_real_26319_hora_perdida,
    teste_hora_realmente_ausente_continua_opcional,
    teste_hora_ilegivel_continua_nao_bloqueando,
    teste_variacoes_de_vestigio_de_hora,
    teste_campos_obrigatorios_continuam_bloqueando,
    teste_observacao_mostra_o_texto_perdido,
    teste_deteccao_conjunta,
    teste_anotacao_interna_nao_vira_evidencia,
    teste_revisao_manual_nao_contorna_a_integridade,
    teste_revisao_manual_nao_aceita_valor_fora_da_base,
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
