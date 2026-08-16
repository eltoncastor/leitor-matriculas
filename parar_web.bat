@echo off
REM Leitor de Matriculas -- encerra backend e frontend (uvicorn/vite) se estiverem rodando
echo Encerrando processos do backend (uvicorn/python) e frontend (node/vite)...
taskkill /FI "WINDOWTITLE eq Leitor de Matriculas - Backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Leitor de Matriculas - Frontend*" /T /F >nul 2>&1
echo Feito. Se alguma janela ainda estiver aberta, pode fechar manualmente.
pause
