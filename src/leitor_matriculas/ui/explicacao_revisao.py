"""
explicacao_revisao.py

Traduz o que o MOTOR DE EVIDÊNCIAS (Fase 17) registrou para o texto que o
operador lê na aba Revisão: qual campo levou o registro a REVISAO, o que o
OCR tinha lido, o que foi normalizado e o que a base respondeu.

FRONTEIRA DESTA CAMADA — ela só LÊ. Não valida, não corrige, não decide, e
não escreve em campo nenhum do formulário. O único caminho para sair de
REVISAO continua sendo `_revisao_confirmar`, que reconstrói o `Registro` e
reroda `classificar_registro` (proteção da Fase 12). Nada aqui encurta
esse caminho.

POR QUE UM MÓDULO SEPARADO, e não texto solto dentro de `ui/app.py`: aqui
não se importa Tkinter. A tradução é função pura de dados puros (a lista
de dicts que `DossieRegistro.como_dicionarios()` produz), então dá para
testá-la sem abrir janela — que é a mesma razão pela qual a Fase 10 criou
o contrato programático da revisão em vez de deixar o teste caçar widgets
na árvore do Tk.

SUGESTÃO DE VALOR: deliberadamente NÃO existe. A medição da Fase 18 sobre
as 5 folhas reais mostrou que, nas 17 correspondências reprovadas, o
dossiê não carrega candidato nenhum — `resolver_motivo`/`resolver_responsavel`
devolvem None quando recusam, e é isso que fica registrado. Fabricar um
candidato aqui exigiria refazer a busca na base, ou seja, mover decisão
para a camada de apresentação. O que se mostra no lugar é o CONTEXTO
medido e aprovado na Fase 16 (quais responsáveis o lote realmente usa),
que informa sem escolher.
"""

import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from leitor_matriculas.parsing.tempo_parser import interpretar_data, interpretar_hora
from leitor_matriculas.validacao import evidencias as ev

# Nome do campo como o operador o vê na folha e no formulário.
ROTULOS = {
    "data": "Data",
    "hora": "Hora",
    "matricula": "Matrícula",
    "motivo": "Motivo",
    "gestor": "Responsável",
}


@dataclass
class ExplicacaoRevisao:
    """O que a aba Revisão mostra sobre a linha atual."""
    campos_bloqueantes: List[str] = field(default_factory=list)
    titulo: str = ""
    detalhes: List[str] = field(default_factory=list)
    por_campo: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def vazia(self) -> bool:
        return not self.detalhes and not self.campos_bloqueantes

    def como_texto(self) -> str:
        if self.vazia:
            return ""
        return "\n".join([self.titulo] + [f"  • {d}" for d in self.detalhes])


def _rotulo(campo: str) -> str:
    return ROTULOS.get(campo, campo)


def _primeira(evidencias, campo, tipo):
    for e in evidencias:
        if e.get("campo") == campo and e.get("tipo") == tipo:
            return e
    return None


def _frases_do_campo(evidencias, campo) -> List[str]:
    """
    A cadeia daquele campo em linguagem de operador: o que o OCR leu, o
    que virou depois da normalização, o que a base respondeu e o que a
    regra concluiu. Nunca expõe nome de tipo/origem interna.
    """
    frases = []

    bruto = _primeira(evidencias, campo, ev.TIPO_OCR_BRUTO)
    ausencia = _primeira(evidencias, campo, ev.TIPO_AUSENCIA)
    if bruto is not None:
        frases.append(f"o OCR leu {bruto.get('valor_observado')!r} nesta coluna")
    elif ausencia is not None:
        frases.append("a coluna ficou vazia: o OCR não associou nenhum texto a ela")

    conflito = _primeira(evidencias, campo, ev.TIPO_CONFLITO)
    if conflito is not None:
        suspeito = conflito.get("valor_observado")
        frases.append(
            f"mas o OCR leu {suspeito!r} nesta linha, que tem a forma de "
            f"{_rotulo(campo).lower()} -- o dado pode estar na folha e ter se perdido"
            if bruto is None else
            f"há um conflito nesta linha: {suspeito!r}"
        )

    normalizacao = _primeira(evidencias, campo, ev.TIPO_NORMALIZACAO)
    if normalizacao is not None:
        frases.append(
            f"foi reescrito como {normalizacao.get('valor_relacionado')!r} "
            f"({normalizacao.get('motivo')})"
        )

    contexto = _primeira(evidencias, campo, ev.TIPO_CONTEXTO)
    if contexto is not None:
        frases.append(
            f"completado com apoio das outras folhas do lote: "
            f"{contexto.get('valor_observado')!r} -> {contexto.get('valor_relacionado')!r}"
        )

    correspondencia = _primeira(evidencias, campo, ev.TIPO_CORRESPONDENCIA_BASE)
    if correspondencia is not None:
        if correspondencia.get("resultado") == ev.FAVORAVEL and correspondencia.get("valor_relacionado"):
            frases.append(f"a base reconheceu como {correspondencia.get('valor_relacionado')!r}")
        elif correspondencia.get("resultado") == ev.DUVIDA:
            frases.append(f"a base NÃO reconheceu ({correspondencia.get('motivo')})")

    return frases


