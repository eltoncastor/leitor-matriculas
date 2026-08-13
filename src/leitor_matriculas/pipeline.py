"""
pipeline.py

Fase 24a (Web MVP): "rodar o pipeline sobre uma folha" — pré-processamento
(`ocr/image_processor.py`) -> OCR (`ocr/engine.py`) -> parser espacial
(`parsing/registro_parser.py`) -> reparo de DATA+HORA mescladas
(`parsing/tempo_parser.py`) -> classificação (`validacao/regras.py`) —
extraído de dentro de `ui/app.py` (`App._processar_uma_pagina` e
`App._adicionar_registros`) para um módulo neutro que TANTO o Tkinter
QUANTO o backend web chamam. Antes da Fase 24a esta lógica só existia como
métodos de `App`, amarrada a `self._ocr_engine`/`self._informar_etapa`/
`self._data_manager` — inutilizável por um processo sem Tkinter (o
backend FastAPI não pode instanciar `App`, que abre uma janela).

O que este módulo NÃO faz, de propósito: não decide fila, não decide
thread, não guarda nenhum estado de sessão (lote, contador, tabela). Isso
continua sendo mecanismo de cada interface -- o worker+queue.Queue do
Tkinter de um lado, o processamento em background do FastAPI do outro --
e por isso não mora aqui. O que mora aqui é só o que as duas interfaces
precisam fazer de forma IDÊNTICA: ler uma folha e classificar cada linha
dela.

Nada neste módulo levanta exceção para quem chama: cada etapa isola sua
própria falha (mesmo padrão que `_processar_uma_pagina` já seguia antes da
extração) -- é o que permite tanto ao worker do Tkinter quanto ao backend
web isolar UMA folha ruim sem abortar o lote inteiro.
"""
import logging

from leitor_matriculas.ocr.image_processor import preprocess_image
from leitor_matriculas.ocr.engine import normalizar_matricula
from leitor_matriculas.parsing.registro_parser import CampoOcr, parse_registros
from leitor_matriculas.parsing.tempo_parser import tentar_separar_data_hora_mesclada
from leitor_matriculas.validacao.regras import classificar_registro
from leitor_matriculas.validacao.recuperacao_matricula import resolver_matricula
from leitor_matriculas.validacao.confirmacao import NAO_ENCONTRADO


def _texto_campo(registro, nome_campo: str) -> str:
    campo = registro.campos.get(nome_campo)
    return campo.texto if campo else ""


def reparar_data_hora_mescladas(registros):
    """
    PROBLEMA 5 (Fase 1 de precisão da extração): corrige o caso real em que
    o próprio detector de texto do OCR colou DATA e HORA em uma única caixa
    (ex.: "14.04 26 20:24" -- visto em teste.jpg). Só age quando exatamente
    um dos dois campos está ausente; `tentar_separar_data_hora_mesclada`
    (tempo_parser.py) só aceita a separação se ambos os pedaços validarem
    de verdade -- nunca inventa. Sem separação segura, o registro segue
    sem alteração (campo ausente -> REVISAO, como já era o caso).
    """
    for registro in registros:
        tem_data = "data" in registro.campos
        tem_hora = "hora" in registro.campos
        if tem_data == tem_hora:
            continue  # ambos presentes ou ambos ausentes: nada a reparar aqui

        campo_fonte = registro.campos["data"] if tem_data else registro.campos["hora"]
        resultado = tentar_separar_data_hora_mesclada(campo_fonte.texto)
        if resultado is None:
            continue

        texto_data, texto_hora = resultado
        registro.campos["data"] = CampoOcr(texto=texto_data, confianca=campo_fonte.confianca, box=campo_fonte.box)
        # `texto_hora` vem None quando a caixa mesclada tinha uma hora
        # impossível ("14.04 -26 90:24"): a DATA legível é aproveitada e a
        # HORA (opcional) continua ausente -- o texto impossível nunca vai
        # para o campo, só para o registro de auditoria logo abaixo.
        if texto_hora is None:
            registro.campos.pop("hora", None)
        else:
            registro.campos["hora"] = CampoOcr(texto=texto_hora, confianca=campo_fonte.confianca, box=campo_fonte.box)
        # Preserva o texto mesclado original para auditoria (nunca some).
        registro.nao_associados.append(
            CampoOcr(texto=f"[data/hora mescladas no OCR: {campo_fonte.texto!r}]", confianca=campo_fonte.confianca, box=campo_fonte.box)
        )


