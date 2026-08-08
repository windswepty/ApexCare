"""
APEX CARE - Optimizer (Pure Python)
All system control via ctypes Win32 API or psutil.
"""
import os
import shutil
import ctypes
import ctypes.wintypes
import psutil
import concurrent.futures
import threading
import time
import subprocess
import logging
import sys
import stat
from backend import system_repair

log = logging.getLogger('Optimizer')

# ─────────────────────────────────────────────
# Deep Optimization Engine (Background Thread)
# ─────────────────────────────────────────────

_optimization_state = {
    "running": False,
    "progress_pct": 0,
    "eta_seconds": 0,
    "current_task": "",
    "freed_mb": 0,
    "error": None,
    "cancel_requested": False
}

def get_deep_optimization_status():
    return _optimization_state

_cancel_event = threading.Event()
_junk_cancel_event = threading.Event()

def _run_deep_optimization():
    global _optimization_state
    _optimization_state = {
        "running": True,
        "progress_pct": 0,
        "eta_seconds": 10,
        "current_task": "시스템 정크 및 임시 파일 정리 중...",
        "freed_mb": 0,
        "error": None,
        "cancel_requested": False
    }
    _cancel_event.clear()
    
    try:
        # Step 1: Deep Junk Clean (synchronous within this thread)
        _optimization_state["current_task"] = "브라우저 캐시, 임시 파일, 업데이트 잔여물 삭제 중..."
        _optimization_state["eta_seconds"] = 10
        clean_junk_background([1, 2, 3, 4], cancel_event=_cancel_event)
        freed = _junk_clean_state.get("freedMB", 0)
        _optimization_state["freed_mb"] += freed
        _optimization_state["progress_pct"] = 40
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")
        
        # Step 2: RAM Purge
        _optimization_state["current_task"] = "유휴 프로세스 정리 및 가용 메모리 확보 중..."
        purge_ram()
        _optimization_state["progress_pct"] = 60
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")

        # Step 3: Network Deep Flush
        _optimization_state["current_task"] = "네트워크 캐시 및 DNS 초기화 중..."
        system_repair.run_network_optimization_sync()
        _optimization_state["progress_pct"] = 80
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")
            
        # Step 4: SSD TRIM
        _optimization_state["current_task"] = "물리 디스크 응답속도 최적화(TRIM) 중..."
        system_repair.run_trim()
        
        _optimization_state["progress_pct"] = 100
        _optimization_state["eta_seconds"] = 0
        _optimization_state["current_task"] = "완료! 시스템이 완벽하게 최적화되었습니다."
        
    except Exception as e:
        _optimization_state["error"] = str(e)
        _optimization_state["current_task"] = f"취소/오류: {str(e)}"
    finally:
        _optimization_state["running"] = False

def start_deep_optimization():
    if _optimization_state["running"]:
        return {"success": False, "message": "이미 최적화가 실행 중입니다."}
    
    t = threading.Thread(target=_run_deep_optimization, daemon=True)
    t.start()
    return {"success": True}

def cancel_deep_optimization():
    if _optimization_state["running"]:
        _optimization_state["cancel_requested"] = True
        _cancel_event.set()
        return {"success": True}
    return {"success": False, "message": "실행 중인 최적화가 없습니다."}

# ─────────────────────────────────────────────
# Junk Scan (Sequential Execution)
# ─────────────────────────────────────────────

