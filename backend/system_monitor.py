"""
APEX CARE - System Monitor (Pure Python)
Uses psutil + ctypes only. Zero external process spawning.
"""
import psutil
import platform
import os
import ctypes
import ctypes.wintypes
import time
import threading
import subprocess
import logging
import gc
log = logging.getLogger('SystemMonitor')

# Cache CPU model info once at import time (WMI is heavy, only call once)
_cpu_model_cache = None

# CPU, GPU, and RAM Cache
_cpu_usage = 0
_gpu_usage = 0
_standby_gb = 0

def _cpu_poller():
    global _cpu_usage
    while True:
        try:
            _cpu_usage = psutil.cpu_percent(interval=1)
        except Exception as e:
            log.debug(f"CPU poller error: {e}")
            _cpu_usage = 0
            
        gc.collect()

# Start CPU poller
_cpu_thread = threading.Thread(target=_cpu_poller, daemon=True)
_cpu_thread.start()

def _gpu_poller():
    global _gpu_usage
    try:
        import win32pdh
        hq = win32pdh.OpenQuery()
        hc = win32pdh.AddCounter(hq, '\\GPU Engine(*)\\Utilization Percentage')
        win32pdh.CollectQueryData(hq)
    except Exception as e:
        # GPU monitoring not available — exit thread silently
        log.debug(f"GPU pdh init error: {e}")
        _gpu_usage = 0
        return

    while True:
        try:
            time.sleep(1)
            win32pdh.CollectQueryData(hq)
            arr = win32pdh.GetFormattedCounterArray(hc, win32pdh.PDH_FMT_DOUBLE)
            usage = 0.0
            if isinstance(arr, dict):
                for k, v in arr.items():
                    if 'engtype_3D' in k:
                        usage += v
            _gpu_usage = round(usage)
        except Exception as e:
            log.debug(f"GPU poller error: {e}")
            _gpu_usage = 0
            time.sleep(1)
            
        gc.collect()

# Start GPU poller automatically
_gpu_thread = threading.Thread(target=_gpu_poller, daemon=True)
_gpu_thread.start()

def _get_cpu_model():
    """Get CPU brand string via registry."""
    global _cpu_model_cache
    if _cpu_model_cache is not None:
        return _cpu_model_cache
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        _cpu_model_cache = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        winreg.CloseKey(key)
    except Exception as e:
        log.debug(f"Failed to get CPU model: {e}")
        _cpu_model_cache = platform.processor() or "Unknown CPU"
    return _cpu_model_cache

_gpu_model_cache = None
def _get_gpu_model():
    global _gpu_model_cache
    if _gpu_model_cache is not None:
        return _gpu_model_cache
    try:
        import pythoncom
        pythoncom.CoInitialize()
        import win32com.client
        wmi = win32com.client.GetObject('winmgmts:')
        controllers = wmi.InstancesOf('Win32_VideoController')
        for c in controllers:
            _gpu_model_cache = c.Name
            break
        if not _gpu_model_cache:
            _gpu_model_cache = "Unknown GPU"
    except Exception as e:
        log.debug(f"Failed to get GPU model: {e}")
        _gpu_model_cache = "Unknown GPU"
    return _gpu_model_cache

