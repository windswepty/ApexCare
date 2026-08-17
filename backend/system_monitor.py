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
from backend import process_guard
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
    """Get top 8 processes by memory. Pure psutil, no external calls.

    시스템 필수 프로세스와 APEX CARE 자기 가족 PID 는 목록 단계에서 제외한다.
    RamBooster.jsx 가 모든 행에 '프로세스 종료' 버튼을 조건 없이 그리기 때문에,
    누를 수 없는 버튼을 보여주는 것보다 애초에 노출하지 않는 편이 낫다.
    (차단 자체는 kill_process / set_process_priority 의 process_guard 관문이 담당한다)
    """
    try:
        procs = []
        own_family = process_guard.get_own_pid_family()
        for p in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                mem_info = p.info.get('memory_info')
                if mem_info is None:
                    continue
                if p.info['pid'] in own_family:
                    continue
                if process_guard.is_protected_name(p.info.get('name')):
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
    """Terminate a process by PID securely with Win32 API / taskkill fallback.

    Zero-Risk Shield: process_guard.check_controllable() 이 단일 관문이다.
    여기서 막히면 시스템 필수 프로세스는 어떤 폴백 경로로도 종료되지 않는다.
    """
    ok, safe_pid, proc_name, error = process_guard.check_controllable(pid, action="kill")
    if not ok:
        log.warning(f"kill_process blocked: pid={pid} name={proc_name} reason={error}")
        return {"success": False, "message": error, "error": error}

    done_msg = f"'{proc_name}' 프로세스를 종료했습니다."
    try:
        # Try psutil first
        try:
            p = psutil.Process(safe_pid)
            p.kill()
            return {"success": True, "message": done_msg}
        except (psutil.AccessDenied, Exception):
            # Fallback 1: Win32 TerminateProcess via ctypes
            try:
                PROCESS_TERMINATE = 0x0001
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, safe_pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return {"success": True, "message": done_msg}
            except Exception as e:
                log.debug(f"Win32 terminate fallback failed: {e}")

            # Fallback 2: taskkill /F /PID  (safe_pid 는 process_guard 가 검증한 양의 정수)
            try:
                res = subprocess.run(f"taskkill /F /PID {safe_pid}", shell=True, capture_output=True, text=True, creationflags=0x08000000, timeout=10)
                if res.returncode == 0:
                    return {"success": True, "message": done_msg}
                fail_msg = "프로세스를 종료할 권한이 없습니다."
                return {"success": False, "message": fail_msg, "error": res.stderr.strip() or fail_msg}
            except Exception as e:
                return {"success": False, "message": "프로세스 종료에 실패했습니다.", "error": str(e)}
    except Exception as e:
        return {"success": False, "message": "프로세스 종료에 실패했습니다.", "error": str(e)}

def set_process_priority(pid, priority):
    """Change process priority (Windows specific classes) with Win32 fallback.

    Zero-Risk Shield:
    - process_guard 가 시스템 필수 프로세스 / APEX CARE 자신을 차단한다.
    - 'realtime' 은 프론트 노출 API 에서 지원하지 않는다 (입력 스택까지 멈출 수 있음).
    - 알 수 없는 값을 조용히 NORMAL 로 낮추지 않고 명시적으로 거절한다.
    """
    bad_value_msg = "지원하지 않는 우선순위 값입니다. (낮음/보통/높음 중에서 선택해 주세요)"
    if not isinstance(priority, str):
        return {"success": False, "message": bad_value_msg, "error": bad_value_msg}

    key = priority.strip().lower()
    if key == 'realtime':
        msg = ("'실시간(Realtime)' 우선순위는 마우스·키보드 입력까지 멈추게 만들 수 있어 "
               "APEX CARE에서는 지원하지 않습니다. '높음(High)'을 사용해 주세요.")
        log.warning(f"set_process_priority blocked: realtime is not exposed (pid={pid})")
        return {"success": False, "message": msg, "error": msg}

    if key not in process_guard.ALLOWED_PRIORITIES:
        return {"success": False, "message": bad_value_msg, "error": bad_value_msg}

    ok, safe_pid, proc_name, error = process_guard.check_controllable(pid, action="priority")
    if not ok:
        log.warning(f"set_process_priority blocked: pid={pid} name={proc_name} reason={error}")
        return {"success": False, "message": error, "error": error}

    done_msg = f"'{proc_name}' 프로세스의 우선순위를 변경했습니다."
    try:
        pri_map = {
            'high': (psutil.HIGH_PRIORITY_CLASS, 0x0080),
            'low': (psutil.IDLE_PRIORITY_CLASS, 0x0040),
            'normal': (psutil.NORMAL_PRIORITY_CLASS, 0x0020)
        }
        target_psutil, target_win32 = pri_map[key]

        try:
            p = psutil.Process(safe_pid)
            p.nice(target_psutil)
            return {"success": True, "message": done_msg}
        except psutil.AccessDenied:
            # Fallback: Win32 SetPriorityClass
            PROCESS_SET_INFORMATION = 0x0200
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, safe_pid)
            if handle:
                res = ctypes.windll.kernel32.SetPriorityClass(handle, target_win32)
                ctypes.windll.kernel32.CloseHandle(handle)
                if res:
                    return {"success": True, "message": done_msg}
            msg = "우선순위 변경 권한이 거부되었습니다."
            return {"success": False, "message": msg, "error": msg}
    except Exception as e:
        return {"success": False, "message": "우선순위 변경에 실패했습니다.", "error": str(e)}

