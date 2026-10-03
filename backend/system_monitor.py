"""
APEX CARE - System Monitor (Pure Python)
Uses psutil + ctypes only. Zero external process spawning.
"""
import psutil
import platform
import os
import ctypes
import ctypes.wintypes
import re
import time
import threading
import subprocess
import logging
from backend import process_guard
log = logging.getLogger('SystemMonitor')

# Cache CPU model info once at import time (WMI is heavy, only call once)
_cpu_model_cache = None

# 마지막으로 잰 CPU·GPU 사용률. 아직 재지 못했으면 None 이다(0 으로 채워 두면 '0%' 로 보인다).
_cpu_usage = None
_gpu_usage = None

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
    global _cpu_usage, _cpu_clock_mhz
    if not _wanted():
        time.sleep(1)
        return False
    try:
        by_time = psutil.cpu_percent(interval=1)
    except Exception as e:
        # 못 쟀으면 지난 값을 두고 시각을 갱신하지 않는다. 오래되면 _fresh_cpu_usage 가 None 을 준다.
        log.debug(f"CPU poller error: {e}")
        by_time = None
    _cpu_utility[0] = None
    _cpu_clock_mhz = _sample_clock()
    # 작업 관리자의 CPU % 는 '% Processor Utility'(시간 × 클럭 비율, 100 에서 자름)다. 부스트 중이면 시간 기준
    # (psutil)보다 높게 나온다. 같은 값을 보여 줘야 사용자가 작업 관리자와 비교해도 어긋나지 않는다.
    # 그 카운터를 못 읽는 PC 에서는 시간 기준 값을 쓴다.
    usage = _cpu_utility[0] if _cpu_utility[0] is not None else by_time
    if usage is not None:
        _cpu_usage = max(0.0, min(100.0, usage))
        _cpu_sample[0] = time.time()
    return True


_cpu_sample = [0.0]      # 마지막으로 CPU 사용률을 잰 시각


def _fresh_cpu_usage():
    """최근(3초 안)에 잰 CPU 사용률. 아직 못 쟀거나 수집기가 쉬다 막 깨어났으면 None('측정 중').

    예전에는 이때 psutil.cpu_percent(interval=None) 을 불렀다. psutil 7 은 그 기준점을 스레드마다 따로
    두는데, pywebview 는 화면 요청마다 새 스레드에서 처리하므로 늘 '첫 호출' 이 되어 0% 가 나왔다.
    수집기는 요청을 받으면 1초 안에 다시 잰다. 그 사이에는 재지 않은 값을 보여 주지 않는다.
    """
    if time.time() - _cpu_sample[0] <= 3:
        return _cpu_usage
    return None


# ── 실제 CPU 클럭 ──────────────────────────────────────────────
# 작업 관리자의 '속도' 와 같은 값: 기본 클럭 × \Processor Information(_Total)\% Processor Performance.
# 부스트 중이면 100% 를 넘는다. 성능 모드가 실제로 무엇을 바꿨는지 사용자가 숫자로 볼 수 있게 한다.
_PDH_FMT_DOUBLE = 0x00000200
_CLOCK_COUNTER = r'\Processor Information(_Total)\% Processor Performance'
_UTILITY_COUNTER = r'\Processor Information(_Total)\% Processor Utility'     # 작업 관리자의 CPU %
_cpu_clock_mhz = None
_cpu_utility = [None]      # 마지막 수집의 % Processor Utility (못 읽었으면 None)
_clock = {'pdh': None, 'query': None, 'counter': None, 'utility': None, 'failed': False, 'last': 0.0}


class _PdhDoubleValue(ctypes.Structure):
    _fields_ = [('CStatus', ctypes.wintypes.DWORD), ('doubleValue', ctypes.c_double)]


_installed_ram_cache = []


def installed_ram_gb():
    """꽂혀 있는 메모리 용량(GB). psutil 의 total 은 내장 그래픽 등이 예약한 만큼 빠진 값이라
    16GB PC 에서 15.4GB 처럼 보인다. 작업 관리자처럼 설치 용량을 따로 보여 주려고 읽는다. 못 읽으면 None."""
    if _installed_ram_cache:
        return _installed_ram_cache[0]
    value = None
    try:
        kb = ctypes.c_ulonglong()
        if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            value = round(kb.value / (1024 * 1024), 1)
    except Exception as e:
        log.debug(f"설치 메모리를 읽지 못했습니다: {e}")
    _installed_ram_cache.append(value)
    return value


