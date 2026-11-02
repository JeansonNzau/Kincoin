@echo off
rem Lance UN noeud. Usage : noeud.bat 1   (ou 2, ou 3)
cd /d "%~dp0"
set "N=%~1"
if "%N%"=="" set "N=1"
set "NODE_NAME=noeud-%N%"
rem Donnees dans AppData (le dossier Documents peut etre protege par Windows)
set "DATA_DIR=%LOCALAPPDATA%\KinCoin\%N%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
set "PUBLIC_URL=http://127.0.0.1:800%N%"
set "FRONTEND_DIR=frontend"
set "MINING=1"
if "%N%"=="1" set "PEERS=http://127.0.0.1:8002,http://127.0.0.1:8003"
if "%N%"=="2" set "PEERS=http://127.0.0.1:8001,http://127.0.0.1:8003"
if "%N%"=="3" set "PEERS=http://127.0.0.1:8001,http://127.0.0.1:8002"
if "%N%"=="3" set "MINING=0"
echo Donnees : %DATA_DIR%
echo Noeud %N% sur http://127.0.0.1:800%N%/app/   (fermez cette fenetre pour l'arreter)
echo Autres PC : http://ADRESSE-IP-DE-CE-PC:800%N%/app/   (adresse IP : commande ipconfig)
rem 0.0.0.0 = accepte aussi les connexions des autres PC du meme reseau
python -m uvicorn kincoin.node:app --host 0.0.0.0 --port 800%N%
