@echo off
echo =========================================
echo 1. Building React Frontend...
echo =========================================
call npm run build

echo.
echo =========================================
echo 2. Building Main Application (PyInstaller)...
echo =========================================
pyinstaller --noconfirm "APEX CARE Payload.spec"

if %errorlevel% neq 0 (
    echo [Error] Main App Build failed!
    exit /b %errorlevel%
)

echo.
echo =========================================
echo 3. Building Uninstaller (PyInstaller)...
echo =========================================
pyinstaller --noconfirm "APEX CARE Uninstaller.spec"

echo.
echo =========================================
echo 4. Building Setup Wizard...
echo =========================================
call build_setup.bat

echo.
echo =========================================
echo ALL BUILDS COMPLETED SUCCESSFULLY!
echo Final Setup File: dist\APEX CARE Setup 1.0.1.exe
echo =========================================
