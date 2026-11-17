@echo off
chcp 65001 >nul
title Estudio ViceCityDay - Atualizar
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && py -3.12 -c "" >nul 2>nul && set "PY=py -3.12"
if not defined PY set "PY=python"

echo Atualizando o yt-dlp (resolve a maioria dos erros de download) e a janela do Estudio...
%PY% -m pip install -U "yt-dlp[default,curl-cffi]" imageio-ffmpeg pywebview
echo.
echo Pronto! Pode abrir o Estudio de novo.
pause
