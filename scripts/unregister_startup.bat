@echo off
chcp 65001 >nul
echo ========================================================
echo   Sabadarmon PACS - Windows Avtomatik Yuklashni O'chirish
echo ========================================================
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SabadarmonPACS" /f
echo.
echo [OK] Windows avtomatik yuklanishidan olib tashlandi.
echo.
pause
