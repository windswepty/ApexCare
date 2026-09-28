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
from backend import process_guard
log = logging.getLogger('SystemMonitor')

# Cache CPU model info once at import time (WMI is heavy, only call once)
_cpu_model_cache = None

# CPU, GPU, and RAM Cache
_cpu_usage = 0
_gpu_usage = 0
_standby_gb = 0

# 화면이 최근에 값을 요청했을 때만 잰다. 창이 최소화됐거나 값을 보여 주는 화면이 없으면
# 백엔드도 쉰다. 예전에는 CPU·GPU 수집 스레드가 창 상태와 상관없이 1초마다 돌았고,
# 매번 강제 가비지 컬렉션(gc.collect)까지 해서 CPU 를 계속 썼다.
_DEMAND_WINDOW_SEC = 15
_last_demand = 0.0


def note_demand():
    global _last_demand
    _last_demand = time.time()


def _wanted():
    return time.time() - _last_demand < _DEMAND_WINDOW_SEC


def _cpu_tick():
    """한 번 잰다. 잴 필요가 없으면 1초 쉬고 False."""
    global _cpu_usage
    if not _wanted():
        time.sleep(1)
        return False
    try:
        _cpu_usage = psutil.cpu_percent(interval=1)
    except Exception as e:
        log.debug(f"CPU poller error: {e}")
        _cpu_usage = 0
    return True


def _cpu_poller():
    while True:
        _cpu_tick()

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
            # GPU Engine(*) 은 프로세스×엔진마다 값이 하나라 수백~수천 개다. 화면이 안 볼 때는 읽지 않는다.
            if not _wanted():
                continue
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

# ── 메모리 목록 크기 (Windows 성능 카운터) ─────────────────────────
# psutil 은 Windows 에서 free 를 available 과 같은 값으로 채운다. 그래서 예전 계산
# 'available - free' 는 대기(Standby) 메모리를 늘 0 으로 냈다. 작업 관리자의 메모리 구성과
# 같은 값을 쓰려고 \Memory 성능 카운터를 PDH 로 읽는다. 영어 카운터 이름을 쓰므로
# 한국어 Windows 에서도 동작한다(PdhAddEnglishCounterW). 관리자 권한은 필요 없다.
_PDH_FMT_LARGE = 0x00000400
_STANDBY_COUNTERS = (
    r'\Memory\Standby Cache Reserve Bytes',
    r'\Memory\Standby Cache Normal Priority Bytes',
    r'\Memory\Standby Cache Core Bytes',
)
_FREE_COUNTER = r'\Memory\Free & Zero Page List Bytes'
_MODIFIED_COUNTER = r'\Memory\Modified Page List Bytes'


class _PdhCounterValue(ctypes.Structure):
    # PDH_FMT_COUNTERVALUE: DWORD CStatus + 8바이트 정렬된 union. LONGLONG 만 쓴다.
    _fields_ = [('CStatus', ctypes.wintypes.DWORD), ('largeValue', ctypes.c_longlong)]


def memory_lists():
    """대기·여유·수정됨 메모리 목록 크기(바이트). 읽지 못하면 None.

    반환: {'standby': int, 'free': int, 'modified': int}
    """
    try:
        pdh = ctypes.WinDLL('pdh')
    except OSError as e:
        log.debug(f"pdh.dll 을 열지 못했습니다: {e}")
        return None
    query = ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
        return None
    try:
        handles = {}
        for path in _STANDBY_COUNTERS + (_FREE_COUNTER, _MODIFIED_COUNTER):
            h = ctypes.c_void_p()
            status = pdh.PdhAddEnglishCounterW(query, ctypes.c_wchar_p(path), None, ctypes.byref(h))
            if status != 0:
                log.debug(f"카운터 추가 실패 {path}: 0x{status & 0xFFFFFFFF:08X}")
                return None
            handles[path] = h
        if pdh.PdhCollectQueryData(query) != 0:
            return None
        values = {}
        for path, h in handles.items():
            v = _PdhCounterValue()
            status = pdh.PdhGetFormattedCounterValue(h, _PDH_FMT_LARGE, None, ctypes.byref(v))
            if status != 0 or v.CStatus != 0:
                log.debug(f"카운터 읽기 실패 {path}: 0x{status & 0xFFFFFFFF:08X}")
                return None
            values[path] = v.largeValue
        return {
            'standby': sum(values[p] for p in _STANDBY_COUNTERS),
            'free': values[_FREE_COUNTER],
            'modified': values[_MODIFIED_COUNTER],
        }
    except Exception as e:
        log.debug(f"메모리 목록을 읽지 못했습니다: {e}")
        return None
    finally:
        pdh.PdhCloseQuery(query)


