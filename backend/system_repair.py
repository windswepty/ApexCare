"""
APEX CARE - System Repair and Advanced Disk Ops
Runs long-running commands like SFC, DISM, and Defrag in hidden subprocesses.
"""
import subprocess

def _run_hidden_cmd(cmd):
    try:
        # CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000, text=True)
        if result.returncode == 0:
            return {"success": True, "message": "성공적으로 완료되었습니다.", "output": result.stdout}
        else:
            return {"success": False, "message": f"작업 실패 (코드: {result.returncode})", "error": result.stderr}
    except Exception as e:
        return {"success": False, "error": str(e)}

import threading

_sfc_state = {"status": "idle"}
_dism_state = {"status": "idle"}

def _run_hidden_cmd_bg(cmd, state_dict):
    try:
        # CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000, text=True)
        if result.returncode == 0:
            state_dict["status"] = "success"
        else:
            state_dict["status"] = "error"
    except Exception:
        state_dict["status"] = "error"

def run_trim():
    """Run disk optimization and TRIM on ALL volumes."""
    # /C means all volumes, /O means optimize (including TRIM for SSDs)
    return _run_hidden_cmd(["defrag.exe", "/C", "/O"])

def run_sfc():
    """Run System File Checker asynchronously."""
    global _sfc_state
    if _sfc_state["status"] == "running":
        return {"success": False, "message": "이미 실행 중입니다."}
    _sfc_state["status"] = "running"
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["sfc.exe", "/scannow"], _sfc_state), daemon=True)
    t.start()
    return {"success": True}

def get_sfc_status():
    return _sfc_state

def run_dism():
    """Run DISM RestoreHealth asynchronously."""
    global _dism_state
    if _dism_state["status"] == "running":
        return {"success": False, "message": "이미 실행 중입니다."}
    _dism_state["status"] = "running"
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["dism.exe", "/Online", "/Cleanup-image", "/Restorehealth"], _dism_state), daemon=True)
    t.start()
    return {"success": True}

def get_dism_status():
    return _dism_state

def optimize_network():
    """Comprehensive network optimization: DNS flush, Winsock reset, Nagle disable, TCP tuning."""
    results = []
    
    # 1. Flush DNS cache
    r1 = _run_hidden_cmd(["ipconfig", "/flushdns"])
    results.append(("DNS Flush", r1.get("success", False)))
    
    # 2. Reset Winsock catalog
    r2 = _run_hidden_cmd(["netsh", "winsock", "reset"])
    results.append(("Winsock Reset", r2.get("success", False)))
    
    # 3. Disable TCP auto-tuning (reduces bufferbloat for gaming)
    _run_hidden_cmd(["netsh", "int", "tcp", "set", "global", "autotuninglevel=disabled"])
    results.append(("TCP AutoTuning Disabled", True))
    
    # 4. Disable Nagle algorithm on all interfaces via registry
    try:
        import winreg
        base_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
        base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path, 0, winreg.KEY_READ)
        
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base_key, i)
                subkey_path = f"{base_path}\\{subkey_name}"
                subkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.SetValueEx(subkey, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(subkey, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(subkey)
                i += 1
            except OSError:
                break
        winreg.CloseKey(base_key)
        results.append(("Nagle Disabled", True))
    except Exception:
        results.append(("Nagle Disabled", False))
    
    # 5. Disable Network Throttling Index
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
            0, winreg.KEY_ALL_ACCESS
        )
        winreg.SetValueEx(key, "NetworkThrottlingIndex", 0, winreg.REG_DWORD, 0xFFFFFFFF)
        winreg.CloseKey(key)
        results.append(("Network Throttling Disabled", True))
    except Exception:
        results.append(("Network Throttling Disabled", False))
    
    success_count = sum(1 for _, s in results if s)
    return {
        "success": True, 
        "message": f"네트워크 최적화 완료 ({success_count}/{len(results)}개 항목 적용)",
        "details": results
    }

