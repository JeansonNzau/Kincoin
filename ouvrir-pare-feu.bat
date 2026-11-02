@echo off
rem Autorise les autres PC du reseau a joindre les noeuds KinCoin (ports 8001 a 8003).
rem A lancer UNE fois : clic droit > Executer en tant qu'administrateur.
net session >nul 2>&1
if errorlevel 1 (
  echo Ce script doit etre lance en administrateur :
  echo clic droit sur ouvrir-pare-feu.bat ^> Executer en tant qu'administrateur.
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="KinCoin" >nul 2>&1
netsh advfirewall firewall add rule name="KinCoin" dir=in action=allow protocol=TCP localport=8001-8003 profile=any
echo.
echo Pare-feu ouvert pour les ports 8001 a 8003.
echo Votre adresse IP sur le reseau :
ipconfig | findstr /C:"IPv4"
pause
