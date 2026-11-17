@echo off
chcp 65001 >nul
echo Atualizando yt-dlp (use quando algum video der erro)...
python -m pip install -U "yt-dlp[default]"
pause
