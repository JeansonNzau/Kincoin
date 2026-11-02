@echo off
rem Lance les 3 noeuds KinCoin dans 3 fenetres, puis ouvre le portefeuille.
cd /d "%~dp0"
start "KinCoin - noeud 1" cmd /k noeud.bat 1
timeout /t 3 /nobreak >nul
start "KinCoin - noeud 2" cmd /k noeud.bat 2
start "KinCoin - noeud 3" cmd /k noeud.bat 3
timeout /t 6 /nobreak >nul
start "" http://127.0.0.1:8001/app/