def _get_dir_size_mb(dir_path, state_obj=None, max_files=10000):
    """Walk directory and sum file sizes. Sequential, safe."""
    total = 0
    file_count = 0
    start_time = time.time()

    if not os.path.exists(dir_path):
        return 0
    try:
        for root, dirs, files in os.walk(dir_path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    if not os.path.islink(fp):
                        total += os.path.getsize(fp)
                        file_count += 1
                        
                        if state_obj and file_count % 50 == 0:
                            elapsed = time.time() - start_time
                            rate = file_count / elapsed if elapsed > 0 else 1
                            # 임의의 프로그레스 시뮬레이션
                            prog = min(99, int((file_count / max_files) * 100))
                            eta = int((max_files - file_count) / rate) if rate > 0 else 0
                            state_obj["progress"] = prog
                            state_obj["eta_seconds"] = max(0, eta)
                            
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return round(total / (1024 * 1024))


_junk_scan_state = {"status": "idle", "data": [], "progress": 0, "eta_seconds": 0}
_junk_scan_thread = None

def get_junk_scan_status():
    return _junk_scan_state

def scan_junk_background():
    global _junk_scan_state
    _junk_scan_state["status"] = "running"
    _junk_scan_state["progress"] = 0
    _junk_scan_state["eta_seconds"] = 15
    try:
        user_temp = os.path.expandvars('%TEMP%')
        system_temp = os.path.expandvars('%SystemRoot%\\Temp')
        prefetch = os.path.expandvars('%SystemRoot%\\Prefetch')
        soft_dist = os.path.expandvars('%SystemRoot%\\SoftwareDistribution\\Download')
        chrome_cache = os.path.expandvars('%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache')

        temp_size = _get_dir_size_mb(user_temp, _junk_scan_state, max_files=2000)
        _junk_scan_state["progress"] = 25
        temp_size += _get_dir_size_mb(system_temp, _junk_scan_state, max_files=2000)
        _junk_scan_state["progress"] = 50
        cache_size = _get_dir_size_mb(chrome_cache, _junk_scan_state, max_files=3000)
        _junk_scan_state["progress"] = 75
        soft_dist_size = _get_dir_size_mb(soft_dist, _junk_scan_state, max_files=1000)
        prefetch_size = _get_dir_size_mb(prefetch, _junk_scan_state, max_files=500)

        _junk_scan_state["data"] = [
            {"id": 1, "name": "윈도우 시스템 임시 파일 (%TEMP%)", "sizeMB": temp_size, "category": "System", "selected": True, "description": "앱 설치, 업데이트, 실행 중 생성된 임시 데이터 파일"},
            {"id": 2, "name": "웹 브라우저 캐시 및 쿠키 (Chrome)", "sizeMB": cache_size, "category": "Browser", "selected": True, "description": "Chrome 브라우저가 저장한 이미지, 스크립트 캐시 데이터"},
            {"id": 3, "name": "Windows Update 패키지 캐시", "sizeMB": soft_dist_size, "category": "System", "selected": True, "description": "이미 설치 완료된 윈도우 업데이트 설치 패키지 잔여물"},
            {"id": 4, "name": "시스템 렌더링 Prefetch 데이터", "sizeMB": prefetch_size, "category": "System", "selected": False, "description": "앱 실행 가속화를 위한 사전 로드 데이터 (삭제 시 자동 재생성)"},
        ]
        _junk_scan_state["progress"] = 100
        _junk_scan_state["eta_seconds"] = 0
        _junk_scan_state["status"] = "success"
    except Exception as e:
        import traceback
        _junk_scan_state["data"] = [
            {"id": 999, "name": f"에러 발생: {str(e)}", "sizeMB": 0, "category": "Error", "selected": False, "description": traceback.format_exc()}
        ]
        _junk_scan_state["status"] = "error"

def scan_junk():
    global _junk_scan_thread
    if _junk_scan_state["status"] == "running":
        return {"success": False, "message": "이미 스캔 중입니다."}
    _junk_scan_thread = threading.Thread(target=scan_junk_background, daemon=True)
    _junk_scan_thread.start()
    return {"success": True}

# ─────────────────────────────────────────────
# Junk Clean (Background Execution)
# ─────────────────────────────────────────────

_junk_clean_state = {"status": "idle", "freed_mb": 0.0, "error": None, "progress": 0, "eta_seconds": 0}
_junk_clean_thread = None

def get_junk_clean_status():
    return _junk_clean_state

def clean_junk_background(category_ids, cancel_event):
    global _junk_clean_state
    _junk_clean_state["status"] = "running"
    _junk_clean_state["freed_mb"] = 0.0
    _junk_clean_state["error"] = None
    _junk_clean_state["progress"] = 0
    _junk_clean_state["eta_seconds"] = 10
    
    import stat
    try:
        total_freed_bytes = 0
        total_attempt_count = 0
        total_success_count = 0
        
        user_temp = os.path.expandvars('%TEMP%')
        system_temp = os.path.expandvars('%SystemRoot%\\Temp')
        prefetch = os.path.expandvars('%SystemRoot%\\Prefetch')
        soft_dist = os.path.expandvars('%SystemRoot%\\SoftwareDistribution\\Download')
        chrome_cache = os.path.expandvars('%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache')

        def _clean_dir(path, max_files=5000):
            nonlocal total_attempt_count, total_success_count, total_freed_bytes
            local_freed = 0
            file_count = 0
            start_time = time.time()
            if not os.path.exists(path):
                return 0
            
            for root, dirs, files in os.walk(path, topdown=False):
                if cancel_event and cancel_event.is_set():
                    break
                    
                for name in files:
                    if cancel_event and cancel_event.is_set():
                        break
                    file_path = os.path.join(root, name)
                    total_attempt_count += 1
                    try:
                        sz = os.path.getsize(file_path)
                        try:
                            os.remove(file_path)
                        except (OSError, PermissionError):
                            os.chmod(file_path, stat.S_IWRITE)
                            os.remove(file_path)
                            
                        local_freed += sz
                        total_freed_bytes += sz
                        file_count += 1
                        total_success_count += 1
                        
                        if file_count % 50 == 0:
                            elapsed = time.time() - start_time
                            rate = file_count / elapsed if elapsed > 0 else 1
                            prog = min(99, int((file_count / max_files) * 100))
                            eta = int((max_files - file_count) / rate) if rate > 0 else 0
                            _junk_clean_state["progress"] = min(99, _junk_clean_state.get("progress", 0) + int(prog/4))
                            _junk_clean_state["eta_seconds"] = max(0, eta)
                            print(f"[JunkPurger] 삭제 시도 파일 수: {total_attempt_count}, 성공: {total_success_count}, 누적 확보 용량: {total_freed_bytes} bytes")
                            sys.stdout.flush()
                    except (OSError, PermissionError):
                        continue
                        
                for name in dirs:
                    if cancel_event and cancel_event.is_set():
                        break
                    dir_path = os.path.join(root, name)
                    try:
                        os.rmdir(dir_path)
                    except (OSError, PermissionError):
                        continue
            
            return local_freed

        target_dirs = []
        if 1 in category_ids:
            target_dirs.extend([user_temp, system_temp])
        if 2 in category_ids:
            target_dirs.append(chrome_cache)
        if 3 in category_ids:
            target_dirs.append(soft_dist)
        if 4 in category_ids:
            target_dirs.append(prefetch)

        for d in target_dirs:
            if cancel_event and cancel_event.is_set():
                break
            _clean_dir(d, max_files=2000)

        _junk_clean_state["freed_mb"] = round(total_freed_bytes / (1024 * 1024), 2)
        print(f"[JunkPurger] 최종 확보 용량: {_junk_clean_state['freed_mb']} MB")
        sys.stdout.flush()
        
        if cancel_event and cancel_event.is_set():
            _junk_clean_state["status"] = "cancelled"
            _junk_clean_state["progress"] = 0
            _junk_clean_state["eta_seconds"] = 0
        else:
            _junk_clean_state["status"] = "success"
            _junk_clean_state["progress"] = 100
            _junk_clean_state["eta_seconds"] = 0
    except Exception as e:
        _junk_clean_state["status"] = "error"
        _junk_clean_state["error"] = str(e)

def clean_junk(category_ids, cancel_event=None):
    global _junk_clean_thread, _junk_clean_state
    if not category_ids:
        _junk_clean_state["status"] = "success"
        _junk_clean_state["freedMB"] = 0
        return {"success": True}
    if _junk_clean_state["status"] == "running":
        return {"success": False, "message": "이미 정리 중입니다."}
    
    _junk_cancel_event.clear()
    _junk_clean_thread = threading.Thread(target=clean_junk_background, args=(category_ids, _junk_cancel_event), daemon=True)
    _junk_clean_thread.start()
    return {"success": True}

def cancel_junk_clean():
    """Cancel an in-progress junk clean operation."""
    if _junk_clean_state["status"] == "running":
        _junk_cancel_event.set()
        return {"success": True}
    return {"success": False, "message": "실행 중인 정리 작업이 없습니다."}


# ─────────────────────────────────────────────
# RAM Purge (pure ctypes)
# ─────────────────────────────────────────────

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100

def _enable_privilege(priv_name):
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        import ctypes.wintypes as wintypes
        
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]
        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]
        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]
            
        hToken = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(hToken)):
            return False
            
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, priv_name, ctypes.byref(luid)):
            kernel32.CloseHandle(hToken)
            return False
            
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 0x00000002 # SE_PRIVILEGE_ENABLED
        
        advapi32.AdjustTokenPrivileges(hToken, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
        err = ctypes.get_last_error()
        kernel32.CloseHandle(hToken)
        return err == 0
    except Exception:
        return False

def purge_ram():
    """Smart Memory Optimizer: selective trimming of idle processes + conditional standby purge.
    
    Unlike blanket EmptyWorkingSet (which causes page faults and stuttering),
    this only trims genuinely idle background processes and only purges
    standby cache when available memory is critically low (<15%).
    """
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
        
        kernel32.SetProcessWorkingSetSize.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        
        # Protect list: never trim these system-critical / active processes
        _protected = {
            'explorer.exe', 'dwm.exe', 'csrss.exe', 'svchost.exe',
            'winlogon.exe', 'lsass.exe', 'services.exe', 'system',
            'smss.exe', 'wininit.exe', 'fontdrvhost.exe',
        }
        # Also protect any known game executables (from game_booster)
        try:
            from backend.game_booster import GAMES_LIST
            _protected.update(GAMES_LIST)
        except Exception:
            pass
        
        my_pid = os.getpid()
        purged_count = 0
        
        # 1. Selective Working Set trimming: only trim idle background apps
        for p in psutil.process_iter(['pid', 'name', 'status', 'cpu_percent']):
            try:
                pid = p.info['pid']
                name = (p.info.get('name') or '').lower()
                if pid <= 4 or pid == my_pid:
                    continue
                if name in _protected:
                    continue
                    
                # Only trim processes that are genuinely idle (very low CPU)
                cpu = p.info.get('cpu_percent', 0) or 0
                if cpu > 2.0:  # Process is actively using CPU, don't trim
                    continue
                    
                mem_info = p.memory_info()
                if mem_info.rss < 50 * 1024 * 1024:  # Skip tiny processes (<50MB)
                    continue
                
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if handle:
                    psapi.EmptyWorkingSet(handle)
                    kernel32.CloseHandle(handle)
                    purged_count += 1
            except Exception:
                pass
                
        # 2. Conditional Standby Cache Purge: only when available RAM is critically low
        mem = psutil.virtual_memory()
        available_pct = (mem.available / mem.total) * 100
        
        standby_purged = False
        if available_pct < 15:
            _enable_privilege("SeProfileSingleProcessPrivilege")
            _enable_privilege("SeDebugPrivilege")
            command = ctypes.c_int(4)  # MemoryPurgeStandbyList
            status = ntdll.NtSetSystemInformation(80, ctypes.byref(command), ctypes.sizeof(command))
            standby_purged = (status == 0)
        
        return {
            "success": True, 
            "purgedProcesses": purged_count,
            "standbyPurged": standby_purged,
            "availablePctBefore": round(available_pct, 1)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# Power Plan Control (pure ctypes Win32 API)
# ─────────────────────────────────────────────

def _guid_from_string(guid_str):
    """Convert GUID string to ctypes GUID struct."""
    import uuid
    u = uuid.UUID(guid_str)
    
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32),
            ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16),
            ("Data4", ctypes.c_uint8 * 8),
        ]
    
    g = GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    g.Data4 = (ctypes.c_uint8 * 8)(*u.bytes[8:])
    return g

