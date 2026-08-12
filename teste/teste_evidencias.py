"""
teste_evidencias.py — Fase 17 (motor de evidências)

Protege as três coisas que a fase precisa garantir:

  1. as evidências são registradas e preservadas (nada do que o pipeline
     já produzia se perde no caminho);
  2. AUSÊNCIA de evidência continua distinguível de evidência NEGATIVA --
     é a distinção que a Fase 12 precisou criar e que um score apagaria;
  3. o motor é OBSERVACIONAL: acrescentá-lo não muda nenhuma decisão.

Sem OCR e sem as planilhas reais: DataManager falso e determinístico, pelo
mesmo motivo de sempre (o conteúdo local de `dados/` não pode decidir se
um teste passa).

Rodar: python teste\teste_evidencias.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from leitor_matriculas.parsing.registro_parser import CampoOcr, Registro
from leitor_matriculas.validacao import evidencias as ev
from leitor_matriculas.validacao.regras import ResultadoValidacao, classificar_registro


class DataManagerFalso:
    def __init__(self, colaboradores=None, motivos=None, gestores=None):
        self._colaboradores = colaboradores if colaboradores is not None else {"1234": {
            "nome": "FULANO DE TAL", "cargo": "OPERADOR", "setor": "LOGÍSTICA"}}
        self._motivos = motivos if motivos is not None else ["HORÁRIO NEGADO", "RH", "ADM"]
        self._gestores = gestores if gestores is not None else ["DANIEL", "NAYSHA", "GR5"]
        self.avisos = []

    @property
    def colaboradores_disponivel(self): return bool(self._colaboradores)

    @property
    def motivos_disponivel(self): return bool(self._motivos)

    @property
    def gestores_disponivel(self): return bool(self._gestores)

    def buscar_colaborador(self, matricula): return self._colaboradores.get(str(matricula))

    def listar_motivos(self): return list(self._motivos)

    def listar_gestores(self): return list(self._gestores)


def _registro(matricula="1234", data="14/04/26", hora="07:53", motivo="HORÁRIO NEGADO",
              gestor="DANIEL", confianca=0.99, nao_associados=None, box=(1, 2, 3, 4)):
    campos = {}
    for nome, texto in (("matricula", matricula), ("data", data), ("hora", hora),
                        ("motivo", motivo), ("gestor", gestor)):
        if texto is not None:
            campos[nome] = CampoOcr(texto=texto, confianca=confianca, box=list(box) if box else None)
    return Registro(indice=1, campos=campos, nao_associados=list(nao_associados or []))


def _classificar(registro, dm=None, **kwargs):
    dm = dm or DataManagerFalso()
    campo = registro.campos.get("matricula")
    colaborador = dm.buscar_colaborador(campo.texto) if campo else None
    return classificar_registro(registro, colaborador, dm, **kwargs)


falhas = []


def verificar(condicao, descricao):
    if condicao:
        print(f"  OK   {descricao}")
    else:
        print(f"  FALHA {descricao}")
        falhas.append(descricao)


# ---------------------------------------------------------------------------
print("\n1. O dossiê existe e cobre os 5 campos LIDOS DA FOLHA")
resultado = _classificar(_registro())
verificar(resultado.status == "CONFIRMADO", "registro completo continua CONFIRMADO")
verificar(isinstance(resultado.dossie, ev.DossieRegistro), "resultado expõe .dossie")
for campo in ev.CAMPOS_COM_EVIDENCIA:
    verificar(not resultado.dossie.sem_evidencia(campo), f"há evidência para '{campo}'")
verificar(
    set(ev.CAMPOS_COM_EVIDENCIA) == {"data", "hora", "matricula", "motivo", "gestor"},
    "os campos cobertos são só os 5 lidos da folha (nome/setor são derivados, ficam fora)",
)
verificar(
    all(e.campo not in ("nome", "setor", "cargo") for e in resultado.dossie.evidencias),
    "nenhuma evidência é criada para nome/setor/cargo",
)

# ---------------------------------------------------------------------------
print("\n2. O contrato antigo do ResultadoValidacao continua intacto")
status, observacao = _classificar(_registro())
verificar(status == "CONFIRMADO", "desempacotamento `status, observacao = ...` continua funcionando")
verificar(isinstance(observacao, str), "a observação continua sendo texto")
verificar(len(_classificar(_registro())) == 2, "o resultado continua sendo uma tupla de 2")
verificar(
    isinstance(ResultadoValidacao("CONFIRMADO", "").dossie, ev.DossieRegistro),
    "um ResultadoValidacao construído à mão ganha um dossiê vazio, nunca None",
)

# ---------------------------------------------------------------------------
print("\n3. O valor ORIGINAL do OCR nunca se perde")
resultado = _classificar(_registro(motivo="Negade", gestor="Damil"))
brutos = {e.campo: e.valor_observado for e in resultado.dossie.evidencias
          if e.tipo == ev.TIPO_OCR_BRUTO}
verificar(brutos.get("motivo") == "Negade", "texto cru do motivo preservado ('Negade')")
verificar(brutos.get("gestor") == "Damil", "texto cru do responsável preservado ('Damil')")
normalizacoes = [e for e in resultado.dossie.do_campo("motivo")
                 if e.tipo == ev.TIPO_CORRESPONDENCIA_BASE]
verificar(
    any(e.valor_observado == "Negade" and e.valor_relacionado == "HORÁRIO NEGADO"
        for e in normalizacoes),
    "a correspondência guarda os DOIS lados: o que foi lido e o que a base devolveu",
)

# ---------------------------------------------------------------------------
print("\n4. AUSÊNCIA de evidência × evidência NEGATIVA são distinguíveis")
# (a) campo vazio, sem nada suspeito na linha -> evidência de AUSENCIA
resultado = _classificar(_registro(hora=None))
hora = resultado.dossie.do_campo("hora")
verificar(not resultado.dossie.sem_evidencia("hora"),
          "campo vazio NÃO é 'sem evidência': o motor olhou e registrou")
verificar(any(e.tipo == ev.TIPO_AUSENCIA for e in hora),
          "campo vazio produz evidência de tipo 'ausencia'")
verificar(not resultado.dossie.duvidas("hora"),
          "hora genuinamente ausente não gera DÚVIDA (campo é opcional)")
verificar(resultado.status == "CONFIRMADO", "hora ausente continua não bloqueando (Fase 2)")

# (b) campo vazio COM vestígio na linha -> evidência de CONFLITO (negativa)
resultado = _classificar(_registro(hora=None, nao_associados=[CampoOcr("07:4", 0.9, None)]))
hora = resultado.dossie.do_campo("hora")
verificar(any(e.tipo == ev.TIPO_CONFLITO for e in hora),
          "campo perdido produz evidência de 'conflito', não de 'ausencia' apenas")
verificar(bool(resultado.dossie.duvidas("hora")),
          "campo perdido produz DÚVIDA -- evidência negativa, não falta de evidência")
verificar(resultado.status == "REVISAO", "proteção da Fase 12 continua bloqueando")

# (c) um campo que o motor não olhou é o ÚNICO caso de 'sem evidência'
vazio = ev.DossieRegistro()
verificar(vazio.sem_evidencia("hora"), "dossiê vazio: sem_evidencia() é True")
vazio.registrar("hora", ev.TIPO_AUSENCIA, "teste", ev.NEUTRO, "campo vazio")
verificar(not vazio.sem_evidencia("hora"),
          "depois de registrar 'ausencia', sem_evidencia() passa a ser False")

# ---------------------------------------------------------------------------
print("\n5. A evidência que era DESCARTADA agora é preservada")
resultado = _classificar(_registro(gestor="Danil"))
correspondencias = [e for e in resultado.dossie.do_campo("gestor")
                    if e.tipo == ev.TIPO_CORRESPONDENCIA_BASE]
verificar(any("similaridade" in e.motivo for e in correspondencias),
          "a similaridade NUMÉRICA do responsável é registrada (era descartada)")
posicoes = [e for e in resultado.dossie.evidencias if e.tipo == ev.TIPO_POSICAO]
verificar(len(posicoes) == 5, "a posição (caixa) de cada um dos 5 campos é registrada")
verificar(posicoes[0].valor_observado == "1,2,3,4", "a caixa é guardada como x1,y1,x2,y2")
brutos = [e for e in resultado.dossie.evidencias if e.tipo == ev.TIPO_OCR_BRUTO]
verificar(all(e.valor_relacionado is not None for e in brutos),
          "a confiança do OCR acompanha cada leitura, inclusive num CONFIRMADO")

# ---------------------------------------------------------------------------
print("\n6. O campo que BLOQUEOU o registro fica identificado")
resultado = _classificar(_registro(data="xx/xx/xx"))
verificar(resultado.status == "REVISAO", "data ilegível continua bloqueando")
regras_data = [e for e in resultado.dossie.do_campo("data") if e.tipo == ev.TIPO_REGRA]
verificar(bool(regras_data), "o bloqueio é registrado no campo DATA")
verificar(all(e.resultado == ev.DUVIDA for e in regras_data), "e é registrado como DÚVIDA")
verificar(not [e for e in resultado.dossie.do_campo("gestor") if e.tipo == ev.TIPO_REGRA],
          "o campo que não bloqueou não recebe evidência de regra bloqueante")

resultado = _classificar(_registro(gestor="ZZZZZZ"))
verificar(resultado.status == "REVISAO", "responsável fora da base continua bloqueando")
verificar(any(e.tipo == ev.TIPO_REGRA for e in resultado.dossie.do_campo("gestor")),
          "o bloqueio por responsável é registrado no campo GESTOR")

# ---------------------------------------------------------------------------
print("\n7. Não existe score — favoráveis e dúvidas ficam listados lado a lado")
verificar(not hasattr(ev, "pontuar"), "o módulo não expõe nenhuma função de pontuação")
resumo = ev.resumo_por_campo(_classificar(_registro(gestor="ZZZZZZ")).dossie)
verificar(set(resumo["gestor"]) == {"favoraveis", "duvidas", "total"},
          "o resumo é contagem por campo, não uma nota")
verificar(all(isinstance(v, int) for v in resumo["gestor"].values()),
          "são contagens inteiras, nunca uma fração/percentual")

# ---------------------------------------------------------------------------
print("\n8. Ida e volta para dados puros (é assim que o dossiê é guardado)")
resultado = _classificar(_registro(hora=None, nao_associados=[CampoOcr("07:4", 0.9, None)]))
planos = resultado.dossie.como_dicionarios()
verificar(all(isinstance(d, dict) for d in planos), "vira lista de dicts puros")
verificar(
    all(isinstance(v, (str, type(None))) for d in planos for v in d.values()),
    "só contém strings/None -- nenhum objeto vivo preso na memória do lote",
)
reconstruido = ev.DossieRegistro.de_dicionarios(planos)
verificar(len(reconstruido) == len(resultado.dossie), "reconstrução preserva a quantidade")
verificar(
    [e.como_dicionario() for e in reconstruido.evidencias] == planos,
    "reconstrução preserva o conteúdo campo a campo",
)
verificar([e.campo for e in reconstruido.evidencias] == [e.campo for e in resultado.dossie.evidencias],
          "reconstrução preserva a ORDEM (a ordem é a cadeia de raciocínio)")

# ---------------------------------------------------------------------------
print("\n9. O motor é OBSERVACIONAL: as decisões não mudam")
casos = [
    ("completo", _registro(), "CONFIRMADO"),
    ("sem hora", _registro(hora=None), "CONFIRMADO"),
    ("hora ilegível", _registro(hora="zz:zz"), "CONFIRMADO"),
    ("hora perdida", _registro(hora=None, nao_associados=[CampoOcr("07:4", 0.9, None)]), "REVISAO"),
    ("data ilegível", _registro(data="xx"), "REVISAO"),
    ("sem data", _registro(data=None), "REVISAO"),
    ("sem matrícula", _registro(matricula=None), "REVISAO"),
    ("matrícula fora da base", _registro(matricula="9999"), "REVISAO"),
    ("confiança baixa", _registro(confianca=0.10), "REVISAO"),
    ("sem motivo", _registro(motivo=None), "REVISAO"),
    ("sem responsável", _registro(gestor=None), "REVISAO"),
    ("responsável fora da base", _registro(gestor="ZZZZZZ"), "REVISAO"),
    ("motivo fora da base", _registro(motivo="ZZZZZZ"), "REVISAO"),
]
for nome, registro, esperado in casos:
    obtido = _classificar(registro).status
    verificar(obtido == esperado, f"{nome}: {esperado} (obtido {obtido})")

# ---------------------------------------------------------------------------
print("\n10. Registrar evidência nunca derruba o processamento")
dossie = ev.DossieRegistro()
try:
    dossie.registrar("campo_inexistente", "tipo_desconhecido", "?", "RESULTADO_ESTRANHO", "x",
                     valor_observado=123, valor_relacionado=None)
    verificar(len(dossie) == 1, "vocabulário inesperado é registrado em vez de virar exceção")
    verificar(dossie.evidencias[0].valor_observado == "123", "valores não-texto viram texto")
except Exception as exc:  # pragma: no cover
    verificar(False, f"registrar() levantou exceção: {exc}")
verificar(ev.DossieRegistro.de_dicionarios(None) is not None,
          "de_dicionarios(None) devolve um dossiê vazio em vez de quebrar")
verificar(vazio.explicar("campo_que_nao_existe").endswith("nenhuma evidência registrada"),
          "explicar() de campo sem evidência devolve texto, não exceção")

# ---------------------------------------------------------------------------
print("\n11. Evidência de CONTEXTO representa os sinais aprovados na Fase 16")
verificar(ev.CONTEXTO_ANO_DO_LOTE in ev.ORIGENS_CONTEXTO, "ano do lote (Fase 9) é origem declarada")
for origem in (ev.CONTEXTO_GESTORES_DO_LOTE, ev.CONTEXTO_ORDEM_CRONOLOGICA,
               ev.CONTEXTO_RUBRICA_REPETIDA):
    verificar(origem in ev.ORIGENS_CONTEXTO,
              f"sinal aprovado na Fase 16 tem origem declarada: {origem}")


class ContextoFalso:
    """Só o contrato que `classificar_registro` usa."""
    def completar_ano(self, texto): return "23/04/26" if texto == "23.04" else None
    def ano_divergente_do_lote(self, texto): return None
    def ano_do_lote(self): return 2026


resultado = _classificar(_registro(data="23.04"), contexto_lote=ContextoFalso())
contextos = [e for e in resultado.dossie.do_campo("data") if e.tipo == ev.TIPO_CONTEXTO]
verificar(len(contextos) == 1, "o ano completado pelo lote vira evidência de 'contexto'")
verificar(contextos[0].origem == ev.CONTEXTO_ANO_DO_LOTE, "com a origem correta")
verificar(contextos[0].valor_observado == "23.04" and contextos[0].valor_relacionado == "23/04/26",
          "guardando o texto sem ano E a data completada")
verificar(resultado.status == "CONFIRMADO", "e a recuperação da Fase 9 continua funcionando")

# ---------------------------------------------------------------------------
print()
if falhas:
    print(f"{len(falhas)} FALHA(S):")
    for f in falhas:
        print(f"  - {f}")
    sys.exit(1)
print("Todos os blocos passaram.")
