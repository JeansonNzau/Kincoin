@echo off
rem Efface les chaines enregistrees pour repartir du bloc genese.
cd /d "%~dp0"
echo Fermez d'abord les 3 fenetres des noeuds.
pause
if exist "%LOCALAPPDATA%\KinCoin" rmdir /s /q "%LOCALAPPDATA%\KinCoin"
echo Donnees effacees. Relancez lancer.bat
pause
