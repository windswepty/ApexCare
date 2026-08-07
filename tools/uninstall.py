import os
import sys
import shutil
from PyQt6.QtWidgets import QApplication, QMessageBox
import win32com.client

def main():
    app = QApplication(sys.argv)
    
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Warning)
    msg_box.setWindowTitle("APEX CARE 삭제")
    msg_box.setText("APEX CARE 프로그램을 완전히 삭제하시겠습니까?")
    msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    
    if msg_box.exec() == QMessageBox.StandardButton.Yes:
        install_dir = os.path.dirname(os.path.abspath(sys.executable))
        
        # STRICT SAFETY CHECK: Only delete if running EXACTLY from LOCALAPPDATA\APEX CARE
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        expected_dir = os.path.join(local_app_data, "APEX CARE")
        
        if os.path.normcase(install_dir) != os.path.normcase(expected_dir):
            msg_err = QMessageBox()
            msg_err.setIcon(QMessageBox.Icon.Critical)
            msg_err.setWindowTitle("제거 오류")
            msg_err.setText(f"정상적인 설치 경로가 아닙니다.\n이 프로그램은 실제 설치된 위치(AppData)에서만 실행 가능합니다.\n현재 경로: {install_dir}")
            msg_err.exec()
            sys.exit(1)
            
        bat_path = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "uninstall_apex.bat")
        
        with open(bat_path, "w", encoding="euc-kr") as f:
            f.write('@echo off\n')
            f.write('timeout /t 2 /nobreak > NUL\n') # wait for uninstaller to exit
            
            # 1. Kill APEX CARE if running
            f.write('taskkill /f /im "APEX CARE.exe" > NUL 2>&1\n')
            f.write('taskkill /f /im "APEX CARE 3.8.1.exe" > NUL 2>&1\n')
            
            # 2. Delete installation directory
            f.write(f'rmdir /s /q "{install_dir}"\n')
            
            # 3. Delete Desktop shortcuts
            shell = win32com.client.Dispatch("WScript.Shell")
            desktop = shell.SpecialFolders("Desktop")
            f.write(f'del /q "{os.path.join(desktop, "APEX CARE.lnk")}" > NUL 2>&1\n')
            
            # Try OneDrive desktop just in case
            onedrive_desktop = os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "바탕 화면")
            if os.path.exists(onedrive_desktop):
                f.write(f'del /q "{os.path.join(onedrive_desktop, "APEX CARE.lnk")}" > NUL 2>&1\n')
                
            # 4. Delete Start Menu shortcut
            start_menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "APEX CARE")
            f.write(f'rmdir /s /q "{start_menu}" > NUL 2>&1\n')

            # 5. Delete Registry key
            f.write('reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\APEX CARE" /f > NUL 2>&1\n')
            
            # 6. Show completion message
            f.write('msg * APEX CARE가 성공적으로 제거되었습니다.\n')
            
            # 6. Delete self (the batch file)
            f.write('del "%~f0"\n')

        os.startfile(bat_path)
        sys.exit(0)

if __name__ == "__main__":
    main()
