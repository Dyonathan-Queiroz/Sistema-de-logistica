@echo off
title Sistema Logistica - Servidor Local

echo.
echo  ====================================
echo   Sistema Logistica - Super GAVIAO  
echo   Servidor Local - Porta 8000       
echo  ====================================
echo.

cd /d "%~dp0"

echo [1/3] Verificando porta 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    echo      Encerrando processo anterior PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/3] Ativando ambiente virtual...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo      AVISO: venv nao encontrado, usando Python global.
)

echo [3/3] Iniciando servidor...
echo.
echo  Acesse: http://localhost:8000
echo  Para parar: Ctrl+C ou feche esta janela
echo.
echo ----------------------------------------

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

echo.
echo  Servidor encerrado.
pause
