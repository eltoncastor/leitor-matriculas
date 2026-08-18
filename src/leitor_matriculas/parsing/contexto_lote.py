"""
contexto_lote.py

Contexto REAL do lote em processamento, acumulado a partir do que já foi
lido nas folhas — hoje só o ANO das datas.

POR QUÊ ISTO EXISTE: o OCR frequentemente entrega a data sem o ano
("23.04"), porque na folha o ano foi escrito pequeno, apagado ou cortado
na foto. `tempo_parser.interpretar_data` recusa esse texto de propósito —
sozinho, ele não permite determinar o ano, e supor um seria exatamente o
"chute" que o sistema não faz.

Mas o ano NÃO precisa ser suposto quando ele está escrito nas OUTRAS
folhas do MESMO lote. Um lote é um conjunto de folhas fotografadas juntas,
do mesmo período; quando TODAS as datas legíveis do lote são do mesmo ano,
completar uma data sem ano com esse ano não é inventar — é usar uma
evidência externa, verificável e registrada na Observação.

REGRAS (mesmo espírito conservador do resto do projeto):
    1. Só entra no contexto data que `interpretar_data` já validou por
       completo (com ano escrito). Data recuperada por contexto NUNCA
       realimenta o contexto — senão um erro se propagaria pelo lote.
    2. É preciso um MÍNIMO de datas confirmadas (MINIMO_DATAS_CONFIAVEIS)
       para o contexto valer. Uma única folha legível não é "o contexto do
       lote".
    3. Um ano só é "o ano do lote" se for PREDOMINANTE com folga: no
       máximo MAXIMO_DATAS_DIVERGENTES datas de outros anos, E pelo menos
       FATOR_PREDOMINANCIA vezes mais datas que essas. As duas condições
       juntas separam as duas situações que se parecem em número mas são
       opostas na prática: um ou dois anos lidos errado pelo OCR no meio
       de dezenas de datas iguais (outlier — o lote continua sendo de um
       ano só), e um lote que de fato atravessa a virada do ano (aí há um
       bloco inteiro de datas do outro ano, e não existe "ano do lote"
       para completar coisa nenhuma).
    4. A data completada ainda passa pela validação de calendário normal
       (`interpretar_data`): 30/02 completado com o ano do lote continua
       sendo recusado.
    5. `ano_divergente_do_lote` faz o caminho inverso e igualmente
       conservador: uma data cujo ano ESTÁ escrito, mas destoa do ano do
       lote, é sinalizada para REVISAO. O ano não é reescrito (isso seria
       inventar) — só se reconhece que aquela linha não pode ser
       confirmada sem alguém olhar o papel.

Este módulo não conhece OCR, registro, nem planilha: recebe e devolve
texto.
"""

from typing import Optional

from leitor_matriculas.parsing.tempo_parser import (
    formatar_data_dd_mm_aa,
    interpretar_data,
    interpretar_data_sem_ano,
)

# Quantas datas COMPLETAS (com ano escrito na folha) o lote precisa ter
# para que o ano delas possa ser usado como contexto. Baixo o suficiente
# para servir a um lote pequeno, alto o suficiente para que uma única
# leitura errada de ano não vire "o ano do lote".
MINIMO_DATAS_CONFIAVEIS = 3

# Quantas datas de OUTROS anos ainda são toleradas como leitura errada do
# OCR. Um lote real que atravessa a virada do ano tem muito mais que isso
# do outro lado, e aí simplesmente não há "ano do lote".
MAXIMO_DATAS_DIVERGENTES = 2
# E quantas vezes o ano predominante tem de superar as divergentes. Sem
# isso, "3 datas de 2025 e 2 de 2026" passaria pelo teto acima e elegeria
# 2025 como "o ano do lote" -- que é justamente o lote de virada de ano
# que não pode eleger ano nenhum.
FATOR_PREDOMINANCIA = 3


