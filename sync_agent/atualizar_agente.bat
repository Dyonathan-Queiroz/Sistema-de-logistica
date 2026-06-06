@echo off
title Atualizar Consinco Sync Agent
color 0A
setlocal EnableDelayedExpansion

REM ============================================================
REM   ATUALIZADOR DO CONSINCO SYNC AGENT
REM   Execute como Administrador no servidor Consinco
REM ============================================================

net session >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERRO] Execute este arquivo como Administrador!
    echo  Clique com botao direito > "Executar como administrador"
    echo.
    pause
    exit /B 1
)

echo.
echo  ============================================================
echo    ATUALIZADOR — CONSINCO SYNC AGENT
echo  ============================================================
echo.

REM ── Localiza o consinco_sync.py neste pendrive ──────────────
set "FONTE=%~dp0consinco_sync.py"
if not exist "%FONTE%" (
    echo  [ERRO] consinco_sync.py nao encontrado ao lado deste .bat
    echo  Certifique-se de que os dois arquivos estao na mesma pasta.
    echo.
    pause
    exit /B 1
)
echo  [OK] Arquivo fonte encontrado: %FONTE%
echo.

REM ── Tenta detectar pasta destino pelo servico NSSM ──────────
set "DESTINO="

where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    for /f "tokens=*" %%i in ('nssm get ConsincoSyncAgent AppDirectory 2^>NUL') do (
        set "DESTINO=%%i"
    )
)

REM ── Tenta detectar pelo Agendador de Tarefas ────────────────
if not defined DESTINO (
    for /f "tokens=*" %%i in ('schtasks /Query /TN "ConsincoSyncAgent" /FO LIST /V 2^>NUL ^| findstr /i "Iniciar em"') do (
        set "LN=%%i"
        set "DESTINO=!LN:Iniciar em:   =!"
    )
)

REM ── Se nao encontrou, pede ao usuario ───────────────────────
if not defined DESTINO (
    echo  [INFO] Nao foi possivel detectar a pasta automaticamente.
    echo.
    set /p DESTINO=" Digite o caminho completo da pasta sync_agent no servidor: "
)

REM Remove espacos/aspas extras
set "DESTINO=%DESTINO:"=%"
for /f "tokens=* delims= " %%a in ("%DESTINO%") do set "DESTINO=%%a"

if not exist "%DESTINO%" (
    echo.
    echo  [ERRO] Pasta nao encontrada: %DESTINO%
    echo  Verifique o caminho e tente novamente.
    echo.
    pause
    exit /B 1
)

echo  [OK] Destino detectado: %DESTINO%
echo.

REM ── Confirmacao ─────────────────────────────────────────────
echo  Resumo da operacao:
echo    Origem : %FONTE%
echo    Destino: %DESTINO%\consinco_sync.py
echo.
set /p CONF=" Confirma a atualizacao? (S/N): "
if /i not "%CONF%"=="S" (
    echo  Operacao cancelada.
    pause
    exit /B 0
)
echo.

REM ── Para o servico ──────────────────────────────────────────
echo  [1/4] Parando o servico...

where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    nssm stop ConsincoSyncAgent >NUL 2>&1
) else (
    schtasks /End /TN "ConsincoSyncAgent" >NUL 2>&1
    taskkill /F /IM python.exe /T >NUL 2>&1
)
timeout /t 3 /nobreak >NUL
echo  [OK] Servico parado.

REM ── Faz backup do arquivo atual ─────────────────────────────
echo  [2/4] Fazendo backup do arquivo atual...
set "TS=%date:~6,4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%"
set "TS=%TS: =0%"
copy "%DESTINO%\consinco_sync.py" "%DESTINO%\consinco_sync.py.bak_%TS%" >NUL 2>&1
echo  [OK] Backup salvo como consinco_sync.py.bak_%TS%

REM ── Copia o arquivo atualizado ──────────────────────────────
echo  [3/4] Copiando arquivo atualizado...
copy /Y "%FONTE%" "%DESTINO%\consinco_sync.py" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo  [ERRO] Falha ao copiar o arquivo!
    echo  Restaurando backup...
    copy /Y "%DESTINO%\consinco_sync.py.bak_%TS%" "%DESTINO%\consinco_sync.py" >NUL
    pause
    exit /B 1
)
echo  [OK] Arquivo atualizado com sucesso.

REM ── Reinicia o servico ──────────────────────────────────────
echo  [4/4] Reiniciando o servico...

where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    nssm start ConsincoSyncAgent >NUL 2>&1
) else (
    schtasks /Run /TN "ConsincoSyncAgent" >NUL 2>&1
)
timeout /t 4 /nobreak >NUL

REM ── Verifica se esta rodando ─────────────────────────────────
echo.
echo  ============================================================
echo    RESULTADO
echo  ============================================================

where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    nssm status ConsincoSyncAgent
) else (
    schtasks /Query /TN "ConsincoSyncAgent" /FO LIST 2>NUL | findstr /i "Status"
)

echo.
echo  [CONCLUIDO] Atualizacao finalizada!
echo  Verifique o log em: %DESTINO%\sync_agent.log
echo.
pause
