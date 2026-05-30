@echo off
title Verificar Status — Consinco Sync Agent
color 0A
echo.
echo ============================================================
echo   STATUS DO CONSINCO SYNC AGENT
echo ============================================================
echo.

REM Verifica se o processo python esta rodando com consinco_sync.py
tasklist /FI "IMAGENAME eq python.exe" /FO CSV 2>NUL | findstr /I "python" >NUL
if %ERRORLEVEL% == 0 (
    echo [RODANDO]  Processo Python encontrado.
) else (
    echo [PARADO]   Nenhum processo Python ativo.
)

echo.

REM Verifica se existe como Servico Windows
sc query "ConsincoSyncAgent" >NUL 2>&1
if %ERRORLEVEL% == 0 (
    echo [SERVICO]  Servico Windows instalado:
    sc query "ConsincoSyncAgent" | findstr "STATE"
) else (
    echo [SERVICO]  Nao instalado como servico Windows.
    echo            Rode instalar_servico.bat para instalar.
)

echo.

REM Mostra as ultimas 10 linhas do log
if exist "sync_agent.log" (
    echo ---- Ultimas linhas do log --------------------------------
    powershell -Command "Get-Content sync_agent.log -Tail 10"
    echo -----------------------------------------------------------
) else (
    echo [LOG] Arquivo sync_agent.log nao encontrado.
)

echo.
pause
