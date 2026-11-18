@echo off
rem Crea PostIt.exe partendo dal sorgente (serve Python 3 per Windows).
rem Uso: doppio clic su questo file. L'exe compare nella cartella "dist".
cd /d "%~dp0"
py -m pip install --user --disable-pip-version-check -q pyinstaller || goto :errore
py -m PyInstaller --noconfirm --clean --onefile --windowed --name PostIt ^
   --icon postit.ico --add-data "postit.ico;." PostIt.pyw || goto :errore
echo.
echo Fatto! Trovi PostIt.exe in: %~dp0dist
pause
exit /b 0
:errore
echo.
echo Qualcosa e' andato storto: controlla di avere Python installato (python.org).
pause
exit /b 1
