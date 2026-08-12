"""
teste_registro_correcoes.py — Fase 20 (H5: histórico de correções humanas)

O módulo testado é infraestrutura de COLETA: ele grava o que o operador
corrigiu e não é lido por ninguém. Por isso o que precisa ser protegido
aqui não é "aprendeu certo" (não há aprendizado), e sim:

  1. o registro preserva o que se perdia -- qual campo mudou, o valor
     anterior, e o texto que o OCR leu em CADA um dos 5 campos (a planilha
     exportada só preservava o da matrícula);
  2. gravar é ADITIVO e nunca destrutivo -- uma correção nova não reescreve
     as anteriores;
  3. uma falha de gravação NUNCA derruba o fluxo (mesmo critério da
     miniatura da foto na Fase 10: comodidade, não dado crítico);
  4. correção que NÃO resolveu é registrada como tal (some primeiro de
     qualquer registro informal, e é justamente o contraexemplo);
  5. NOME e SETOR não entram -- não são lidos da folha, são derivados da
     matrícula por busca na base.

Sem OCR, sem as planilhas reais e sem tocar no arquivo real de `dados/`:
tudo vai para um arquivo temporário.

Rodar: python teste\teste_registro_correcoes.py
"""

import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from leitor_matriculas.dados import registro_correcoes as rc


def _dossie_de_exemplo():
    """Dossiê como a Fase 17 o grava: o `ocr_bruto` de cada campo e a
    evidência de `regra`/DUVIDA que identifica o campo bloqueante."""
    return [
        {"campo": "data", "tipo": "ocr_bruto", "origem": "ocr.engine", "resultado": "NEUTRO",
         "motivo": "texto lido pelo OCR nesta coluna", "valor_observado": "28.04.20",
         "valor_relacionado": None},
        {"campo": "gestor", "tipo": "ocr_bruto", "origem": "ocr.engine", "resultado": "NEUTRO",
         "motivo": "texto lido pelo OCR nesta coluna", "valor_observado": "ANiDERSON",
         "valor_relacionado": None},
        {"campo": "motivo", "tipo": "ocr_bruto", "origem": "ocr.engine", "resultado": "NEUTRO",
         "motivo": "texto lido pelo OCR nesta coluna", "valor_observado": "NoGAAO",
         "valor_relacionado": None},
        {"campo": "data", "tipo": "regra", "origem": "validacao.regras", "resultado": "DUVIDA",
         "motivo": "ano da data destoa do restante do lote", "valor_observado": "28.04.20",
         "valor_relacionado": None},
    ]


def _antes():
    return {
        "data": "28/04/20", "hora": "14:08", "matricula": "30874",
        "nome": "FULANO DE TAL", "setor": "ENTREGA", "cargo": "AUX",
        "gestor": "ANDERSON", "motivo": "NoGAAO",
        "pagina_origem": 3, "status": "REVISAO",
        "observacao": "ano da data (2020) destoa do restante do lote (2026)",
        "evidencias": _dossie_de_exemplo(),
    }


def _depois():
    d = _antes()
    d.update({
        "data": "28/04/26", "gestor": "ANDERSON ABREU", "motivo": "HORÁRIO NEGADO",
        "status": "CONFIRMADO", "observacao": "corrigido manualmente",
    })
    return d


# ---------------------------------------------------------------------------
# 1. O registro preserva o que se perdia
# ---------------------------------------------------------------------------
antes, depois = _antes(), _depois()
reg = rc.montar_registro_correcao(antes, depois, antes["evidencias"])

assert reg["campos_alterados"] == ["data", "motivo", "gestor"], reg["campos_alterados"]
assert reg["campos"]["data"]["antes"] == "28/04/20"
assert reg["campos"]["data"]["depois"] == "28/04/26"
assert reg["campos"]["hora"]["alterado"] is False
# O texto BRUTO do OCR de cada campo -- a peça que a planilha exportada
# só preservava para a matrícula.
assert reg["campos"]["gestor"]["ocr"] == "ANiDERSON", reg["campos"]["gestor"]
assert reg["campos"]["motivo"]["ocr"] == "NoGAAO"
assert reg["campos"]["data"]["ocr"] == "28.04.20"
# Campo sem leitura de OCR no dossiê fica explicitamente sem leitura --
# não vira string vazia, que seria indistinguível de "o OCR leu nada".
assert reg["campos"]["matricula"]["ocr"] is None
assert reg["campos_bloqueantes_antes"] == ["data"], reg["campos_bloqueantes_antes"]
assert reg["status_antes"] == "REVISAO" and reg["status_depois"] == "CONFIRMADO"
assert reg["resolveu"] is True
assert reg["pagina"] == 3
assert reg["esquema"] == rc.ESQUEMA and reg["versao_sistema"] == rc.VERSAO_SISTEMA
assert reg["quando"]
print("OK: a correção preserva campo alterado, valor anterior, texto do OCR e campo bloqueante")

# ---------------------------------------------------------------------------
# 2. NOME e SETOR não entram (não são lidos da folha)
# ---------------------------------------------------------------------------
assert set(reg["campos"]) == set(rc.CAMPOS_REGISTRADOS)
assert "nome" not in reg["campos"] and "setor" not in reg["campos"]
print("OK: NOME e SETOR ficam de fora -- são derivados da matrícula, não lidos do papel")

