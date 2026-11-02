@echo off
rem Installe les bibliotheques de KinCoin puis lance les tests.
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo Python est introuvable. Installez Python 3.11 ou plus depuis python.org
  echo en cochant la case "Add python.exe to PATH", puis relancez ce fichier.
  pause
  exit /b 1
)
echo Installation des bibliotheques...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo L'installation a echoue. Verifiez votre connexion Internet et relancez.
  pause
  exit /b 1
)
echo.
echo Lancement des tests...
python -m unittest discover -s tests
echo.
echo Installation terminee. Double-cliquez maintenant sur lancer.bat
pause
