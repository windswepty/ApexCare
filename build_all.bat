@echo off
setlocal
rem Run from the folder this script lives in, whatever the caller's current directory is.
cd /d "%~dp0"

rem Every step is checked by its exit code AND by the file it must produce.
rem Old outputs are deleted first so a stale exe can never pass the check.
set "PAYLOAD_EXE=dist\APEX CARE Payload.exe"
set "UNINSTALLER_EXE=dist\APEX CARE Uninstaller.exe"
set "SETUP_EXE=dist\APEX CARE Setup 1.0.1.exe"

rem Remove the previous installer up front: after a failed run, no old installer is left to be shipped by mistake.
if exist "%SETUP_EXE%" del /q "%SETUP_EXE%"

echo =========================================
echo 1. Building React Frontend...
echo =========================================
if exist "dist_react\index.html" del /q "dist_react\index.html"
call npm run build
if errorlevel 1 (set "FAILED=React frontend (npm run build)" & goto :fail)
if not exist "dist_react\index.html" (set "FAILED=React frontend: dist_react\index.html was not created" & goto :fail)

echo.
echo =========================================
echo 2. Building Main Application (PyInstaller)...
echo =========================================
if exist "%PAYLOAD_EXE%" del /q "%PAYLOAD_EXE%"
pyinstaller --noconfirm "APEX CARE Payload.spec"
if errorlevel 1 (set "FAILED=Main application (APEX CARE Payload.spec)" & goto :fail)
if not exist "%PAYLOAD_EXE%" (set "FAILED=Main application: %PAYLOAD_EXE% was not created" & goto :fail)

echo.
echo =========================================
echo 3. Building Uninstaller (PyInstaller)...
echo =========================================
rem *.spec is in .gitignore, so a fresh clone or worktree may not have this file.
if not exist "APEX CARE Uninstaller.spec" (set "FAILED=Uninstaller: APEX CARE Uninstaller.spec not found (it is gitignored)" & goto :fail)
if exist "%UNINSTALLER_EXE%" del /q "%UNINSTALLER_EXE%"
pyinstaller --noconfirm "APEX CARE Uninstaller.spec"
if errorlevel 1 (set "FAILED=Uninstaller (APEX CARE Uninstaller.spec)" & goto :fail)
if not exist "%UNINSTALLER_EXE%" (set "FAILED=Uninstaller: %UNINSTALLER_EXE% was not created" & goto :fail)

echo.
echo =========================================
echo 4. Building Setup Wizard...
echo =========================================
call "%~dp0build_setup.bat"
if errorlevel 1 (set "FAILED=Setup wizard (build_setup.bat)" & goto :fail)
if not exist "%SETUP_EXE%" (set "FAILED=Setup wizard: %SETUP_EXE% was not created" & goto :fail)

echo.
echo =========================================
echo ALL BUILDS COMPLETED SUCCESSFULLY!
echo Final Setup File: %SETUP_EXE%
echo =========================================
exit /b 0

:fail
echo.
echo =========================================
echo [Error] BUILD FAILED: %FAILED%
echo No installer was produced. See the output above.
echo =========================================
exit /b 1
