"""
validacao.py

Classifica um Registro (do registro_parser) em CONFIRMADO / REVISAO / ERRO,
usando as bases carregadas pelo DataManager. Não inventa dados: quando não
há como validar algo (base vazia, campo ausente), não penaliza — apenas não
confirma.

Data e hora são tratadas como dados estruturados (ver tempo_parser.py) e
têm pesos DIFERENTES (requisito funcional definitivo):

    - DATA é OBRIGATÓRIA: uma data que não possa ser interpretada com
      segurança (ilegível, impossível, formato inesperado, campo vazio,
      ano ausente) manda o registro para REVISAO.
    - HORA é OPCIONAL: ausente ou ilegível, ela NUNCA impede o
      CONFIRMADO. Se data, matrícula, motivo e responsável estiverem
      confirmados, o registro é CONFIRMADO mesmo sem hora nenhuma.

Nenhum dos dois é corrigido ou "chutado" para um valor provável. Quando a
hora existe e é válida, é preservada em `.hora_confirmada`; quando está
ausente ou ilegível, `.hora_confirmada` é None e quem monta a exportação
deixa o campo VAZIO — nunca escreve o texto ilegível do OCR na planilha
(seria indistinguível de uma hora real). Nesse caso um aviso com o texto
bruto vai para a Observação, para auditoria: nada some em silêncio.

MOTIVO e RESPONSÁVEL (Fase 1 de precisão da extração — PROBLEMAS 3/4): a
comparação contra as bases não é mais só exata. Primeiro tenta bater
exatamente (como antes); se não bater, tenta uma correspondência
aproximada CONTROLADA (`correspondencia_aproximada.py`) contra os
candidatos daquela base — só aceita quando a similaridade passa de um
limiar e não há ambiguidade entre os dois melhores candidatos. Ambíguo ou
abaixo do limiar continua indo para REVISAO, exatamente como uma
divergência exata continuaria indo hoje. Nunca inventa um valor fora da
base.

RESPONSÁVEL: usa `resolver_responsavel` (correspondencia_aproximada.py),
que também lida com o caso opcional em que um Auxiliar de Prevenção de
Perdas anota o próprio nome junto ao gestor (ex.: "GR3 - DIANA - ESLEANE")
— esse texto residual é descartado (nunca contamina a identificação do
gestor), mas o nome do auxiliar em si não é reconhecido nem faz parte do
resultado: não é usado na planilha final, e tentar corrigi-lo por
aproximação se mostrou arriscado em nomes curtos (ex.: "Eslon"
reconhecido erroneamente como "ELTON").
"""

import unicodedata
from typing import Optional

from leitor_matriculas.parsing.registro_parser import Registro
from leitor_matriculas.parsing.tempo_parser import (
    avaliar_hora_opcional,
    interpretar_hora,
    validar_data,
)
from leitor_matriculas.validacao.correspondencia_aproximada import (
    buscar_correspondencia,
    resolver_responsavel,
)

CONFIANCA_MINIMA_MATRICULA = 0.80


def _norm(t) -> str:
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", str(t).strip().lower())
    return "".join(c for c in t if not unicodedata.combining(c))


class ResultadoValidacao(tuple):
    """
    Compatível com o tuple (status, observacao) que já era devolvido por
    `classificar_registro` (e é como os testes/`ui.py` já desempacotavam o
    resultado) — `status, observacao = classificar_registro(...)` continua
    funcionando sem alteração nenhuma.

    Além disso, expõe `.status`/`.observacao` por nome e, quando a
    correspondência aproximada (PROBLEMAS 3/4) aceitou uma correção de
    motivo/responsável, `.motivo_confirmado`/`.gestor_confirmado` com o
    valor normalizado (nunca sobrescreve o texto original do OCR — quem
    monta a exportação decide se usa a correção ou o texto bruto).

    `.hora_confirmada` segue a mesma ideia para a HORA (campo opcional): é
    o texto da hora quando ela pôde ser interpretada com segurança, e None
    quando está ausente ou ilegível — nesse caso quem exporta deixa a
    célula VAZIA em vez de escrever o texto ilegível do OCR.
    """

    def __new__(cls, status, observacao, motivo_confirmado=None, gestor_confirmado=None,
                hora_confirmada=None):
        obj = super().__new__(cls, (status, observacao))
        obj.motivo_confirmado = motivo_confirmado
        obj.gestor_confirmado = gestor_confirmado
        obj.hora_confirmada = hora_confirmada
        return obj

    @property
    def status(self):
        return self[0]

    @property
    def observacao(self):
        return self[1]


