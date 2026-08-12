"""
evidencias.py

Representação EXPLÍCITA do que sustenta cada decisão sobre um campo:
por que aquele valor foi aceito, corrigido, recusado ou mandado para
REVISAO.

POR QUE ISTO EXISTE: a informação já existia — ela só estava espalhada e,
em boa parte, era descartada. O levantamento sobre as 40 liberações reais
mostrou que o pipeline PRODUZ e JOGA FORA, em toda execução: o segundo
melhor candidato de motivo (40/40), a posição (caixa) de cada campo
(38/40), a similaridade numérica do responsável (37/40) e a confiança do
OCR da matrícula nos registros CONFIRMADO (19/40). Nada disso chegava a
nenhum consumidor: o que sobrevivia era a `observacao`, uma frase pronta
em português, boa para o operador ler e imprestável para outra camada
raciocinar em cima.

O QUE ESTE MÓDULO É -- e o que ele NÃO é:

    É  um registro descritivo: "isto foi observado, veio daqui, e este é
       o papel que teve na decisão".
    NÃO decide nada. Não classifica, não corrige, não confirma, não
       bloqueia. Segue o mesmo espírito de `validacao/integridade.py`,
       que também só descreve evidência e deixa a decisão para
       `validacao/regras.py`.

Por isso o motor é OBSERVACIONAL: acrescentá-lo não muda nenhum status.
Se algum dia for preciso mudar uma regra para conseguir registrar uma
evidência, a evidência é que fica de fora — a regra de negócio não se
dobra para o registro dela.

DELIBERADAMENTE NÃO EXISTE UM SCORE. Não há nota de 0 a 100, nem soma
ponderada, nem "confiança geral" do registro. Um número desses seria
exatamente o critério arbitrário que este projeto evita: ele apagaria a
diferença entre "não há evidência" e "há evidência contrária", que é
justamente a distinção que a Fase 12 precisou criar para não confirmar
registro com campo perdido. Os fatores favoráveis e os fatores de dúvida
ficam LISTADOS, lado a lado, e quem lê decide.

CAMPOS COBERTOS: só os 5 campos LIDOS DA FOLHA -- `data`, `hora`,
`matricula`, `motivo`, `gestor`. NOME e SETOR ficam de fora por
requisito funcional: eles não são lidos do papel, são derivados da
matrícula por busca em `Colaboradores.xlsx`. Não são evidência do mesmo
tipo, e tratá-los como se fossem sugeriria que houve leitura onde houve
consulta.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Vocabulário fechado. É fechado de propósito: um tipo/resultado livre em
# string vira, em duas fases, um vocabulário divergente que ninguém
# consegue consultar.
# ---------------------------------------------------------------------------

CAMPOS_COM_EVIDENCIA = ("data", "hora", "matricula", "motivo", "gestor")

TIPO_OCR_BRUTO = "ocr_bruto"                      # o que o OCR entregou, sem tratamento
TIPO_NORMALIZACAO = "normalizacao"                # o valor foi reescrito por uma regra conhecida
TIPO_CORRESPONDENCIA_BASE = "correspondencia_base"  # confronto com Colaboradores/Motivos/Gestores
TIPO_POSICAO = "posicao"                          # onde o campo estava na folha (caixa do OCR)
TIPO_CONTEXTO = "contexto"                        # outras linhas/folhas do mesmo lote
TIPO_REGRA = "regra"                              # a regra que decidiu (ou deixou de bloquear)
TIPO_AUSENCIA = "ausencia"                        # não havia o que observar
TIPO_CONFLITO = "conflito"                        # evidências que se contradizem

TIPOS = (
    TIPO_OCR_BRUTO, TIPO_NORMALIZACAO, TIPO_CORRESPONDENCIA_BASE, TIPO_POSICAO,
    TIPO_CONTEXTO, TIPO_REGRA, TIPO_AUSENCIA, TIPO_CONFLITO,
)

# O papel da evidência na decisão. Três valores, não uma escala: uma
# escala convidaria a somar, e somar é o score que não queremos.
FAVORAVEL = "FAVORAVEL"   # sustenta o valor
DUVIDA = "DUVIDA"         # põe o valor em dúvida (não necessariamente bloqueia)
NEUTRO = "NEUTRO"         # fato registrado, sem peso a favor ou contra

RESULTADOS = (FAVORAVEL, DUVIDA, NEUTRO)

# ---------------------------------------------------------------------------
# Origens de CONTEXTO.
#
# Duas já são produzidas hoje (Fase 9, `parsing/contexto_lote.py`). As
# outras três são exatamente os sinais que a MEDIÇÃO da Fase 16 aprovou
# como seguros para MOSTRAR ao operador e proibiu de usar para confirmar
# -- estão declarados aqui para que a Fase 18 tenha onde encaixá-los, e
# NÃO são emitidos por este módulo nem por ninguém ainda. Declarar o
# nome não cria o mecanismo: a Fase 16 mediu e descartou a produção
# automática desses sinais, e esta fase não a reintroduz.
# ---------------------------------------------------------------------------
CONTEXTO_ANO_DO_LOTE = "ano_do_lote"                          # emitido (Fase 9)
CONTEXTO_ANO_DIVERGENTE = "ano_divergente_do_lote"            # emitido (Fase 9)
CONTEXTO_GESTORES_DO_LOTE = "gestores_do_lote"                # reservado -> Fase 18
CONTEXTO_ORDEM_CRONOLOGICA = "ordem_cronologica_da_folha"     # reservado -> Fase 18
CONTEXTO_RUBRICA_REPETIDA = "rubrica_repetida_na_folha"       # reservado -> Fase 18

ORIGENS_CONTEXTO = (
    CONTEXTO_ANO_DO_LOTE, CONTEXTO_ANO_DIVERGENTE,
    CONTEXTO_GESTORES_DO_LOTE, CONTEXTO_ORDEM_CRONOLOGICA, CONTEXTO_RUBRICA_REPETIDA,
)


@dataclass(frozen=True)
class Evidencia:
    """
    Um fato observado sobre UM campo.

    campo             -- um de CAMPOS_COM_EVIDENCIA.
    tipo              -- um de TIPOS.
    origem            -- quem produziu o fato (módulo/função, ou uma das
                         ORIGENS_CONTEXTO). É o que permite auditar de
                         onde veio cada afirmação.
    valor_observado   -- o que se viu (texto do OCR, valor normalizado...).
    valor_relacionado -- o outro lado da comparação, quando há um
                         (candidato da base, valor anterior, ano do lote).
                         None quando a evidência não é uma comparação.
    resultado         -- FAVORAVEL / DUVIDA / NEUTRO.
    motivo            -- frase curta explicando o fato.

    Imutável (`frozen`): evidência registrada não se reescreve. Se a
    leitura mudar, isso é uma evidência NOVA, e as duas ficam no dossiê.
    """
    campo: str
    tipo: str
    origem: str
    resultado: str
    motivo: str
    valor_observado: Optional[str] = None
    valor_relacionado: Optional[str] = None

    def como_dicionario(self) -> dict:
        return {
            "campo": self.campo, "tipo": self.tipo, "origem": self.origem,
            "resultado": self.resultado, "motivo": self.motivo,
            "valor_observado": self.valor_observado,
            "valor_relacionado": self.valor_relacionado,
        }


class DossieRegistro:
    """
    As evidências de UM registro (uma liberação), na ordem em que foram
    observadas.

    A ordem importa e é preservada: ela é a própria cadeia de raciocínio
    (o que o OCR leu -> como foi normalizado -> o que a base respondeu ->
    que regra decidiu). Reordenar por campo ou por peso destruiria isso.
    """

    def __init__(self):
        self._evidencias: List[Evidencia] = []

    # ------------------------------------------------------------------
    def registrar(self, campo: str, tipo: str, origem: str, resultado: str, motivo: str,
                  valor_observado=None, valor_relacionado=None) -> None:
        """
        Acrescenta uma evidência. Nunca levanta exceção por conteúdo
        inesperado -- registrar evidência não pode ser o que derruba o
        processamento de um lote de 50 folhas. Um campo/tipo/resultado
        fora do vocabulário é registrado assim mesmo (e fica visível na
        auditoria), em vez de virar um crash.
        """
        self._evidencias.append(Evidencia(
            campo=campo, tipo=tipo, origem=origem, resultado=resultado, motivo=motivo,
            valor_observado=None if valor_observado is None else str(valor_observado),
            valor_relacionado=None if valor_relacionado is None else str(valor_relacionado),
        ))

    # ------------------------------------------------------------------
    @property
    def evidencias(self) -> List[Evidencia]:
        return list(self._evidencias)

    def __len__(self) -> int:
        return len(self._evidencias)

    def do_campo(self, campo: str) -> List[Evidencia]:
        return [e for e in self._evidencias if e.campo == campo]

    def favoraveis(self, campo: str) -> List[Evidencia]:
        return [e for e in self.do_campo(campo) if e.resultado == FAVORAVEL]

    def duvidas(self, campo: str) -> List[Evidencia]:
        return [e for e in self.do_campo(campo) if e.resultado == DUVIDA]

    def sem_evidencia(self, campo: str) -> bool:
        """
        True só quando NADA foi observado sobre o campo -- o motor não
        olhou para ele.

        Isto é diferente, e tem de continuar diferente, de existir uma
        evidência de tipo `ausencia` (o motor olhou e o campo estava
        vazio) e de existir uma evidência DUVIDA (o motor olhou e o que
        viu é suspeito). Achatar os três num "sem informação" só é
        possível com um score -- e é justamente a distinção que a Fase 12
        precisou criar para não confirmar registro com campo perdido.
        """
        return not self.do_campo(campo)

    def explicar(self, campo: str) -> str:
        """
        A cadeia de evidências do campo em uma linha, para auditoria e
        depuração. Não é texto de interface: a Fase 18 monta a
        apresentação a partir das evidências estruturadas, não desta
        string.
        """
        do_campo = self.do_campo(campo)
        if not do_campo:
            return f"{campo}: nenhuma evidência registrada"
        return f"{campo}: " + " | ".join(
            f"[{e.tipo}/{e.resultado}] {e.motivo}" for e in do_campo
        )

    def como_dicionarios(self) -> List[dict]:
        """
        Dados puros (listas/dicts/strings), sem referência a Registro,
        imagem ou dataclass -- é assim que o dossiê é guardado no dict de
        exportação sem prender objetos vivos na memória do lote.
        """
        return [e.como_dicionario() for e in self._evidencias]

    # ------------------------------------------------------------------
    @classmethod
    def de_dicionarios(cls, dados) -> "DossieRegistro":
        """Reconstrói um dossiê a partir de `como_dicionarios()` (ida e
        volta sem perda). Quem consumir na revisão precisa disto."""
        dossie = cls()
        for d in dados or []:
            dossie.registrar(
                campo=d.get("campo", ""), tipo=d.get("tipo", ""), origem=d.get("origem", ""),
                resultado=d.get("resultado", NEUTRO), motivo=d.get("motivo", ""),
                valor_observado=d.get("valor_observado"),
                valor_relacionado=d.get("valor_relacionado"),
            )
        return dossie


def resumo_por_campo(dossie: DossieRegistro) -> Dict[str, dict]:
    """
    Contagem de favoráveis/dúvidas por campo. Contagem, não pontuação:
    não há soma nem peso, e um campo com 3 favoráveis e 1 dúvida NÃO é
    "75% confiável" -- é um campo com uma dúvida a resolver.
    """
    return {
        campo: {
            "favoraveis": len(dossie.favoraveis(campo)),
            "duvidas": len(dossie.duvidas(campo)),
            "total": len(dossie.do_campo(campo)),
        }
        for campo in CAMPOS_COM_EVIDENCIA
    }
