@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto python_ready
set "PYTHON_EXE=python"
:python_ready
if /I "%~1"=="--check" goto check
"%PYTHON_EXE%" gui.py
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" exit /b 0
echo.
echo GUI failed. Please keep this error message for troubleshooting.
pause
exit /b %RESULT%
:check
"%PYTHON_EXE%" -c "import tkinter,numpy,mss,pyautogui,lcd_settings; import ast,pathlib; ast.parse(pathlib.Path('gui.py').read_text(encoding='utf-8')); print('Launcher and GUI dependencies OK')"
exit /b %ERRORLEVEL%
