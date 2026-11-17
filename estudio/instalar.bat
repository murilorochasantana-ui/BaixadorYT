@echo off
chcp 65001 >nul
title Estudio ViceCityDay - Instalacao
cd /d "%~dp0"

rem Usa o Python 3.12 (o PC pode ter outras versoes instaladas)
set "PY="
where py >nul 2>nul && py -3.12 -c "" >nul 2>nul && set "PY=py -3.12"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [!] Python nao encontrado. Instalando o Python 3.12...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python instalado. FECHE esta janela e rode o instalar.bat de novo.
  pause
  exit /b
)

echo [1/4] Instalando yt-dlp, ffmpeg e a janela do Estudio...
%PY% -m pip install -U "yt-dlp[default,curl-cffi]" imageio-ffmpeg pywebview
if errorlevel 1 (
  echo.
  echo [!] A instalacao falhou. Confira a internet e rode o instalar.bat de novo.
  pause
  exit /b
)

echo [2/4] Conferindo o Deno (necessario para o YouTube)...
where deno >nul 2>nul || winget install -e --id DenoLand.Deno --accept-package-agreements --accept-source-agreements

echo [3/4] Conferindo o WebView2 (motor da janela, ja vem no Windows 11)...
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>nul || winget install -e --id Microsoft.EdgeWebView2Runtime --accept-package-agreements --accept-source-agreements

echo [4/4] Criando atalho "Estudio ViceCityDay" na Area de Trabalho...
for /f "delims=" %%P in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%P"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Estudio ViceCityDay.lnk');$s.TargetPath='%PYW%';$s.Arguments='\"%~dp0Estudio.pyw\"';$s.WorkingDirectory='%~dp0';$s.Save()"

echo.
echo === Pronto! Abra o "Estudio ViceCityDay" na Area de Trabalho ===
echo (Para transcrever videos sem legenda, rode tambem o instalar_transcricao.bat)
pause
