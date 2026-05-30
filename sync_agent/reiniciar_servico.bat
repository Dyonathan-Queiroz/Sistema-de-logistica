@echo off
title Reiniciar — Consinco Sync Agent
color 0C

net session >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERRO: Execute como Administrador!
    pause
    exit /B 1
)

pushd "%~dp0"

echo Parando agente...

where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    nssm stop ConsincoSyncAgent
) else (
    schtasks /End /TN "ConsincoSyncAgent" >NUL 2>&1
    taskkill /F /IM python.exe /T >NUL 2>&1
)

timeout /t 3 /nobreak >NUL
echo Reiniciando...

where nssm >NUL 2>&1
if %ERRORLEVEL% == 0 (
    nssm start ConsincoSyncAgent
) else (
    schtasks /Run /TN "ConsincoSyncAgent"
)

echo.
echo [OK] Agente reiniciado!
popd
pause
