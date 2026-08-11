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

DATA e HORA saem sempre em FORMATO CANÔNICO (`dd/mm/aa` e `HH:MM`, via
`normalizar_data`/`normalizar_hora`), nunca com o separador que o OCR
leu — a planilha não pode misturar "14.04.26", "14-04-26" e "28/04/26",
nem "18.59" e "07:53". Normalizar o formato não afrouxa a validação: uma
hora impossível ("90:24") continua ilegível e a célula sai vazia; uma
data que não possa ser interpretada continua bloqueando (-> REVISAO).

MOTIVO e RESPONSÁVEL (Fase 1 de precisão da extração — PROBLEMAS 3/4): a
comparação contra as bases não é mais só exata. Primeiro tenta bater
exatamente (como antes); se não bater, tenta uma correspondência
aproximada CONTROLADA (`correspondencia_aproximada.py`) contra os
candidatos daquela base — só aceita quando a similaridade passa de um
limiar e não há ambiguidade entre os dois melhores candidatos. Ambíguo ou
abaixo do limiar continua indo para REVISAO, exatamente como uma
divergência exata continuaria indo hoje. Nunca inventa um valor fora da
base.

MOTIVO: usa `resolver_motivo` (correspondencia_aproximada.py), que além
da correspondência aproximada canonicaliza a família de sinônimos
"negado" da base ("NEGADO"/"NEGADA"/"H. NEGADO"/"Horário negado") para
`HORÁRIO NEGADO` quando a leitura veio corrompida do OCR — é justamente
por serem sinônimos quase idênticos entre si que essas entradas geravam
AMBIGUA e mandavam para REVISAO um registro cuja evidência era clara. Um
match EXATO nunca é canonicalizado, e a normalização fica registrada na
Observação.

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
    normalizar_data,
    normalizar_hora,
    validar_data,
)
from leitor_matriculas.validacao.correspondencia_aproximada import (
    resolver_motivo,
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

    `.data_confirmada` é a DATA já no formato canônico `dd/mm/aa`, ou None
    quando não pôde ser interpretada com segurança (aí o registro já vai
    para REVISAO de qualquer forma). `.matricula_confirmada` é a matrícula
    só com dígitos depois da recuperação contextual, ou None quando não
    houve recuperação a aplicar.
    """

    def __new__(cls, status, observacao, motivo_confirmado=None, gestor_confirmado=None,
                hora_confirmada=None, data_confirmada=None, matricula_confirmada=None):
        obj = super().__new__(cls, (status, observacao))
        obj.motivo_confirmado = motivo_confirmado
        obj.gestor_confirmado = gestor_confirmado
        obj.hora_confirmada = hora_confirmada
        obj.data_confirmada = data_confirmada
        obj.matricula_confirmada = matricula_confirmada
        return obj

    @property
    def status(self):
        return self[0]

    @property
    def observacao(self):
        return self[1]


def _resolver_motivo_do_registro(campo, candidatos):
    """
    Resolve o MOTIVO contra a base (ver
    `correspondencia_aproximada.resolver_motivo`). Devolve
    (valor_confirmado, aviso, erro):
        - erro: mensagem de REVISAO (SEM_CORRESPONDENCIA/AMBIGUA), ou None
          se pôde confirmar (exato, aproximado ou normalizado).
        - valor_confirmado: o texto a usar (só quando erro é None).
        - aviso: nota para a Observação quando houve correção por
          aproximação ou normalização da família "negado" (nunca
          preenchido em correspondência exata).
    """
    resultado = resolver_motivo(campo.texto, candidatos)

    if resultado.status == "EXATA":
        return resultado.motivo_confirmado, None, None

    if resultado.status == "NORMALIZADA":
        return resultado.motivo_confirmado, (
            f"motivo normalizado para {resultado.motivo_confirmado} a partir do OCR: "
            f"'{resultado.texto_original}'"
        ), None

    if resultado.status == "APROXIMADA":
        return resultado.motivo_confirmado, (
            f"motivo reconhecido por aproximação: '{resultado.motivo_confirmado}' "
            f"(OCR: '{resultado.texto_original}', similaridade {resultado.similaridade:.2f})"
        ), None

    if resultado.status == "AMBIGUA":
        return None, None, (
            f"motivo '{campo.texto}' ambíguo entre candidatos "
            f"parecidos na base"
            f"{' (' + resultado.segundo_candidato + ')' if resultado.segundo_candidato else ''} "
            f"-- não é possível confirmar com segurança"
        )

    # SEM_CORRESPONDENCIA (VAZIO/SEM_CANDIDATOS não chegam aqui — quem
    # chama só invoca isto quando o campo existe e a base está disponível)
    return None, None, f"motivo '{campo.texto}' não reconhecido na base"


def classificar_registro(
    registro: Registro,
    colaborador: Optional[dict],
    data_manager,
    resultado_matricula=None,
) -> ResultadoValidacao:
    """
    Devolve um ResultadoValidacao; status in {"CONFIRMADO","REVISAO"}.

    `resultado_matricula` (opcional) é o `ResultadoMatricula` da
    recuperação contextual da matrícula (ver
    `validacao/recuperacao_matricula.py`), quando quem chama já a
    executou para poder consultar a base. É opcional de propósito: sem
    ele, o comportamento é exatamente o anterior — o parâmetro só
    acrescenta o bloqueio por ambiguidade e a nota de recuperação na
    observação.
    """
    # HORA é opcional e NUNCA bloqueia: é avaliada primeiro, uma única vez,
    # e o resultado acompanha TODOS os retornos abaixo -- inclusive os de
    # REVISAO por outro motivo. Assim uma hora legítima nunca é perdida só
    # porque o registro precisou ir para revisão por causa de outro campo.
    # `normalizar_hora` devolve a hora já em HH:MM (ou None quando ilegível):
    # a planilha nunca repete o separador que o OCR leu ("18.59" -> "18:59").
    campo_hora_reg = registro.campos.get("hora")
    texto_hora = campo_hora_reg.texto if campo_hora_reg else ""
    hora_confirmada = normalizar_hora(texto_hora)
    aviso_hora = avaliar_hora_opcional(texto_hora)

    # DATA canônica (dd/mm/aa) -- calculada uma vez e devolvida em todos os
    # retornos, pelo mesmo motivo da hora: se a data é legível, a planilha
    # deve mostrá-la normalizada mesmo num registro que foi para REVISAO
    # por causa de outro campo.
    campo_data = registro.campos.get("data")
    texto_data = campo_data.texto if campo_data else ""
    data_confirmada = normalizar_data(texto_data)

    matricula_confirmada = None
    if resultado_matricula is not None and resultado_matricula.matricula:
        matricula_confirmada = resultado_matricula.matricula

    # GESTOR e MOTIVO são resolvidos AQUI, antes de qualquer retorno
    # bloqueante, pelo mesmo motivo da hora e da data: o resultado
    # acompanha TODOS os retornos abaixo. Antes eles só eram resolvidos no
    # fim da função, então um registro barrado mais cedo (data ilegível,
    # matrícula fora da base...) chegava à planilha com o texto CRU do OCR
    # nessas colunas -- exatamente o "Hiv. Nigado"/"Negade" que não pode
    # aparecer na saída final. Resolver antes não afrouxa nada: os erros
    # que estes dois campos produzem continuam sendo aplicados no fim, e
    # nenhuma checagem bloqueante mudou de lugar.
    #
    # Cada um é resolvido de forma INDEPENDENTE do outro (cada um só
    # contra a sua própria base -- ver PROBLEMAS 3/4): mesmo quando um
    # falha, o outro continua sendo avaliado, para que uma correção aceita
    # num campo não fique perdida só porque o outro precisou ir para
    # revisão.
    erros_campos = []
    avisos_campos = []

    gestor_confirmado = None
    campo_gestor = registro.campos.get("gestor")
    if campo_gestor and data_manager.gestores_disponivel:
        resultado_responsavel = resolver_responsavel(campo_gestor.texto, data_manager.listar_gestores())
        if resultado_responsavel.status in ("EXATA", "APROXIMADA"):
            gestor_confirmado = resultado_responsavel.gestor_confirmado
            if resultado_responsavel.houve_normalizacao:
                avisos_campos.append(
                    f"responsável reconhecido por aproximação: '{gestor_confirmado}' "
                    f"(OCR: '{campo_gestor.texto}')"
                )
        elif resultado_responsavel.status == "AMBIGUA":
            erros_campos.append(
                f"responsável '{campo_gestor.texto}' ambíguo entre candidatos parecidos na base "
                f"-- não é possível confirmar com segurança"
            )
        else:
            erros_campos.append(f"responsável '{campo_gestor.texto}' não reconhecido na base")

    motivo_confirmado = None
    campo_motivo = registro.campos.get("motivo")
    if campo_motivo and data_manager.motivos_disponivel:
        motivo_confirmado, aviso_motivo, erro_motivo = _resolver_motivo_do_registro(
            campo_motivo, data_manager.listar_motivos()
        )
        if erro_motivo:
            erros_campos.append(erro_motivo)
        elif aviso_motivo:
            avisos_campos.append(aviso_motivo)

    def _resultado(status, observacao, **extras):
        extras.setdefault("hora_confirmada", hora_confirmada)
        extras.setdefault("data_confirmada", data_confirmada)
        extras.setdefault("matricula_confirmada", matricula_confirmada)
        extras.setdefault("motivo_confirmado", motivo_confirmado)
        extras.setdefault("gestor_confirmado", gestor_confirmado)
        return ResultadoValidacao(status, observacao, **extras)

    def _bloqueio(motivo_do_bloqueio):
        """REVISAO por uma checagem bloqueante. A razão do bloqueio vem
        primeiro (é o que o operador precisa ler), mas os avisos de
        normalização de motivo/responsável vão junto: eles carregam o
        texto CRU do OCR, que sai das colunas normalizadas e não pode
        sumir da auditoria."""
        partes = [motivo_do_bloqueio] + avisos_campos
        return _resultado("REVISAO", "; ".join(partes))

    if not registro.completo:
        return _bloqueio("matrícula não identificada pelo OCR")

    # DATA é obrigatória: esta continua sendo uma checagem bloqueante.
    erro_data = validar_data(texto_data)
    if erro_data:
        return _bloqueio(erro_data)

    campo_matricula = registro.campos["matricula"]

    # Recuperação contextual da matrícula: quando duas leituras plausíveis
    # existem DE VERDADE na base, são duas pessoas possíveis -- escolher
    # uma seria exatamente o "CONFIRMADO incorreto" que o sistema evita.
    if resultado_matricula is not None and resultado_matricula.status == "AMBIGUA":
        candidatos = ", ".join(resultado_matricula.candidatos or [])
        return _bloqueio(
            f"matrícula '{resultado_matricula.texto_original}' ambígua -- "
            f"mais de uma leitura existe na base ({candidatos})"
        )

    if resultado_matricula is not None and resultado_matricula.status == "IRRECUPERAVEL":
        return _bloqueio(
            f"matrícula '{resultado_matricula.texto_original}' não pôde ser "
            f"convertida com segurança para dígitos"
        )

    if colaborador is None:
        if data_manager.colaboradores_disponivel:
            return _bloqueio("matrícula não encontrada na base de colaboradores")
        return _bloqueio("base de colaboradores indisponível")

    if campo_matricula.confianca is not None and campo_matricula.confianca < CONFIANCA_MINIMA_MATRICULA:
        return _bloqueio(
            f"confiança da matrícula baixa ({campo_matricula.confianca * 100:.0f}%)"
        )

    # Passadas as checagens bloqueantes, só resta aplicar o que gestor e
    # motivo (já resolvidos lá em cima) apuraram.
    # O aviso de hora ilegível entra como AVISO (nunca como erro): ele
    # documenta na Observação por que a célula Hora saiu em branco, sem
    # jamais derrubar o registro para REVISAO.
    avisos = [aviso_hora] if aviso_hora else []
    # Recuperação da matrícula aceita (ex.: "+" lido como 7, confirmado
    # por existir só essa leitura na base) fica registrada na Observação
    # -- o operador precisa poder ver que aquele número foi corrigido.
    if resultado_matricula is not None and resultado_matricula.houve_recuperacao:
        avisos.append(
            f"matrícula recuperada: '{resultado_matricula.texto_original}' -> "
            f"'{resultado_matricula.matricula}' (confirmada na base de colaboradores)"
        )
    avisos.extend(avisos_campos)

    if erros_campos:
        return _resultado("REVISAO", "; ".join(erros_campos))

    return _resultado("CONFIRMADO", "; ".join(avisos))