def processar_uma_pagina(imagem_bgr, ocr_engine, informar_etapa=None):
    """
    Devolve (imagem_processada, registros, erro). Nunca levanta exceção:
    cada etapa é isolada, e uma falha em qualquer uma delas volta como
    `erro` (texto) em vez de propagar -- é assim que o Tkinter e a web
    conseguem marcar SÓ aquela folha como ERRO e continuar o lote.

    `ocr_engine` já precisa estar pronto (a criação/cache do engine é
    responsabilidade de quem chama -- o Tkinter guarda `self._ocr_engine`,
    o backend web guarda o seu próprio; os dois evitam recriar o modelo a
    cada folha pelo mesmo motivo, mas cada um decide como).

    `informar_etapa`, se fornecido, é chamado com uma frase em português
    descrevendo o passo atual (ex.: "Lendo o texto escrito à mão"). É
    puramente informativo -- nunca decide nada -- e cada chamador entrega o
    canal que fizer sentido para a própria interface (fila+`self.after` no
    desktop, campo de progresso consultável por `lote_id` no backend web).
    """
    def _informar(texto):
        if informar_etapa is None:
            return
        try:
            informar_etapa(texto)
        except Exception:
            logging.exception("Falha ao informar a etapa atual (apenas informativo)")

    _informar("Preparando a imagem da folha")
    try:
        imagem_processada = preprocess_image(imagem_bgr)
    except Exception as exc:
        return None, [], f"Erro no pré-processamento: {exc}"

    _informar("Lendo o texto escrito à mão (esta é a parte demorada)")
    try:
        resultados_ocr = ocr_engine.recognize(imagem_processada)
    except Exception as exc:
        return imagem_processada, [], f"Erro no OCR: {exc}"

    _informar("Organizando as linhas e colunas da folha")
    try:
        registros = parse_registros(resultados_ocr).registros
        reparar_data_hora_mescladas(registros)
    except Exception as exc:
        return imagem_processada, [], f"Erro no parser espacial: {exc}"

    _informar("Conferindo os dados contra as bases")
    return imagem_processada, registros, None


