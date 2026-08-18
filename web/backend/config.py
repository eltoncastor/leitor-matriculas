"""
web/backend/config.py

Fase 26a. Configuração do backend por variável de ambiente. Até aqui o
projeto não tinha NENHUM mecanismo de configuração (auditoria desta fase:
nenhum `.env`, nenhuma variável lida em lugar nenhum) -- tudo era
constante no código. Com o OCR podendo rodar noutra máquina, passa a
existir uma decisão que muda por INSTALAÇÃO, não por código: quem executa
o OCR deste backend.

MODOS
-----
`local` (padrão)  -- o próprio processo roda o OCR, numa thread. É o
                     comportamento de sempre e o que o modo desktop
                     (`web/desktop_app.py`) e o `.exe` continuam usando:
                     uma janela nativa não tem Worker remoto nenhum, e não
                     faria sentido exigir um.
`servidor`        -- este processo NÃO roda OCR. Os lotes ficam
                     aguardando um Worker reivindicá-los. É o modo da VPS.

O padrão é `local` de propósito: é o que preserva o comportamento anterior
para quem não configurar nada, e um erro de configuração na VPS resulta em
"a máquina errada trabalhou", não em "o lote sumiu".
"""
import os

MODO_LOCAL = "local"
MODO_SERVIDOR = "servidor"

VARIAVEL_MODO = "LEITOR_MODO"


def modo() -> str:
    valor = (os.environ.get(VARIAVEL_MODO) or MODO_LOCAL).strip().lower()
    return MODO_SERVIDOR if valor == MODO_SERVIDOR else MODO_LOCAL


def roda_ocr_neste_processo() -> bool:
    return modo() == MODO_LOCAL
