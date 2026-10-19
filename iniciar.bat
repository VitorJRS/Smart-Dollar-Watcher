@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title Smart Dollar Watcher - Radar Quantitativo & WhatsApp Bot
echo ===================================================================
echo   💵 SMART DOLLAR WATCHER - MOTOR QUANTITATIVO + WHATSAPP BOT
echo ===================================================================
echo.
echo Iniciando servidor e ponte WhatsApp Web...
echo Abra seu navegador em: http://localhost:8000
echo.
start "" http://localhost:8000
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
