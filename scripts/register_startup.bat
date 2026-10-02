@echo off
chcp 65001 >nul
echo ========================================================
echo   Sabadarmon PACS - Windows Avtomatik Yuklash Sozlamasi
echo ========================================================
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SabadarmonPACS" /t REG_SZ /d "\"D:\PACS\PACS_System.exe\" --background" /f
echo.
echo [OK] Sabadarmon PACS Windows avtomatik yuklanishiga qo'shildi!
echo Kompyuter yoqilganda dastur orqa fonda jimgina ishga tushadi,
echo kompyuter o'chganda esa o'zi avtomatik to'xtaydi.
echo.
pause
