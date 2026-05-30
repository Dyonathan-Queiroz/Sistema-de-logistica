@echo off
title Consinco Sync Agent
color 0A

REM ── pushd aceita caminhos de rede (UNC) criando drive temporario ──
pushd "%~dp0"
if %ERRORLEVEL% NEQ 0 (
    echo ERRO: Nao foi possivel acessar a pasta do agente.
    pause
    exit /B 1
)

echo.
echo ============================================================
echo   CONSINCO SYNC AGENT
echo   Pasta: %CD%
echo ============================================================
echo.

REM ── 1. Verifica Python ──────────────────────────────────────
echo [1/3] Verificando Python...
python --version >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo.
    echo  ERRO: Python nao encontrado no PATH!
    echo  Instale o Python e marque "Add to PATH" na instalacao.
    echo.
    popd
    pause
    exit /B 1
)
python --version
echo       OK!
echo.

REM ── 2. Instala dependencias ──────────────────────────────────
echo [2/3] Instalando/verificando dependencias...
pip install -r requirements.txt -q
if %ERRORLEVEL% NEQ 0 (
    color 0C
    echo.
    echo  ERRO: Falha ao instalar dependencias!
    echo  Verifique sua conexao com a internet.
    echo.
    popd
    pause
    exit /B 1
)
echo       OK!
echo.

REM ── 3. Verifica .env ────────────────────────────────────────
echo [3/3] Verificando arquivo .env...
if not exist ".env" (
    color 0C
    echo.
    echo  ERRO: Arquivo .env nao encontrado!
    echo  Crie o arquivo .env nesta pasta com as credenciais.
    echo.
    popd
    pause
    exit /B 1
)
echo       OK!
echo.

REM ── Inicia o agente ──────────────────────────────────────────
echo ============================================================
echo   INICIANDO AGENTE — pressione CTRL+C para encerrar
echo ============================================================
echo.

python consinco_sync.py

REM ── Se chegou aqui, o agente encerrou ────────────────────────
echo.
echo ============================================================
color 0E
echo   AGENTE ENCERRADO  —  Codigo de saida: %ERRORLEVEL%
echo ============================================================
echo.
echo Verifique o arquivo registro_entregas.txt para detalhes.
echo.
popd
pause
