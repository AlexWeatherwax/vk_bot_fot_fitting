@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "imladris_bundle=%~dp0"
for %%F in (Install.ps1 Common.ps1 Start.ps1 Launch.cmd Show-Key.cmd) do (
    if not exist "%imladris_bundle%%%F" goto missing_files
)
set "imladris_powershell=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%imladris_powershell%" goto missing_powershell

"%imladris_powershell%" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%imladris_bundle%Install.ps1"
set "imladris_exit=%ERRORLEVEL%"
if not "%imladris_exit%"=="0" goto installation_failed
exit /b 0

:missing_files
echo.
echo Imladris: installation files are missing.
echo Right-click the ZIP archive, choose "Extract All", then open Install.cmd
echo from the extracted Imladris folder. Do not run it inside the ZIP archive.
echo Keep all files from the extracted bundle in the same folder.
set "imladris_exit=1"
goto wait_before_exit

:missing_powershell
echo.
echo Imladris: Windows PowerShell was not found.
echo This installer requires Windows 10 or Windows 11 with Windows PowerShell 5.1.
set "imladris_exit=1"
goto wait_before_exit

:installation_failed
echo.
echo Imladris installation failed. Exit code: %imladris_exit%
echo Keep this window open and send a screenshot of the error shown above.

:wait_before_exit
echo.
pause
exit /b %imladris_exit%
