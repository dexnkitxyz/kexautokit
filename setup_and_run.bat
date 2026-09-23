@echo off
chcp 65001 >nul
REM รันจากโฟลเดอร์ Project

echo.
echo ============================================
echo ติดตั้งไลบรารี Python...
echo ============================================
echo.

.venv\Scripts\python.exe -m pip install pdf2image pyzbar pillow pyautogui pygetwindow pyperclip pytesseract

echo.
echo ============================================
echo ติดตั้งเสร็จ กำลังรันโปรแกรม...
echo ============================================
echo.

.venv\Scripts\python.exe auto_receive.py

pause
