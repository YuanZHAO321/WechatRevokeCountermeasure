@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Installing dependencies...
python -m pip install customtkinter pyinstaller

echo Building exe...
python -m PyInstaller build.spec --clean

echo Done. Output: dist\WeChatAntiRevoke.exe
pause
