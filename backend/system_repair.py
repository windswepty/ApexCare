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

def run_trim():
    """Run disk optimization and TRIM on ALL volumes."""
    # /C means all volumes, /O means optimize (including TRIM for SSDs)
    return _run_hidden_cmd(["defrag.exe", "/C", "/O"])

def run_sfc():
    """Run System File Checker."""
    return _run_hidden_cmd(["sfc.exe", "/scannow"])

def run_dism():
    """Run DISM RestoreHealth."""
    return _run_hidden_cmd(["dism.exe", "/Online", "/Cleanup-image", "/Restorehealth"])

def optimize_network():
    """Flush DNS and reset Winsock for ultimate network ping."""
    _run_hidden_cmd(["ipconfig", "/flushdns"])
    _run_hidden_cmd(["netsh", "winsock", "reset"])
    return {"success": True, "message": "네트워크 DNS 및 Winsock 초기화 완료"}
