@echo off
REM Leitor de Matriculas -- inicia o frontend (Vite/React)
REM Gerado como atalho de conveniencia -- ver web/README.md para os comandos manuais.
cd /d "%~dp0"

if not exist ".tools\node-v22.14.0-win-x64\node.exe" (
    echo [ERRO] Nao encontrei o Node.js portatil em .tools\node-v22.14.0-win-x64
    echo Se voce ja tem Node.js instalado no sistema, pode ignorar e rodar direto:
    echo   cd web\frontend ^&^& npm run dev
    pause
    exit /b 1
)

set "PATH=%~dp0.tools\node-v22.14.0-win-x64;%PATH%"
cd web\frontend

echo.
echo === Frontend (Vite) subindo ===
echo Confira no terminal abaixo a porta exata (normalmente 5173).
echo Pressione Ctrl+C para parar.
echo.
call npm run dev

echo.
echo === Frontend encerrado ===
pause
