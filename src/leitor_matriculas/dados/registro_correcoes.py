"""
registro_correcoes.py

Registro em disco das CORREÇÕES HUMANAS aplicadas na aba Revisão
(Fase 20 -- H5).

POR QUE ISTO EXISTE
-------------------
Este módulo NÃO aprende nada, NÃO decide nada e NÃO é lido por nenhuma
parte do sistema. Ele só grava, depois que a decisão já foi tomada, o que
o operador corrigiu. É infraestrutura de COLETA, não de aprendizado.

A justificativa é uma medição, não uma expectativa. A Fase 20 tentou
avaliar quatro hipóteses de aprendizado (ajuste de limiares, expansão de
vocabulário, priorização de sugestões e mapeamento OCR->valor) e todas as
quatro esbarraram no MESMO obstáculo: não existe histórico. O único
vestígio de uma sessão real de operador era uma planilha exportada com 7
linhas marcadas "corrigido manualmente" -- e essa planilha guarda o
estado POSTERIOR à correção. Descobrir o que foi corrigido exigiu
reprocessar o PDF inteiro pelo OCR e comparar as duas saídas por
diferença; o resultado é uma INFERÊNCIA, não um registro, e nem sequer é
estável (a Fase 15 mediu que duas execuções do OCR sobre as mesmas
imagens divergem entre si).

O que se perdia a cada correção, e que este módulo passa a preservar:

    - QUAL campo foi corrigido (a planilha só diz que "algo" foi);
    - o VALOR ANTERIOR de cada campo (sobrescrito em memória por
      `_revisao_confirmar`);
    - o TEXTO BRUTO QUE O OCR LEU em cada um dos 5 campos (a planilha só
      preserva o da matrícula, na coluna técnica);
    - qual campo BLOQUEAVA o registro antes da correção;
    - se a correção de fato resolveu (o operador pode corrigir e a linha
      continuar em REVISAO).

Tudo isso JÁ EXISTE em memória no instante da confirmação -- não é
telemetria nova, é deixar de jogar fora. O dossiê da Fase 17 é o que
torna o texto bruto de todos os campos recuperável aqui.

O QUE ESTE MÓDULO NÃO PODE FAZER
--------------------------------
    - não é lido por `classificar_registro` nem por `_revisao_confirmar`;
    - não influencia nenhum status, nenhuma sugestão e nenhuma planilha;
    - não pode derrubar o fluxo principal: qualquer falha de escrita é
      engolida (só vai para o log), pelo mesmo critério que a Fase 10
      aplica à miniatura da foto -- é comodidade para o futuro, não dado
      crítico do lote em andamento.

REVERSIBILIDADE: como nada lê o arquivo, apagá-lo devolve o sistema
exatamente ao estado anterior a esta fase. Não há conhecimento aprendido
escondido em constante, condicional ou lista -- só um arquivo de texto
que ninguém consulta.

FORMATO: JSONL (uma correção por linha). Escolhido por ser append-only --
uma correção nova nunca reescreve as anteriores, e um arquivo truncado no
meio ainda tem todas as linhas anteriores legíveis. Cada linha carrega
`esquema` e `versao_sistema` para que uma mudança futura de formato seja
identificável sem adivinhação.

PRIVACIDADE: o arquivo contém matrículas, nomes de gestores e datas
reais. Fica em `dados/` (junto das outras bases reais) e está no
`.gitignore` pelo mesmo motivo que os XLSX: nunca deve ser versionado.
"""

import datetime
import json
import logging
import os
from typing import Optional

# Versão do sistema estampada em cada correção. É o que permite, no
# futuro, separar correções feitas por versões diferentes do programa --
# uma correção registrada antes de uma mudança de regra não é evidência
# sobre o comportamento de depois dela.
VERSAO_SISTEMA = "0.6.0-fase20"

# Versão do FORMATO do registro. Muda quando os campos mudarem, para que
# um leitor futuro saiba o que esperar de cada linha.
ESQUEMA = 1

NOME_ARQUIVO_PADRAO = "correcoes_humanas.jsonl"

# Os 5 campos LIDOS DA FOLHA. Os mesmos de `evidencias.CAMPOS_COM_EVIDENCIA`
# e pela mesma razão: NOME e SETOR não são lidos do papel, são derivados da
# matrícula por busca na base -- não há correção humana de leitura a
# registrar sobre eles.
CAMPOS_REGISTRADOS = ("data", "hora", "matricula", "motivo", "gestor")


def caminho_padrao() -> str:
    """
    `<raiz>/dados/correcoes_humanas.jsonl`.

    Mesma resolução de caminho (e mesma armadilha) de `data_manager.py`:
    este arquivo está em `<raiz>/src/leitor_matriculas/dados/`, logo a
    raiz são três níveis acima. Mover este módulo de profundidade quebra
    o caminho em silêncio.
    """
    raiz_projeto = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )
    return os.path.join(raiz_projeto, "dados", NOME_ARQUIVO_PADRAO)


