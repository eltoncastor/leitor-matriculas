"""
validacao/confirmacao.py

Fase 24a (Web MVP): extraído de `ui/app.py::_revisao_confirmar`, que era
até aqui o ÚNICO lugar do sistema onde um registro saía de REVISAO para
CONFIRMADO por decisão humana. `confirmar_revisao_manual` é agora ESSE
único lugar — tanto o Tkinter (`_revisao_confirmar`, que passou a ser só
widget: ler os campos, chamar esta função, atualizar contador/tabela/
navegação) quanto o backend web (`web/backend/rotas/lotes.py`) chamam a
MESMA função. Nunca duplicar esta decisão em dois lugares — é exatamente o
que o preâmbulo da Fase 24 pede para evitar.

O que esta função faz é idêntico, campo a campo, ao que `_revisao_confirmar`
fazia antes da extração (ver `git log` da Fase 24a para o diff exato):
reconstrói um `Registro` sintético a partir dos valores já editados/
digitados (confiança 1.0 — foram verificados por uma pessoa, deixaram de
ser hipótese de OCR; não é um valor inventado), preserva o
`ocr_nao_associados` original do registro (Fase 12 — sem isso a revisão
manual vira porta dos fundos para o campo perdido que aquela fase passou a
bloquear), roda a MESMA `classificar_registro` do fluxo automático, e só
então decide: o registro só sai de REVISAO se o resultado for genuinamente
CONFIRMADO.

Não é widget nenhum — não importa `tkinter` nem sabe que existe uma
janela. Recebe strings e um dict (o registro de exportação, no mesmo
formato de `pipeline.montar_registro_exportacao`), devolve o que o
chamador precisa para atualizar O SEU PRÓPRIO estado (contador de widgets,
resposta JSON, o que for) — a decisão em si já foi tomada dentro desta
função.
"""
from dataclasses import dataclass

from leitor_matriculas.ocr.engine import normalizar_matricula
from leitor_matriculas.parsing.registro_parser import CampoOcr, Registro
from leitor_matriculas.validacao.regras import classificar_registro
from leitor_matriculas.validacao.recuperacao_matricula import resolver_matricula
from leitor_matriculas.dados import registro_correcoes

# Placeholder explícito para Nome/Cargo/Setor quando a matrícula não pôde
# ser associada a um colaborador da base — nunca deixamos a célula "vazia
# aparentemente válida" (requisito funcional definitivo, ver CLAUDE.md).
# Definido AQUI (fonte única) porque agora tanto `ui/app.py` quanto o
# backend web precisam mostrar exatamente o mesmo texto; antes da Fase 24a
# só existia dentro de `ui/app.py`.
NAO_ENCONTRADO = "(não encontrado)"


@dataclass
class ResultadoConfirmacaoManual:
    """
    O que o chamador precisa para atualizar o PRÓPRIO estado — a decisão
    já foi tomada. `registro` é o MESMO dict recebido, já atualizado
    in-place (mesma convenção que `_revisao_confirmar` sempre usou).
    """
    registro: dict
    status_anterior: str
    confirmou_agora: bool  # True só quando o registro estava != CONFIRMADO e passou a estar
    # A observação CRUA que `classificar_registro` devolveu, sem o prefixo
    # "corrigido manualmente"/"revisão manual incompleta --" que já foi
    # aplicado dentro de `registro["observacao"]`. Existe só para quem
    # chama poder compor a PRÓPRIA mensagem (ex.: o Tkinter mostra "Ainda
    # não é possível confirmar: {isto}" no formulário de revisão) sem
    # precisar desmontar o prefixo do texto já formatado.
    observacao_classificacao: str


