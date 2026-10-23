@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title Smart Dollar Watcher - Radar Quantitativo & WhatsApp Bot
echo ===================================================================
echo   💵 SMART DOLLAR WATCHER - MOTOR QUANTITATIVO + WHATSAPP BOT
echo ===================================================================
echo.

if not exist .venv\Scripts\python.exe (
    echo [Setup] Criando ambiente virtual Python...
    py -3 -m venv .venv
    echo [Setup] Instalando dependencias Python...
    .\.venv\Scripts\pip.exe install -r requirements.txt
)

if not exist whatsapp-bridge\node_modules (
    echo [Setup] Instalando dependencias do WhatsApp (Node.js)...
    cd whatsapp-bridge
    call npm.cmd install
    cd ..
)

echo.
echo Iniciando servidor e ponte WhatsApp Web...
echo Abra seu navegador em: http://localhost:8000
echo.
start "" http://localhost:8000
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
