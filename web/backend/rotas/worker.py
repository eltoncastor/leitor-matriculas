"""
web/backend/rotas/worker.py

Fase 26b. Endpoints que um Worker (o processo que roda o OCR de verdade)
usa para conversar com a VPS. Nenhuma decisão de negócio mora aqui -- é
só o protocolo de "quem está com qual Job e o que ele já entregou",
implementado em cima do que `web/backend/estado.py` já expõe.

DIREÇÃO DA CONEXÃO: sempre Worker -> VPS. O Worker está atrás de NAT, sem
IP público e sem porta aberta -- ele faz polling (`GET /jobs/next`) e
entrega resultado por POST, nunca é ele quem recebe uma conexão.

MONTAGEM (ver `web/backend/main.py`): este router é incluído **só** sob
`/api/worker`, e explicitamente **nunca** sob `/leitor/api/worker` -- o
Cloudflare Tunnel da VPS só roteia `/leitor/*`, então essa decisão de
montagem já torna a superfície de Worker inalcançável da internet
pública, por construção (ver D9 no relatório desta fase). O acesso real é
pela Tailscale; o token (`auth_worker.py`) é a segunda camada, nunca a
única.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .. import auth_worker, config, estado
from ..esquemas import (
    ConcluirRequest, ErroDeDocumentoRequest, HeartbeatRequest, HeartbeatResposta,
    JobReivindicado, ProgressoRequest, ProximoJobResposta, ResultadoPaginaRequest,
    ResultadoPaginaResposta, StatusWorkerResposta,
)

router = APIRouter(prefix="/worker", tags=["worker"])


def _lote_ou_404(lote_id: str) -> estado.LoteState:
    lote = estado.obter_lote(lote_id)
    if lote is None:
        raise HTTPException(status_code=404, detail=f"Lote '{lote_id}' não encontrado")
    return lote


def _exigir_posse(lote: estado.LoteState, worker_id: str, tentativa: int) -> None:
    """
    Confere a ficha de cerca E o `worker_id` juntos (`estado.
    tentativa_valida`) -- não só a tentativa. É o que a missão pediu com
    "nunca confiar cegamente no worker_id": ele participa de verdade da
    decisão de posse, não é só um rótulo de log.
    """
    if not estado.tentativa_valida(lote, worker_id, tentativa):
        raise HTTPException(
            status_code=409,
            detail=f"Este Worker não é mais o dono do lote '{lote.id}' (lease expirado ou tentativa antiga)",
        )


@router.post("/register")
def registrar(worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    Não persiste nada -- não existe uma "tabela de Workers" nesta fase
    (decisão explícita: um `worker_id`/`lease_ate`/`ultimo_heartbeat` por
    JOB já cobre o que importa; um Worker sem Job nenhum não é estado que
    precise ser lembrado). Serve para o Worker validar a própria
    configuração (`OCR_WORKER_TOKEN`) antes de começar a fazer polling.
    """
    logging.info("[Worker %s] registrado", worker_id)
    return {"registrado": True, "worker_id": worker_id}