def confirmar_revisao_manual(
    registro: dict,
    *,
    data: str = "",
    hora: str = "",
    matricula: str = "",
    gestor: str = "",
    motivo: str = "",
    data_manager,
    contexto_lote=None,
) -> ResultadoConfirmacaoManual:
    """
    Aplica uma correção manual a `registro` (dict de exportação, mutado
    in-place) e reavalia com a MESMA validação do fluxo automático.

    `data`/`hora`/`matricula`/`gestor`/`motivo`: os valores editados pelo
    operador (texto cru — esta função faz o mesmo tratamento que o fluxo
    automático faz para o texto do OCR: normaliza a matrícula, tenta
    recuperação contextual, etc.). Uma string vazia significa "o operador
    não preencheu esse campo" — não confundir com "o operador quer
    apagar", que este fluxo não oferece.

    `data_manager`: a mesma instância (`DataManager`) usada para classificar
    o lote inteiro — a consulta de colaborador/gestor/motivo precisa ver a
    MESMA base.

    `contexto_lote`: o `ContextoLote` do lote a que este registro pertence
    (opcional — sem ele, uma data sem ano digitada na revisão continua sem
    poder ser completada por contexto, exatamente como no fluxo automático).
    """
    data_digitada = (data or "").strip()
    hora_digitada = (hora or "").strip()
    matricula_digitada = (matricula or "").strip()
    gestor_digitado = (gestor or "").strip()
    motivo_digitado = (motivo or "").strip()

    # Mesmo tratamento do fluxo automático: a matrícula final só pode
    # conter dígitos, mesmo vinda de digitação manual.
    matricula_normalizada = normalizar_matricula(matricula_digitada) if matricula_digitada else ""
    resultado_matricula = resolver_matricula(
        matricula_normalizada,
        existe_na_base=(
            (lambda m: data_manager.buscar_colaborador(m) is not None)
            if data_manager.colaboradores_disponivel else None
        ),
    )
    matricula_normalizada = resultado_matricula.matricula or ""

    campos_sinteticos = {}
    if data_digitada:
        campos_sinteticos["data"] = CampoOcr(texto=data_digitada, confianca=1.0, box=None)
    if hora_digitada:
        campos_sinteticos["hora"] = CampoOcr(texto=hora_digitada, confianca=1.0, box=None)
    if matricula_normalizada:
        campos_sinteticos["matricula"] = CampoOcr(texto=matricula_normalizada, confianca=1.0, box=None)
    if gestor_digitado:
        campos_sinteticos["gestor"] = CampoOcr(texto=gestor_digitado, confianca=1.0, box=None)
    if motivo_digitado:
        campos_sinteticos["motivo"] = CampoOcr(texto=motivo_digitado, confianca=1.0, box=None)

    # A evidência de campo perdido detectada no processamento automático
    # (ver validacao/integridade.py) precisa SOBREVIVER à revisão manual.
    # Sem isto, o registro sintético nasceria sem `nao_associados`, a
    # checagem de integridade não teria o que ver, e bastaria confirmar
    # manualmente para reverter o bloqueio da Fase 12 — uma porta dos
    # fundos para o problema que ela existe para fechar. Isto NÃO prende
    # o operador: a checagem só dispara quando o campo continua VAZIO.
    sobras = [
        CampoOcr(texto=texto, confianca=None, box=None)
        for texto in (registro.get("ocr_nao_associados") or [])
    ]
    registro_sintetico = Registro(indice=0, campos=campos_sinteticos, nao_associados=sobras)

    # Re-consulta a base pela matrícula corrigida -- Nome/Setor/Cargo têm
    # que refletir a matrícula certa, nunca ficar mostrando NAO_ENCONTRADO
    # para um registro que acabou de ser confirmado com matrícula válida.
    colaborador = (
        data_manager.buscar_colaborador(matricula_normalizada) if matricula_normalizada else None
    )

    resultado = classificar_registro(
        registro_sintetico, colaborador, data_manager,
        resultado_matricula=resultado_matricula,
        contexto_lote=contexto_lote,
    )

    # Fase 20 (H5): fotografia do estado ANTERIOR, tirada aqui porque as
    # linhas abaixo sobrescrevem o dict no lugar. Sem esta cópia, o valor
    # que estava em cada campo antes da correção -- e o dossiê com o texto
    # que o OCR havia lido em cada um dos 5 campos -- deixa de existir no
    # instante seguinte.
    estado_anterior = dict(registro)

    registro["matricula"] = matricula_normalizada
    registro["nome"] = colaborador["nome"] if colaborador else NAO_ENCONTRADO
    registro["cargo"] = colaborador["cargo"] if colaborador else NAO_ENCONTRADO
    registro["setor"] = colaborador["setor"] if colaborador else NAO_ENCONTRADO
    registro["data"] = resultado.data_confirmada or ""
    registro["hora"] = resultado.hora_confirmada or ""
    registro["gestor"] = resultado.gestor_confirmado or gestor_digitado
    registro["motivo"] = resultado.motivo_confirmado or motivo_digitado
    # O dossiê acompanha a REavaliação: depois de uma correção manual, a
    # evidência que vale é a da decisão que acabou de ser tomada, não a da
    # leitura original do OCR (que continua registrada dentro do próprio
    # dossiê, como `ocr_bruto`).
    registro["evidencias"] = resultado.dossie.como_dicionarios()
    if matricula_normalizada:
        registro["confianca_matricula"] = 1.0
    if gestor_digitado:
        registro["confianca_gestor"] = 1.0
    if motivo_digitado:
        registro["confianca_motivo"] = 1.0

    status_anterior = registro["status"]
    registro["status"] = resultado.status
    if resultado.status == "CONFIRMADO":
        registro["observacao"] = (
            "corrigido manualmente" if not resultado.observacao
            else f"corrigido manualmente; {resultado.observacao}"
        )
    else:
        registro["observacao"] = f"revisão manual incompleta -- {resultado.observacao}"

    confirmou_agora = resultado.status == "CONFIRMADO" and status_anterior != "CONFIRMADO"

    # Fase 20 (H5): grava a correção no histórico -- DEPOIS que a decisão
    # já foi tomada, e sem participar dela. `registrar_correcao` já engole
    # as próprias falhas (disco cheio, arquivo aberto no Excel) e devolve
    # False, pelo mesmo critério da miniatura da foto na Fase 10 -- perder
    # uma linha de histórico não pode custar o lote que ainda não foi
    # exportado. Registra também a correção que NÃO resolveu.
    registro_correcoes.registrar_correcao(
        antes=estado_anterior,
        depois=registro,
        evidencias_antes=estado_anterior.get("evidencias"),
    )

    return ResultadoConfirmacaoManual(
        registro=registro,
        status_anterior=status_anterior,
        confirmou_agora=confirmou_agora,
        observacao_classificacao=resultado.observacao,
    )
