@echo off
echo ===================================================
echo  Creando YouTubeDownloader.exe (standalone)
echo ===================================================
echo.
pip install pyinstaller
echo.
echo Compilando...
pyinstaller --onefile --console --name "YouTubeDownloader" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import yt_dlp ^
  --hidden-import imageio_ffmpeg ^
  main.py
echo.
if exist "dist\YouTubeDownloader.exe" (
    echo ===================================================
    echo  LISTO! Ejecutable en: dist\YouTubeDownloader.exe
    echo ===================================================
) else (
    echo [ERROR] No se pudo crear el ejecutable.
)
pause
