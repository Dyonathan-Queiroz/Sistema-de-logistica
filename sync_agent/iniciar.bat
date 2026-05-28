@echo off
title Consinco Sync Agent
cd /d "%~dp0"
echo Instalando dependencias...
pip install -r requirements.txt -q
echo.
echo Iniciando agente de sincronizacao...
echo Pressione CTRL+C para encerrar.
echo.
python consinco_sync.py
pause
