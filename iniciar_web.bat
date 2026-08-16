@echo off
REM Leitor de Matriculas -- sobe backend + frontend juntos, cada um em sua janela
cd /d "%~dp0"

echo Iniciando backend e frontend em janelas separadas...
start "Leitor de Matriculas - Backend"  cmd /k ""%~dp0iniciar_backend.bat""
timeout /t 2 /nobreak >nul
start "Leitor de Matriculas - Frontend" cmd /k ""%~dp0iniciar_frontend.bat""

echo.
echo Duas janelas foram abertas (Backend e Frontend). Aguarde alguns segundos
echo ate o frontend terminar de subir, depois acesse no navegador o endereco
echo que aparecer na janela do Frontend (normalmente http://localhost:5173).
echo.
echo Para parar, feche as duas janelas ou aperte Ctrl+C em cada uma.
pause
