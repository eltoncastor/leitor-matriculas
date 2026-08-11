"""
teste/teste_recuperacao_contextual.py

Recuperação contextual de OCR e redução SEGURA de REVISAO.

O que esta fase acrescentou, e é o que se testa aqui:

    1. MOTIVO   -- lista FECHADA de 7 motivos. Toda a família
                   "NEGADO/NEGADA/H. NEGADO/H.V. negado" e suas
                   deformações de OCR saem como HORÁRIO NEGADO, e os
                   outros 6 motivos continuam intactos (não podem ser
                   absorvidos pela família).
    2. GESTOR   -- código GR lido por tabela FECHADA de confusões de OCR
                   e confirmado contra a base; ambíguo continua REVISAO.
    3. DATA     -- ano completado pelo CONTEXTO DO LOTE quando o OCR não
                   leu o ano; formato deformado recuperado; ano que
                   destoa do lote vai para REVISAO.
    4. HORA     -- separador trocado/apagado e hora colada a outro texto
                   recuperados; hora impossível continua recusada.
    5. MATRÍCULA -- só dígitos na saída; recuperação inequívoca mantida;
                   ambígua continua REVISAO.
    6. STATUS   -- normalizar um campo NÃO confirma o registro sozinho.

Não usa PaddleOCR nem as planilhas reais: bases sintéticas com o mesmo
conteúdo das reais (a lista fechada de 7 motivos).

Uso:
    python teste\\teste_recuperacao_contextual.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from leitor_matriculas.parsing.contexto_lote import ContextoLote  # noqa: E402
from leitor_matriculas.parsing.registro_parser import Registro, CampoOcr  # noqa: E402
from leitor_matriculas.parsing.tempo_parser import (  # noqa: E402
    interpretar_data_sem_ano,
    normalizar_data,
    normalizar_hora,
    recuperar_hora,
    tentar_separar_data_hora_mesclada,
)
from leitor_matriculas.validacao.correspondencia_aproximada import (  # noqa: E402
    MOTIVO_HORARIO_NEGADO,
    resolver_motivo,
    resolver_responsavel,
)
from leitor_matriculas.validacao.recuperacao_matricula import resolver_matricula  # noqa: E402
from leitor_matriculas.validacao.regras import classificar_registro  # noqa: E402

# Lista FECHADA de motivos válidos desta versão do sistema (o conteúdo
# real de dados/Motivos.xlsx).
MOTIVOS = ["HORÁRIO NEGADO", "RH", "ADM", "ARMÁRIOS", "FOLGA FIXA",
           "ESQUECEU CRACHÁ", "TREINAMENTO"]
GESTORES = ["GR1 – TEODORO", "GR3 - BEATRIZ", "GR4 - RENATO GUIMARÃES", "GR5 - OTAVIO",
            "GRL - LUCIA", "ROBERTO", "MARCELO TORRES", "MARCELO SOUZA", "HELIO",
            "SOUZA", "MARTIM", "NORBERTO", "TAMIRES", "VICENTE",
            "GR1", "GR3", "GR4", "GR5", "GRL", "TORRES", "M. TORRES", "MARCELO"]

COLABORADOR = {"matricula": "19547", "nome": "FULANO DE TAL",
               "cargo": "ATENDENTE", "setor": "VENDAS"}

falhas = []


def checar(cond, msg):
    print(("  OK    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


class _DMFalso:
    def __init__(self, colaboradores=None):
        self._colaboradores = colaboradores or {}
        self.colaboradores_disponivel = True
        self.gestores_disponivel = True
        self.motivos_disponivel = True

    def listar_gestores(self):
        return list(GESTORES)

    def listar_motivos(self):
        return list(MOTIVOS)

    def buscar_colaborador(self, matricula):
        return self._colaboradores.get(str(matricula))


def _registro(matricula="19547", data="14.04.26", hora="07:53",
              motivo="Negado", gestor="GR5", confianca=0.99):
    campos = {}
    if matricula:
        campos["matricula"] = CampoOcr(matricula, confianca, None)
    if data:
        campos["data"] = CampoOcr(data, 0.9, None)
    if hora:
        campos["hora"] = CampoOcr(hora, 0.9, None)
    if motivo:
        campos["motivo"] = CampoOcr(motivo, 0.9, None)
    if gestor:
        campos["gestor"] = CampoOcr(gestor, 0.9, None)
    return Registro(indice=1, campos=campos)


def _contexto_de_2026():
    """Contexto de um lote como o real: várias folhas com datas de 2026."""
    contexto = ContextoLote()
    for texto in ["14.04.26", "14.04.26", "14.04.26", "28.04.26", "23.04.26"]:
        contexto.registrar_data(texto)
    return contexto


# ---------------------------------------------------------------------------
# 1. MOTIVO -- família NEGADO/NEGADA -> HORÁRIO NEGADO
# ---------------------------------------------------------------------------

def teste_motivo_familia_negado():
    print("=== MOTIVO: NEGADO/NEGADA e deformações -> HORÁRIO NEGADO ===")
    # Os casos nomeados no requisito desta fase.
    for texto in ["NEGADO", "NEGADA", "Negado", "Negada", "Negade", "Negade.",
                  "Negaola", "Negoide", "NEGAND",
                  "Hiv. Nigado", "H.v. vigaolb", "H. V. vigaolo", "Hev. Nigadb",
                  "H.v. vegaco", "I Wegado", "H. NEGADO", "H. V. NEGADO"]:
        r = resolver_motivo(texto, MOTIVOS)
        checar(r.motivo_confirmado == MOTIVO_HORARIO_NEGADO,
               f"{texto!r} -> HORÁRIO NEGADO (obtido: {r.motivo_confirmado!r}, {r.status})")
    print()


def teste_motivo_ne6400_por_evidencia_combinada():
    print("=== MOTIVO: 'NE6400' recuperado por evidência combinada ===")
    # "NE6400" = NEGADO com 6->G, 4->A, 0->O (dígitos lidos no lugar de
    # letras). Só é aceito porque a evidência estrutural é forte, não
    # porque o limiar foi afrouxado.
    r = resolver_motivo("NE6400", MOTIVOS)
    checar(r.motivo_confirmado == MOTIVO_HORARIO_NEGADO,
           f"'NE6400' -> HORÁRIO NEGADO (obtido: {r.motivo_confirmado!r}, {r.status})")
    checar(r.status == "NORMALIZADA" and r.houve_fallback,
           f"'NE6400' registrado como normalização (status={r.status}, fallback={r.houve_fallback})")
    print()


def teste_motivos_da_lista_fechada_preservados():
    print("=== MOTIVO: os outros 6 motivos NÃO são absorvidos pela família ===")
    for texto, esperado in [("RH", "RH"), ("ADM", "ADM"), ("ARMÁRIOS", "ARMÁRIOS"),
                            ("Armarios", "ARMÁRIOS"), ("FOLGA FIXA", "FOLGA FIXA"),
                            ("Folga fixa", "FOLGA FIXA"),
                            ("ESQUECEU CRACHÁ", "ESQUECEU CRACHÁ"),
                            ("Esqueceu cracha", "ESQUECEU CRACHÁ"),
                            ("TREINAMENTO", "TREINAMENTO"),
                            ("Treinamento", "TREINAMENTO")]:
        r = resolver_motivo(texto, MOTIVOS)
        checar(r.motivo_confirmado == esperado,
               f"{texto!r} -> {esperado!r} (obtido: {r.motivo_confirmado!r})")
    print()


def teste_motivo_sem_evidencia_continua_revisao():
    print("=== MOTIVO: sem evidência suficiente, nada vira HORÁRIO NEGADO ===")
    # Texto sem relação nenhuma, e texto que se PARECE com a família mas
    # não tem nem o esqueleto N-G-D nem a abreviação de "horário".
    for texto in ["XPTO INEXISTENTE", "NEGOCIO", "VENDEDOR", "MATRICULA",
                  "RESPONSAVEL", "Manutencao"]:
        r = resolver_motivo(texto, MOTIVOS)
        checar(r.motivo_confirmado != MOTIVO_HORARIO_NEGADO,
               f"{texto!r} NÃO vira HORÁRIO NEGADO (obtido: {r.motivo_confirmado!r})")
    print()


# ---------------------------------------------------------------------------
# 2. GESTOR -- código GR
# ---------------------------------------------------------------------------

def teste_gestor_codigo_gr():
    print("=== GESTOR: código GR prevalece sobre o texto secundário ===")
    for texto, esperado in [("GR3", "GR3 - BEATRIZ"),
                            ("GR5", "GR5 - OTAVIO"),
                            ("6R05", "GR5 - OTAVIO"),
                            ("6R5", "GR5 - OTAVIO"),
                            ("GRS", "GR5 - OTAVIO"),
                            ("GR5 - Lorenne", "GR5 - OTAVIO"),
                            ("GR5 - Lorena", "GR5 - OTAVIO"),
                            ("GR5 - Eosee", "GR5 - OTAVIO"),
                            ("GRS- Lorenne", "GR5 - OTAVIO"),
                            ("GRS - Eose", "GR5 - OTAVIO"),
                            ("GR3 - Lorenom", "GR3 - BEATRIZ"),
                            ("GR4 - Greane", "GR4 - RENATO GUIMARÃES")]:
        r = resolver_responsavel(texto, GESTORES)
        checar(r.gestor_confirmado == esperado,
               f"{texto!r} -> {esperado!r} (obtido: {r.gestor_confirmado!r}, {r.status})")
    print()


def teste_gestor_identificacao_mais_especifica_ganha():
    print("=== GESTOR: a maior sequência confiável continua ganhando do código nu ===")
    # O código nunca pode atropelar uma identificação MAIS específica que
    # bate exatamente com a base.
    r = resolver_responsavel("GR3 - BEATRIZ - LORENA", GESTORES)
    checar(r.status == "EXATA" and r.gestor_confirmado == "GR3 - BEATRIZ",
           f"'GR3 - BEATRIZ - LORENA' -> EXATA/'GR3 - BEATRIZ' (obtido: {r.status}/{r.gestor_confirmado!r})")
    print()


def teste_responsavel_cortado_ou_ambiguo_continua_revisao():
    print("=== GESTOR: cortado, ilegível ou ambíguo -> REVISAO ===")
    # Códigos que não existem na base, códigos com letra que não é código
    # nenhum, e nomes cortados/irreconhecíveis.
    for texto in ["GRM—E", "GRY-E", "6R0", "GRI", "Geos", "penu - Esear",
                  "podincan", "freimsa", "groimay", "Damif", "Daw", "way", "6R0"]:
        r = resolver_responsavel(texto, GESTORES)
        checar(r.gestor_confirmado is None,
               f"{texto!r} -> REVISAO (obtido: {r.gestor_confirmado!r}, {r.status})")
    print()


# ---------------------------------------------------------------------------
# 3. DATA -- contexto do lote e formato deformado
# ---------------------------------------------------------------------------

def teste_data_sem_ano_reconhecida_mas_nao_completada_sozinha():
    print("=== DATA: dia/mês sem ano são reconhecidos, mas nunca completados sozinhos ===")
    checar(interpretar_data_sem_ano("23.04") == (23, 4), "'23.04' -> (23, 4)")
    checar(interpretar_data_sem_ano("14/04") == (14, 4), "'14/04' -> (14, 4)")
    checar(interpretar_data_sem_ano("32.04") is None, "'32.04' (dia impossível) -> None")
    checar(interpretar_data_sem_ano("23.13") is None, "'23.13' (mês impossível) -> None")
    checar(interpretar_data_sem_ano("23.04.26") is None, "'23.04.26' (já tem ano) -> None")
    # A validação normal continua recusando data sem ano.
    checar(normalizar_data("23.04") is None,
           "normalizar_data('23.04') continua None -- o módulo sozinho nunca completa o ano")
    print()


def teste_data_sem_ano_com_contexto_do_lote():
    print("=== DATA: ano completado pelo contexto do lote ===")
    contexto = _contexto_de_2026()
    checar(contexto.ano_do_lote() == 2026, f"ano do lote = 2026 (obtido: {contexto.ano_do_lote()})")
    checar(contexto.completar_ano("23.04") == "23/04/26",
           f"'23.04' -> '23/04/26' (obtido: {contexto.completar_ano('23.04')!r})")
    checar(contexto.completar_ano("14.04") == "14/04/26",
           f"'14.04' -> '14/04/26' (obtido: {contexto.completar_ano('14.04')!r})")
    # Sem contexto suficiente, nada é completado.
    vazio = ContextoLote()
    checar(vazio.completar_ano("23.04") is None,
           "lote sem datas confirmadas não completa ano nenhum")
    poucas = ContextoLote()
    poucas.registrar_data("14.04.26")
    checar(poucas.completar_ano("23.04") is None,
           "uma única data confirmada não é 'o contexto do lote'")
    # Lote que atravessa dois anos de verdade: não há ano do lote.
    dois_anos = ContextoLote()
    for texto in ["30.12.25", "30.12.25", "31.12.25", "02.01.26", "02.01.26"]:
        dois_anos.registrar_data(texto)
    checar(dois_anos.ano_do_lote() is None and dois_anos.completar_ano("23.04") is None,
           "lote com dois anos de verdade -> nenhum ano de contexto")
    # Data impossível não é salva pelo contexto.
    checar(contexto.completar_ano("30.02") is None,
           "'30.02' + ano do lote continua sendo data impossível -> None")
    print()


def teste_contexto_tolera_ano_lido_errado_mas_sinaliza():
    print("=== DATA: um ano lido errado não derruba o contexto, mas vai para REVISAO ===")
    contexto = _contexto_de_2026()
    contexto.registrar_data("28/04/20")  # leitura errada isolada
    checar(contexto.ano_do_lote() == 2026,
           f"um outlier não muda o ano do lote (obtido: {contexto.ano_do_lote()})")
    checar(contexto.ano_divergente_do_lote("28/04/20") == 2020,
           "a linha com ano divergente é sinalizada")
    checar(contexto.ano_divergente_do_lote("28/04/26") is None,
           "linha com o ano do lote não é sinalizada")

    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    r = classificar_registro(_registro(data="28/04/20"), COLABORADOR, dm, contexto_lote=contexto)
    checar(r.status == "REVISAO" and "destoa" in r.observacao,
           f"data com ano divergente -> REVISAO (obtido: {r.status} -- {r.observacao})")
    # E o ano NÃO é reescrito: o que está escrito continua escrito.
    checar(r.data_confirmada == "28/04/20",
           f"o ano divergente não é reescrito (obtido: {r.data_confirmada!r})")
    print()


def teste_data_com_formato_deformado():
    print("=== DATA: formato deformado recuperado quando os dígitos são inequívocos ===")
    for texto, esperado in [("14.04 -26", "14/04/26"),
                            ("14.0.4.26", "14/04/26"),
                            ("14.04:26", "14/04/26"),
                            ("23.0426", "23/04/26"),
                            ("14-04-26", "14/04/26"),
                            ("14.04.2026", "14/04/26")]:
        checar(normalizar_data(texto) == esperado,
               f"{texto!r} -> {esperado!r} (obtido: {normalizar_data(texto)!r})")
    print()


def teste_data_impossivel_ou_ambigua_continua_recusada():
    print("=== DATA: impossível ou ambígua continua recusada ===")
    for texto in ["31.04.26", "23.13.26", "32.04.26", "vinte e três de abril",
                  "140426", "28/04/20 14.:08", "1.4.0.4.2.6.7"]:
        checar(normalizar_data(texto) is None,
               f"{texto!r} -> None (obtido: {normalizar_data(texto)!r})")

    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    r = classificar_registro(_registro(data="31.04.26"), COLABORADOR, dm,
                             contexto_lote=_contexto_de_2026())
    checar(r.status == "REVISAO" and r.data_confirmada is None,
           f"data impossível -> REVISAO mesmo com contexto de lote (obtido: {r.status})")
    print()


# ---------------------------------------------------------------------------
# 4. HORA -- recuperação segura
# ---------------------------------------------------------------------------

def teste_hora_separadores_deformados():
    print("=== HORA: separador trocado ou apagado -> HH:MM ===")
    for texto, esperado in [("07.53", "07:53"), ("11.27", "11:27"), ("07 53", "07:53"),
                            ("11 27", "11:27"), ("7:53", "07:53"), ("11h05", "11:05"),
                            ("2:44", "02:44"), ("18.59", "18:59")]:
        checar(normalizar_hora(texto) == esperado,
               f"{texto!r} -> {esperado!r} (obtido: {normalizar_hora(texto)!r})")
    print()


def teste_hora_colada_a_outro_texto():
    print("=== HORA: hora colada a texto sem números é recuperada ===")
    for texto, esperado in [("12:55 Miguel", "12:55"), ("11:06 Faina", "11:06"),
                            ("11:10 will", "11:10"), ("14.:08", "14:08")]:
        checar(recuperar_hora(texto) == esperado,
               f"{texto!r} -> {esperado!r} (obtido: {recuperar_hora(texto)!r})")
    # Com outros dígitos sobrando, não há leitura segura.
    checar(recuperar_hora("12:55 13:40") is None,
           "dois trechos de hora -> ambíguo, nada é escolhido")
    checar(recuperar_hora("12:55 30945") is None,
           "dígitos sobrando fora do trecho -> nenhuma recuperação")
    print()


def teste_hora_impossivel_continua_recusada():
    print("=== HORA: impossível continua recusada e nunca vira CONFIRMADO ===")
    for texto in ["90:24", "99:99", "25:00", "12:75"]:
        checar(normalizar_hora(texto) is None and recuperar_hora(texto) is None,
               f"{texto!r} -> None (normalizar={normalizar_hora(texto)!r}, "
               f"recuperar={recuperar_hora(texto)!r})")

    # A hora é OPCIONAL: uma hora impossível não bloqueia o registro, mas
    # a célula sai VAZIA e o texto bruto fica registrado na Observação --
    # o valor "90:24" nunca chega à planilha.
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    r = classificar_registro(_registro(hora="90:24"), COLABORADOR, dm)
    checar(r.hora_confirmada is None, f"hora impossível não é exportada (obtido: {r.hora_confirmada!r})")
    checar("90:24" in r.observacao, "o texto bruto da hora impossível fica na Observação")
    print()


def teste_data_hora_mescladas_com_hora_impossivel():
    print("=== HORA: caixa data+hora mesclada com hora impossível -> só a data ===")
    # A DATA legível não pode ser perdida por causa da HORA (campo
    # opcional) -- mas a hora impossível também não pode entrar.
    resultado = tentar_separar_data_hora_mesclada("14.04 -26 90:24")
    checar(resultado is not None and resultado[0] == "14.04.26" and resultado[1] is None,
           f"'14.04 -26 90:24' -> data 14.04.26 e hora ausente (obtido: {resultado!r})")
    checar(normalizar_data(resultado[0]) == "14/04/26",
           f"a data separada vira 14/04/26 (obtido: {normalizar_data(resultado[0])!r})")
    # Os dois válidos continuam sendo separados normalmente.
    checar(tentar_separar_data_hora_mesclada("28/04/26 14.:08") == ("28.04.26", "14:08"),
           f"'28/04/26 14.:08' -> ('28.04.26', '14:08') "
           f"(obtido: {tentar_separar_data_hora_mesclada('28/04/26 14.:08')!r})")
    # Sem trecho de hora nenhum, nada é separado.
    checar(tentar_separar_data_hora_mesclada("28/04/26") is None,
           "texto que é só data não é 'separado'")
    print()


# ---------------------------------------------------------------------------
# 5. MATRÍCULA -- só dígitos
# ---------------------------------------------------------------------------

def teste_matricula_recuperada_e_so_digitos():
    print("=== MATRÍCULA: recuperação inequívoca e saída só com dígitos ===")
    base = {"19547", "30874"}
    existe = lambda m: m in base  # noqa: E731

    r = resolver_matricula("1954+", existe_na_base=existe)
    checar(r.matricula == "19547" and r.status == "RECUPERADA",
           f"'1954+' -> '19547' (obtido: {r.matricula!r}, {r.status})")
    r = resolver_matricula("308+4", existe_na_base=existe)
    checar(r.matricula == "30874" and r.status == "RECUPERADA",
           f"'308+4' -> '30874' (obtido: {r.matricula!r}, {r.status})")

    # Duas leituras plausíveis existindo na base: ninguém escolhe.
    ambos = {"19547", "19544"}
    r = resolver_matricula("1954+", existe_na_base=lambda m: m in ambos)
    checar(r.status == "AMBIGUA",
           f"'1954+' com 19547 e 19544 na base -> AMBIGUA (obtido: {r.status})")

    dm = _DMFalso(colaboradores={"19547": COLABORADOR, "19544": COLABORADOR})
    resultado_matricula = resolver_matricula("1954+", existe_na_base=lambda m: m in ambos)
    r = classificar_registro(_registro(matricula="1954+"), COLABORADOR, dm,
                             resultado_matricula=resultado_matricula)
    checar(r.status == "REVISAO" and "ambígua" in r.observacao,
           f"matrícula ambígua -> REVISAO (obtido: {r.status} -- {r.observacao})")

    # Nenhuma saída contém caractere que não seja dígito.
    for texto in ["1954+", "308+4", "1.9160", "19 547", "195-47", "O9547", "l9547"]:
        r = resolver_matricula(texto, existe_na_base=lambda _m: False)
        checar(r.matricula.isdigit() or r.matricula == "",
               f"{texto!r} -> saída só com dígitos ou vazia (obtido: {r.matricula!r})")
    print()


# ---------------------------------------------------------------------------
# 6. STATUS -- normalizar um campo não confirma o registro
# ---------------------------------------------------------------------------

def teste_normalizacao_nao_confirma_sozinha():
    print("=== STATUS: normalizar um campo NÃO confirma o registro ===")
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    contexto = _contexto_de_2026()

    # Motivo recuperado + responsável incerto -> REVISAO.
    r = classificar_registro(_registro(motivo="NE6400", gestor="podincan"),
                             COLABORADOR, dm, contexto_lote=contexto)
    checar(r.status == "REVISAO" and r.motivo_confirmado == MOTIVO_HORARIO_NEGADO,
           f"motivo recuperado + responsável incerto -> REVISAO (obtido: {r.status})")

    # Data recuperada por contexto + matrícula fora da base -> REVISAO.
    r = classificar_registro(_registro(data="23.04"), None, dm, contexto_lote=contexto)
    checar(r.status == "REVISAO" and r.data_confirmada == "23/04/26",
           f"data recuperada + matrícula fora da base -> REVISAO (obtido: {r.status}, "
           f"data={r.data_confirmada!r})")

    # Gestor identificado + matrícula ausente -> REVISAO.
    r = classificar_registro(_registro(matricula="", gestor="GR5"), None, dm,
                             contexto_lote=contexto)
    checar(r.status == "REVISAO" and r.gestor_confirmado == "GR5 - OTAVIO",
           f"gestor identificado + matrícula ausente -> REVISAO (obtido: {r.status})")

    # Todos os campos seguros -> CONFIRMADO (e a saída já normalizada).
    r = classificar_registro(_registro(data="23.04", motivo="Negade", gestor="GRS- Lmone"),
                             COLABORADOR, dm, contexto_lote=contexto)
    checar(r.status == "CONFIRMADO", f"todos os campos seguros -> CONFIRMADO (obtido: {r.status} -- {r.observacao})")
    checar(r.data_confirmada == "23/04/26" and r.motivo_confirmado == MOTIVO_HORARIO_NEGADO
           and r.gestor_confirmado == "GR5 - OTAVIO",
           f"saída normalizada (obtido: {r.data_confirmada!r}/{r.motivo_confirmado!r}/{r.gestor_confirmado!r})")
    checar("23.04" in r.observacao,
           "a Observação registra o texto original e o ano completado por contexto")
    print()


def teste_motivo_e_responsavel_ausentes_bloqueiam():
    print("=== STATUS: MOTIVO ou RESPONSÁVEL ausentes -> REVISAO ===")
    # Campos obrigatórios da folha: uma célula em branco não é "vazia e
    # válida", é uma linha que o OCR não leu.
    dm = _DMFalso(colaboradores={"19547": COLABORADOR})
    r = classificar_registro(_registro(gestor=""), COLABORADOR, dm)
    checar(r.status == "REVISAO" and "responsável não identificado" in r.observacao,
           f"responsável ausente -> REVISAO (obtido: {r.status} -- {r.observacao})")
    r = classificar_registro(_registro(motivo=""), COLABORADOR, dm)
    checar(r.status == "REVISAO" and "motivo não identificado" in r.observacao,
           f"motivo ausente -> REVISAO (obtido: {r.status} -- {r.observacao})")
    print()


TESTES = [
    teste_motivo_familia_negado,
    teste_motivo_ne6400_por_evidencia_combinada,
    teste_motivos_da_lista_fechada_preservados,
    teste_motivo_sem_evidencia_continua_revisao,
    teste_gestor_codigo_gr,
    teste_gestor_identificacao_mais_especifica_ganha,
    teste_responsavel_cortado_ou_ambiguo_continua_revisao,
    teste_data_sem_ano_reconhecida_mas_nao_completada_sozinha,
    teste_data_sem_ano_com_contexto_do_lote,
    teste_contexto_tolera_ano_lido_errado_mas_sinaliza,
    teste_data_com_formato_deformado,
    teste_data_impossivel_ou_ambigua_continua_recusada,
    teste_hora_separadores_deformados,
    teste_hora_colada_a_outro_texto,
    teste_hora_impossivel_continua_recusada,
    teste_data_hora_mescladas_com_hora_impossivel,
    teste_matricula_recuperada_e_so_digitos,
    teste_normalizacao_nao_confirma_sozinha,
    teste_motivo_e_responsavel_ausentes_bloqueiam,
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