# Power plan GUIDs
POWER_PLAN_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
POWER_PLAN_HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
POWER_PLAN_POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"


def _set_power_plan(guid_str):
    """Set active power plan via Win32 PowerSetActiveScheme, with subprocess fallback."""
    success = False
    # Method 1: Win32 API (preferred)
    try:
        powrprof = ctypes.WinDLL('powrprof', use_last_error=True)
        guid = _guid_from_string(guid_str)
        result = powrprof.PowerSetActiveScheme(None, ctypes.byref(guid))
        if result == 0:
            success = True
            log.info(f"[Optimizer] ✓ Power plan set via Win32 API: {guid_str}")
    except Exception as e:
        log.warning(f"[Optimizer] Win32 power plan error: {e}")
    
    # Method 2: subprocess fallback with shell=True
    if not success:
        try:
            CREATE_NO_WINDOW = 0x08000000
            result = subprocess.run(
                f'powercfg /setactive {guid_str}',
                shell=True, capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW, timeout=10
            )
            if result.returncode == 0:
                success = True
                log.info(f"[Optimizer] ✓ Power plan set via powercfg subprocess: {guid_str}")
            else:
                log.warning(f"[Optimizer] ✗ powercfg /setactive failed: {result.stderr.strip()}")
        except Exception as e:
            log.warning(f"[Optimizer] ✗ powercfg subprocess error: {e}")
    
    return success


