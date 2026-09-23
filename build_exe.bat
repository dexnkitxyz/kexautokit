@echo off
setlocal
chcp 65001 >nul

echo ============================================
echo Building auto_receive.exe
echo ============================================

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo ERROR: PyInstaller was not found in .venv
    echo Run setup_and_run.bat first or install PyInstaller in .venv.
    exit /b 1
)

if not exist "auto_receive.py" (
    echo ERROR: auto_receive.py was not found.
    exit /b 1
)

".venv\Scripts\pyinstaller.exe" --noconfirm --clean auto_receive.spec
if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete:
echo   dist\auto_receive\auto_receive.exe
echo.
echo Copy the entire dist\auto_receive folder when distributing the app.
endlocal
