@echo off
rem ============================================================
rem  ZZBox - run from source (no packaging needed)
rem  Keep this file pure ASCII and CRLF only. cmd.exe parses
rem  .bat with the OEM code page (GBK on zh-CN); any non-ASCII
rem  byte corrupts line boundaries and the whole script breaks.
rem ============================================================
setlocal
pushd "%~dp0"

rem pythonw.exe = no console window. Switch to python.exe to see errors.
set "PY=C:\Python315\pythonw.exe"
if not exist "%PY%" goto nopy

"%PY%" main.py %*
popd
endlocal
goto :eof

:nopy
echo.
echo   [ERROR] Python not found: %PY%
echo   Open this .bat and change the PY line to your python.exe path.
echo.
pause
popd
endlocal
