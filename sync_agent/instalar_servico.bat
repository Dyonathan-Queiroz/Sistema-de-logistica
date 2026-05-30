@echo off
title Instalar Servico — Consinco Sync Agent
color 0E

REM Precisa rodar como Administrador
net session >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERRO: Execute este arquivo como Administrador!
    pause
    exit /B 1
)

REM pushd aceita caminhos de rede (UNC)
pushd "%~dp0"

echo.
echo ============================================================
echo   INSTALAR CONSINCO SYNC AGENT COMO SERVICO WINDOWS
echo   Pasta: %CD%
echo ============================================================
echo.

REM Descobre onde esta o python
for /f "delims=" %%i in ('where python 2^>NUL') do set PYTHON=%%i
if not defined PYTHON (
    echo ERRO: Python nao encontrado no PATH!
    popd
    pause
    exit /B 1
)
echo [OK] Python encontrado: %PYTHON%

REM Pasta atual (pode ser UNC mapeado por pushd)
set PASTA=%CD%

REM Remove servico antigo se existir
sc query "ConsincoSyncAgent" >NUL 2>&1
if %ERRORLEVEL% == 0 (
    echo Removendo servico anterior...
    sc stop "ConsincoSyncAgent" >NUL 2>&1
    sc delete "ConsincoSyncAgent" >NUL 2>&1
    timeout /t 2 /nobreak >NUL
)

REM Verifica se NSSM esta disponivel
where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    echo [OK] NSSM encontrado — instalando servico...
    nssm install ConsincoSyncAgent "%PYTHON%" "%PASTA%\consinco_sync.py"
    nssm set ConsincoSyncAgent AppDirectory "%PASTA%"
    nssm set ConsincoSyncAgent DisplayName "Consinco Sync Agent"
    nssm set ConsincoSyncAgent Description "Sincronizacao Oracle Consinco para Sistema Logistico Gaviao"
    nssm set ConsincoSyncAgent Start SERVICE_AUTO_START
    nssm set ConsincoSyncAgent AppStdout "%PASTA%\sync_agent.log"
    nssm set ConsincoSyncAgent AppStderr "%PASTA%\sync_agent.log"
    nssm set ConsincoSyncAgent AppRotateFiles 1
    nssm set ConsincoSyncAgent AppRotateBytes 5242880
    echo.
    echo [OK] Servico instalado com NSSM!
) else (
    echo [INFO] NSSM nao encontrado — usando Agendador de Tarefas...
    schtasks /Create /TN "ConsincoSyncAgent" /TR "\"%PYTHON%\" \"%PASTA%\consinco_sync.py\"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F
    if %ERRORLEVEL% == 0 (
        echo [OK] Tarefa agendada criada! Inicia automaticamente ao ligar o servidor.
    ) else (
        echo [ERRO] Falha ao criar tarefa agendada.
    )
)

echo.
echo ============================================================
echo   INICIANDO O SERVICO AGORA...
echo ============================================================

where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    nssm start ConsincoSyncAgent
) else (
    schtasks /Run /TN "ConsincoSyncAgent"
    echo Aguarde 5 segundos...
    timeout /t 5 /nobreak >NUL
)

echo.
echo Pronto! Para verificar o status rode: verificar_status.bat
echo.
popd
pause