_base_mhz_cache = []


def cpu_base_mhz():
    """레지스트리의 CPU 기본 클럭(MHz). 읽지 못하면 None."""
    if _base_mhz_cache:
        return _base_mhz_cache[0]
    value = None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            value = int(winreg.QueryValueEx(k, "~MHz")[0]) or None
    except Exception as e:
        log.debug(f"기본 클럭을 읽지 못했습니다: {e}")
    _base_mhz_cache.append(value)
    return value


def clock_from(base_mhz, perf_pct):
    if not base_mhz or perf_pct is None or perf_pct <= 0:
        return None
    return int(round(base_mhz * perf_pct / 100.0))


def _sample_clock():
    """지금 CPU 가 도는 클럭(MHz). 처음 한 번은 기준점만 잡고 None. 한 번 실패하면 다시 시도하지 않는다.

    같은 수집에서 작업 관리자의 CPU %(% Processor Utility)도 읽어 _cpu_utility 에 둔다.
    두 카운터는 '지난 수집 이후 평균' 이다. 수집기가 쉬다 깨어나 지난 수집이 오래됐으면(3초 넘게)
    그 평균은 지금 값이 아니므로 버리고 기준점만 새로 잡는다.
    """
    c = _clock
    if c['failed']:
        return None
    try:
        if c['query'] is None:
            pdh = ctypes.WinDLL('pdh')
            q, h, u = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
            if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
                raise OSError('PdhOpenQueryW')
            if pdh.PdhAddEnglishCounterW(q, ctypes.c_wchar_p(_CLOCK_COUNTER), None, ctypes.byref(h)) != 0:
                pdh.PdhCloseQuery(q)
                raise OSError('PdhAddEnglishCounterW')
            # Windows 8 이전에는 없다. 없으면 CPU % 는 시간 기준(psutil)으로 둔다.
            if pdh.PdhAddEnglishCounterW(q, ctypes.c_wchar_p(_UTILITY_COUNTER), None, ctypes.byref(u)) != 0:
                u = None
            pdh.PdhCollectQueryData(q)
            c.update(pdh=pdh, query=q, counter=h, utility=u, last=time.time())
            return None
        pdh = c['pdh']
        stale = time.time() - c['last'] > 3
        c['last'] = time.time()
        if pdh.PdhCollectQueryData(c['query']) != 0 or stale:
            return None
        v = _PdhDoubleValue()
        if c['utility'] is not None:
            if (pdh.PdhGetFormattedCounterValue(c['utility'], _PDH_FMT_DOUBLE, None, ctypes.byref(v)) == 0
                    and v.CStatus == 0):
                _cpu_utility[0] = v.doubleValue
        v = _PdhDoubleValue()
        if pdh.PdhGetFormattedCounterValue(c['counter'], _PDH_FMT_DOUBLE, None, ctypes.byref(v)) != 0 or v.CStatus != 0:
            return None
        return clock_from(cpu_base_mhz(), v.doubleValue)
    except Exception as e:
        log.debug(f"CPU 클럭 카운터를 쓸 수 없습니다: {e}")
        c['failed'] = True
        return None


def _cpu_poller():
    while True:
        _cpu_tick()

# Start CPU poller
_cpu_thread = threading.Thread(target=_cpu_poller, daemon=True)
_cpu_thread.start()

_ADAPTER_RE = re.compile(r'luid_0x[0-9a-fA-F]+_0x[0-9a-fA-F]+_phys_\d+')


def gpu_3d_usage(samples):
    """'GPU Engine(*)\\Utilization Percentage' 값들에서 3D 엔진 사용률(%)을 구한다.

    인스턴스 하나가 '프로세스 × 그래픽 어댑터 × 엔진' 이다. 어댑터마다 프로세스들의 3D 값을 더하고,
    가장 바쁜 어댑터 값을 쓴다(작업 관리자의 GPU '3D' 와 같은 방식). 예전에는 어댑터를 가리지 않고 모두
    더해, 내장·외장 그래픽이 함께 일하면 두 장치의 합이 한 장치의 사용률처럼 보였다.
    3D 인스턴스가 하나도 없으면 0(3D 를 쓰는 프로세스가 없음).
    """
    per_adapter = {}
    for name, value in (samples or {}).items():
        if 'engtype_3D' not in name:
            continue
        m = _ADAPTER_RE.search(name)
        key = m.group(0) if m else ''
        per_adapter[key] = per_adapter.get(key, 0.0) + (value or 0.0)
    usage = max(per_adapter.values()) if per_adapter else 0.0
    return min(100, round(usage))


