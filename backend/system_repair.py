"""
APEX CARE - System Repair and Advanced Disk Ops
Runs long-running commands like SFC, DISM, Defrag, and Network optimization in hidden subprocesses with full logging and error handling.
"""
import subprocess
import threading
import logging

log = logging.getLogger('SystemRepair')
CREATE_NO_WINDOW = 0x08000000

def _run_hidden_cmd(cmd_list):
    """Run system command with shell=True and return detailed output."""
    try:
        cmd_str = " ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=120
        )
        if result.returncode == 0:
            return {"success": True, "message": "성공적으로 완료되었습니다.", "output": result.stdout}
        else:
            return {"success": False, "message": f"작업 실패 (코드: {result.returncode})", "error": result.stderr or result.stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# Background task state dictionaries
# ─────────────────────────────────────────────

_sfc_state = {"status": "idle", "output": "", "error": None}
_dism_state = {"status": "idle", "output": "", "error": None}
_trim_state = {"status": "idle", "output": "", "error": None}
_network_state = {"status": "idle", "message": "", "details": []}

def _run_hidden_cmd_bg(cmd_list, state_dict, timeout_sec=600):
    try:
        cmd_str = " ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list
        log.info(f"Starting background command: {cmd_str}")
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout_sec
        )
        state_dict["output"] = result.stdout
        if result.returncode == 0:
            state_dict["status"] = "success"
            log.info(f"✓ Command succeeded: {cmd_str}")
        else:
            state_dict["status"] = "error"
            state_dict["error"] = result.stderr or result.stdout
            log.warning(f"✗ Command failed (code {result.returncode}): {cmd_str} -> {state_dict['error']}")
    except Exception as e:
        state_dict["status"] = "error"
        state_dict["error"] = str(e)
        log.warning(f"⚠ Command exception: {cmd_str} -> {e}")

# ─────────────────────────────────────────────
# TRIM / Disk Optimization (async)
# ─────────────────────────────────────────────

def run_trim():
    """Run disk optimization and TRIM on ALL volumes asynchronously."""
    global _trim_state
    if _trim_state["status"] == "running":
        return {"success": False, "message": "이미 디스크 최적화가 실행 중입니다."}
    _trim_state["status"] = "running"
    _trim_state["error"] = None
    _trim_state["output"] = ""
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["defrag.exe", "/C", "/O"], _trim_state, 300), daemon=True)
    t.start()
    return {"success": True}

def get_trim_status():
    return _trim_state

# ─────────────────────────────────────────────
# SFC (async)
# ─────────────────────────────────────────────

def run_sfc():
    """Run System File Checker asynchronously."""
    global _sfc_state
    if _sfc_state["status"] == "running":
        return {"success": False, "message": "이미 SFC 무결성 검사가 실행 중입니다."}
    _sfc_state["status"] = "running"
    _sfc_state["error"] = None
    _sfc_state["output"] = ""
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["sfc.exe", "/scannow"], _sfc_state, 900), daemon=True)
    t.start()
    return {"success": True}

def get_sfc_status():
    return _sfc_state

# ─────────────────────────────────────────────
# DISM (async)
# ─────────────────────────────────────────────

def run_dism():
    """Run DISM RestoreHealth asynchronously."""
    global _dism_state
    if _dism_state["status"] == "running":
        return {"success": False, "message": "이미 DISM 복구 작업이 실행 중입니다."}
    _dism_state["status"] = "running"
    _dism_state["error"] = None
    _dism_state["output"] = ""
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["dism.exe", "/Online", "/Cleanup-image", "/Restorehealth"], _dism_state, 1200), daemon=True)
    t.start()
    return {"success": True}

def get_dism_status():
    return _dism_state

# ─────────────────────────────────────────────
# Network Optimization (async + sync)
# ─────────────────────────────────────────────

def _run_network_optimization_internal():
    """The actual network optimization logic."""
    global _network_state
    try:
        results = []
        
        # 1. Flush DNS cache
        r1 = _run_hidden_cmd(["ipconfig", "/flushdns"])
        results.append(("DNS Flush", r1.get("success", False)))
        
        # 2. Reset Winsock catalog
        r2 = _run_hidden_cmd(["netsh", "winsock", "reset"])
        results.append(("Winsock Reset", r2.get("success", False)))
        
        # 3. Disable TCP auto-tuning (reduces bufferbloat for gaming)
        r3 = _run_hidden_cmd(["netsh", "int", "tcp", "set", "global", "autotuninglevel=disabled"])
        results.append(("TCP AutoTuning Disabled", r3.get("success", False)))
        
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
        except Exception as e:
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
        _network_state["status"] = "success"
        _network_state["message"] = f"네트워크 최적화 완료 ({success_count}/{len(results)}개 항목 적용)"
        _network_state["details"] = results
        return {
            "success": True, 
            "message": _network_state["message"],
            "details": results
        }
    except Exception as e:
        _network_state["status"] = "error"
        _network_state["message"] = str(e)
        return {"success": False, "error": str(e)}

def run_network_optimization_sync():
    """Synchronous network optimization. Used internally by deep optimization."""
    return _run_network_optimization_internal()

def _run_network_bg():
    """Background thread wrapper for network optimization."""
    global _network_state
    _network_state["status"] = "running"
    _run_network_optimization_internal()

def optimize_network():
    """Comprehensive network optimization (async)."""
    global _network_state
    if _network_state["status"] == "running":
        return {"success": False, "message": "이미 네트워크 최적화가 실행 중입니다."}
    _network_state["status"] = "running"
    t = threading.Thread(target=_run_network_bg, daemon=True)
    t.start()
    return {"success": True}

def get_network_status():
    return _network_state