def get_system_stats():
    """Get system stats using only psutil and WMI for GPU."""
    note_demand()
    try:
        cpu_usage = _cpu_usage
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('C:\\')
        
        cpu_model = _get_cpu_model()
        cpu_cores = psutil.cpu_count(logical=False) or 0
        cpu_threads = psutil.cpu_count(logical=True) or 0
        
        # 메모리 구성은 작업 관리자와 같은 성능 카운터 값이다. 읽지 못하면 None 으로 둔다(추측하지 않는다).
        GB = 1024 ** 3
        lists = memory_lists()
        if lists:
            standby_gb = round(lists['standby'] / GB, 1)
            free_gb = round(lists['free'] / GB, 1)
            modified_gb = round(lists['modified'] / GB, 1)
            # 사용 중 = 전체 - 사용 가능(대기+여유) - 수정됨  (작업 관리자의 '사용 중')
            in_use_gb = round(max(mem.total - mem.available - lists['modified'], 0) / GB, 1)
        else:
            standby_gb = free_gb = modified_gb = in_use_gb = None

        return {
            'cpuModel': cpu_model,
            'cpuCores': cpu_cores,
            'cpuThreads': cpu_threads,
            'cpuUsage': round(cpu_usage),
            'ramUsedGB': round(mem.used / (1024**3), 1),
            'ramTotalGB': round(mem.total / (1024**3), 1),
            'ramPct': round(mem.percent),
            'ramStandbyGB': standby_gb,
            'ramFreeGB': free_gb,
            'ramModifiedGB': modified_gb,
            'ramInUseGB': in_use_gb,
            'ramAvailableGB': round(mem.available / GB, 1),
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


# psutil 의 Windows 우선순위 클래스 → 화면 표시 (작업 관리자와 같은 이름)
_PRIORITY_LABEL = {
    psutil.IDLE_PRIORITY_CLASS: '낮음',
    psutil.BELOW_NORMAL_PRIORITY_CLASS: '보통 미만',
    psutil.NORMAL_PRIORITY_CLASS: '보통',
    psutil.ABOVE_NORMAL_PRIORITY_CLASS: '보통 초과',
    psutil.HIGH_PRIORITY_CLASS: '높음',
    psutil.REALTIME_PRIORITY_CLASS: '실시간',
}


_cpu_seen_pids = set()


def get_processes():
    """Get top 8 processes by memory. Pure psutil, no external calls.

    시스템 필수 프로세스와 APEX CARE 자기 가족 PID 는 목록 단계에서 제외한다.
    RamBooster.jsx 가 모든 행에 '프로세스 종료' 버튼을 조건 없이 그리기 때문에,
    누를 수 없는 버튼을 보여주는 것보다 애초에 노출하지 않는 편이 낫다.
    (차단 자체는 kill_process · process_boost.set_priority 의 process_guard 관문이 담당한다)
    """
    try:
        global _cpu_seen_pids
        procs = []
        seen_now = set()
        own_family = process_guard.get_own_pid_family()
        for p in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent', 'nice']):
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
                    # psutil 은 프로세스를 처음 잴 때 cpu_percent 를 0.0 으로 준다(측정값이 아니다).
                    # 처음 본 PID 는 None 으로 두고 UI 가 '측정 중' 으로 보여준다.
                    pid = p.info['pid']
                    first_sample = pid not in _cpu_seen_pids
                    seen_now.add(pid)
                    raw_cpu = p.info.get('cpu_percent') or 0
                    num_cores = psutil.cpu_count(logical=True) or 1
                    cpu_text = None if first_sample else f"{raw_cpu / num_cores:.1f}%"
                    procs.append({
                        'id': p.info['pid'],
                        'pid': p.info['pid'],
                        'name': p.info['name'] or 'unknown',
                        'memoryMB': round(mem_mb),
                        'cpuPct': cpu_text,
                        # 실제 우선순위 클래스. 예전에는 모든 프로세스에 'Normal' 을 박아 넣었다.
                        'priority': _PRIORITY_LABEL.get(p.info.get('nice'), '알 수 없음'),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        _cpu_seen_pids = seen_now
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
        p = psutil.Process(safe_pid)
        p.kill()
        return {"success": True, "message": done_msg}
    except psutil.NoSuchProcess:
        return {"success": True, "message": f"'{proc_name}' 프로세스는 이미 종료되었습니다."}
    except Exception:
        pass

    # 폴백 1: Win32 TerminateProcess. 반환값을 확인한다 — 예전에는 핸들만 열리면
    # 종료에 실패해도 '종료했습니다' 라고 했다.
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, safe_pid)
        if handle:
            ok = kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)
            if ok:
                return {"success": True, "message": done_msg}
    except Exception as e:
        log.debug(f"Win32 terminate fallback failed: {e}")

    # 폴백 2: taskkill. 셸을 거치지 않고 인자 리스트로 넘긴다.
    try:
        res = subprocess.run(["taskkill", "/F", "/PID", str(safe_pid)], shell=False,
                             capture_output=True, text=True, errors='replace', creationflags=0x08000000, timeout=10)
        if res.returncode == 0:
            return {"success": True, "message": done_msg}
        fail_msg = "프로세스를 종료할 권한이 없습니다."
        return {"success": False, "message": fail_msg, "error": res.stderr.strip() or fail_msg}
    except Exception as e:
        return {"success": False, "message": "프로세스 종료에 실패했습니다.", "error": str(e)}