def _gpu_poller():
    global _gpu_usage, _gpu_state
    try:
        import win32pdh
        hq = win32pdh.OpenQuery()
        hc = win32pdh.AddCounter(hq, '\\GPU Engine(*)\\Utilization Percentage')
        win32pdh.CollectQueryData(hq)
    except Exception as e:
        # 이 PC 에서는 GPU 사용률을 읽을 수 없다. 0% 로 꾸며 보이지 않고 '측정 불가' 로 알린다.
        log.debug(f"GPU pdh init error: {e}")
        _gpu_usage = None
        _gpu_state = 'unavailable'
        return

    last_collect = time.time()
    while True:
        try:
            time.sleep(1)
            # GPU Engine(*) 은 프로세스×엔진마다 값이 하나라 수백~수천 개다. 화면이 안 볼 때는 읽지 않는다.
            if not _wanted():
                continue
            win32pdh.CollectQueryData(hq)
            now = time.time()
            idle = now - last_collect
            last_collect = now
            if idle > _GPU_MAX_INTERVAL:
                # 사용률은 직전 수집과 이번 수집 사이의 평균이다. 쉬다 깨어난 첫 수집은 쉬는 동안의 평균이라
                # '지금 값' 이 아니다. 기준점으로만 쓰고 다음 수집부터 보여 준다.
                continue
            arr = win32pdh.GetFormattedCounterArray(hc, win32pdh.PDH_FMT_DOUBLE)
            usage = gpu_3d_usage(arr if isinstance(arr, dict) else {})
            _gpu_usage = min(100, round(usage))      # 가장 바쁜 어댑터의 3D 엔진 값(작업 관리자와 같은 방식)
            _gpu_sample[0] = time.time()
            _gpu_state = 'ok'
        except Exception as e:
            # 한 번 못 읽었다고 0% 로 보이지 않는다. 지난 값은 오래되면 get_system_stats 가 버린다.
            log.debug(f"GPU poller error: {e}")
            time.sleep(1)


_GPU_MAX_INTERVAL = 3        # 직전 수집이 이보다 오래됐으면 이번 수집은 기준점일 뿐이다(초)
_gpu_sample = [0.0]          # 마지막으로 GPU 사용률을 잰 시각
_gpu_state = 'measuring'     # 'measuring' | 'ok' | 'unavailable'


def _fresh_gpu_usage():
    """최근(3초 안)에 잰 GPU 사용률. 아직 못 쟀거나 쉬다 막 깨어났으면 None('측정 중')."""
    if _gpu_state == 'unavailable':
        return None
    if time.time() - _gpu_sample[0] <= 3:
        return _gpu_usage
    return None

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
        _cpu_model_cache = platform.processor() or "알 수 없음"
    return _cpu_model_cache

_gpu_model_cache = None

# 화면 출력만 하는 가상·원격 어댑터. 실제 그래픽카드가 따로 있으면 이 이름을 보여 주지 않는다.
_VIRTUAL_GPU_HINTS = ('microsoft basic', 'microsoft 기본', 'remote display', 'remote desktop', 'virtual',
                      'parsec', 'citrix', 'displaylink', 'spacedesk', 'indirect display')


def _is_integrated_gpu(low):
    """내장 그래픽인가. 외장 그래픽카드가 함께 있으면 외장을 대표로 보여 준다(게임이 쓰는 쪽).

    Intel 은 Arc A·B 시리즈(외장)만 빼고 내장이다. AMD 는 'Radeon ... Graphics' 로 끝나면
    APU 내장(Radeon 780M Graphics, RX Vega 11 Graphics)이고, 외장은 'Radeon RX 7800 XT' 처럼 끝난다.
    """
    if 'intel' in low:
        return not re.search(r'arc\S*\s+[ab]\d', low)
    return 'radeon' in low and low.rstrip().endswith('graphics')


