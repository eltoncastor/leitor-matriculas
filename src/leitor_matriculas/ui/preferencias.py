"""
ui/preferencias.py

Sub-fase 22e (Fase 22 -- redesign visual): persistência mínima da
preferência de tema (claro/escuro) -- a ÚNICA preferência real que
existe no projeto até agora. A auditoria da 21a (sidebar) e da 21d
("Configurações") já tinham concluído que não existe nenhuma outra
opção de usuário real para guardar; um alternador de tema É, ele
mesmo, uma preferência real, então este módulo existe só para ela,
não como o início de uma tela de Configurações.

Puro, sem Tkinter: só lê/escreve um JSON de uma chave. Testável sem
abrir janela, mesmo espírito de `ui/estilos.py`/`ui/mensagens.py`.

FICA FORA de `dados/` de propósito: `dados/` é reservado às bases de
referência (Colaboradores/Gestores/Motivos) e ao histórico de correções
humanas (Fase 20), que carregam dado real de operação (matrículas,
nomes). Preferência de tema não é dado de negócio nenhum -- misturar os
dois faria parecer que este arquivo precisa do mesmo cuidado de
privacidade que aqueles, e não precisa.

Falha de leitura/escrita nunca derruba a aplicação -- mesmo critério já
usado em `dados/registro_correcoes.py` e na miniatura da Fase 10: uma
preferência de interface não pode custar o uso do programa. Sem
persistência (arquivo ausente, corrompido ou sem permissão de escrita),
o programa simplesmente abre no tema claro padrão -- nunca trava a
abertura, nunca lança para quem chama.
"""

import json
import logging
import os

NOME_ARQUIVO = "preferencias_ui.json"


def caminho_padrao() -> str:
    """
    `<raiz>/preferencias_ui.json`.

    Mesma resolução de caminho de `dados/data_manager.py` e
    `dados/registro_correcoes.py` (três níveis acima deste arquivo --
    `ui/` -> `leitor_matriculas/` -> `src/` -> raiz) mas apontando para
    a RAIZ do projeto, não para dentro de `dados/`.
    """
    raiz_projeto = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )
    return os.path.join(raiz_projeto, NOME_ARQUIVO)


def carregar_tema_escuro(caminho: str = None) -> bool:
    """
    Devolve True se a última sessão salva estava no tema escuro.

    Qualquer falha (arquivo ausente -- o caso normal na primeira vez que
    o programa roda --, corrompido, sem permissão) devolve False: abre
    no tema claro, nunca trava a abertura do programa por causa de uma
    preferência.
    """
    caminho = caminho or caminho_padrao()
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return bool(dados.get("tema_escuro", False))
    except Exception:
        return False


def salvar_tema_escuro(escuro: bool, caminho: str = None) -> bool:
    """
    Grava a preferência de tema. Devolve False (nunca lança) se a
    escrita falhar -- disco cheio ou pasta sem permissão de escrita não
    pode impedir o operador de continuar usando o programa, só a
    preferência não persiste para a próxima sessão.
    """
    caminho = caminho or caminho_padrao()
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"tema_escuro": bool(escuro)}, f)
        return True
    except Exception:
        logging.exception("Falha ao salvar a preferência de tema (apenas cosmético)")
        return False