# ---------------------------------------------------------------------------
# 3. Correção que NÃO resolveu é registrada como tal
# ---------------------------------------------------------------------------
nao_resolveu = _antes()
nao_resolveu["gestor"] = "ANDERSON ABREU"
nao_resolveu["status"] = "REVISAO"
nao_resolveu["observacao"] = "revisão manual incompleta -- data não identificada"
reg2 = rc.montar_registro_correcao(_antes(), nao_resolveu, _antes()["evidencias"])
assert reg2["resolveu"] is False
assert reg2["status_depois"] == "REVISAO"
assert reg2["campos_alterados"] == ["gestor"]
print("OK: correção que continuou em REVISAO é registrada (contraexemplo não se perde)")

# ---------------------------------------------------------------------------
# 4. Gravação é ADITIVA: uma correção nova não reescreve as anteriores
# ---------------------------------------------------------------------------
pasta = tempfile.mkdtemp(prefix="teste_correcoes_")
caminho = os.path.join(pasta, "sub", "correcoes_humanas.jsonl")  # pasta criada na hora

assert rc.registrar_correcao(_antes(), _depois(), _antes()["evidencias"], caminho=caminho) is True
assert rc.registrar_correcao(_antes(), nao_resolveu, _antes()["evidencias"], caminho=caminho) is True

lidas = rc.ler_correcoes(caminho)
assert len(lidas) == 2, len(lidas)
assert lidas[0]["resolveu"] is True and lidas[1]["resolveu"] is False
# uma linha por correção, JSON válido em cada uma
with open(caminho, encoding="utf-8") as fh:
    linhas = [l for l in fh.read().split("\n") if l.strip()]
assert len(linhas) == 2
for linha in linhas:
    json.loads(linha)
print("OK: gravação append-only -- a segunda correção não reescreveu a primeira")

# ---------------------------------------------------------------------------
# 5. Ida e volta pelo arquivo preserva o conteúdo
# ---------------------------------------------------------------------------
assert lidas[0]["campos"]["gestor"]["ocr"] == "ANiDERSON"
assert lidas[0]["campos_alterados"] == ["data", "motivo", "gestor"]
print("OK: ida e volta pelo arquivo preserva a correção inteira")

# ---------------------------------------------------------------------------
# 6. Falha de gravação NUNCA derruba o fluxo
# ---------------------------------------------------------------------------
# Caminho impossível (um arquivo existente usado como se fosse pasta).
arquivo_no_lugar_da_pasta = os.path.join(pasta, "arquivo.txt")
with open(arquivo_no_lugar_da_pasta, "w", encoding="utf-8") as fh:
    fh.write("nao sou uma pasta")
caminho_ruim = os.path.join(arquivo_no_lugar_da_pasta, "correcoes.jsonl")
# A falha é esperada AQUI: o módulo registra a exceção no log e segue. O
# traceback é justamente o comportamento correto, mas silenciá-lo evita que
# a saída deste teste pareça um erro para quem o roda.
logging.disable(logging.CRITICAL)
try:
    assert rc.registrar_correcao(_antes(), _depois(), None, caminho=caminho_ruim) is False
finally:
    logging.disable(logging.NOTSET)
print("OK: falha de gravação devolve False, sem levantar exceção")

# Conteúdo inesperado também não pode explodir.
assert rc.registrar_correcao({}, {}, None, caminho=caminho) is True
assert rc.registrar_correcao(_antes(), _depois(), "isto não é uma lista de evidências",
                             caminho=caminho) is True
assert rc.ler_correcoes(os.path.join(pasta, "nao_existe.jsonl")) == []
print("OK: dict vazio, dossiê inválido e arquivo inexistente são tolerados")

# Arquivo com uma linha corrompida no meio não invalida as demais.
with open(caminho, "a", encoding="utf-8", newline="\n") as fh:
    fh.write("{isto nao e json\n")
assert rc.registrar_correcao(_antes(), _depois(), None, caminho=caminho) is True
lidas_depois = rc.ler_correcoes(caminho)
assert len(lidas_depois) == 5, len(lidas_depois)
print("OK: linha corrompida é pulada sem inutilizar o histórico anterior")

# ---------------------------------------------------------------------------
# 7. O caminho padrão aponta para dados/ na RAIZ (mesma resolução do
#    DataManager -- três níveis acima do pacote)
# ---------------------------------------------------------------------------
padrao = rc.caminho_padrao()
assert padrao.endswith(os.path.join("dados", "correcoes_humanas.jsonl")), padrao
assert os.path.isdir(os.path.dirname(padrao)), padrao
print("OK: caminho padrão resolve para <raiz>/dados/correcoes_humanas.jsonl")

# ---------------------------------------------------------------------------
# 8. O módulo não é lido por ninguém do fluxo de decisão (REVERSIBILIDADE)
# ---------------------------------------------------------------------------
raiz_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
for modulo in ("validacao/regras.py", "validacao/evidencias.py",
               "exportacao/xlsx_exporter.py", "parsing/registro_parser.py"):
    with open(os.path.join(raiz_src, "leitor_matriculas", modulo), encoding="utf-8") as fh:
        assert "registro_correcoes" not in fh.read(), modulo
with open(os.path.join(raiz_src, "leitor_matriculas", "ui", "app.py"), encoding="utf-8") as fh:
    conteudo_app = fh.read()
# A interface só GRAVA. Ler o histórico (ler_correcoes) em qualquer ponto do
# fluxo seria transformar coleta em decisão -- que é o que esta fase não faz.
assert "registrar_correcao" in conteudo_app
assert "ler_correcoes" not in conteudo_app
print("OK: nenhum módulo de decisão importa o histórico; a UI só grava, nunca lê")

print("\nTodos os testes de registro de correções humanas passaram.")