def explicar(evidencias, observacao: str = "") -> ExplicacaoRevisao:
    """
    Monta a explicação da linha a partir do dossiê já gravado (lista de
    dicts de `DossieRegistro.como_dicionarios()`).

    `observacao` é o texto que a validação já produzia; entra só como
    último recurso, quando o dossiê não existe (registros carregados de
    uma sessão anterior à Fase 17). Nunca é inventado texto: sem dossiê e
    sem observação, a explicação sai VAZIA e a aba mostra o que já
    mostrava antes.
    """
    evidencias = list(evidencias or [])
    if not evidencias:
        if observacao:
            return ExplicacaoRevisao(titulo="Motivo registrado pela validação:",
                                     detalhes=[observacao])
        return ExplicacaoRevisao()

    # O campo que bloqueou é aquele com uma evidência de REGRA em DÚVIDA --
    # é exatamente o que `classificar_registro` registra ao barrar.
    bloqueantes = [e for e in evidencias
                   if e.get("tipo") == ev.TIPO_REGRA and e.get("resultado") == ev.DUVIDA]
    campos = []
    for e in bloqueantes:
        if e.get("campo") not in campos:
            campos.append(e.get("campo"))

    explicacao = ExplicacaoRevisao(campos_bloqueantes=campos)
    if campos:
        nomes = ", ".join(_rotulo(c) for c in campos)
        explicacao.titulo = (
            f"A dúvida está em: {nomes}" if len(campos) == 1
            else f"A dúvida está em {len(campos)} campos: {nomes}"
        )
    else:
        explicacao.titulo = "Esta linha está em revisão:"

    for campo in campos:
        frases = _frases_do_campo(evidencias, campo)
        motivos_regra = [e.get("motivo") for e in bloqueantes if e.get("campo") == campo]
        frases.extend(motivos_regra)
        explicacao.por_campo[campo] = frases
        for frase in frases:
            explicacao.detalhes.append(f"{_rotulo(campo)}: {frase}")

    if not campos and observacao:
        explicacao.detalhes.append(observacao)
    return explicacao


# ---------------------------------------------------------------------------
# SINAIS DE CONTEXTO (Fase 16 -> tipos declarados na Fase 17)
#
# Só os que a MEDIÇÃO aprovou. São informativos: entram como destaque na
# tela e não tocam em `revisao_vars`, não pré-selecionam nada e não
# participam de nenhuma decisão.
#
# O terceiro sinal declarado na Fase 17 (`rubrica_repetida_na_folha`) NÃO
# é emitido -- ver o comentário em `agrupar_rubricas_parecidas`.
# ---------------------------------------------------------------------------

def _gestores_do_lote(registros) -> List[str]:
    """Responsáveis que o LOTE comprovou: os que a validação conseguiu
    casar com a base. Recusas e ambiguidades não entram."""
    aceitos = []
    for r in registros:
        observacao = r.get("observacao") or ""
        if "não reconhecido na base" in observacao or "ambíguo entre" in observacao:
            continue
        gestor = (r.get("gestor") or "").strip()
        if gestor and gestor not in aceitos:
            aceitos.append(gestor)
    return sorted(aceitos)


def _quebra_ordem_cronologica(registros, indice) -> Optional[str]:
    """
    A folha é preenchida de cima para baixo, então (DATA, HORA) deveria
    crescer linha a linha. Quando a linha atual vem ANTES da anterior da
    MESMA folha, alguma das duas datas/horas foi lida errado.

    Medido na Fase 16: 28 de 31 pares consecutivos comparáveis são
    monotônicos, e as 3 violações são exatamente os 3 defeitos reais de
    data -- com ZERO falsos positivos (inclusive uma virada de dia
    legítima, que a regra por frequência acusava indevidamente e esta
    não). Ainda assim é só um DESTAQUE: nada é corrigido, e a linha não
    muda de status por causa disto.
    """
    atual = registros[indice]
    pagina = atual.get("pagina_origem")

    def chave(r):
        data = interpretar_data(r.get("data") or "")
        hora = interpretar_hora(r.get("hora") or "")
        return (data, hora) if (data and hora) else None

    minha = chave(atual)
    if minha is None:
        return None

    anterior = None
    for i in range(indice - 1, -1, -1):
        if registros[i].get("pagina_origem") != pagina:
            break
        anterior = registros[i]
        break
    if anterior is None:
        return None

    dele = chave(anterior)
    if dele is None or minha >= dele:
        return None
    return (
        f"esta linha ({atual.get('data')} {atual.get('hora')}) vem ANTES da linha "
        f"acima ({anterior.get('data')} {anterior.get('hora')}) na mesma folha -- "
        f"a folha é preenchida de cima para baixo, então confira a data/hora no papel"
    )


