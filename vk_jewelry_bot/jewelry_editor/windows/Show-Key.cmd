@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "imladris_public_key=%LOCALAPPDATA%\Imladris\owner_ed25519.pub"
if not exist "%imladris_public_key%" goto missing_key
start "" "%SystemRoot%\System32\notepad.exe" "%imladris_public_key%"
if errorlevel 1 goto open_failed
exit /b 0

:missing_key
echo.
echo Imladris: the public key was not found for this Windows account.
echo Open Install.cmd from the extracted Imladris folder first.
goto wait_before_exit

:open_failed
echo.
echo Imladris could not open Notepad.
echo Open this PUBLIC key file in Notepad and send its text to your specialist:
echo "%imladris_public_key%"

:wait_before_exit
echo.
pause
exit /b 1
