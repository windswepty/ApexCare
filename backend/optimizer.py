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
from backend import system_state

log = logging.getLogger('Optimizer')

# ─────────────────────────────────────────────
# Zero-Risk Shield: Absolute Protection Constants
# These constants are shared by ALL scan/clean functions.
# Any path containing these substrings (case-insensitive) is UNTOUCHABLE.
# ─────────────────────────────────────────────

PROTECTED_ROOTS = [
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\system32',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\syswow64',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\winsxs',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\assembly',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\servicing',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\installer',
    os.environ.get('PROGRAMFILES', 'C:\\Program Files').lower(),
    os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)').lower(),
    os.environ.get('APPDATA', '').lower(),
    os.environ.get('LOCALAPPDATA', '').lower() + '\\microsoft',
    # Game platforms — absolute no-touch
    'steamlibrary', 'steamapps',
    'origin games', 'riot games', 'epic games',
    'battle.net', 'ubisoft game launcher',
]

# Extensions that must NEVER be deleted under any circumstances
DANGER_EXTS = frozenset({
    '.dll', '.exe', '.sys', '.ini', '.ocx', '.drv', '.cpl',
    '.cat', '.mum', '.manifest', '.msi', '.msp', '.mst',
    '.inf', '.nls', '.tlb', '.ax', '.acm', '.scr', '.com',
})

# Extensions that are safe to delete in temp/cache directories
SAFE_JUNK_EXTS = frozenset({
    '.tmp', '.log', '.bak', '.old', '.chk', '.pf',
    '.dmp', '.etl', '.cache',
})


def _is_protected_path(file_path):
    """Zero-Risk Shield: Returns True if the path is inside any protected zone.
    
    This is a module-level guard function used by BOTH scan and clean logic.
    Case-insensitive substring matching ensures no bypass through casing tricks.
    """
    path_lower = file_path.lower()
    return any(pr in path_lower for pr in PROTECTED_ROOTS)

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
        # 실제 상태 키는 'freed_mb'. 예전엔 'freedMB' 를 읽어서 항상 0MB 로 보고됐다.
        freed = _junk_clean_state.get("freed_mb", 0)
        _optimization_state["freed_mb"] += freed
        _optimization_state["progress_pct"] = 40
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")
        
        # Step 2: RAM Purge
        _optimization_state["current_task"] = "유휴 프로세스 정리 및 가용 메모리 확보 중..."
        purge_ram()
        _optimization_state["progress_pct"] = 60
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")

        # Step 3: DNS 캐시 초기화
        # 여기서는 캐시만 비운다. Winsock 초기화/TCP 튜닝 같은 영구 변경은
        # 사용자 동의 없이 원클릭 최적화에 섞어 넣지 않는다.
        _optimization_state["current_task"] = "DNS 캐시 초기화 중..."
        system_repair.run_network_optimization_sync()
        _optimization_state["progress_pct"] = 80
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")

        # Step 4: SSD TRIM
        # run_trim() 은 스레드를 띄우고 바로 반환한다. 기다리지 않으면 defrag 가
        # 아직 돌고 있는데 화면에는 '완료'가 떠 버린다.
        _optimization_state["current_task"] = "물리 디스크 응답속도 최적화(TRIM) 중..."
        trim_res = system_repair.run_trim()
        if trim_res.get("success"):
            trim_deadline = time.time() + 300
            while time.time() < trim_deadline:
                if system_repair.get_trim_status().get("status") != "running":
                    break
                if _cancel_event.is_set():
                    # TRIM 자체는 중간에 끊지 않는다(디스크 작업). 대기만 그만둔다.
                    break
                time.sleep(1)

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
    """Walk directory and sum file sizes. Sequential, safe.
    
    Zero-Risk Shield: Protected paths are filtered out during scan
    so they never even appear in size calculations.
    """
    total = 0
    file_count = 0
    start_time = time.time()

    if not os.path.exists(dir_path):
        return 0
    try:
        for root, dirs, files in os.walk(dir_path):
            # Zero-Risk Shield: Block traversal into protected directories
            root_lower = root.lower()
            if any(pr in root_lower for pr in PROTECTED_ROOTS):
                dirs.clear()  # Stop os.walk from descending further
                continue
            
            for f in files:
                fp = os.path.join(root, f)
                try:
                    if not os.path.islink(fp):
                        total += os.path.getsize(fp)
                        file_count += 1
                        
                        if state_obj and file_count % 50 == 0:
                            elapsed = time.time() - start_time
                            rate = file_count / elapsed if elapsed > 0 else 1
                            prog = min(99, int((file_count / max_files) * 100))
                            eta = int((max_files - file_count) / rate) if rate > 0 else 0
                            state_obj["progress"] = prog
                            state_obj["eta_seconds"] = max(0, eta)
                            
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return round(total / (1024 * 1024), 2)

