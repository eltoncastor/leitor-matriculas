"""
teste/teste_alternar_tema.py

Sub-fase 22e (Fase 22 -- redesign visual): a alternância de tema
claro/escuro em tempo de execução (`App._alternar_tema`) e a
persistência da preferência (`ui/preferencias.py`).

ARQUIVO SEPARADO de propósito -- não um bloco a mais em
`teste_ui_integracao.py`, e por isso mesmo com UMA SÓ `App()` criada em
todo o processo (`teste_tk_*` abaixo), não uma por função de teste.
`self.style.theme_use(...)` (ttkbootstrap) depende de `tkinter.
_default_root`/`Style.master`, e esse vínculo só fica correto para a
PRIMEIRA janela Tk criada no processo -- confirmado por medição direta
(ver `saida/avaliacao_fase22_redesign.md`, seção 22e): com uma única
`App()` durante toda a vida do processo, a troca de tema funciona sem
nenhum erro; assim que uma SEGUNDA `App()` é criada no mesmo processo
(mesmo depois de destruir a primeira -- foi tentado e reproduz igual),
a MESMA troca de tema lança um `TclError` de dentro do próprio
`ttkbootstrap` ao gerar os recursos visuais do tema novo (`scale_size`
chamando `self.style.master.tk`, que aponta para a raiz Tk da janela
JÁ destruída). É um limite conhecido do `ttkbootstrap` para múltiplas
janelas por processo -- a mesma classe do `TclError` cosmético do
`TPanedwindow` já documentado nas sub-fases 22c/22d --, não um bug
desta sub-fase, e não afeta o uso real (o programa só cria uma `App()`
por processo, nunca duas). Por isso este arquivo cria só UMA `App()`
(a função `teste_tk_ciclo_completo_de_alternancia_de_tema`) em vez de
uma por caso, e é por isso que é um arquivo À PARTE: um teste isolado
por processo é o único jeito de garantir "primeira e única janela",
exatamente como a operação real.

Uso:
    python teste\\teste_alternar_tema.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch

from leitor_matriculas.ui.app import App
from leitor_matriculas.ui import estilos
from leitor_matriculas.ui import preferencias


def teste_tk_ciclo_completo_de_alternancia_de_tema():
    """
    Uma única `App()` para todo o ciclo: abre no claro (sem preferência
    salva) -> alterna pra escuro (troca de verdade + persiste) -> volta
    pro claro (troca de verdade + persiste) -> nenhum registro/base/
    status foi alterado no meio disso. Tudo numa função só de propósito
    -- ver o porquê no docstring do módulo.
    """
    print("=== Teste 1: ciclo completo de alternância de tema (uma só App() no processo) ===")
    tmp = tempfile.mkdtemp(prefix="teste_tema_")
    arquivo = os.path.join(tmp, "preferencias_ui.json")
    with patch("leitor_matriculas.ui.app.Messagebox.show_error"), \
         patch("leitor_matriculas.ui.app.Messagebox.show_warning"), \
         patch("leitor_matriculas.ui.app.Messagebox.show_info"), \
         patch("leitor_matriculas.ui.preferencias.caminho_padrao", return_value=arquivo):
        app = App()

        # -- 1a: sem preferência salva, abre no tema claro -------------
        assert not app._tema_escuro
        assert app.style.theme_use() == estilos.TEMA_CLARO
        assert not estilos.modo_escuro_ativo()
        print("  OK: abre em TEMA_CLARO sem preferência salva")

        # -- 1b: dados sintéticos, para provar que trocar de tema é SÓ
        # apresentação (nenhum registro/base/status muda) -------------
        app._registros_exportacao = [
            {
                "data": "23/04/26", "hora": "07:53", "matricula": "10001",
                "nome": "Fulano de Tal", "cargo": "Auxiliar", "setor": "Logística",
                "gestor": "GR1 - Fulano", "motivo": "RH", "pagina_origem": 1,
                "status": "CONFIRMADO", "confianca_matricula": 0.9,
                "confianca_gestor": "", "confianca_motivo": "", "observacao": "",
                "texto_ocr_original": "10001", "ocr_nao_associados": [], "evidencias": [],
            },
            {
                "data": "23/04/26", "hora": "", "matricula": "99999",
                "nome": "(não encontrado)", "cargo": "(não encontrado)", "setor": "(não encontrado)",
                "gestor": "X", "motivo": "ADM", "pagina_origem": 1,
                "status": "REVISAO", "confianca_matricula": 0.5,
                "confianca_gestor": "", "confianca_motivo": "",
                "observacao": "matrícula não encontrada na base de colaboradores",
                "texto_ocr_original": "99999", "ocr_nao_associados": [], "evidencias": [],
            },
        ]
        app._sincronizar_tabela_principal()
        registros_antes = [dict(r) for r in app._registros_exportacao]
        avisos_bases_antes = list(app._data_manager.avisos)
        pendentes_antes = app._indices_pendentes_revisao()
        confirmados_antes = app._contador_confirmados
        revisao_antes = app._contador_revisao

        # -- 1c: alterna para escuro -- troca de verdade + persiste ----
        app._alternar_tema()
        assert app._tema_escuro
        assert app.style.theme_use() == estilos.TEMA_ESCURO
        assert estilos.modo_escuro_ativo()
        with open(arquivo, encoding="utf-8") as f:
            assert json.load(f) == {"tema_escuro": True}
        print("  OK: _alternar_tema troca o tema ativo de verdade e grava a preferência em disco")

        # -- 1d: nada de negócio mudou no meio da troca -----------------
        assert app._registros_exportacao == registros_antes, "trocar de tema alterou um registro"
        assert app._data_manager.avisos == avisos_bases_antes
        assert app._indices_pendentes_revisao() == pendentes_antes
        assert app._contador_confirmados == confirmados_antes
        assert app._contador_revisao == revisao_antes
        print("  OK: nenhum registro/base/contador de status foi alterado pela troca de tema")

        # -- 1e: volta para claro -- troca de verdade + persiste -------
        app._alternar_tema()
        assert not app._tema_escuro
        assert app.style.theme_use() == estilos.TEMA_CLARO
        assert not estilos.modo_escuro_ativo()
        with open(arquivo, encoding="utf-8") as f:
            assert json.load(f) == {"tema_escuro": False}
        print("  OK: alternar de volta funciona e atualiza a preferência salva")

        app.destroy()
    print()


def teste_carregar_tema_escuro_tolera_arquivo_ausente_ou_corrompido():
    print("=== Teste 2: preferência ausente/corrompida nunca trava -- cai no tema claro (sem Tk) ===")
    tmp = tempfile.mkdtemp(prefix="teste_tema_")
    ausente = os.path.join(tmp, "nao_existe.json")
    assert preferencias.carregar_tema_escuro(ausente) is False

    corrompido = os.path.join(tmp, "corrompido.json")
    with open(corrompido, "w", encoding="utf-8") as f:
        f.write("{ isto nao é json valido")
    assert preferencias.carregar_tema_escuro(corrompido) is False
    print("  OK")
    print()


def teste_salvar_tema_escuro_nunca_lanca_em_falha_de_escrita():
    print("=== Teste 3: falha ao salvar (pasta inexistente) devolve False, nunca lança (sem Tk) ===")
    caminho_invalido = os.path.join(
        tempfile.mkdtemp(prefix="teste_tema_"), "subpasta_que_nao_existe", "preferencias_ui.json"
    )
    resultado = preferencias.salvar_tema_escuro(True, caminho_invalido)
    assert resultado is False
    print("  OK")
    print()


if __name__ == "__main__":
    teste_tk_ciclo_completo_de_alternancia_de_tema()
    teste_carregar_tema_escuro_tolera_arquivo_ausente_ou_corrompido()
    teste_salvar_tema_escuro_nunca_lanca_em_falha_de_escrita()
    print("=" * 60)
    print("TESTE DE ALTERNANCIA DE TEMA (SUB-FASE 22E): TUDO OK")