def get_system_stats():
    """Get system stats using only psutil and WMI for GPU."""
    try:
        cpu_usage = _cpu_usage
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('C:\\')
        
        cpu_model = _get_cpu_model()
        cpu_cores = psutil.cpu_count(logical=False) or 0
        cpu_threads = psutil.cpu_count(logical=True) or 0
        
        # Standby memory estimation via psutil (available - free)
        standby_bytes = mem.available - mem.free
        standby_gb = round(max(standby_bytes, 0) / (1024**3), 1)
            
        return {
            'cpuModel': cpu_model,
            'cpuCores': cpu_cores,
            'cpuThreads': cpu_threads,
            'cpuUsage': round(cpu_usage),
            'ramUsedGB': round(mem.used / (1024**3), 1),
            'ramTotalGB': round(mem.total / (1024**3), 1),
            'ramPct': round(mem.percent),
            'ramStandbyGB': standby_gb,
            'diskUsedGB': round(disk.used / (1024**3)),
            'diskTotalGB': round(disk.total / (1024**3)),
            'diskPct': round(disk.percent),
            'gpuUsage': _gpu_usage,
            'gpuModel': _get_gpu_model(),
            'cpuTemp': 0, # Not easily available without admin + WMI classes or external tools
            'osInfo': f"{platform.system()} {platform.release()} ({platform.machine()})",
            'uptimeSec': int(time.time() - psutil.boot_time())
        }
    except Exception as e:
        print(f"[SystemMonitor] Error: {e}")
        return None


def get_processes():
    """Get top 8 processes by memory. Pure psutil, no external calls."""
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                mem_info = p.info.get('memory_info')
                if mem_info is None:
                    continue
                mem_mb = mem_info.rss / (1024 * 1024)
                if mem_mb > 10:  # Only show processes using > 10MB
                    raw_cpu = p.info.get('cpu_percent', 0) or 0
                    num_cores = psutil.cpu_count(logical=True) or 1
                    normalized_cpu = raw_cpu / num_cores
                    procs.append({
                        'id': p.info['pid'],
                        'pid': p.info['pid'],
                        'name': p.info['name'] or 'unknown',
                        'memoryMB': round(mem_mb),
                        'cpuPct': f"{normalized_cpu:.1f}%",
                        'priority': 'Normal',
                        'status': 'Running'
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        procs.sort(key=lambda x: x['memoryMB'], reverse=True)
        return procs[:8]
    except Exception as e:
        print(f"[SystemMonitor] Process list error: {e}")
        return []

def kill_process(pid):
    """Terminate a process by PID securely with Win32 API / taskkill fallback."""
    try:
        if pid == os.getpid():
            return {"success": False, "error": "APEX CARE 자체를 종료할 수 없습니다."}
        
        # Try psutil first
        try:
            p = psutil.Process(pid)
            p.kill()
            return {"success": True}
        except (psutil.AccessDenied, Exception):
            # Fallback 1: Win32 TerminateProcess via ctypes
            try:
                PROCESS_TERMINATE = 0x0001
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return {"success": True}
            except Exception as e:
                log.debug(f"Win32 terminate fallback failed: {e}")
            
            # Fallback 2: taskkill /F /PID
            try:
                res = subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True, text=True, creationflags=0x08000000)
                if res.returncode == 0:
                    return {"success": True}
                return {"success": False, "error": res.stderr.strip() or "프로세스를 종료할 권한이 없습니다."}
            except Exception as e:
                return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def set_process_priority(pid, priority):
    """Change process priority (Windows specific classes) with Win32 fallback."""
    try:
        pri_map = {
            'high': (psutil.HIGH_PRIORITY_CLASS, 0x0080),
            'low': (psutil.IDLE_PRIORITY_CLASS, 0x0040),
            'realtime': (psutil.REALTIME_PRIORITY_CLASS, 0x0100),
            'normal': (psutil.NORMAL_PRIORITY_CLASS, 0x0020)
        }
        target_psutil, target_win32 = pri_map.get(priority.lower(), (psutil.NORMAL_PRIORITY_CLASS, 0x0020))
        
        try:
            p = psutil.Process(pid)
            p.nice(target_psutil)
            return {"success": True}
        except psutil.AccessDenied:
            # Fallback: Win32 SetPriorityClass
            PROCESS_SET_INFORMATION = 0x0200
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
            if handle:
                res = ctypes.windll.kernel32.SetPriorityClass(handle, target_win32)
                ctypes.windll.kernel32.CloseHandle(handle)
                if res:
                    return {"success": True}
            return {"success": False, "error": "우선순위 변경 권한이 거부되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}

