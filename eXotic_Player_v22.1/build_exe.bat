@echo off
setlocal
REM Compila eXotic Player -> dist\eXoticPlayer\eXoticPlayer.exe
REM Ejecutar dentro de la carpeta del proyecto (con Python 64 bits y VLC 64 bits instalados).

if not exist "C:\Program Files\VideoLAN\VLC\libvlc.dll" (
  echo No encuentro VLC en "C:\Program Files\VideoLAN\VLC". Instala VLC 64 bits o edita la ruta en eXoticPlayer.spec
  pause & exit /b 1
)
if not exist supabase_config.json (
  echo Falta supabase_config.json en esta carpeta.
  pause & exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (pause & exit /b 1)

python -m PyInstaller --noconfirm --clean eXoticPlayer.spec || (pause & exit /b 1)

REM deno.exe (opcional, lo usa yt-dlp): si existe tools\deno.exe se copia junto al .exe
if exist tools\deno.exe (
  xcopy /E /I /Y tools "dist\eXoticPlayer\tools" >nul
  echo Copiado tools\deno.exe
)

echo.
echo Listo: dist\eXoticPlayer\eXoticPlayer.exe  (comprime TODA la carpeta para repartirla)
pause
