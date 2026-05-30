@echo off
title Verificar Status — Consinco Sync Agent
color 0A

pushd "%~dp0"

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

REM Mostra as ultimas 10 linhas do registro legivel
if exist "registro_entregas.txt" (
    echo ---- Ultimas entregas sincronizadas -----------------------
    powershell -Command "Get-Content registro_entregas.txt -Tail 10"
    echo -----------------------------------------------------------
    echo.
    set /P ABRIR="Abrir registro_entregas.txt no Bloco de Notas? (S/N): "
    if /I "%ABRIR%"=="S" start notepad.exe "%CD%\registro_entregas.txt"
) else (
    echo [LOG] Nenhuma entrega sincronizada ainda.
    echo       O arquivo registro_entregas.txt sera criado na proxima sincronizacao.
)

echo.
popd
pause
