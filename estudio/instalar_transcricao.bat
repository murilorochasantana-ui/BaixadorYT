@echo off
chcp 65001 >nul
title Estudio ViceCityDay - Instalar transcricao (Whisper)
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && py -3.12 -c "" >nul 2>nul && set "PY=py -3.12"
if not defined PY set "PY=python"

echo Instalando o Whisper (transcreve videos que nao tem legenda: TikTok, Instagram, Twitch...)
echo Isso so precisa ser feito uma vez.
echo.
%PY% -m pip install -U faster-whisper
echo.
echo Pronto! Na primeira transcricao o Estudio baixa o modelo (~460 MB), depois fica salvo.
pause
