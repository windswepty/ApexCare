import os
import sys
import shutil
import ctypes
import subprocess
import winreg
import tempfile

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)

def install():
    if not is_admin():
        run_as_admin()
        sys.exit()
    
    install_dir = r"C:\Program Files\APEX CARE"
    
    try:
        if not os.path.exists(install_dir):
            os.makedirs(install_dir)
            
        # Get bundled exe paths
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        payload_exe = os.path.join(base_path, 'APEX_CARE.exe')
        uninstall_exe = os.path.join(base_path, 'Uninstall.exe')
        
        # Copy files
        if os.path.exists(payload_exe):
            shutil.copy2(payload_exe, os.path.join(install_dir, 'APEX_CARE.exe'))
        if os.path.exists(uninstall_exe):
            shutil.copy2(uninstall_exe, os.path.join(install_dir, 'Uninstall.exe'))
            
        # Create Desktop Shortcut
        desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
        shortcut_path = os.path.join(desktop, "APEX CARE MAX.lnk")
        
        vbs_script = f'''
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{install_dir}\\APEX_CARE.exe"
oLink.WorkingDirectory = "{install_dir}"
oLink.Description = "APEX CARE MAX"
oLink.Save
'''
        vbs_path = os.path.join(tempfile.gettempdir(), 'create_shortcut.vbs')
        with open(vbs_path, 'w', encoding='utf-8') as f:
            f.write(vbs_script)
        subprocess.run(['cscript', '//nologo', vbs_path], creationflags=0x08000000)
        os.remove(vbs_path)
        
        # Add to Programs and Features (Control Panel)
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\APEX_CARE"
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "APEX CARE MAX")
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{install_dir}\\Uninstall.exe"')
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f'"{install_dir}\\APEX_CARE.exe"')
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "APEX CARE")
        winreg.CloseKey(key)
        
        ctypes.windll.user32.MessageBoxW(0, "APEX CARE MAX 설치가 성공적으로 완료되었습니다!\n바탕화면의 아이콘을 실행해주세요.", "설치 완료", 0x40)
        
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(0, f"설치 중 오류가 발생했습니다:\n{str(e)}", "설치 오류", 0x10)

if __name__ == '__main__':
    install()