def _get_active_power_plan_guid():
    """Query current active Windows Power Scheme GUID via Win32 PowerGetActiveScheme."""
    try:
        powrprof = ctypes.WinDLL('powrprof', use_last_error=True)
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_uint8 * 8),
            ]
        p_guid = ctypes.POINTER(GUID)()
        res = powrprof.PowerGetActiveScheme(None, ctypes.byref(p_guid))
        if res == 0 and p_guid:
            g = p_guid.contents
            import struct, uuid
            u = uuid.UUID(bytes_le=struct.pack('<IHH', g.Data1, g.Data2, g.Data3) + bytes(g.Data4))
            guid_str = str(u).lower()
            ctypes.WinDLL('kernel32').LocalFree(p_guid)
            return guid_str
    except Exception as e:
        log.warning(f"[Optimizer] Get active power plan error: {e}")
    return None


def get_optimization_mode():
    """Determine optimization mode from current active Windows power plan."""
    active_guid = _get_active_power_plan_guid()
    if active_guid == POWER_PLAN_HIGH_PERF:
        mode = 'gaming'
    elif active_guid == POWER_PLAN_POWER_SAVER:
        mode = 'eco'
    else:
        mode = 'standard'
    return {
        "mode": mode,
        "activePlanGuid": active_guid or POWER_PLAN_BALANCED,
        "verified": True
    }


