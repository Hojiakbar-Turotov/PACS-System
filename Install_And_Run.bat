@echo off
chcp 65001 >nul
echo ========================================================
echo   Sabadarmon MSKT PACS Tizimi - O'rnatish va Ishga Tushirish
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [OGOHLANTIRISH] Python topilmadi! Iltimos, Python 3.11 o'rnating va "Add python.exe to PATH" ni belgilang.
    pause
    exit /b 1
)

echo 1. Kutubxonalarni o'rnatish tekshirilmoqda...
python -m pip install -r "%~dp0requirements.txt" --quiet

echo.
echo 2. Windows avtomatik ishga tushirish sozlanmoqda...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SabadarmonPACS" /t REG_SZ /d "\"%~dp0PACS_System.exe\" --background" /f >nul

echo.
echo 3. PACS Server ishga tushirilmoqda...
start "" "%~dp0PACS_System.exe"

echo [OK] Tizim muvaffaqiyatli ishga tushirildi!
echo Brauzerda http://localhost:8000 manzili ochilmoqda.
timeout /t 3 >nul