class ContextoLote:
    """Acumula o que as folhas já lidas do lote comprovam. Só cresce; é
    reiniciado junto com os resultados (ver "Limpar resultados" na UI)."""

    def __init__(self):
        self._anos = {}  # ano -> quantas datas completas o comprovam

    # ------------------------------------------------------------------
    # Serialização (Fase 26a). Existe por um motivo concreto: a revisão
    # manual (`POST /lotes/{id}/registros/{indice}/confirmar`) reclassifica
    # o registro passando ESTE contexto, e isso acontece DEPOIS do lote
    # concluído -- muitas vezes bem depois. Sem persistir o contexto, um
    # reinício do backend faria a mesma confirmação decidir diferente
    # (uma data sem ano deixaria de poder ser completada), o que é
    # exatamente o tipo de divergência silenciosa que o projeto evita.
    #
    # O estado inteiro é `{ano: contagem}`. Não há nada derivado a
    # recalcular: `ano_do_lote()` é função pura desse dicionário.
    def como_dicionario(self) -> dict:
        # Chaves viram texto no JSON; devolvemos int aqui e reconvertemos
        # na volta, para o formato não depender de quem serializa.
        return {"anos": {str(ano): quantidade for ano, quantidade in self._anos.items()}}

    @classmethod
    def de_dicionario(cls, dados: Optional[dict]) -> "ContextoLote":
        contexto = cls()
        for ano, quantidade in ((dados or {}).get("anos") or {}).items():
            try:
                contexto._anos[int(ano)] = int(quantidade)
            except (TypeError, ValueError):
                # Entrada corrompida no arquivo de estado: ignorar aquele
                # ano é mais seguro que abortar o lote inteiro -- o efeito
                # máximo é o contexto ficar mais fraco (menos recuperação),
                # nunca eleger um ano errado.
                continue
        return contexto

    # ------------------------------------------------------------------
    def registrar_data(self, texto_data: Optional[str]) -> None:
        """
        Alimenta o contexto com uma data lida na folha. Só conta se ela
        for interpretável POR COMPLETO (com ano); qualquer outra coisa
        (vazia, ilegível, sem ano) é simplesmente ignorada — nunca levanta
        exceção nem contamina o contexto.
        """
        data = interpretar_data(texto_data)
        if data is None:
            return
        self._anos[data.year] = self._anos.get(data.year, 0) + 1

    # ------------------------------------------------------------------
    @property
    def total_datas_confiaveis(self) -> int:
        return sum(self._anos.values())

    def ano_do_lote(self) -> Optional[int]:
        """
        O ano do lote, ou None quando não há evidência suficiente: menos
        de MINIMO_DATAS_CONFIAVEIS datas completas, ou nenhum ano
        predominante com folga (ver regra 3 no topo do módulo).
        """
        if not self._anos:
            return None

        ano, quantidade = max(self._anos.items(), key=lambda par: par[1])
        divergentes = self.total_datas_confiaveis - quantidade
        if divergentes > MAXIMO_DATAS_DIVERGENTES:
            return None
        if quantidade < max(MINIMO_DATAS_CONFIAVEIS, FATOR_PREDOMINANCIA * divergentes):
            return None
        return ano

    def ano_divergente_do_lote(self, texto_data: Optional[str]) -> Optional[int]:
        """
        Devolve o ano de `texto_data` quando ele está escrito, é uma data
        válida, e DESTOA do ano do lote — o sinal de que aquela linha teve
        o ano lido errado (ex.: "28/04/20" numa remessa em que todas as
        outras 30 datas são de 2026).

        Devolve None quando não há divergência a apontar: texto ilegível,
        sem ano, ano igual ao do lote, ou lote sem ano definido.

        Quem chama usa isto para mandar a linha para REVISAO — nunca para
        reescrever o ano. O ano escrito na folha é o que está escrito; o
        que o contexto mostra é que ele não pode ser confirmado sozinho.
        """
        ano_lote = self.ano_do_lote()
        if ano_lote is None:
            return None

        data = interpretar_data(texto_data)
        if data is None or data.year == ano_lote:
            return None
        return data.year

    # ------------------------------------------------------------------
    def completar_ano(self, texto_data: Optional[str]) -> Optional[str]:
        """
        Completa uma data SEM ANO ("23.04") com o ano do lote e devolve o
        texto canônico `dd/mm/aa`, ou None quando isso não pode ser feito
        com segurança:

            - o texto não é uma data sem ano (inclusive: já tem ano, ou
              não é data nenhuma) -> None, quem chama segue o caminho
              normal;
            - o lote não tem ano definido (evidência insuficiente ou mais
              de um ano) -> None;
            - dia/mês + ano do lote não formam uma data de calendário
              válida (ex.: "30.02") -> None.
        """
        dia_mes = interpretar_data_sem_ano(texto_data)
        if dia_mes is None:
            return None

        ano = self.ano_do_lote()
        if ano is None:
            return None

        dia, mes = dia_mes
        data = interpretar_data(f"{dia:02d}/{mes:02d}/{ano:04d}")
        if data is None:
            return None
        return formatar_data_dd_mm_aa(data)
