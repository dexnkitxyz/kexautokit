@echo off
setlocal
chcp 65001 >nul
REM ติดตั้ง dependency และรันจากโฟลเดอร์โปรเจกต์

echo.
echo ============================================
echo ติดตั้งไลบรารี Python...
echo ============================================
echo.

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: ไม่พบ Python หรือไม่สามารถเรียก pip ได้
    pause
    exit /b 1
)

"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: ติดตั้งไลบรารีไม่สำเร็จ
    pause
    exit /b 1
)

echo.
echo ============================================
echo ติดตั้งเสร็จ กำลังรันโปรแกรม...
echo ============================================
echo.

"%PYTHON%" auto_receive.py

pause
endlocal
