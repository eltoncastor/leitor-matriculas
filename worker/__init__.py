"""
worker/

Fase 26c. O processo que roda o OCR de verdade (PC Windows do operador),
falando com a VPS pelo protocolo `/api/worker/*` (ver `web/backend/rotas/
worker.py` e `saida/auditoria_fase26_ocr_worker.md`). Não hospeda FastAPI
nem frontend, não abre porta pública, não exige IP público, port
forwarding, Docker ou Linux -- só faz requisições de saída (`Worker ->
VPS`), sempre.

Estrutura:
    config.py     variáveis de ambiente / .env
    cliente.py    cliente HTTP do protocolo (stdlib só, sem `requests`)
    heartbeat.py  prova de vida do PROCESSO, thread própria e independente
                  do laço de OCR
    execucao.py   o laço principal: reivindica um Job, baixa os arquivos,
                  roda `leitor_matriculas.pipeline`, entrega o resultado

Rodar:
    python -m worker
"""
