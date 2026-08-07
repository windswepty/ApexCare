"""
APEX CARE - System Monitor (Pure Python)
Uses psutil + ctypes only. Zero external process spawning.
"""
import psutil
import platform
import os
import ctypes
import ctypes.wintypes
import ctypes.wintypes
import time
import threading

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
        except Exception:
            _cpu_usage = 0

# Start CPU poller
_cpu_thread = threading.Thread(target=_cpu_poller, daemon=True)
_cpu_thread.start()

def _gpu_poller():
    global _gpu_usage
    global _standby_gb
    try:
        import pythoncom
        pythoncom.CoInitialize()
        import win32com.client
        wmi = win32com.client.GetObject('winmgmts:')
    except Exception as e:
        with open("wmi_error.txt", "a") as f:
            f.write(f"WMI Init Error: {e}\n")
        return
        
    while True:
        try:
            # Removed heavy GPU utilization WMI query that caused CPU spikes (2.6s query time).
            _gpu_usage = 0
            
            # Query Standby Memory
            try:
                mem_perf = wmi.InstancesOf('Win32_PerfFormattedData_PerfOS_Memory')
                if mem_perf:
                    p = mem_perf[0]
                    normal = int(getattr(p, 'StandbyCacheNormalPriorityBytes', 0))
                    core = int(getattr(p, 'StandbyCacheCoreBytes', 0))
                    reserve = int(getattr(p, 'StandbyCacheReserveBytes', 0))
                    _standby_gb = round((normal + core + reserve) / (1024**3), 1)
            except Exception:
                pass
                
        except Exception:
            _gpu_usage = 0
        time.sleep(1)

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
    except Exception:
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
    except Exception:
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
        
        # Standby memory estimation via WMI Poller
        standby_gb = _standby_gb
            
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
