@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "imladris_start=%LOCALAPPDATA%\Imladris\Start.ps1"
set "imladris_powershell=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%imladris_start%" goto missing_installation
if not exist "%imladris_powershell%" goto missing_powershell
start "" "%imladris_powershell%" -NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "%imladris_start%"
if errorlevel 1 goto launch_failed
exit /b 0

:missing_installation
echo.
echo Imladris is not installed for this Windows account.
echo Extract the whole ZIP archive, then open Install.cmd from the extracted folder.
goto wait_before_exit

:missing_powershell
echo.
echo Imladris: Windows PowerShell was not found.
echo This launcher requires Windows 10 or Windows 11 with Windows PowerShell 5.1.
goto wait_before_exit

:launch_failed
echo.
echo Imladris could not start. Keep this window open and send a screenshot.

:wait_before_exit
echo.
pause
exit /b 1
