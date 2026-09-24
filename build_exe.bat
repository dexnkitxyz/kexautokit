@echo off
setlocal
chcp 65001 >nul

echo ============================================
echo Building kexauto.exe
echo ============================================

set "PYINSTALLER=.venv-1\Scripts\pyinstaller.exe"
if not exist "%PYINSTALLER%" (
    set "PYINSTALLER=.venv\Scripts\pyinstaller.exe"
)

if not exist "%PYINSTALLER%" (
    where pyinstaller >nul 2>&1
    if not errorlevel 1 set "PYINSTALLER=pyinstaller"
)

if "%PYINSTALLER%"=="pyinstaller" (
    echo Using PyInstaller from PATH
) else if not exist "%PYINSTALLER%" (
    echo ERROR: PyInstaller was not found.
    echo Run setup_and_run.bat first or install it with:
    echo   python -m pip install -r requirements.txt
    exit /b 1
)

if not exist "auto_receive.py" (
    echo ERROR: auto_receive.py was not found.
    exit /b 1
)

"%PYINSTALLER%" --noconfirm --clean --distpath dist_release --workpath build_release auto_receive.spec
if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete:
echo   dist_release\kexauto.exe
echo.
echo Copy dist_release\kexauto.exe when distributing the app.
endlocal