def montar_registro_exportacao(registro, numero_pagina, data_manager, contexto_lote=None):
    """
    Classifica um `Registro` (já extraído de uma folha por
    `processar_uma_pagina`) e monta o dict pronto para `xlsx_exporter`/a
    API web/a tabela ao vivo do Tkinter -- a MESMA forma que as duas
    interfaces consomem. Não decide UI nenhuma (contador, tabela, fila);
    só classifica e formata.

    Devolve (registro_exportacao, aviso_sem_matricula). `aviso_sem_
    matricula` é uma frase pronta em português quando a linha não teve
    matrícula identificável (o registro NÃO é descartado -- vai para
    REVISAO com o que tem --, mas quem chama precisa saber que a linha
    existe e por quê: é o mesmo aviso que alimentava `App._avisos_
    descarte`); `None` quando a matrícula foi identificada normalmente.
    """
    campo_matricula = registro.campos.get("matricula")
    texto_matricula = campo_matricula.texto if campo_matricula else ""
    # Primeiro as confusões já conhecidas (O->0, I->1, S->5, B->8, só
    # quando o texto já parece matrícula), depois a recuperação contextual
    # dos caracteres que sobraram (ex.: "+" -> 7), que usa a base de
    # colaboradores como evidência.
    matricula_normalizada = normalizar_matricula(texto_matricula) if texto_matricula else ""
    resultado_matricula = resolver_matricula(
        matricula_normalizada,
        existe_na_base=(
            (lambda m: data_manager.buscar_colaborador(m) is not None)
            if data_manager.colaboradores_disponivel else None
        ),
    )
    # A matrícula exibida/exportada é SEMPRE só dígitos (requisito
    # funcional): quando a recuperação não conseguiu chegar a uma leitura
    # só-dígitos, a célula sai VAZIA em vez de levar o texto cru do OCR
    # ("1954+", "195.4"). Nada se perde -- o texto original continua na
    # coluna técnica de OCR, na Observação e no aviso de retorno.
    matricula_normalizada = resultado_matricula.matricula or ""

    colaborador = None
    if registro.completo and resultado_matricula.status != "AMBIGUA":
        colaborador = data_manager.buscar_colaborador(matricula_normalizada)

    resultado_classificacao = classificar_registro(
        registro, colaborador, data_manager,
        resultado_matricula=resultado_matricula,
        contexto_lote=contexto_lote,
    )
    status, observacao = resultado_classificacao.status, resultado_classificacao.observacao

    nome = colaborador["nome"] if colaborador else NAO_ENCONTRADO
    cargo = colaborador["cargo"] if colaborador else NAO_ENCONTRADO
    setor = colaborador["setor"] if colaborador else NAO_ENCONTRADO
    # DATA sai sempre no formato canônico dd/mm/aa; quando não pôde ser
    # interpretada com segurança, a célula sai VAZIA (o registro já está
    # em REVISAO). Mesma regra da Hora, e pelo mesmo motivo: escrever
    # "23.04" ou "14.0.4.26" misturaria formatos e seria indistinguível de
    # uma data de verdade. O texto cru não se perde -- fica na Observação.
    data_ = resultado_classificacao.data_confirmada or ""
    # HORA é campo OPCIONAL: só vai para a tabela/planilha quando pôde ser
    # interpretada com segurança. Ausente ou ilegível, sai VAZIA -- nunca
    # com o texto ilegível do OCR, que seria indistinguível de uma hora
    # real. O texto bruto fica registrado na Observação.
    hora = resultado_classificacao.hora_confirmada or ""
    # PROBLEMAS 3/4: quando a correspondência aproximada aceitou uma
    # correção, usa o valor normalizado; o texto bruto do OCR continua
    # disponível na Observação quando isso acontece, e como fallback aqui
    # quando não houve correção nenhuma.
    gestor = resultado_classificacao.gestor_confirmado or _texto_campo(registro, "gestor")
    motivo = resultado_classificacao.motivo_confirmado or _texto_campo(registro, "motivo")
    campo_gestor = registro.campos.get("gestor")
    campo_motivo = registro.campos.get("motivo")

    conf_matricula = campo_matricula.confianca if campo_matricula else None

    aviso_sem_matricula = None
    if not resultado_matricula.matricula:
        aviso_sem_matricula = (
            "linha sem matrícula identificável"
            + (f" (OCR leu: '{texto_matricula}')" if texto_matricula else " (coluna vazia)")
            + " -- mantida em REVISÃO, nenhuma matrícula foi inventada"
        )

    registro_exportacao = {
        "data": data_, "hora": hora,
        "matricula": matricula_normalizada,
        "nome": nome, "cargo": cargo, "setor": setor,
        "gestor": gestor, "motivo": motivo,
        "pagina_origem": numero_pagina, "status": status,
        "confianca_matricula": conf_matricula,
        "confianca_gestor": campo_gestor.confianca if campo_gestor else "",
        "confianca_motivo": campo_motivo.confianca if campo_motivo else "",
        "observacao": observacao,
        "texto_ocr_original": texto_matricula,
        # Texto que o OCR leu nesta linha e o parser não conseguiu associar
        # a coluna nenhuma. Guardado para a revisão manual poder rodar a
        # MESMA checagem de integridade do fluxo automático (ver
        # `validacao/confirmacao.py`). Chave técnica: o xlsx_exporter só lê
        # as colunas que conhece e ignora esta.
        "ocr_nao_associados": [
            c.texto for c in (registro.nao_associados or []) if (c.texto or "").strip()
        ],
        # Fase 17 (motor de evidências): o dossiê do registro, em dados
        # puros. Mesma natureza de chave técnica que `ocr_nao_associados`
        # acima -- fica fora das COLUNAS do xlsx_exporter, não aparece na
        # planilha; é o que a Fase 18/o backend web usam para explicar a
        # revisão.
        "evidencias": resultado_classificacao.dossie.como_dicionarios(),
    }
    return registro_exportacao, aviso_sem_matricula


def registro_erro_pagina(numero_pagina, mensagem):
    """Linha ERRO (página inteira que falhou) -- mesmo formato de dict que
    `montar_registro_exportacao` devolve, para que a tabela/planilha/API
    não precisem distinguir os dois casos por formato."""
    return {
        "data": "", "hora": "", "matricula": "", "nome": "", "cargo": "", "setor": "",
        "gestor": "", "motivo": "",
        "pagina_origem": numero_pagina, "status": "ERRO",
        "confianca_matricula": "", "confianca_gestor": "", "confianca_motivo": "",
        "observacao": mensagem, "texto_ocr_original": "",
    }
