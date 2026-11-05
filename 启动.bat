@echo off
rem ============================================================
rem  ZZBox launcher
rem  Keep this file pure ASCII and CRLF only. cmd.exe parses
rem  .bat with the OEM code page (GBK on zh-CN); any non-ASCII
rem  byte corrupts line boundaries and the whole script breaks.
rem  The build folder name is looked up at run time on purpose.
rem ============================================================
setlocal enabledelayedexpansion
pushd "%~dp0"

set "TARGET="
for /f "delims=" %%D in ('dir /b /ad /o-n "ZZBox*" 2^>nul') do (
    if not defined TARGET if exist "%%~fD\ZZBox.exe" set "TARGET=%%~fD\ZZBox.exe"
)

if defined TARGET goto runexe
goto missing

:runexe
start "" "%TARGET%"
goto end

:missing
echo.
echo   [ERROR] ZZBox.exe not found.
echo   Expected a sub-folder like "ZZBox v0.6.1" that contains ZZBox.exe.
echo.
pause

:end
popd
endlocal