def agrupar_rubricas_parecidas(registros, indice, limiar=0.5):
    """
    NÃO É USADO -- fica aqui documentado, com a medição que o reprovou.

    A ideia era destacar linhas da mesma folha com rubrica parecida
    ("estas 3 linhas parecem ter o mesmo responsável"). Medido sobre as 5
    folhas reais, a similaridade NÃO separa grupo verdadeiro de falso:

        trio verdadeiro (p4 L6/L7/L8, conferido na foto como a mesma
        rubrica "Anderson"):            0,500 / 0,400 / 0,533
        pares FALSOS mais bem pontuados:
            p3 L1 x L2 = 0,600  (são GR4 e GRL -- gestores diferentes)
            p4 L3 x L4 = 0,593  (são GR4 e um nome fora da base)

    Ou seja, os DOIS pares mais parecidos do lote inteiro são
    agrupamentos errados, e ficam ACIMA de todo o trio verdadeiro.
    Qualquer limiar que pegue o trio traz os falsos junto. Mostrar isso
    ao operador seria afirmar "estas linhas têm o mesmo responsável"
    justamente onde não têm -- o modo de falha que a Fase 16 mediu e
    proibiu. Fica sem emitir até haver evidência melhor que similaridade
    de texto (ex.: comparar recortes da imagem, fora do escopo).
    """
    atual = registros[indice]
    pagina = atual.get("pagina_origem")
    alvo = (atual.get("ocr_gestor") or "").strip().upper()
    if not alvo:
        return []
    parecidas = []
    for i, r in enumerate(registros):
        if i == indice or r.get("pagina_origem") != pagina:
            continue
        outro = (r.get("ocr_gestor") or "").strip().upper()
        if outro and difflib.SequenceMatcher(None, alvo, outro).ratio() >= limiar:
            parecidas.append(i)
    return parecidas


def sinais_de_contexto(registros, indice) -> List[ev.Evidencia]:
    """
    Os sinais de contexto aplicáveis à linha `indice`, como `Evidencia`
    do vocabulário da Fase 17 (tipo `contexto`, com as origens que aquela
    fase declarou e deixou reservadas).

    São INFORMATIVOS. Quem chama exibe e nada mais: não preenchem campo,
    não pré-selecionam candidato e não entram em nenhuma decisão.
    """
    if not registros or not (0 <= indice < len(registros)):
        return []

    sinais = []

    # A lista de responsáveis do lote só aparece quando é o RESPONSÁVEL que
    # está em dúvida. Medido nas 5 folhas reais: sem essa condição o sinal
    # dispararia em 21 de 21 linhas, inclusive nas barradas por Data ou
    # Hora -- e um aviso que aparece sempre deixa de ser aviso e vira ruído
    # que o operador aprende a ignorar (é a mesma conclusão do diagnóstico
    # de captura). Com a condição, ele aparece nas 11 linhas em que
    # realmente ajuda.
    em_duvida = explicar(registros[indice].get("evidencias")).campos_bloqueantes
    gestores = _gestores_do_lote(registros) if "gestor" in em_duvida else []
    if gestores:
        sinais.append(ev.Evidencia(
            campo="gestor", tipo=ev.TIPO_CONTEXTO, origem=ev.CONTEXTO_GESTORES_DO_LOTE,
            resultado=ev.NEUTRO,
            motivo=(f"este lote usa {len(gestores)} responsável(is); a lista abaixo é só "
                    f"para consulta -- o sistema não escolhe por você"),
            valor_observado=" | ".join(gestores),
        ))

    quebra = _quebra_ordem_cronologica(registros, indice)
    if quebra:
        sinais.append(ev.Evidencia(
            campo="data", tipo=ev.TIPO_CONTEXTO, origem=ev.CONTEXTO_ORDEM_CRONOLOGICA,
            resultado=ev.DUVIDA, motivo=quebra,
        ))

    return sinais
