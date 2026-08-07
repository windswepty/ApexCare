import os
import sys
import shutil
import ctypes
import subprocess
import winreg
import time

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)

def uninstall():
    if not is_admin():
        run_as_admin()
        sys.exit()
    
    install_dir = r"C:\Program Files\APEX CARE"
    
    try:
        # Ask for confirmation
        res = ctypes.windll.user32.MessageBoxW(0, "APEX CARE MAX를 정말로 제거하시겠습니까?", "제거 확인", 0x24) # MB_YESNO | MB_ICONQUESTION
        if res != 6: # IDYES
            sys.exit()
            
        # Kill process if running
        subprocess.run(['taskkill', '/F', '/IM', 'APEX_CARE.exe', '/T'], creationflags=0x08000000, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        time.sleep(1)
        
        # Remove Desktop Shortcut
        desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
        shortcut_path = os.path.join(desktop, "APEX CARE MAX.lnk")
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
            
        # Remove from Registry
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_ALL_ACCESS)
            winreg.DeleteKey(key, "APEX_CARE")
            winreg.CloseKey(key)
        except Exception:
            pass
            
        # We cannot delete the uninstaller while it's running.
        # Create a self-deleting batch script to remove the folder.
        bat_script = f'''@echo off
ping 127.0.0.1 -n 2 > nul
rmdir /S /Q "{install_dir}"
del "%~f0"
'''
        bat_path = os.path.join(os.environ["TEMP"], "uninstall_apex.bat")
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(bat_script)
            
        subprocess.Popen(['cmd.exe', '/c', bat_path], creationflags=0x08000000)
        
        ctypes.windll.user32.MessageBoxW(0, "제거가 완료되었습니다.", "제거 성공", 0x40)
        
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(0, f"제거 중 오류가 발생했습니다:\n{str(e)}", "제거 오류", 0x10)

if __name__ == '__main__':
    uninstall()