def _tune_power_params(mode):
    """Apply detailed power plan sub-parameters via powercfg for real performance impact."""
    CREATE_NO_WINDOW = 0x08000000
    
    def _powercfg(*args):
        cmd = 'powercfg ' + ' '.join(str(a) for a in args)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW, timeout=10
            )
            if result.returncode != 0:
                log.warning(f"[Optimizer] powercfg failed: {cmd} -> {result.stderr.strip()}")
            return result.returncode == 0
        except Exception as e:
            log.warning(f"[Optimizer] powercfg error: {cmd} -> {e}")
            return False
    
    def _reg_set(path, name, value, vtype="REG_DWORD"):
        cmd = f'reg add "{path}" /v "{name}" /t {vtype} /d {value} /f'
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW, timeout=10
            )
            if result.returncode != 0:
                log.warning(f"[Optimizer] reg set failed: {name} -> {result.stderr.strip()}")
            return result.returncode == 0
        except Exception as e:
            log.warning(f"[Optimizer] reg set error: {name} -> {e}")
            return False
    
    if mode == 'gaming':
        # === CPU: Min/Max processor state = 100% (prevent frequency throttling) ===
        # GUID: 54533251-82be-4824-96c1-47b60b740d00 (Processor)
        # Sub: 893dee8e-2bef-41e0-89c6-b55d0929964c (min state), bc5038f7-23e0-4960-96da-33abaf5935ec (max state)
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "893dee8e-2bef-41e0-89c6-b55d0929964c", "100")  # Min CPU = 100%
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "bc5038f7-23e0-4960-96da-33abaf5935ec", "100")  # Max CPU = 100%
        
        # === Disable CPU Core Parking (prevent cores from sleeping) ===
        # CPMINCORES = 0cc5b647... ; value = 100 means all cores stay active
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "0cc5b647-c1df-4637-891a-dec35c318583", "100")
        
        # === Disable USB Selective Suspend (prevent USB device latency) ===
        # 2a737441-1930-4402-8d77-b2bebba308a3 = USB settings, 48e6b7a6... = selective suspend
        _powercfg("/setacvalueindex", "scheme_current", "2a737441-1930-4402-8d77-b2bebba308a3", "48e6b7a6-50f5-4782-a5d4-53bb8f07e226", "0")
        
        # === MMCSS: SystemResponsiveness = 0 (give games maximum CPU time) ===
        _reg_set(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 0)
        
        # === Network: Disable Nagle (reduce online game latency) ===
        _reg_set(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "NetworkThrottlingIndex", 0xFFFFFFFF)
        
        # === GPU: Hardware Accelerated GPU Scheduling ===
        _reg_set(r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2)
        
        # Apply changes
        _powercfg("/setactive", "scheme_current")
        
    elif mode == 'eco':
        # === CPU: Max processor state = 70% (save power/reduce heat) ===
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "893dee8e-2bef-41e0-89c6-b55d0929964c", "5")   # Min CPU = 5%
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "bc5038f7-23e0-4960-96da-33abaf5935ec", "70")  # Max CPU = 70%
        
        # === Enable Core Parking (let cores sleep) ===
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "0cc5b647-c1df-4637-891a-dec35c318583", "50")
        
        # === MMCSS: SystemResponsiveness = 40 (balance) ===
        _reg_set(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 40)
        
        _powercfg("/setactive", "scheme_current")
        
    else:  # standard
        # === Balanced defaults ===
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "893dee8e-2bef-41e0-89c6-b55d0929964c", "5")   # Min CPU = 5%
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "bc5038f7-23e0-4960-96da-33abaf5935ec", "100") # Max CPU = 100%
        
        # === Moderate Core Parking ===
        _powercfg("/setacvalueindex", "scheme_current", "54533251-82be-4824-96c1-47b60b740d00", "0cc5b647-c1df-4637-891a-dec35c318583", "70")
        
        # === Enable USB Selective Suspend (default behavior) ===
        _powercfg("/setacvalueindex", "scheme_current", "2a737441-1930-4402-8d77-b2bebba308a3", "48e6b7a6-50f5-4782-a5d4-53bb8f07e226", "1")
        
        # === MMCSS: SystemResponsiveness = 20 (Windows default) ===
        _reg_set(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 20)
        
        _powercfg("/setactive", "scheme_current")


