@echo off
rem  Launch one GUI in its OWN window and its OWN process tree.
rem  Closing this launcher - or any other window - will NOT kill it.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PYCMD="
if exist "%~dp0_python\python.exe" set "PYCMD="%~dp0_python\python.exe""
if not defined PYCMD if exist "%~dp0python_path.txt" (
  set /p PYFROMFILE=<"%~dp0python_path.txt"
  if exist "!PYFROMFILE!" set "PYCMD="!PYFROMFILE!""
)
if not defined PYCMD (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
  echo  [ERROR] No Python found on this computer.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0_launch_gui.py" (
  echo  [ERROR] _launch_gui.py is missing from this folder.
  echo.
  pause
  exit /b 1
)

rem  `start` puts the GUI in a NEW window with its own process tree,
rem  so nothing here is attached to this console any more.
start "Strava-ADS" !PYCMD! "%~dp0_launch_gui.py" ads

echo  The GUI is opening in its own window:  Strava-ADS
echo  You may close THIS window now - it will not affect the GUI.
echo.
echo  To STOP collecting, use the STOP button in the GUI - never
echo  close the console window while a task is running.
timeout /t 6 >nul
endlocal
