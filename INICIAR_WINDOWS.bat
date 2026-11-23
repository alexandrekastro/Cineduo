@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CineDuo - Nosso ranking de filmes
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 app.py
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python app.py
    ) else (
        echo.
        echo ERRO: Python nao foi encontrado no computador.
        echo Instale o Python em https://www.python.org/downloads/
        echo Na instalacao, marque "Add Python to PATH".
        pause
    )
)
if errorlevel 1 pause
