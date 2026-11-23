@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CineDuo - Modo Celular na Rede WiFi
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 app.py --network
) else (
    python app.py --network
)
if errorlevel 1 pause
