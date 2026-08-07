@echo off
echo =========================================
echo APEX CARE Setup Wizard Build Script
echo =========================================

echo [1/2] Cleaning up previous build files...
if exist "build\APEX CARE Setup 1.0.3" rmdir /s /q "build\APEX CARE Setup 1.0.3"
if exist "dist\APEX CARE Setup 1.0.3.exe" del /q "dist\APEX CARE Setup 1.0.3.exe"

echo [2/2] Building Setup Wizard with PyInstaller...
pyinstaller --noconfirm --onefile --windowed --icon="public\setup_icon.ico" --add-data "dist/APEX CARE Payload.exe;." --add-data "dist/APEX CARE Uninstaller.exe;." --add-data "public/eula.txt;." --add-data "public/setup_icon.ico;." --name "APEX CARE Setup 1.0.3" tools/setup_wizard.py

if %errorlevel% neq 0 (
    echo [Error] Build failed!
    exit /b %errorlevel%
)

echo.
echo Cleaning up intermediate payload files from dist folder...
del /q "dist\APEX CARE Payload.exe"
del /q "dist\APEX CARE Uninstaller.exe"

echo.
echo =========================================
echo Build complete!
echo Output: dist\APEX CARE Setup 1.0.3.exe
echo =========================================