def pick_gpu_name(names):
    """그래픽 어댑터 이름 목록에서 대표 하나를 고른다.

    예전에는 WMI 가 처음 돌려준 것을 썼다. 내장+외장 노트북은 내장 그래픽이, 원격 접속 도구를
    깐 PC 는 'Microsoft 기본 디스플레이 어댑터' 같은 가상 어댑터가 GPU 로 보였다.
    외장 > 내장 > 가상 순으로 고르고, 같은 순위면 WMI 순서를 따른다. 목록이 비었으면 None.
    """
    names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
    if not names:
        return None

    def rank(n):
        low = n.lower()
        if any(h in low for h in _VIRTUAL_GPU_HINTS):
            return 2
        if _is_integrated_gpu(low):
            return 1
        return 0
    return sorted(names, key=rank)[0]


def _get_gpu_model():
    global _gpu_model_cache
    if _gpu_model_cache is not None:
        return _gpu_model_cache
    try:
        import pythoncom
        pythoncom.CoInitialize()
        import win32com.client
        wmi = win32com.client.GetObject('winmgmts:')
        names = [c.Name for c in wmi.InstancesOf('Win32_VideoController')]
        _gpu_model_cache = pick_gpu_name(names) or "알 수 없음"
    except Exception as e:
        log.debug(f"Failed to get GPU model: {e}")
        _gpu_model_cache = "알 수 없음"
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


def system_drive():
    """Windows 가 설치된 드라이브 문자('C:' 등)."""
    d = (os.environ.get('SystemDrive') or '').strip().rstrip('\\/')
    return d if re.fullmatch(r'[A-Za-z]:', d) else 'C:'


def _all_drives():
    """대시보드용 드라이브 목록(문자 순). 매체 종류(SSD/HDD)는 느려서 묻지 않는다. 읽지 못하면 None."""
    try:
        from backend import storage
        drives = storage.get_drives(detect_media=False)
    except Exception as e:
        log.debug(f"드라이브 목록을 읽지 못했습니다: {e}")
        return None
    keep = ('label', 'system', 'removable', 'totalGB', 'usedGB', 'freeGB', 'percent')
    return sorted(({k: d[k] for k in keep} for d in drives), key=lambda d: d['label'].upper())


def get_system_stats():
    """Get system stats using only psutil and WMI for GPU."""
    note_demand()
    try:
        cpu_usage = _fresh_cpu_usage()
        mem = psutil.virtual_memory()
        # Windows 가 설치된 드라이브. C: 로 고정하면 C: 가 없는 PC 에서 이 함수 전체가 실패해 앱이 로딩 화면에서 멈췄다.
        drive = system_drive()
        try:
            disk = psutil.disk_usage(drive + '\\')
        except Exception as e:
            log.debug(f"{drive} 사용량을 읽지 못했습니다: {e}")
            disk = None

        cpu_model = _get_cpu_model()
        # 읽지 못하면(일부 가상 머신에서 None) None 으로 둔다. 0 은 '코어 0개' 라는 거짓이고,
        # 초기 설정 마법사가 그 0 으로 저사양을 판정해 SysMain 을 끄자고 제안했다.
        cpu_cores = psutil.cpu_count(logical=False) or None
        cpu_threads = psutil.cpu_count(logical=True) or None
        
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
            # 작업 관리자와 같은 % Processor Utility(없으면 시간 기준). None = 아직 재지 못함('측정 중')
            'cpuUsage': None if cpu_usage is None else round(cpu_usage),
            # 클럭도 수집기가 쉬다 깨어난 직후에는 오래된 값이라 CPU % 와 같은 기준으로 버린다
            'cpuClockMHz': _cpu_clock_mhz if cpu_usage is not None else None,   # 아직 못 쟀으면 None('측정 중')
            'cpuBaseMHz': cpu_base_mhz(),
            'ramUsedGB': round(mem.used / (1024**3), 1),
            'ramTotalGB': round(mem.total / (1024**3), 1),          # Windows 가 쓸 수 있는 용량
            'ramInstalledGB': installed_ram_gb(),                    # 꽂혀 있는 용량 (예약분 포함)
            'ramPct': round(mem.percent),
            'ramStandbyGB': standby_gb,
            'ramFreeGB': free_gb,
            'ramModifiedGB': modified_gb,
            'ramInUseGB': in_use_gb,
            'ramAvailableGB': round(mem.available / GB, 1),
            'systemDrive': drive,
            'diskUsedGB': round(disk.used / (1024**3)) if disk else None,
            'diskTotalGB': round(disk.total / (1024**3)) if disk else None,
            # 반올림한 전체에서 반올림한 사용량을 빼면 1GB 씩 어긋난다. 남은 용량은 따로 잰다.
            'diskFreeGB': round(disk.free / (1024**3)) if disk else None,
            'diskPct': round(disk.percent) if disk else None,
            # 연결된 모든 드라이브(꽂거나 빼면 다음 갱신 때 반영). 읽지 못하면 None — 화면은 위의 시스템 드라이브만 보여 준다
            'drives': _all_drives(),
            'gpuUsage': _fresh_gpu_usage(),       # None = 측정 중 또는 측정 불가(gpuUsageState 로 구분)
            'gpuUsageState': _gpu_state,
            'gpuModel': _get_gpu_model(),
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


