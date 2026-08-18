"""
web/backend/testes/teste_job_persistencia.py

Fase 26a. Cobre o que a divisão "OCR no Worker / classificação na VPS"
introduziu de novo, e SÓ isso -- nada aqui roda OCR nem lê as planilhas
reais.

O bloco mais importante é o de ORDEM (bloco 4). Ele não é zelo: o
`ContextoLote` é DEPENDENTE DE PREFIXO (`ano_do_lote()` decide contra o
que foi registrado até aquele ponto, com limiares de mínimo, divergência e
predominância), e os índices de `registros` são posicionais -- consumidos
por `POST /registros/{indice}/confirmar` e por `sinais_de_contexto`, que
inclusive olha os VIZINHOS. Uma página aplicada fora de ordem mudaria
classificação de linhas reais em silêncio, sem quebrar teste nenhum dos
que já existiam.

Rodar:
    python web\\backend\\testes\\teste_job_persistencia.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))

from leitor_matriculas.parsing.contexto_lote import ContextoLote  # noqa: E402
from leitor_matriculas.parsing.registro_parser import CampoOcr, Registro  # noqa: E402
from web.backend import armazenamento, estado  # noqa: E402

_RAIZ = tempfile.mkdtemp(prefix="armazenamento_teste_job_")
armazenamento.definir_raiz(_RAIZ)


class _DataManagerFake:
    """Mesma forma mínima que `teste_api_mock.py` usa: as planilhas reais do
    operador nunca podem decidir se um teste passa."""
    colaboradores_disponivel = True
    gestores_disponivel = False
    motivos_disponivel = False
    avisos = []

    def buscar_colaborador(self, matricula):
        return {"nome": "FULANO", "cargo": "OPERADOR", "setor": "EXPEDICAO"} if matricula == "28972" else None

    def listar_motivos(self):
        return []

    def listar_gestores(self):
        return []


estado._data_manager = _DataManagerFake()


def _limpar():
    estado._lotes.clear()
    for lote_id in armazenamento.listar_lotes():
        armazenamento.remover_lote(lote_id)


def _pagina(numero, matricula, data="14/04/26"):
    """Uma página com UM registro, no formato que o Worker entrega."""
    registro = Registro(
        indice=1,
        campos={
            "matricula": CampoOcr(matricula, 0.95, [450, 10, 520, 40]),
            "data": CampoOcr(data, 0.95, [60, 10, 130, 40]),
            "gestor": CampoOcr("GR1", 0.9, [880, 10, 940, 40]),
            "motivo": CampoOcr("RH", 0.9, [700, 10, 760, 40]),
        },
        nao_associados=[CampoOcr("ruido", 0.3, [1, 1, 2, 2])],
        y_min=10, y_max=40,
    )
    return {"numero": numero, "erro": None, "fase_erro": None,
            "registros": [registro.como_dicionario()]}


def _criar_lote(total_paginas):
    lote_id = estado.reservar_lote_id()
    armazenamento.criar_lote(lote_id)
    caminhos = [os.path.join(armazenamento.pasta_entrada(lote_id), f"f{i}.jpg")
                for i in range(1, total_paginas + 1)]
    return estado.criar_lote(tipo=estado.TIPO_IMAGENS, caminhos=caminhos,
                             pasta_temp=armazenamento.pasta_lote(lote_id), lote_id=lote_id)


def _rodar_motora(lote, timeout=10.0):
    thread = threading.Thread(target=estado.processar_lote, args=(lote.id,), daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "a thread-motora não terminou"
    return lote


# ---------------------------------------------------------------------------
def teste_round_trip_registro():
    print("\n=== Bloco 1: Registro/CampoOcr atravessam a rede sem perder nada ===")
    original = Registro(
        indice=7,
        campos={"matricula": CampoOcr("26319", 0.91, [1, 2, 3, 4]),
                "hora": CampoOcr("07:4", None, None)},
        nao_associados=[CampoOcr("tiago", 0.5, [9, 9, 9, 9])],
        y_min=11, y_max=44,
    )
    import json
    volta = Registro.de_dicionario(json.loads(json.dumps(original.como_dicionario())))

    assert volta == original, "o round-trip alterou o registro"
    assert isinstance(volta.campos["matricula"], CampoOcr), \
        "campos precisa voltar como CampoOcr -- montar_registro_exportacao acessa .texto"
    assert volta.completo is True, "a propriedade `completo` parou de funcionar após o round-trip"
    assert volta.campos["hora"].confianca is None and volta.campos["hora"].box is None, \
        "confianca/box None precisam sobreviver (motor que não informa posição)"
    assert Registro.de_dicionario(Registro(indice=1).como_dicionario()).completo is False
    print("  OK: ida e volta preserva campos, nao_associados, y_min/y_max, None e `completo`")


def teste_round_trip_contexto():
    print("\n=== Bloco 2: ContextoLote sobrevive a um reinício ===")
    contexto = ContextoLote()
    for texto in ["14/04/26", "14/04/26", "14/04/26", "13/04/26"]:
        contexto.registrar_data(texto)
    esperado = contexto.ano_do_lote()
    assert esperado == 2026

    import json
    volta = ContextoLote.de_dicionario(json.loads(json.dumps(contexto.como_dicionario())))
    assert volta.ano_do_lote() == esperado
    assert volta.total_datas_confiaveis == contexto.total_datas_confiaveis
    # É isto que justifica persistir: a confirmação manual reclassifica
    # usando o contexto, muitas vezes horas depois do lote concluir.
    assert volta.completar_ano("23.04") == contexto.completar_ano("23.04")
    assert ContextoLote.de_dicionario(None).ano_do_lote() is None
    assert ContextoLote.de_dicionario({"anos": {"lixo": "x"}}).total_datas_confiaveis == 0, \
        "entrada corrompida deve enfraquecer o contexto, nunca eleger um ano errado"
    print("  OK: ano do lote, contagem e `completar_ano` idênticos; entrada corrompida ignorada")


def teste_nome_de_arquivo_seguro():
    print("\n=== Bloco 3: nome de arquivo enviado pelo cliente ===")
    casos = {
        "../../../etc/passwd": "passwd",
        r"..\..\windows\system32\x.jpg": "x.jpg",
        "folha.jpg": "folha.jpg",
        "pas:ta/no|me?.png": "no_me_.png",
        "..": None,       # vira o nome sintético
        "": None,
        "   ": None,
    }
    for entrada, esperado in casos.items():
        obtido = armazenamento.nome_seguro(entrada, indice=3)
        assert "/" not in obtido and "\\" not in obtido, f"{entrada!r} -> {obtido!r} ainda tem separador"
        assert obtido not in ("", ".", ".."), f"{entrada!r} -> {obtido!r}"
        if esperado is not None:
            assert obtido == esperado, f"{entrada!r} -> {obtido!r}, esperado {esperado!r}"

    assert armazenamento.nome_seguro("CON.jpg").lower().startswith("_con"), \
        "nome reservado do Windows precisa ser desviado"
    assert len(armazenamento.nome_seguro("a" * 500 + ".jpg")) < 200

    # O caminho montado nunca pode sair da pasta do lote.
    lote_id = estado.reservar_lote_id()
    pasta = armazenamento.criar_lote(lote_id)
    destino = os.path.abspath(os.path.join(pasta, armazenamento.nome_seguro("../../fora.jpg")))
    assert destino.startswith(os.path.abspath(pasta)), "path traversal escapou da pasta do lote"

    for invalido in ["../outro", "nao-hex!", "", "a" * 100]:
        try:
            armazenamento.pasta_lote(invalido)
        except ValueError:
            continue
        raise AssertionError(f"lote_id inválido aceito: {invalido!r}")
    print("  OK: traversal, separadores, nome reservado, nome vazio e lote_id inválido barrados")


def teste_ordem_de_aplicacao_independe_da_ordem_de_chegada():
    print("\n=== Bloco 4: página fora de ordem NÃO é aplicada fora de ordem ===")
    _limpar()

    # (a) chegada na ordem natural
    lote_a = _criar_lote(3)
    for numero in (1, 2, 3):
        estado.depositar_resultado_pagina(lote_a, numero, _pagina(numero, f"2897{numero}"))
    _rodar_motora(lote_a)
    ordem_a = [r["pagina_origem"] for r in lote_a.registros]
    matriculas_a = [r["matricula"] for r in lote_a.registros]

    # (b) chegada embaralhada -- o Worker pode entregar fora de ordem após
    #     uma retomada, e um segundo Worker entregaria em paralelo
    _limpar()
    lote_b = _criar_lote(3)
    thread = threading.Thread(target=estado.processar_lote, args=(lote_b.id,), daemon=True)
    thread.start()
    for numero in (3, 1, 2):
        estado.depositar_resultado_pagina(lote_b, numero, _pagina(numero, f"2897{numero}"))
        time.sleep(0.05)
    thread.join(timeout=10)
    assert not thread.is_alive()

    ordem_b = [r["pagina_origem"] for r in lote_b.registros]
    assert ordem_a == ordem_b == [1, 2, 3], f"ordem física quebrou: {ordem_a} vs {ordem_b}"
    assert matriculas_a == [r["matricula"] for r in lote_b.registros], \
        "a mesma folha caiu em posição diferente conforme a ordem de chegada"
    assert lote_b.status == estado.STATUS_CONCLUIDO
    print(f"  OK: chegou 3,1,2 e foi aplicado {ordem_b} -- ordem física e índices preservados")


def teste_reenvio_nao_duplica():
    print("\n=== Bloco 5: reenvio da mesma página é no-op (e não conta o ano duas vezes) ===")
    _limpar()
    lote = _criar_lote(2)

    assert estado.depositar_resultado_pagina(lote, 1, _pagina(1, "28972")) == "aceito"
    assert estado.depositar_resultado_pagina(lote, 1, _pagina(1, "28972")) == "duplicado", \
        "reenvio após queda de conexão precisa ser recusado como duplicado"
    assert estado.depositar_resultado_pagina(lote, 2, _pagina(2, "28973")) == "aceito"
    _rodar_motora(lote)

    assert len(lote.registros) == 2, f"o reenvio duplicou registros: {len(lote.registros)}"
    assert lote.contexto_lote.total_datas_confiaveis == 2, \
        f"a data do reenvio foi contada duas vezes no contexto: {lote.contexto_lote.total_datas_confiaveis}"
    print("  OK: 2 páginas, 2 registros, 2 datas no contexto -- nada contado em dobro")


def teste_ficha_de_cerca_rejeita_worker_obsoleto():
    print("\n=== Bloco 6: Worker de uma tentativa antiga é rejeitado ===")
    _limpar()
    lote = _criar_lote(2)
    tentativa_original = lote.tentativa

    estado.reenfileirar(lote, "lease expirado")
    assert lote.tentativa == tentativa_original + 1

    # O Worker antigo continua VIVO e postando -- este é o caso real, não
    # hipotético: o lease expira por lentidão, não por morte.
    assert estado.depositar_resultado_pagina(
        lote, 1, _pagina(1, "28972"), tentativa=tentativa_original) == "obsoleto"
    assert 1 not in lote.paginas_recebidas, "página de tentativa obsoleta entrou mesmo assim"

    assert estado.depositar_resultado_pagina(
        lote, 1, _pagina(1, "28972"), tentativa=lote.tentativa) == "aceito"
    print("  OK: página da tentativa anterior recusada; a da tentativa vigente aceita")


def teste_lote_sobrevive_a_reinicio():
    print("\n=== Bloco 7: o lote sobrevive ao processo morrer ===")
    _limpar()
    # 3 páginas de propósito: `MINIMO_DATAS_CONFIAVEIS = 3`, então é a
    # partir daqui que o contexto ELEGE um ano de verdade. Com menos, a
    # comparação abaixo seria None == None e não provaria nada.
    lote = _criar_lote(3)
    for numero in (1, 2, 3):
        estado.depositar_resultado_pagina(lote, numero, _pagina(numero, "28972"))
    _rodar_motora(lote)
    lote_id = lote.id
    registros_antes = [dict(r) for r in lote.registros]
    ano_antes = lote.contexto_lote.ano_do_lote()
    assert ano_antes == 2026, f"o contexto precisa ter elegido um ano para o teste valer: {ano_antes}"

    # Simula o reinício: a memória do processo vai embora, o disco fica.
    estado._lotes.clear()

    recuperado = estado.obter_lote(lote_id)
    assert recuperado is not None, "o lote não foi recuperado do disco"
    assert recuperado.status == estado.STATUS_CONCLUIDO
    assert [r["matricula"] for r in recuperado.registros] == [r["matricula"] for r in registros_antes]
    assert [r["pagina_origem"] for r in recuperado.registros] == [r["pagina_origem"] for r in registros_antes]
    assert recuperado.contexto_lote.ano_do_lote() == ano_antes, \
        "sem o contexto, a confirmação manual pós-reinício decidiria diferente"
    print(f"  OK: {len(recuperado.registros)} registros, ordem e contexto (ano {ano_antes}) recuperados")


def teste_retomada_reaproveita_o_ocr_ja_feito():
    print("\n=== Bloco 8: retomada não refaz o OCR já gravado ===")
    _limpar()
    lote = _criar_lote(3)
    estado.depositar_resultado_pagina(lote, 1, _pagina(1, "28972"))
    estado.depositar_resultado_pagina(lote, 2, _pagina(2, "28973"))

    assert armazenamento.paginas_persistidas(lote.id) == {1, 2}
    assert estado.paginas_pendentes(lote) == [], "sem total_paginas ainda não há o que pedir"

    estado.registrar_total_paginas(lote, 3)
    assert estado.paginas_pendentes(lote) == [3], \
        "a retomada pediria páginas que já custaram ~40 s de OCR cada"

    # E a motora aproveita o que está em disco mesmo com o buffer vazio
    # (o caso pós-reinício: o buffer em memória não existe mais).
    lote.resultados_pagina.clear()
    lote.paginas_recebidas.clear()
    estado.depositar_resultado_pagina(lote, 3, _pagina(3, "28974"))
    _rodar_motora(lote)
    assert [r["pagina_origem"] for r in lote.registros] == [1, 2, 3]
    print("  OK: só a página 3 seria pedida de novo; 1 e 2 vieram do disco")


def teste_varredura_de_inicializacao():
    print("\n=== Bloco 9: varredura de inicialização (recuperação + retenção) ===")
    _limpar()

    # Um lote que ficou preso em "processando" (o processo morreu no meio).
    preso = _criar_lote(2)
    with preso.lock:
        preso.status = estado.STATUS_PROCESSANDO
        preso.fase_worker = estado.FASE_ATRIBUIDO
    estado.persistir(preso)
    id_preso = preso.id

    # Um lote velho o bastante para a retenção levar.
    velho = _criar_lote(1)
    with velho.lock:
        velho.criado_em = time.time() - (armazenamento.DIAS_RETENCAO_PADRAO + 5) * 86400
    estado.persistir(velho)
    id_velho = velho.id

    estado._lotes.clear()
    resumo = estado.recuperar_lotes_do_disco()

    assert id_velho not in armazenamento.listar_lotes(), "a retenção não removeu o lote antigo"
    assert resumo["removidos"] >= 1
    recuperado = estado.obter_lote(id_preso)
    assert recuperado is not None
    assert recuperado.fase_worker == estado.FASE_AGUARDANDO_WORKER, \
        "um lote preso em 'processando' ficaria travado para sempre, como antes da Fase 26"
    assert recuperado.tentativa >= 1, "reenfileirar precisa invalidar o Worker anterior"
    print(f"  OK: lote preso voltou para a fila (tentativa {recuperado.tentativa}); lote antigo removido")


def teste_erro_de_pagina_mantem_a_mensagem_da_vps():
    print("\n=== Bloco 10: a frase de erro continua sendo montada na VPS ===")
    _limpar()
    lote = _criar_lote(2)
    # O Worker devolve o erro CRU; quem conhece o nome do arquivo que o
    # usuário enviou é a VPS.
    estado.depositar_resultado_pagina(lote, 1, {
        "numero": 1, "erro": "Não foi possível abrir a imagem", "fase_erro": "leitura", "registros": []})
    estado.depositar_resultado_pagina(lote, 2, _pagina(2, "28972"))
    _rodar_motora(lote)

    linha_erro = lote.registros[0]
    assert linha_erro["status"] == "ERRO"
    assert linha_erro["observacao"].startswith("Falha ao abrir 'f1.jpg':"), linha_erro["observacao"]
    assert len(lote.erros_paginas) == 1
    assert len(lote.avisos_contagem) == 1, \
        "a página que falhou não pode gerar aviso de contagem; a que deu certo, sim"
    assert lote.avisos_contagem[0]["pagina"] == 2
    print(f"  OK: {linha_erro['observacao'][:60]}...")


def teste_persistencia_concorrente():
    print("\n=== Bloco 11: dois escritores simultâneos do mesmo lote ===")
    _limpar()
    lote = _criar_lote(1)
    falhas = []

    def _martelar():
        try:
            for _ in range(40):
                estado.persistir(lote, com_registros=True)
        except Exception as exc:  # pragma: no cover
            falhas.append(exc)

    # Achado real desta sub-fase, não hipotético: com um nome de arquivo
    # temporário FIXO, a thread-motora e uma requisição HTTP salvando o
    # mesmo lote no mesmo instante disputavam o mesmo `.tmp` e o
    # `os.replace` estourava `PermissionError [WinError 32]` no Windows.
    threads = [threading.Thread(target=_martelar) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not falhas, f"escrita concorrente falhou: {falhas[:1]}"
    dados = armazenamento.ler_estado(lote.id)
    assert dados is not None and dados["id"] == lote.id, "o estado ficou ilegível após a disputa"
    sobras = [n for n in os.listdir(armazenamento.pasta_lote(lote.id)) if n.endswith(".tmp")]
    assert not sobras, f"sobraram arquivos temporários: {sobras}"
    print("  OK: 160 gravações concorrentes, estado íntegro, nenhum .tmp órfão")


def main():
    try:
        teste_round_trip_registro()
        teste_round_trip_contexto()
        teste_nome_de_arquivo_seguro()
        teste_ordem_de_aplicacao_independe_da_ordem_de_chegada()
        teste_reenvio_nao_duplica()
        teste_ficha_de_cerca_rejeita_worker_obsoleto()
        teste_lote_sobrevive_a_reinicio()
        teste_retomada_reaproveita_o_ocr_ja_feito()
        teste_varredura_de_inicializacao()
        teste_erro_de_pagina_mantem_a_mensagem_da_vps()
        teste_persistencia_concorrente()
        print("\n" + "=" * 70)
        print("JOB / PERSISTÊNCIA / ORDEM (FASE 26a): TUDO OK")
    finally:
        shutil.rmtree(_RAIZ, ignore_errors=True)


if __name__ == "__main__":
    main()
