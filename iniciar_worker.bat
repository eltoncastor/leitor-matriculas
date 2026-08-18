@echo off
REM Leitor de Matriculas -- inicia o Worker (OCR remoto, Fase 26)
REM Gerado como atalho de conveniencia -- ver web/README.md para os comandos manuais.
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Nao encontrei venv\Scripts\activate.bat nesta pasta.
    echo Confira se este .bat esta na raiz do projeto, ao lado da pasta "venv".
    pause
    exit /b 1
)

if not exist ".env" (
    echo [AVISO] Nao encontrei um arquivo .env nesta pasta.
    echo Copie .env.example para .env e preencha API_BASE_URL / OCR_WORKER_ID / OCR_WORKER_TOKEN.
    echo O programa vai continuar e mostrar o erro exato se faltar alguma variavel.
    echo.
)

call venv\Scripts\activate.bat
echo.
echo === Worker (leitura de OCR) iniciando ===
echo Ctrl+C encerra o Worker com seguranca (espera o Job atual terminar).
echo.
python -m worker

echo.
echo === Worker encerrado ===
pause