def get_processes(limit=8):
    """메모리를 많이 쓰는 순으로 프로세스 목록. limit 개까지(0 이나 None 이면 전부). psutil 만 쓴다.

    RAM 화면은 상위 8개를 보여 주고, 게이밍 탭의 우선순위 조정은 이름으로 찾아야 하므로 전부 받는다.
    예전에는 늘 8개만 돌려줘서 게이밍 탭의 검색으로 게임이나 원하는 앱을 찾을 수 없었다.

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
                # 재사용된 PID 의 캐시 객체는 끝난 프로세스의 이름·생성 시각을 준다(psutil 7). 새로 고쳐도 옛 이름이 보였다
                if not p.is_running():
                    continue
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
                    try:
                        created = p.create_time()
                    except Exception:
                        created = None
                    procs.append({
                        'id': p.info['pid'],
                        'pid': p.info['pid'],
                        # 생성 시각. 종료할 때 같은 프로세스인지 확인한다(그 사이 PID 가 재사용될 수 있다)
                        'created': created,
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
        try:
            limit = int(limit or 0)
        except (TypeError, ValueError):
            limit = 8
        return procs[:limit] if limit > 0 else procs
    except Exception as e:
        print(f"[SystemMonitor] Process list error: {e}")
        return []

def kill_process(pid, created=None):
    """Terminate a process by PID securely with Win32 API / taskkill fallback.

    Zero-Risk Shield: process_guard.check_controllable() 이 단일 관문이다.
    여기서 막히면 시스템 필수 프로세스는 어떤 폴백 경로로도 종료되지 않는다.
    """
    ok, safe_pid, proc_name, error = process_guard.check_controllable(pid, action="kill")
    if not ok:
        log.warning(f"kill_process blocked: pid={pid} name={proc_name} reason={error}")
        return {"success": False, "message": error, "error": error}

    done_msg = f"'{proc_name}' 프로세스를 종료했습니다."
    if created is not None:
        # 목록을 본 뒤 그 프로세스가 끝나고 다른 프로그램이 같은 PID 를 받았으면 그것을 종료하게 된다
        try:
            same = abs(psutil.Process(safe_pid).create_time() - float(created)) < 0.01
        except psutil.NoSuchProcess:
            return {"success": True, "message": f"'{proc_name}' 프로세스는 이미 종료되었습니다."}
        except (TypeError, ValueError, psutil.Error):
            same = False
        if not same:
            msg = "목록을 본 뒤 그 프로세스가 끝나 다른 프로그램이 같은 번호를 받았습니다. 목록을 새로 고쳐 주세요."
            return {"success": False, "message": msg, "error": msg}
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
        from backend.system_repair import sys_tool
        res = subprocess.run([sys_tool("taskkill.exe"), "/F", "/PID", str(safe_pid)], shell=False,
                             capture_output=True, text=True, errors='replace', creationflags=0x08000000, timeout=10)
        if res.returncode == 0:
            return {"success": True, "message": done_msg}
        fail_msg = "프로세스를 종료할 권한이 없습니다."
        return {"success": False, "message": fail_msg, "error": res.stderr.strip() or fail_msg}
    except Exception as e:
        return {"success": False, "message": "프로세스 종료에 실패했습니다.", "error": str(e)}