def _resolver_campo_com_correspondencia(campo, candidatos, nome_campo_legivel):
    """
    Aplica a correspondência aproximada a um campo (motivo OU gestor)
    contra os candidatos de uma base. Devolve (valor_confirmado, aviso,
    erro):
        - erro: mensagem de REVISAO (SEM_CORRESPONDENCIA/AMBIGUA), ou None
          se pôde confirmar (exato ou aproximado).
        - valor_confirmado: o texto normalizado a usar (só quando erro é None).
        - aviso: nota para a Observação quando houve correção por
          aproximação (nunca preenchido em correspondência exata).
    """
    resultado = buscar_correspondencia(campo.texto, candidatos)

    if resultado.status in ("EXATA", "APROXIMADA"):
        aviso = None
        if resultado.houve_normalizacao:
            aviso = (
                f"{nome_campo_legivel} reconhecido por aproximação: "
                f"'{resultado.valor_sugerido}' (OCR: '{resultado.texto_original}', "
                f"similaridade {resultado.similaridade:.2f})"
            )
        return resultado.valor_sugerido, aviso, None

    if resultado.status == "AMBIGUA":
        return None, None, (
            f"{nome_campo_legivel} '{campo.texto}' ambíguo entre candidatos "
            f"parecidos na base ('{resultado.valor_sugerido or ''}'"
            f"{' e ' + resultado.segundo_candidato if resultado.segundo_candidato else ''}) "
            f"-- não é possível confirmar com segurança"
        )

    # SEM_CORRESPONDENCIA (VAZIO/SEM_CANDIDATOS não chegam aqui — quem
    # chama só invoca isto quando o campo existe e a base está disponível)
    return None, None, f"{nome_campo_legivel} '{campo.texto}' não reconhecido na base"


def classificar_registro(
    registro: Registro,
    colaborador: Optional[dict],
    data_manager,
) -> ResultadoValidacao:
    """Devolve um ResultadoValidacao; status in {"CONFIRMADO","REVISAO"}."""
    # HORA é opcional e NUNCA bloqueia: é avaliada primeiro, uma única vez,
    # e o resultado acompanha TODOS os retornos abaixo -- inclusive os de
    # REVISAO por outro motivo. Assim uma hora legítima nunca é perdida só
    # porque o registro precisou ir para revisão por causa de outro campo.
    campo_hora_reg = registro.campos.get("hora")
    texto_hora = campo_hora_reg.texto if campo_hora_reg else ""
    hora_confirmada = texto_hora if interpretar_hora(texto_hora) is not None else None
    aviso_hora = avaliar_hora_opcional(texto_hora)

    if not registro.completo:
        return ResultadoValidacao(
            "REVISAO", "matrícula não identificada pelo OCR", hora_confirmada=hora_confirmada
        )

    # DATA é obrigatória: esta continua sendo uma checagem bloqueante.
    campo_data = registro.campos.get("data")
    erro_data = validar_data(campo_data.texto if campo_data else "")
    if erro_data:
        return ResultadoValidacao("REVISAO", erro_data, hora_confirmada=hora_confirmada)

    campo_matricula = registro.campos["matricula"]

    if colaborador is None:
        if data_manager.colaboradores_disponivel:
            return ResultadoValidacao(
                "REVISAO", "matrícula não encontrada na base de colaboradores",
                hora_confirmada=hora_confirmada,
            )
        return ResultadoValidacao(
            "REVISAO", "base de colaboradores indisponível", hora_confirmada=hora_confirmada
        )

    if campo_matricula.confianca is not None and campo_matricula.confianca < CONFIANCA_MINIMA_MATRICULA:
        return ResultadoValidacao(
            "REVISAO", f"confiança da matrícula baixa ({campo_matricula.confianca * 100:.0f}%)",
            hora_confirmada=hora_confirmada,
        )

    # Gestor e motivo são resolvidos de forma INDEPENDENTE um do outro (cada
    # um só contra a sua própria base -- ver PROBLEMAS 3/4) e nenhum dos
    # dois interrompe a checagem do outro: mesmo quando um falha, o outro
    # continua sendo avaliado, para que uma correção aceita num campo não
    # fique perdida só porque o outro campo precisou ir para revisão.
    # O aviso de hora ilegível entra como AVISO (nunca como erro): ele
    # documenta na Observação por que a célula Hora saiu em branco, sem
    # jamais derrubar o registro para REVISAO.
    avisos = [aviso_hora] if aviso_hora else []
    erros = []

    gestor_confirmado = None
    campo_gestor = registro.campos.get("gestor")
    if campo_gestor and data_manager.gestores_disponivel:
        resultado_responsavel = resolver_responsavel(campo_gestor.texto, data_manager.listar_gestores())
        if resultado_responsavel.status in ("EXATA", "APROXIMADA"):
            gestor_confirmado = resultado_responsavel.gestor_confirmado
            if resultado_responsavel.houve_normalizacao:
                avisos.append(
                    f"responsável reconhecido por aproximação: '{gestor_confirmado}' "
                    f"(OCR: '{campo_gestor.texto}')"
                )
        elif resultado_responsavel.status == "AMBIGUA":
            erros.append(
                f"responsável '{campo_gestor.texto}' ambíguo entre candidatos parecidos na base "
                f"-- não é possível confirmar com segurança"
            )
        else:
            erros.append(f"responsável '{campo_gestor.texto}' não reconhecido na base")

    motivo_confirmado = None
    campo_motivo = registro.campos.get("motivo")
    if campo_motivo and data_manager.motivos_disponivel:
        motivo_confirmado, aviso, erro = _resolver_campo_com_correspondencia(
            campo_motivo, data_manager.listar_motivos(), "motivo"
        )
        if erro:
            erros.append(erro)
        elif aviso:
            avisos.append(aviso)

    if erros:
        return ResultadoValidacao(
            "REVISAO", "; ".join(erros), motivo_confirmado=motivo_confirmado,
            gestor_confirmado=gestor_confirmado, hora_confirmada=hora_confirmada,
        )

    return ResultadoValidacao(
        "CONFIRMADO", "; ".join(avisos), motivo_confirmado=motivo_confirmado,
        gestor_confirmado=gestor_confirmado, hora_confirmada=hora_confirmada,
    )