@router.post("/heartbeat", response_model=HeartbeatResposta)
def heartbeat(corpo: HeartbeatRequest, worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    Prova de vida do PROCESSO do Worker -- independente do laço de OCR
    (ver D6 no relatório da fase; `LEASE_S`/`INTERVALO_HEARTBEAT_S` em
    `estado.py`). Sem `lote_id`, é só um "estou vivo, sem Job no momento"
    -- útil para o Worker confirmar conectividade mesmo ocioso.
    """
    if corpo.lote_id is None:
        return HeartbeatResposta(ainda_dono=True)
    lote = _lote_ou_404(corpo.lote_id)
    ainda_dono = estado.renovar_lease(lote, worker_id, corpo.tentativa)
    return HeartbeatResposta(ainda_dono=ainda_dono)


@router.get("/jobs/next", response_model=ProximoJobResposta)
def proximo_job(worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    Só INDICA um candidato -- não reivindica nada (ver `POST .../claim`
    logo abaixo). Dois Workers podem receber o mesmo `lote_id` aqui; só um
    deles vai conseguir reivindicá-lo de verdade, o outro leva 409 e
    volta a perguntar. `lote_id=None` (200, nunca 404) é o caso normal de
    "nada para fazer agora" -- fila vazia não é erro.
    """
    return ProximoJobResposta(lote_id=estado.proximo_job_disponivel())


@router.post("/jobs/{lote_id}/claim", response_model=JobReivindicado)
def reivindicar_job(lote_id: str, worker_id: str = Depends(auth_worker.verificar_worker)):
    """Claim atômico -- ver `estado.reivindicar`. 409 quando outro Worker
    já reivindicou primeiro (a corrida é decidida dentro do lock do
    `LoteState`, nunca aqui)."""
    lote = _lote_ou_404(lote_id)
    tentativa = estado.reivindicar(lote, worker_id)
    if tentativa is None:
        raise HTTPException(
            status_code=409,
            detail=f"O lote '{lote_id}' já não está disponível (outro Worker chegou primeiro)",
        )
    with lote.lock:
        tipo, total_paginas, nomes = lote.tipo, lote.total_paginas, list(lote.caminhos)
    return JobReivindicado(
        lote_id=lote.id,
        tentativa=tentativa,
        tipo=tipo,
        total_paginas=total_paginas,
        nomes_arquivos=[os.path.basename(c) for c in nomes],
        paginas_pendentes=estado.paginas_pendentes(lote),
    )


@router.get("/jobs/{lote_id}/arquivos/{indice}")
def baixar_arquivo(lote_id: str, indice: int, tentativa: int,
                    worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    O Worker baixa o arquivo de entrada UMA VEZ (`indice=0` para PDF --
    um lote de PDF tem um único arquivo de entrada, a folha inteira;
    `indice = número da página - 1` para imagens, mesma correspondência
    de `estado._nome_do_arquivo`). Exige posse do Job: só quem
    reivindicou pode baixar, mesmo com o token válido -- um arquivo pode
    conter dado sensível (nome, matrícula) e não há razão para um Worker
    alheio ao Job enxergá-lo.
    """
    lote = _lote_ou_404(lote_id)
    _exigir_posse(lote, worker_id, tentativa)
    with lote.lock:
        caminhos = list(lote.caminhos)
    if not (0 <= indice < len(caminhos)):
        raise HTTPException(status_code=404, detail=f"Arquivo {indice} não existe no lote '{lote_id}'")
    caminho = caminhos[indice]
    if not os.path.isfile(caminho):
        raise HTTPException(status_code=404, detail="Arquivo de entrada não encontrado no armazenamento")
    return FileResponse(caminho, filename=os.path.basename(caminho))


@router.post("/jobs/{lote_id}/paginas/{numero}", response_model=ResultadoPaginaResposta, status_code=202)
def entregar_pagina(lote_id: str, numero: int, corpo: ResultadoPaginaRequest,
                    worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    Entrega o resultado do OCR de uma página -- SEM classificar nada
    aqui (isso é a thread-motora, do lado VPS). `resultado` == "aceito" |
    "duplicado" | "obsoleto"; os três são respostas de SUCESSO do ponto
    de vista HTTP (o Worker não precisa distinguir "aceito" de
    "duplicado" para saber que pode seguir para a próxima página -- só
    "obsoleto" significa "pare de trabalhar neste Job").

    NÃO usa `_exigir_posse` aqui de propósito -- só `estado.depositar_
    resultado_pagina`, que compara a `tentativa` recebida contra a ATUAL
    do Job, e é isso (não `fase_worker`/`worker_id`, que a conclusão do
    Job já zera) que decide "aceito"/"duplicado"/"obsoleto". Achado real
    desta sub-fase: reenviar a MESMA última página depois que o Job já
    concluiu (`fase_worker` voltou a `local`) é um caso genuíno -- o
    Worker não sabe que a VPS já terminou -- e precisa continuar
    respondendo "duplicado", nunca 409.
    """
    lote = _lote_ou_404(lote_id)
    resultado = estado.depositar_resultado_pagina(
        lote, numero,
        {"numero": numero, "erro": corpo.erro, "fase_erro": corpo.fase_erro, "registros": corpo.registros},
        tentativa=corpo.tentativa,
    )
    return ResultadoPaginaResposta(resultado=resultado)


@router.put("/jobs/{lote_id}/paginas/{numero}/miniatura", status_code=204)
async def entregar_miniatura(lote_id: str, numero: int, tentativa: int, request: Request,
                              worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    Canal SEPARADO do resultado de propósito (D7 do relatório): a foto é
    comodidade da revisão, não dado -- `_comprimir_para_miniatura` nunca
    lança no lado Worker, e este endpoint segue a mesma filosofia: uma
    falha aqui não pode custar o resultado do OCR daquela página, que
    levou ~40 s. Corpo é `image/jpeg` cru, sem base64/multipart -- o
    volume medido (~250-600 KB/página) não justifica a complexidade.

    LENIENTE quanto à posse, mesmo motivo de `/progresso`: sem ownership
    válida (incluindo "o Job já concluiu entre o Worker mandar a página e
    mandar a foto dela"), simplesmente não grava nada -- devolve 204 do
    mesmo jeito, nunca 409, porque perder UMA miniatura não é uma falha
    que o Worker precise tratar.
    """
    lote = _lote_ou_404(lote_id)
    if estado.tentativa_valida(lote, worker_id, tentativa):
        conteudo = await request.body()
        estado.depositar_miniatura(lote, numero, conteudo)
    return None


@router.post("/jobs/{lote_id}/progresso", status_code=204)
def progresso(lote_id: str, corpo: ProgressoRequest, worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    `etapa_atual` -- o texto livre que `Processamento.jsx` já renderiza
    (mesmas frases de `pipeline.processar_uma_pagina`: "Lendo o texto
    escrito à mão...", etc.). `total_paginas` é aceito aqui mas raramente
    precisa ser enviado: a VPS já calcula sozinha (`estado.
    _descobrir_total_paginas`, rodando contra a CÓPIA do arquivo que ela
    própria recebeu no upload -- `pdf_reader.contar_paginas` para PDF,
    `len(caminhos)` de graça para imagens) logo no início de `processar_
    lote`, ANTES de qualquer Worker sequer existir. O campo só serve de
    reforço redundante (nunca é a fonte de verdade) caso um dia esse
    cálculo local falhe.

    Fica LENIENTE de propósito quando este Worker não é mais dono do Job
    (ownership perdida, ou o Job já concluiu) -- diferente de `/paginas/
    {numero}` e `/erro`, que continuam estritos. Motivo, achado real
    durante esta sub-fase: entregar o RESULTADO da ÚLTIMA página pode
    fazer a VPS concluir o Job (e liberar `worker_id`/`fase_worker`)
    ANTES da chamada de progresso seguinte deste mesmo Worker executar --
    409'ar isso seria punir uma corrida inofensiva por uma mensagem
    puramente informativa. Sem posse válida, a chamada simplesmente não
    altera nada e devolve sucesso mesmo assim.
    """
    lote = _lote_ou_404(lote_id)
    if estado.tentativa_valida(lote, worker_id, corpo.tentativa):
        if corpo.etapa_atual is not None:
            estado.registrar_etapa(lote, corpo.etapa_atual)
        if corpo.total_paginas is not None:
            estado.registrar_total_paginas(lote, corpo.total_paginas)
        estado.registrar_progresso_worker(lote, worker_id, corpo.tentativa)
    return None


@router.post("/jobs/{lote_id}/concluir", status_code=204)
def concluir(lote_id: str, corpo: ConcluirRequest, worker_id: str = Depends(auth_worker.verificar_worker)):
    """
    O Worker já entregou todas as páginas que ia entregar. NÃO conclui o
    Job -- quem decide isso é a thread-motora, ao aplicar a última
    página; isto só libera a posse perante outros Workers (ver `estado.
    liberar_apos_producao`).

    Também LENIENTE (ver `/progresso` acima, mesmo motivo): se o Job já
    concluiu sozinho entre o Worker entregar a última página e chamar
    isto, não há posse nenhuma para liberar -- `liberar_apos_producao`
    devolve `False` e este endpoint trata isso como sucesso mesmo assim,
    nunca como erro do Worker."""
    lote = _lote_ou_404(lote_id)
    estado.liberar_apos_producao(lote, worker_id, corpo.tentativa)
    return None


@router.post("/jobs/{lote_id}/erro", status_code=204)
def erro_de_documento(lote_id: str, corpo: ErroDeDocumentoRequest,
                      worker_id: str = Depends(auth_worker.verificar_worker)):
    """Falha do DOCUMENTO INTEIRO (arquivo que não abre, PDF sem páginas)
    -- diferente de uma página individual falhar (isso é `POST .../
    paginas/{numero}` com `erro` preenchido)."""
    lote = _lote_ou_404(lote_id)
    if not estado.marcar_falha_de_documento(lote, worker_id, corpo.tentativa, corpo.mensagem):
        raise HTTPException(status_code=409, detail="Este Worker não é mais o dono deste lote")
    return None


@router.get("/status", response_model=StatusWorkerResposta)
def status_worker():
    """
    Sem autenticação de propósito -- é um resumo agregado, sem dado de
    negócio nem o token (ver docstring do módulo: a proteção real desta
    superfície é a montagem fora de `/leitor` + a rede Tailscale). Mesma
    filosofia de `GET /saude`.
    """
    return StatusWorkerResposta(modo=config.modo(), **estado.resumo_jobs())
