@echo off
REM Leitor de Matriculas -- inicia o backend (FastAPI/uvicorn)
REM Gerado como atalho de conveniencia -- ver web/README.md para os comandos manuais.
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Nao encontrei venv\Scripts\activate.bat nesta pasta.
    echo Confira se este .bat esta na raiz do projeto, ao lado da pasta "venv".
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
echo.
echo === Backend (FastAPI) subindo em http://0.0.0.0:8000 ===
echo Uso local: http://127.0.0.1:8000/docs
echo Uso remoto (Tailscale): http://SEU-IP-TAILSCALE:8000/docs
echo Pressione Ctrl+C para parar.
echo.
python web\backend\main.py

echo.
echo === Backend encerrado ===
pause