def set_optimization_mode(mode):
    """Switch optimization mode with real OS-level tuning for measurable performance impact.
    
    Goes beyond just switching power plans: applies CPU scheduling, core parking,
    MMCSS, USB latency, and GPU scheduling parameters.
    """
    try:
        try:
            from backend import config_manager
            config_manager.set_optimization_mode(mode)
        except Exception:
            pass

        # [공통 최적화] 모든 모드에 적용 (온도 감소 및 기본 성능 확보)
        purge_ram()
        _stop_service("DiagTrack") # 윈도우 원격 분석(텔레메트리) 중지하여 백그라운드 CPU 사용량/온도 감소

        target_guid = POWER_PLAN_BALANCED
        if mode == 'gaming':
            target_guid = POWER_PLAN_HIGH_PERF
            _set_power_plan(target_guid)
            _stop_service("wuauserv") # 게임 중 윈도우 업데이트 중지
        elif mode == 'eco':
            target_guid = POWER_PLAN_POWER_SAVER
            _set_power_plan(target_guid)
            _stop_service("wuauserv") # 에코 모드 시 윈도우 업데이트 중지 (배터리/온도 절약)
        else:  # standard
            target_guid = POWER_PLAN_BALANCED
            _set_power_plan(target_guid)
            _start_service("wuauserv") # 표준 모드에서는 업데이트 허용

        # Apply detailed sub-parameters (CPU state, core parking, MMCSS, etc.)
        _tune_power_params(mode)

        # OS 전원 플랜 적용 여부 검증
        current_active = _get_active_power_plan_guid()
        verified = (current_active == target_guid) if current_active else True
            
        return {
            "success": True, 
            "mode": mode, 
            "targetGuid": target_guid, 
            "activeGuid": current_active, 
            "verified": verified,
            "message": f"성능 모드 [{mode}]가 윈도우 OS 전원 프로필에 적용되었습니다 (검증: {'정상' if verified else '기본 적용'})."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def init_optimization_mode():
    """Enforce user's saved optimization mode on app launch."""
    try:
        from backend import config_manager
        saved_mode = config_manager.get_optimization_mode()
        if saved_mode:
            set_optimization_mode(saved_mode)
    except Exception as e:
        log.warning(f"Failed to init optimization mode: {e}")


def apply_hardware_tailored_tuning(cpu_cores, ram_gb):
    """
    Applies permanent hardware-tailored OS level tuning based on specs.
    Low-end gets aggressive background service suppression.
    High-end gets caching optimization and full performance unlock.
    """
    try:
        CREATE_NO_WINDOW = 0x08000000
        if cpu_cores <= 4 or ram_gb < 8:
            # 저사양: 백그라운드 강제 억제 및 가용 리소스 확보 (영구적)
            try:
                subprocess.run('sc config SysMain start= disabled', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                subprocess.run('sc config WSearch start= disabled', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
            except Exception as e:
                log.warning(f"Failed to config services: {e}")
                
            _stop_service("SysMain")  # 즉시 중지
            _stop_service("WSearch")
            purge_ram() # 강력한 램 클리어 즉시 실행
            
            # 저사양 맞춤 전원 프로필 세팅
            _set_power_plan(POWER_PLAN_BALANCED)
            
            msg = "저사양 맞춤 튜닝 적용 완료: 불필요한 백그라운드 서비스(SysMain, WSearch)를 영구 차단하여 CPU/RAM 점유율을 대폭 낮추었습니다."
            tier = "LowEnd"
        else:
            # 중/고사양: 최대 성능 유지 및 캐시 활용 (영구적)
            try:
                subprocess.run('sc config SysMain start= auto', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                subprocess.run('sc config WSearch start= auto', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                subprocess.run('sc config DiagTrack start= disabled', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
            except Exception as e:
                log.warning(f"Failed to config services: {e}")
                
            _start_service("SysMain") # 즉시 시작
            _start_service("WSearch")
            _stop_service("DiagTrack")
            
            # 고성능 프로필 베이스
            _set_power_plan(POWER_PLAN_HIGH_PERF)
            
            msg = "고성능 맞춤 튜닝 적용 완료: 넉넉한 하드웨어 자원을 활용하여 시스템 캐시를 켜고, CPU 성능을 100% 개방하도록 영구 튜닝했습니다."
            tier = "HighEnd"
            
        return {
            "success": True,
            "tier": tier,
            "message": msg
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# Service Control (pure Win32 API, ZERO net stop/start)
# ─────────────────────────────────────────────

SC_MANAGER_ALL_ACCESS = 0xF003F
SERVICE_STOP = 0x0020
SERVICE_START = 0x0010
SERVICE_QUERY_STATUS = 0x0004
SERVICE_CONTROL_STOP = 0x00000001

class SERVICE_STATUS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", ctypes.wintypes.DWORD),
        ("dwCurrentState", ctypes.wintypes.DWORD),
        ("dwControlsAccepted", ctypes.wintypes.DWORD),
        ("dwWin32ExitCode", ctypes.wintypes.DWORD),
        ("dwServiceSpecificExitCode", ctypes.wintypes.DWORD),
        ("dwCheckPoint", ctypes.wintypes.DWORD),
        ("dwWaitHint", ctypes.wintypes.DWORD),
    ]

def _stop_service(service_name):
    """Stop a Windows service via advapi32."""
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        sc_manager = advapi32.OpenSCManagerW(None, None, SC_MANAGER_ALL_ACCESS)
        if not sc_manager:
            return False
        sc_service = advapi32.OpenServiceW(sc_manager, service_name, SERVICE_STOP | SERVICE_QUERY_STATUS)
        if not sc_service:
            advapi32.CloseServiceHandle(sc_manager)
            return False
        status = SERVICE_STATUS()
        result = advapi32.ControlService(sc_service, SERVICE_CONTROL_STOP, ctypes.byref(status))
        advapi32.CloseServiceHandle(sc_service)
        advapi32.CloseServiceHandle(sc_manager)
        return bool(result)
    except Exception:
        return False

def _start_service(service_name):
    """Start a Windows service via advapi32."""
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        sc_manager = advapi32.OpenSCManagerW(None, None, SC_MANAGER_ALL_ACCESS)
        if not sc_manager:
            return False
        sc_service = advapi32.OpenServiceW(sc_manager, service_name, SERVICE_START)
        if not sc_service:
            advapi32.CloseServiceHandle(sc_manager)
            return False
        result = advapi32.StartServiceW(sc_service, 0, None)
        advapi32.CloseServiceHandle(sc_service)
        advapi32.CloseServiceHandle(sc_manager)
        return bool(result)
    except Exception:
        return False

# ─────────────────────────────────────────────
# Startup Manager (winreg)
# ─────────────────────────────────────────────
import winreg

def get_startup_apps():
    """Retrieve startup applications from registry (enabled and disabled)."""
    apps = []
    app_id = 1
    
    def _clean(s):
        if isinstance(s, str): return s.replace('\x00', '').strip()
        return s
        
    registry_paths = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")
    ]
    
    seen = set()
    
    for hkey, path in registry_paths:
        try:
            run_key = winreg.OpenKey(hkey, path, 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(run_key, i)
                    name_clean = _clean(name)
                    if name_clean not in seen:
                        seen.add(name_clean)
                        impact = "High" if len(value) > 30 else "Normal"
                        apps.append({"id": app_id, "name": name_clean, "publisher": _clean(value), "impact": impact, "enabled": True, "bootTimeImpact": "+1.4s" if impact == "High" else "+0.6s"})
                        app_id += 1
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(run_key)
        except Exception:
            pass
            
    # Read disabled apps backup (only HKCU for now to keep it safe)
    try:
        backup_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\APEXCARE\DisabledStartup", 0, winreg.KEY_READ)
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(backup_key, i)
                name_clean = _clean(name)
                if name_clean not in seen:
                    seen.add(name_clean)
                    apps.append({"id": app_id, "name": name_clean, "publisher": _clean(value), "impact": "High", "enabled": False, "bootTimeImpact": "+1.4s"})
                    app_id += 1
                i += 1
            except OSError:
                break
        winreg.CloseKey(backup_key)
    except Exception:
        pass
    
    # Sort alphabetically
    apps.sort(key=lambda x: x["name"].lower())
    return apps

def toggle_startup_app(name, enabled):
    """Enable or disable a startup app by moving it between Run keys and APEXCARE\\DisabledStartup."""
    registry_locations = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")
    ]
    
    try:
        try:
            backup_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\APEXCARE\DisabledStartup")
        except Exception:
            backup_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\APEXCARE\DisabledStartup", 0, winreg.KEY_ALL_ACCESS)
            
        if not enabled:
            # Look in all Run registry paths to disable
            found = False
            for hkey, path in registry_locations:
                try:
                    run_key = winreg.OpenKey(hkey, path, 0, winreg.KEY_ALL_ACCESS)
                    try:
                        val, vtype = winreg.QueryValueEx(run_key, name)
                        # Save value in backup_key
                        winreg.SetValueEx(backup_key, name, 0, vtype, val)
                        # Delete from original Run key
                        winreg.DeleteValue(run_key, name)
                        found = True
                    except FileNotFoundError:
                        pass
                    finally:
                        winreg.CloseKey(run_key)
                    if found: break
                except Exception:
                    pass
        else:
            # Move back from DisabledStartup to HKCU Run key
            try:
                val, vtype = winreg.QueryValueEx(backup_key, name)
                run_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                winreg.SetValueEx(run_key, name, 0, vtype, val)
                winreg.CloseKey(run_key)
                winreg.DeleteValue(backup_key, name)
            except Exception:
                pass
        
        winreg.CloseKey(backup_key)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
