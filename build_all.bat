@echo off
echo =========================================
echo 1. Building React Frontend...
echo =========================================
call npm run build

echo.
echo =========================================
echo 2. Building Main Application (PyInstaller)...
echo =========================================
pyinstaller --noconfirm --onefile --windowed --uac-admin --icon="public\icon.ico" --add-data "dist_react;dist_react" --name "APEX CARE Payload" main.py

if %errorlevel% neq 0 (
    echo [Error] Main App Build failed!
    exit /b %errorlevel%
)

echo.
echo =========================================
echo 3. Building Uninstaller (PyInstaller)...
echo =========================================
pyinstaller --noconfirm --onefile --windowed --uac-admin --icon="public\setup_icon.ico" --name "APEX CARE Uninstaller" tools\uninstall.py

echo.
echo =========================================
echo 4. Building Setup Wizard...
echo =========================================
call build_setup.bat

echo.
echo =========================================
echo ALL BUILDS COMPLETED SUCCESSFULLY!
echo Final Setup File: dist\APEX CARE Setup 1.0.3.exe
echo =========================================
