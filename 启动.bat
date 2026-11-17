@echo off
rem ============================================================
rem  ZZBox launcher
rem  Keep this file pure ASCII and CRLF only. cmd.exe parses
rem  .bat with the OEM code page (GBK on zh-CN); any non-ASCII
rem  byte corrupts line boundaries and the whole script breaks.
rem  Order: ZZBox.exe next to this file first, then a versioned
rem  sub-folder (the older package layout).
rem ============================================================
setlocal enabledelayedexpansion
pushd "%~dp0"

if exist "%~dp0ZZBox.exe" (
    start "" "%~dp0ZZBox.exe"
    goto end
)

set "TARGET="
for /f "delims=" %%D in ('dir /b /ad /o-n "ZZBox*" 2^>nul') do (
    if not defined TARGET if exist "%%~fD\ZZBox.exe" set "TARGET=%%~fD\ZZBox.exe"
)

if defined TARGET (
    start "" "%TARGET%"
    goto end
)
goto missing

:missing
echo.
echo   [ERROR] ZZBox.exe not found next to this file.
echo   Put this .bat beside ZZBox.exe, or in a folder that
echo   contains a "ZZBox vX.Y.Z" sub-folder with ZZBox.exe.
echo.
pause

:end
popd
endlocal
