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

# Cache CPU model info once at import time (WMI is heavy, only call once)
_cpu_model_cache = None

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
    except Exception:
        _cpu_model_cache = platform.processor() or "Unknown CPU"
    return _cpu_model_cache


def get_system_stats():
    """Get system stats using only psutil."""
    try:
        cpu_usage = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('C:\\')
        
        cpu_model = _get_cpu_model()
        cpu_cores = psutil.cpu_count(logical=False) or 0
        cpu_threads = psutil.cpu_count(logical=True) or 0
        
        # Standby memory estimation
        standby_gb = 0
        if hasattr(mem, 'free'):
            standby_gb = round((mem.total - mem.used - mem.free) / (1024**3), 1)
            
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
            'cpuTemp': 0,
            'osInfo': f"{platform.system()} {platform.release()} ({platform.machine()})",
            'uptimeSec': round(time.time() - psutil.boot_time())
        }
    except Exception as e:
        with open("error_log.txt", "a") as f:
            f.write(f"[SystemMonitor] Error: {e}\n")
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
                    procs.append({
                        'id': p.info['pid'],
                        'pid': p.info['pid'],
                        'name': p.info['name'] or 'unknown',
                        'memoryMB': round(mem_mb),
                        'cpuPct': f"{p.info.get('cpu_percent', 0) or 0:.1f}%",
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
    """Terminate a process by PID securely."""
    try:
        if pid == os.getpid():
            return {"success": False, "error": "APEX CARE 자체를 종료할 수 없습니다."}
        p = psutil.Process(pid)
        p.terminate()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def set_process_priority(pid, priority):
    """Change process priority (Windows specific classes)."""
    try:
        p = psutil.Process(pid)
        pri = priority.lower()
        if pri == 'high':
            p.nice(psutil.HIGH_PRIORITY_CLASS)
        elif pri == 'low':
            p.nice(psutil.IDLE_PRIORITY_CLASS)
        elif pri == 'realtime':
            p.nice(psutil.REALTIME_PRIORITY_CLASS)
        else:
            p.nice(psutil.NORMAL_PRIORITY_CLASS)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
