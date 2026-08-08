import os
import winreg
import subprocess
import shutil

def get_installed_apps():
    """Retrieve installed applications from the Windows Registry."""
    apps = []
    seen = set()
    
    registry_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
    ]
    
    app_id = 0
    for hkey, path in registry_paths:
        try:
            key = winreg.OpenKey(hkey, path)
            num_subkeys = winreg.QueryInfoKey(key)[0]
            for i in range(num_subkeys):
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    
                    try:
                        # Helper to clean registry strings of null characters
                        def _clean(s):
                            if isinstance(s, str): return s.replace('\x00', '').strip()
                            return s
                            
                        display_name = _clean(winreg.QueryValueEx(subkey, "DisplayName")[0])
                        if not display_name or display_name in seen:
                            continue
                        
                        try:
                            uninstall_string = _clean(winreg.QueryValueEx(subkey, "UninstallString")[0])
                        except FileNotFoundError:
                            continue
                            
                        publisher = ""
                        try: publisher = _clean(winreg.QueryValueEx(subkey, "Publisher")[0])
                        except: pass
                        
                        install_date = ""
                        try: install_date = _clean(winreg.QueryValueEx(subkey, "InstallDate")[0])
                        except: pass
                        
                        estimated_size = 0
                        try: estimated_size = winreg.QueryValueEx(subkey, "EstimatedSize")[0] # KB
                        except: pass
                        
                        seen.add(display_name)
                        app_id += 1
                        
                        apps.append({
                            "id": str(app_id),
                            "name": display_name,
                            "publisher": publisher,
                            "installDate": install_date,
                            "sizeMB": round(estimated_size / 1024) if estimated_size else 0,
                            "uninstallString": uninstall_string
                        })
                    except FileNotFoundError:
                        pass
                    except Exception as e:
                        log.debug(f"Failed to read subkey info: {e}")
                    finally:
                        winreg.CloseKey(subkey)
            winreg.CloseKey(key)
        except Exception as e:
            log.warning(f"Failed to read registry key {path}: {e}")
            
    # Sort alphabetically
    apps.sort(key=lambda x: x["name"].lower())
    return apps

def run_uninstall(uninstall_string):
    """Execute the uninstaller string."""
    try:
        # Many uninstall strings contain quotes or arguments
        # If it's MSIExec, we can format it
        if "msiexec" in uninstall_string.lower() and "/I" in uninstall_string.upper():
            uninstall_string = uninstall_string.replace("/I", "/X").replace("/i", "/x")
            
        # We launch it asynchronously or wait, but uninstalls usually require UI.
        # So we just launch it.
        subprocess.Popen(uninstall_string, shell=True)
        return {"success": True, "message": "언인스톨러가 실행되었습니다. 화면의 지시를 따라 삭제를 완료해주세요."}
    except Exception as e:
        return {"success": False, "error": str(e)}

def find_leftovers(app_name):
    """Find leftover folders in AppData and ProgramFiles based on app name."""
    leftovers = []
    
    if not app_name or len(app_name) < 3:
        return leftovers
        
    search_dirs = [
        os.environ.get('APPDATA', ''),
        os.environ.get('LOCALAPPDATA', ''),
        os.environ.get('ProgramFiles', ''),
        os.environ.get('ProgramFiles(x86)', ''),
        os.environ.get('ProgramData', '')
    ]
    
    # Filter common generic names to prevent accidental system wipes
    forbidden = ["microsoft", "windows", "google", "intel", "amd", "nvidia"]
    if app_name.lower() in forbidden:
        return leftovers
        
    # Simplify app name for searching
    search_term = app_name.split()[0].lower()
    
    for base_dir in search_dirs:
        if not base_dir or not os.path.exists(base_dir): continue
        try:
            for item in os.listdir(base_dir):
                if search_term in item.lower():
                    full_path = os.path.join(base_dir, item)
                    if os.path.isdir(full_path):
                        # Calculate size
                        size = 0
                        try:
                            for dirpath, _, filenames in os.walk(full_path):
                                for f in filenames:
                                    fp = os.path.join(dirpath, f)
                                    if not os.path.islink(fp):
                                        size += os.path.getsize(fp)
                        except Exception as e:
                            log.debug(f"Error calculating size for {full_path}: {e}")
                        leftovers.append({
                            "path": full_path,
                            "sizeMB": round(size / (1024*1024), 2)
                        })
        except Exception as e:
            log.warning(f"Error searching base dir {base_dir}: {e}")
            
    return leftovers

def clean_leftovers(paths):
    """Delete leftover folders safely with strict boundary protection."""
    deleted_mb = 0
    failed = 0
    
    # Allowed root directories for leftover deletion
    allowed_roots = [
        os.environ.get('APPDATA', '').lower(),
        os.environ.get('LOCALAPPDATA', '').lower(),
        os.environ.get('ProgramFiles', '').lower(),
        os.environ.get('ProgramFiles(x86)', '').lower(),
        os.environ.get('ProgramData', '').lower()
    ]
    allowed_roots = [r for r in allowed_roots if r]
    
    for p in paths:
        if not os.path.exists(p) or not os.path.isdir(p):
            failed += 1
            continue
            
        p_lower = p.lower()
        
        # Security Guard 1: Must be inside one of the allowed roots
        if not any(p_lower.startswith(r) for r in allowed_roots):
            failed += 1
            continue
            
        # Security Guard 2: Must not BE the root itself
        if p_lower in allowed_roots or len(p_lower) <= 15:
            failed += 1
            continue
            
        # Security Guard 3: Prevent deleting critical subfolders
        forbidden_subfolders = ["\\microsoft", "\\windows", "\\google", "\\intel", "\\amd", "\\nvidia"]
        if any(f in p_lower for f in forbidden_subfolders):
            failed += 1
            continue
            
        try:
            # Calculate size before deletion
            size = sum(os.path.getsize(os.path.join(dirpath, f)) for dirpath, _, fns in os.walk(p) for f in fns)
            shutil.rmtree(p, ignore_errors=True)
            if not os.path.exists(p):
                deleted_mb += (size / (1024*1024))
            else:
                failed += 1
        except Exception as e:
            log.warning(f"Error removing leftover {p}: {e}")
            failed += 1
                
    return {"success": True, "freedMB": round(deleted_mb, 2), "failed": failed}