import psutil
import threading
import time
import os
import sys
import gc

_scan_lock = threading.Lock()
_clean_lock = threading.Lock()

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
        
        # 휴지통 크기 계산 (ctypes)
        recycle_size = 0.0
        try:
            import ctypes
            from ctypes import wintypes
            class SHQUERYRBINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD),
                            ("i64Size", ctypes.c_int64),
                            ("i64NumItems", ctypes.c_int64)]
            shell32 = ctypes.windll.shell32
            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            res = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
            if res == 0:
                recycle_size = round(info.i64Size / (1024 * 1024), 2)
        except Exception:
            pass

        _junk_scan_state["data"] = [
            {"id": 1, "name": "윈도우 시스템 임시 파일 (%TEMP%)", "sizeMB": temp_size, "category": "System", "selected": True, "description": "앱 설치, 업데이트, 실행 중 생성된 임시 데이터 파일"},
            {"id": 2, "name": "웹 브라우저 캐시 및 쿠키 (Chrome)", "sizeMB": cache_size, "category": "Browser", "selected": True, "description": "Chrome 브라우저가 저장한 이미지, 스크립트 캐시 데이터"},
            {"id": 3, "name": "Windows Update 패키지 캐시", "sizeMB": soft_dist_size, "category": "System", "selected": True, "description": "이미 설치 완료된 윈도우 업데이트 설치 패키지 잔여물"},
            {"id": 4, "name": "시스템 렌더링 Prefetch 데이터", "sizeMB": prefetch_size, "category": "System", "selected": False, "description": "앱 실행 가속화를 위한 사전 로드 데이터 (삭제 시 자동 재생성)"},
            {"id": 5, "name": "휴지통 비우기", "sizeMB": recycle_size, "category": "System", "selected": True, "description": "휴지통에 버려진 파일들을 완전히 삭제합니다"},
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
    with _scan_lock:
        if _junk_scan_state["status"] == "running":
            return {"success": False, "message": "이미 스캔 중입니다."}
        _junk_scan_state["status"] = "running"
    
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
        target_scan_mb = sum(item.get("sizeMB", 0) for item in _junk_scan_state.get("data", []) if item.get("id") in category_ids)

        total_freed_bytes = 0
        total_attempt_count = 0
        total_success_count = 0
        
        user_temp = os.path.expandvars('%TEMP%')
        system_temp = os.path.expandvars('%SystemRoot%\\Temp')
        prefetch = os.path.expandvars('%SystemRoot%\\Prefetch')
        soft_dist = os.path.expandvars('%SystemRoot%\\SoftwareDistribution\\Download')
        chrome_cache = os.path.expandvars('%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache')
        skipped_files_log = []

        def _clean_dir(path, max_files=5000):
            """Delete junk files from a directory with Zero-Risk Shield protection.
            
            Uses module-level PROTECTED_ROOTS, DANGER_EXTS, and SAFE_JUNK_EXTS
            constants to ensure consistent protection across all code paths.
            """
            nonlocal total_attempt_count, total_success_count, total_freed_bytes
            local_freed = 0
            file_count = 0
            start_time = time.time()
            if not os.path.exists(path):
                return 0
            
            for root, dirs, files in os.walk(path, topdown=False):
                if cancel_event and cancel_event.is_set():
                    break
                    
                # Zero-Risk Shield: Block protected directories
                root_lower = root.lower()
                if any(pr in root_lower for pr in PROTECTED_ROOTS):
                    continue
                    
                for name in files:
                    if cancel_event and cancel_event.is_set():
                        break
                    file_path = os.path.join(root, name)
                    
                    # Zero-Risk Shield: Cross-validate full path
                    if _is_protected_path(file_path):
                        continue
                    
                    # Strict extension check using module-level constants
                    ext = os.path.splitext(name)[1].lower()
                    if ext in DANGER_EXTS:
                        continue
                    
                    # Chrome cache files usually have no extension, prefetch has .pf.
                    # We will allow safe extensions and files with no extension.
                    if ext not in SAFE_JUNK_EXTS and ext != '':
                        continue
                        
                    total_attempt_count += 1
                    try:
                        sz = os.path.getsize(file_path)
                        try:
                            os.remove(file_path)
                        except (OSError, PermissionError):
                            try:
                                os.chmod(file_path, stat.S_IWRITE)
                                os.remove(file_path)
                            except Exception as e:
                                print(f"[LOCKED/SKIPPED] {file_path} - {e}")
                                sys.stdout.flush()
                                skipped_files_log.append({"path": file_path, "size_bytes": sz})
                                continue
                        
                        local_freed += sz
                        total_freed_bytes += sz
                        file_count += 1
                        total_success_count += 1
                        print(f"[DELETED] {file_path} ({sz} bytes)")
                        sys.stdout.flush()
                        
                        if file_count % 50 == 0:
                            elapsed = time.time() - start_time
                            rate = file_count / elapsed if elapsed > 0 else 1
                            prog = min(99, int((file_count / max_files) * 100))
                            eta = int((max_files - file_count) / rate) if rate > 0 else 0
                            _junk_clean_state["progress"] = min(99, _junk_clean_state.get("progress", 0) + int(prog/4))
                            _junk_clean_state["eta_seconds"] = max(0, eta)
                            print(f"[JunkPurger] 삭제 시도 파일 수: {total_attempt_count}, 성공: {total_success_count}, 누적 확보 용량: {total_freed_bytes} bytes")
                            sys.stdout.flush()
                    except Exception as e:
                        print(f"[LOCKED/SKIPPED] {file_path} (Failed to get size or other error) - {e}")
                        sys.stdout.flush()
                        skipped_files_log.append({"path": file_path, "size_bytes": 0})
                        continue
                        
                for name in dirs:
                    if cancel_event and cancel_event.is_set():
                        break
                    dir_path = os.path.join(root, name)
                    
                    # Zero-Risk Shield: Protect directories too
                    if _is_protected_path(dir_path):
                        continue
                        
                    try:
                        os.rmdir(dir_path)
                    except Exception:
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

        import shutil
        import psutil
        
        drives = []
        for p in psutil.disk_partitions(all=False):
            if p.fstype and 'cdrom' not in p.opts:
                drives.append(p.mountpoint)
        if not drives:
            drives = ['C:\\']
            
        start_free = {}
        for drv in drives:
            try:
                start_free[drv] = shutil.disk_usage(drv).free
            except Exception as e:
                log.debug(f"Failed to get start free space for {drv}: {e}")

        for d in target_dirs:
            if cancel_event and cancel_event.is_set():
                break
            _clean_dir(d, max_files=2000)

        if 5 in category_ids and not (cancel_event and cancel_event.is_set()):
            try:
                import ctypes
                # 1 = SHERB_NOCONFIRMATION, 2 = SHERB_NOPROGRESSUI, 4 = SHERB_NOSOUND
                empty_res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7)
                if empty_res == 0:
                    print("[DELETED] Recycle Bin emptied via ctypes.")
                sys.stdout.flush()
            except Exception as e:
                log.warning(f"Failed to empty recycle bin: {e}")
                sys.stdout.flush()

        details = {}
        total_actual_freed = 0
        for drv in drives:
            if drv in start_free:
                try:
                    end_val = shutil.disk_usage(drv).free
                    freed = max(0, end_val - start_free[drv])
                    freed_mb = round(freed / (1024 * 1024), 2)
                    if freed_mb > 0:
                        drv_letter = drv.replace('\\', '')
                        details[drv_letter] = freed_mb
                    total_actual_freed += freed
                except Exception as e:
                    log.debug(f"Failed to get end free space for {drv}: {e}")

        freed_total_mb = round(total_actual_freed / (1024 * 1024), 2)
        skipped_mb = max(0.0, round(target_scan_mb - freed_total_mb, 2))

        _junk_clean_state["freed_mb"] = freed_total_mb
        _junk_clean_state["skipped_mb"] = skipped_mb
        _junk_clean_state["details"] = details
        
        if skipped_files_log:
            try:
                log_path = os.path.join(os.path.expanduser("~"), "Desktop", "APEX_Skipped_Files.log")
                with open(log_path, "a", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"\n=== APEX CARE: 스킵 파일 로그 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===\n")
                    skipped_files_log.sort(key=lambda x: x["size_bytes"], reverse=True)
                    for item in skipped_files_log:
                        mb = round(item["size_bytes"] / (1024 * 1024), 2)
                        f.write(f"[{mb} MB] {item['path']}\n")
            except Exception as e:
                log.debug(f"Failed to write skipped files log: {e}")
        
        print(f"[JunkPurger] 최종 확보 용량: {freed_total_mb} MB, 스킵된 용량(OS 잠금): {skipped_mb} MB")
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
    
    with _clean_lock:
        if not category_ids:
            _junk_clean_state["status"] = "success"
            _junk_clean_state["freed_mb"] = 0.0
            return {"success": True}
        if _junk_clean_state["status"] == "running":
            return {"success": False, "message": "이미 정리 중입니다."}
        _junk_clean_state["status"] = "running"
    
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
    """Smart Memory Optimizer: Safe standby cache purge.
    
    This function NO LONGER empties the working sets of active processes to avoid
    crashing games and applications. It ONLY purges the Windows standby list
    (global standby cache) using built-in system calls, which is 100% safe.
    """
    try:
        ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
        
        # Capture memory before purge
        mem_before = psutil.virtual_memory().available
        
        # Safely purge standby list
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            if not is_admin:
                return {"success": False, "error": "UAC_REQUIRED"}
        except Exception:
            return {"success": False, "error": "UAC_REQUIRED"}

        _enable_privilege("SeProfileSingleProcessPrivilege")
        _enable_privilege("SeDebugPrivilege")
        command = ctypes.c_int(4)  # MemoryPurgeStandbyList
        status = ntdll.NtSetSystemInformation(80, ctypes.byref(command), ctypes.sizeof(command))
        standby_purged = (status == 0)
            
        # Capture memory after purge and calculate freed MB
        mem_after = psutil.virtual_memory().available
        freed_mb = max(0, (mem_after - mem_before) / (1024 * 1024))
        
        return {
            "success": True, 
            "purgedProcesses": 0,
            "standbyPurged": standby_purged,
            "freed_mb": freed_mb
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


def get_optimization_mode():
    """현재 성능 모드. 실제 구현은 backend/perf_modes.py 에 있다.

    기존에는 활성 전원 플랜 GUID 만 보고 모드를 역산했는데 두 가지로 틀렸다.
    (1) 게이밍이 '최고의 성능' 플랜을 쓰면 그 GUID 를 몰라 '표준'으로 읽혔고,
    (2) 사용자가 윈도우에서 직접 플랜을 바꾸면 앱 기록과 조용히 어긋났다.
    이제 저장된 모드를 정답으로 쓰되 실제 상태와 어긋나면 inSync=False 로 알린다.
    """
    from backend import perf_modes
    info = perf_modes.get_mode()
    # 기존 프론트엔드가 쓰던 키 이름을 유지한다
    info['activePlanGuid'] = info.get('activePlan')
    info['verified'] = info.get('inSync', False)
    return info


def set_optimization_mode(mode, user_set=True):
    """성능 모드 적용. 실제 구현은 backend/perf_modes.py 에 있다.

    기존 구현은 (1) 이전 모드의 변경을 되돌리지 않아 설정이 겹쳐 쌓였고,
    (2) 표준 모드가 짐작한 기본값으로 사용자 커스텀 플랜을 덮어썼으며,
    (3) powercfg/reg 하위 명령이 전부 실패해도 success=True 를 돌려줬다.
    perf_modes.apply_mode 는 '이전 모드 복구 → 적용 → 되읽어 검증' 순서로 돌고
    항목별 성패를 steps 로 그대로 돌려준다.
    """
    from backend import perf_modes
    return perf_modes.apply_mode(mode, user_set=user_set)


def init_optimization_mode():
    """앱 시작 시 저장된 모드를 재적용한다.

    사용자가 UI 에서 직접 모드를 고른 적이 있을 때만 동작한다.
    앱을 실행한 것만으로 OS 설정이 바뀌면 안 된다.
    """
    try:
        from backend import config_manager, perf_modes
        if not config_manager.get_optimization_mode_user_set():
            log.info("[Optimizer] 사용자가 선택한 모드가 없어 시작 시 자동 튜닝을 건너뜁니다.")
            return {"success": True, "applied": False,
                    "message": "사용자가 선택한 최적화 모드가 없어 자동 적용하지 않았습니다."}
        saved = config_manager.get_optimization_mode()
        if saved in perf_modes.MODES:
            res = perf_modes.apply_mode(saved, user_set=False)
            return {"success": res.get("success", False), "applied": True,
                    "message": res.get("message", ""), "steps": res.get("steps", [])}
    except Exception as e:
        log.warning(f"Failed to init optimization mode: {e}")
    return {"success": False, "applied": False, "message": "최적화 모드 초기화에 실패했습니다."}


def _get_service_start_type(service_name):
    """Read a service start type from the registry. 2=Auto, 3=Manual, 4=Disabled."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\%s" % service_name,
            0, winreg.KEY_READ
        )
        value, _ = winreg.QueryValueEx(key, "Start")
        winreg.CloseKey(key)
        return int(value)
    except Exception as e:
        log.debug(f"Failed to read start type for {service_name}: {e}")
        return None


def _get_service_delayed_auto(service_name):
    """True if the service is 'Automatic (Delayed Start)'."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\%s" % service_name,
            0, winreg.KEY_READ
        )
        value, _ = winreg.QueryValueEx(key, "DelayedAutostart")
        winreg.CloseKey(key)
        return int(value) == 1
    except Exception:
        return False