def _texto_ocr_por_campo(evidencias) -> dict:
    """
    Extrai do dossiê ANTERIOR o texto que o OCR leu em cada campo.

    É a peça que não sobrevivia à correção: `_revisao_confirmar`
    sobrescreve `registro["evidencias"]` com o dossiê da REavaliação, cujo
    `ocr_bruto` passa a ser o valor DIGITADO pela pessoa. Sem capturar
    antes, a leitura original do OCR some para todos os campos menos a
    matrícula.
    """
    leituras = {}
    for evidencia in evidencias or []:
        if not isinstance(evidencia, dict):
            continue
        if evidencia.get("tipo") != "ocr_bruto":
            continue
        campo = evidencia.get("campo")
        # Só a PRIMEIRA leitura de cada campo: é a original.
        if campo in CAMPOS_REGISTRADOS and campo not in leituras:
            leituras[campo] = evidencia.get("valor_observado")
    return leituras


def _campos_bloqueantes(evidencias) -> list:
    """
    Quais campos derrubaram o registro, segundo o dossiê anterior. É a
    pergunta que a `observacao` só respondia em prosa, e a que qualquer
    análise futura de "o que o humano teve de consertar" precisa fazer.
    """
    bloqueantes = []
    for evidencia in evidencias or []:
        if not isinstance(evidencia, dict):
            continue
        if evidencia.get("tipo") == "regra" and evidencia.get("resultado") == "DUVIDA":
            campo = evidencia.get("campo")
            if campo and campo not in bloqueantes:
                bloqueantes.append(campo)
    return bloqueantes


def montar_registro_correcao(antes: dict, depois: dict, evidencias_antes=None) -> dict:
    """
    Monta o dicionário de UMA correção, sem tocar em disco (é a parte
    testável sem arquivo).

    `antes`  -- cópia do dict de exportação ANTES da reclassificação.
    `depois` -- o mesmo dict DEPOIS.
    `evidencias_antes` -- `registro["evidencias"]` de antes da sobrescrita.

    Não interpreta nem julga a correção: só descreve os dois estados e
    aponta o que mudou entre eles. Decidir o que isso significa é problema
    de quem for analisar o arquivo, com volume suficiente para tanto.
    """
    leituras_ocr = _texto_ocr_por_campo(evidencias_antes)

    campos = {}
    alterados = []
    for campo in CAMPOS_REGISTRADOS:
        valor_antes = (antes.get(campo) or "") if antes else ""
        valor_depois = (depois.get(campo) or "") if depois else ""
        mudou = str(valor_antes).strip() != str(valor_depois).strip()
        if mudou:
            alterados.append(campo)
        campos[campo] = {
            "antes": str(valor_antes),
            "depois": str(valor_depois),
            "ocr": leituras_ocr.get(campo),
            "alterado": mudou,
        }

    return {
        "esquema": ESQUEMA,
        "versao_sistema": VERSAO_SISTEMA,
        # Hora local, sem fuso: o operador raciocina sobre o próprio
        # relógio, e o arquivo é local à instalação.
        "quando": datetime.datetime.now().isoformat(timespec="seconds"),
        "pagina": (antes or {}).get("pagina_origem"),
        "status_antes": (antes or {}).get("status"),
        "status_depois": (depois or {}).get("status"),
        # A correção pode NÃO resolver: `_revisao_confirmar` só tira da
        # lista o que a validação aceitar. Uma correção que não resolveu é
        # evidência tão legítima quanto uma que resolveu -- e some primeiro
        # de qualquer registro informal.
        "resolveu": (depois or {}).get("status") == "CONFIRMADO",
        "campos_bloqueantes_antes": _campos_bloqueantes(evidencias_antes),
        "campos_alterados": alterados,
        "campos": campos,
        "observacao_antes": (antes or {}).get("observacao") or "",
        "observacao_depois": (depois or {}).get("observacao") or "",
    }


def registrar_correcao(antes: dict, depois: dict, evidencias_antes=None,
                       caminho: Optional[str] = None) -> bool:
    """
    Acrescenta UMA correção ao arquivo. Devolve True quando gravou.

    NUNCA levanta exceção: disco cheio, pasta somente-leitura, arquivo
    aberto no Excel -- nada disso pode interromper uma revisão em
    andamento. Falhar aqui custa uma linha de histórico; deixar a exceção
    escapar custaria o lote inteiro que ainda não foi exportado.
    """
    destino = caminho or caminho_padrao()
    try:
        linha = json.dumps(
            montar_registro_correcao(antes, depois, evidencias_antes),
            ensure_ascii=False,
        )
        pasta = os.path.dirname(destino)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        # "a" + newline="\n": append puro, uma linha por correção, sem
        # reescrever nada do que já está lá.
        with open(destino, "a", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(linha + "\n")
        return True
    except Exception:
        logging.exception("Falha ao registrar a correção humana (o fluxo continua)")
        return False


def ler_correcoes(caminho: Optional[str] = None) -> list:
    """
    Lê o arquivo de volta. Existe para a ANÁLISE futura e para os testes
    -- o sistema em execução não chama isto em lugar nenhum.

    Linhas ilegíveis são puladas em silêncio: um arquivo truncado por uma
    queda de energia não pode inutilizar todo o histórico anterior.
    """
    origem = caminho or caminho_padrao()
    correcoes = []
    try:
        with open(origem, encoding="utf-8") as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    correcoes.append(json.loads(linha))
                except ValueError:
                    continue
    except FileNotFoundError:
        return []
    except Exception:
        logging.exception("Falha ao ler o histórico de correções humanas")
        return []
    return correcoes
