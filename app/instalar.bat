@echo off
chcp 65001 >nul
title Baixador YT - Instalacao
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python nao encontrado. Instalando...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python instalado. FECHE esta janela e rode o instalar.bat de novo.
  pause
  exit /b
)
echo [1/3] Instalando yt-dlp e ffmpeg...
python -m pip install -U "yt-dlp[default,curl-cffi]" imageio-ffmpeg
echo [2/3] Instalando Deno (necessario para o YouTube)...
winget install -e --id DenoLand.Deno --accept-package-agreements --accept-source-agreements
echo [3/3] Criando atalho na Area de Trabalho...
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%P
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Baixador YT.lnk');$s.TargetPath='%PYW%';$s.Arguments='\"%~dp0BaixadorYT.pyw\"';$s.WorkingDirectory='%~dp0';$s.Save()"
echo.
echo === Pronto! Abra o "Baixador YT" na Area de Trabalho ===
pause