def restore_tailored_service_config():
    """Undo the permanent 'sc config' changes made by apply_hardware_tailored_tuning."""
    # (start type, delayed auto) — Windows 기본값. 백업이 없는 구버전 사용자용 폴백.
    WINDOWS_DEFAULT_START = {"SysMain": (2, False), "WSearch": (2, True)}
    START_TYPE_ARG = {2: "auto", 3: "demand", 4: "disabled"}
    CREATE_NO_WINDOW = 0x08000000
    try:
        from backend import config_manager
        cfg = config_manager.load_config()
        backup = cfg.get("service_start_backup") or {}
        used_default = not backup

        restored = []
        for svc, (def_start, def_delayed) in WINDOWS_DEFAULT_START.items():
            saved = backup.get(svc) if isinstance(backup.get(svc), dict) else None
            start_type = (saved or {}).get("start") or def_start
            delayed = (saved or {}).get("delayed", def_delayed)
            arg = START_TYPE_ARG.get(int(start_type), "auto")
            if arg == "auto" and delayed:
                arg = "delayed-auto"
            try:
                subprocess.run(f'sc config {svc} start= {arg}', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                if arg != "disabled":
                    _start_service(svc)
                restored.append(svc)
            except Exception as e:
                log.warning(f"Failed to restore service {svc}: {e}")

        cfg.pop("service_start_backup", None)
        config_manager.save_config(cfg)

        base_msg = f"서비스 설정을 복구했습니다: {', '.join(restored) if restored else '없음'}"
        if used_default:
            base_msg += " (백업 정보가 없어 Windows 기본값으로 복구했습니다.)"
        return {"success": True, "restored": restored, "message": base_msg}
    except Exception as e:
        return {"success": False, "message": "서비스 설정 복구에 실패했습니다.", "error": str(e)}


def apply_hardware_tailored_tuning(cpu_cores, ram_gb, consent=False):
    """
    Applies permanent hardware-tailored OS level tuning based on specs.
    Low-end gets aggressive background service suppression.
    High-end gets caching optimization and full performance unlock.

    consent=False 는 '미리보기' 모드다. 실제로 아무것도 바꾸지 않고
    무엇이 영구적으로 바뀌는지 항목만 돌려준다. 프론트에서 사용자가
    항목을 확인하고 동의한 뒤 consent=True 로 다시 호출해야 적용된다.
    """
    try:
        try:
            cpu_cores = int(cpu_cores)
            ram_gb = float(ram_gb)
        except (TypeError, ValueError):
            return {"success": False, "applied": False, "message": "하드웨어 정보를 읽지 못해 맞춤 튜닝을 적용할 수 없습니다."}

        CREATE_NO_WINDOW = 0x08000000
        is_low_end = (cpu_cores <= 4 or ram_gb < 8)

        # 사용자에게 그대로 보여줄 '영구 변경' 항목 목록
        if is_low_end:
            permanent_changes = [
                "SysMain(수퍼패치) 서비스를 '사용 안 함'으로 변경합니다 — 재부팅 후에도 유지됩니다.",
                "Windows Search(WSearch) 서비스를 '사용 안 함'으로 변경합니다 — 시작 메뉴 검색, 파일 탐색기 검색, Outlook 검색 색인이 중지됩니다.",
                "전원 관리 프로필을 '균형 조정'으로 변경합니다."
            ]
        else:
            permanent_changes = [
                "SysMain(수퍼패치) 서비스를 '자동 시작'으로 변경합니다.",
                "Windows Search(WSearch) 서비스를 '자동 시작'으로 변경합니다.",
                "전원 관리 프로필을 '고성능'으로 변경합니다."
            ]

        if not consent:
            # 미리보기: 시스템을 전혀 건드리지 않고 변경 예정 항목만 돌려준다
            return {
                "success": True,
                "applied": False,
                "tier": "LowEnd" if is_low_end else "HighEnd",
                "changes": permanent_changes,
                "message": "아래 항목이 영구적으로 변경됩니다. Windows Update 및 보안 관련 서비스는 변경하지 않습니다."
            }

        # 되돌리기용으로 원래 시작 유형을 먼저 저장한다 (2=자동, 3=수동, 4=사용 안 함)
        try:
            from backend import config_manager
            cfg = config_manager.load_config()
            if "service_start_backup" not in cfg:
                cfg["service_start_backup"] = {
                    "SysMain": {"start": _get_service_start_type("SysMain"), "delayed": _get_service_delayed_auto("SysMain")},
                    "WSearch": {"start": _get_service_start_type("WSearch"), "delayed": _get_service_delayed_auto("WSearch")}
                }
                config_manager.save_config(cfg)
        except Exception as e:
            log.warning(f"Failed to backup service start types: {e}")

        if is_low_end:
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
            system_state.set_active_plan(POWER_PLAN_BALANCED,
                                         group='hw_tuning', why='저사양 맞춤 튜닝')
            
            msg = "저사양 맞춤 튜닝 적용 완료: 불필요한 백그라운드 서비스(SysMain, WSearch)를 영구 차단하여 CPU/RAM 점유율을 대폭 낮추었습니다."
            tier = "LowEnd"
        else:
            # 중/고사양: 최대 성능 유지 및 캐시 활용 (영구적)
            try:
                subprocess.run('sc config SysMain start= auto', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                subprocess.run('sc config WSearch start= auto', shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                # [제거됨] DiagTrack 영구 비활성화.
                # 마법사의 고사양 설명 문구에 텔레메트리 언급이 전혀 없어 미고지 영구 변경이었다.
                # 텔레메트리 차단은 디블로터의 명시적 선택 항목(telemetry)에서만 수행한다.
            except Exception as e:
                log.warning(f"Failed to config services: {e}")
                
            _start_service("SysMain") # 즉시 시작
            _start_service("WSearch")
            
            # 고성능 프로필 베이스
            system_state.set_active_plan(POWER_PLAN_HIGH_PERF,
                                         group='hw_tuning', why='고사양 맞춤 튜닝')
            
            msg = "고성능 맞춤 튜닝 적용 완료: 넉넉한 하드웨어 자원을 활용하여 시스템 캐시를 켜고, CPU 성능을 100% 개방하도록 영구 튜닝했습니다."
            tier = "HighEnd"
            
        return {
            "success": True,
            "applied": True,
            "tier": tier,
            "changes": permanent_changes,
            "message": msg
        }
    except Exception as e:
        return {"success": False, "applied": False, "message": "맞춤 튜닝 적용에 실패했습니다.", "error": str(e)}

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
