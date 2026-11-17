@echo off
chcp 65001 >nul
title Baixador YT - Instalar transcricao (Whisper)
echo Instalando o Whisper (transcreve videos que nao tem legenda: TikTok, Instagram, Twitch...)
echo Isso so precisa ser feito uma vez.
echo.
python -m pip install -U faster-whisper
echo.
echo Pronto! Na primeira transcricao o app baixa o modelo (~460 MB), depois fica salvo.
pause
