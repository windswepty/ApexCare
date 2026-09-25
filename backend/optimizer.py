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
    
    # 단계별 성패를 모은다. 예전에는 하위 단계가 전부 실패해도 마지막에
    # "완료! 시스템이 완벽하게 최적화되었습니다." 로 끝냈다.
    steps = []
    _optimization_state["steps"] = steps

    try:
        # Step 1: Deep Junk Clean (synchronous within this thread)
        _optimization_state["current_task"] = "브라우저 캐시, 임시 파일, 업데이트 잔여물 삭제 중..."
        _optimization_state["eta_seconds"] = 10
        clean_junk_background([1, 2, 3, 4], cancel_event=_cancel_event)
        # 실제 상태 키는 'freed_mb'. 예전엔 'freedMB' 를 읽어서 항상 0MB 로 보고됐다.
        freed = _junk_clean_state.get("freed_mb", 0)
        _optimization_state["freed_mb"] += freed
        junk_ok = _junk_clean_state.get("status") in ("success", "cancelled")
        steps.append({"name": "정크 파일 정리", "ok": junk_ok,
                      "detail": f"{freed}MB 확보" if junk_ok
                                else _junk_clean_state.get("error", "실패")})
        _optimization_state["progress_pct"] = 40
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")

        # Step 2: RAM Purge
        # 예전 문구 '유휴 프로세스 정리' 는 사실이 아니었다. purge_ram 은 프로세스를 건드리지 않는다.
        _optimization_state["current_task"] = "대기 메모리 비우는 중..."
        ram_res = purge_ram()
        if ram_res.get("success"):
            b, a = ram_res.get("standbyBeforeBytes"), ram_res.get("standbyAfterBytes")
            ram_detail = (f"대기 {b / 1024**3:.1f} GB → {a / 1024**3:.1f} GB"
                          if b is not None and a is not None else "전후 크기는 측정하지 못함")
        else:
            ram_detail = ram_res.get("message") or ram_res.get("error", "관리자 권한이 필요할 수 있습니다")
        steps.append({"name": "대기 메모리 비우기", "ok": bool(ram_res.get("success")), "detail": ram_detail})
        _optimization_state["progress_pct"] = 60
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")

        # Step 3: DNS 캐시 초기화
        # 여기서는 캐시만 비운다. Winsock 초기화/TCP 튜닝 같은 영구 변경은
        # 사용자 동의 없이 원클릭 최적화에 섞어 넣지 않는다.
        _optimization_state["current_task"] = "DNS 캐시 초기화 중..."
        dns_res = system_repair.run_network_optimization_sync()
        steps.append({"name": "DNS 캐시 초기화", "ok": bool(dns_res.get("success")),
                      "detail": "" if dns_res.get("success") else dns_res.get("message", "실패")})
        _optimization_state["progress_pct"] = 80
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")

        # Step 4: SSD TRIM
        # run_trim() 은 스레드를 띄우고 바로 반환한다. 기다리지 않으면 defrag 가
        # 아직 돌고 있는데 화면에는 '완료'가 떠 버린다.
        _optimization_state["current_task"] = "디스크 최적화(TRIM) 중..."
        trim_res = system_repair.run_trim()
        trim_ok = False
        if trim_res.get("success"):
            trim_deadline = time.time() + 300
            while time.time() < trim_deadline:
                st = system_repair.get_trim_status().get("status")
                if st != "running":
                    trim_ok = (st == "success")
                    break
                if _cancel_event.is_set():
                    # TRIM 자체는 중간에 끊지 않는다(디스크 작업). 대기만 그만둔다.
                    break
                time.sleep(1)
        steps.append({"name": "디스크 최적화(TRIM)", "ok": trim_ok,
                      "detail": "" if trim_ok
                                else system_repair.get_trim_status().get("error", "완료 확인 실패")})

        failed = [s for s in steps if not s["ok"]]
        _optimization_state["progress_pct"] = 100
        _optimization_state["eta_seconds"] = 0
        _optimization_state["failedCount"] = len(failed)
        _optimization_state["current_task"] = (
            f"완료 — {len(steps) - len(failed)}개 단계 성공"
            + (f", {len(failed)}개 실패" if failed else "")
        )

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
            # 기본 체크 해제. 이 목록에서 유일하게 복구가 불가능한 항목이다.
            # 다른 항목은 임시·캐시 파일이라 OS 가 다시 만들지만, 휴지통을 비우면
            # 사용자가 '나중에 확인하려고' 넣어둔 파일이 영영 사라진다.
            # 사용자가 직접 체크해야만 실행된다.
            {"id": 5, "name": "휴지통 비우기", "sizeMB": recycle_size, "category": "System",
             "selected": False, "irreversible": True,
             "description": "휴지통 안의 파일을 완전히 삭제합니다. 되돌릴 수 없습니다."},
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
    """대기 목록(Standby list)을 비운다. 실행 중인 프로세스의 작업 집합은 건드리지 않는다.

    예전 구현의 문제:
      1. NtSetSystemInformation 이 실패해도 success=True 를 돌려줬다(standbyPurged 만 False).
      2. '확보량' 을 available 전후 차이로 쟀는데, 대기 메모리는 원래 available 에 들어 있어서
         비워도 available 은 거의 변하지 않는다. 늘 0 에 가까운 값이었다.
      3. 필요 없는 SeDebugPrivilege 까지 켰다.

    이제 호출이 STATUS_SUCCESS 일 때만 성공이고, 전후 대기·여유 메모리를
    성능 카운터로 측정해 돌려준다(측정하지 못하면 None).
    """
    from backend import system_monitor

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False
    if not is_admin:
        return {"success": False, "error": "UAC_REQUIRED",
                "message": "대기 메모리를 비우려면 관리자 권한이 필요합니다."}

    try:
        before = system_monitor.memory_lists()
        priv_ok = _enable_privilege("SeProfileSingleProcessPrivilege")
        ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
        command = ctypes.c_int(4)  # MemoryPurgeStandbyList
        # 80 = SystemMemoryListInformation
        status = ntdll.NtSetSystemInformation(80, ctypes.byref(command), ctypes.sizeof(command)) & 0xFFFFFFFF
        if status != 0:
            hint = "" if priv_ok else " 권한(SeProfileSingleProcessPrivilege)을 켜지 못했습니다."
            return {"success": False, "error": f"NTSTATUS 0x{status:08X}",
                    "message": f"대기 메모리를 비우지 못했습니다 (NTSTATUS 0x{status:08X}).{hint}"}
        after = system_monitor.memory_lists()
        return {
            "success": True,
            "standbyBeforeBytes": before['standby'] if before else None,
            "standbyAfterBytes": after['standby'] if after else None,
            "freeBeforeBytes": before['free'] if before else None,
            "freeAfterBytes": after['free'] if after else None,
        }
    except Exception as e:
        detail = str(e) or type(e).__name__
        return {"success": False, "error": detail, "message": f"대기 메모리를 비우지 못했습니다: {detail}"}


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


# ─────────────────────────────────────────────
# 하드웨어 맞춤 튜닝
# ─────────────────────────────────────────────
# 서비스 시작 유형은 system_state.set_service_start 로만 바꾼다(원래 값 기록 → 변경 → 되읽어 확인).
# 되돌리기는 system_state.restore_group(HW_TUNING_GROUP) 이다.
# 실행 중인 서비스를 즉시 멈추거나 시작하지 않는다. 그 상태는 기록·복구할 수 없어서다.
# 시작 유형 변경은 다음 부팅부터 반영된다.

HW_TUNING_GROUP = 'hw_tuning'
_HW_TUNING_SERVICES = ('SysMain', 'WSearch')
_SERVICE_START_LABEL = {'auto': '자동', 'delayed-auto': '자동(지연된 시작)',
                        'demand': '수동', 'disabled': '사용 안 함'}


def _legacy_service_backup():
    """구버전이 settings.json 에 남긴 service_start_backup. 없으면 {}."""
    try:
        from backend import config_manager
        b = config_manager.load_config().get("service_start_backup")
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def restore_tailored_service_config():
    """맞춤 튜닝이 바꾼 설정을 원래대로 되돌린다.

    1) system_state 저널의 hw_tuning 그룹을 restore_group 으로 되돌린다.
    2) 구버전이 settings.json 에 남긴 service_start_backup 이 '있을 때만' 그 값으로 되돌린다.
    기록이 없으면 아무것도 바꾸지 않는다. 예전에는 백업이 없으면 추측한 Windows 기본값으로
    SysMain·WSearch 를 켜서, 앱이 바꾼 적 없는 서비스까지 바꿨다.
    """
    steps = []
    try:
        pending = {k: e for k, e in system_state.pending_changes().items()
                   if e.get('group') == HW_TUNING_GROUP}
        if pending:
            r = system_state.restore_group(HW_TUNING_GROUP)
            reasons = {f.get('key'): f.get('reason') for f in r.get('failed', [])}
            left = system_state.pending_changes()
            for k, e in pending.items():
                label = e.get('service') or e.get('why') or k
                ok = k not in left
                steps.append({"name": f"{label} 복구", "ok": ok,
                              "detail": "" if ok else (reasons.get(k) or "복구 실패")})

        backup = _legacy_service_backup()
        if backup:
            from backend import config_manager
            done = []
            for svc, saved in backup.items():
                start = saved.get("start") if isinstance(saved, dict) else None
                if svc not in _HW_TUNING_SERVICES or start not in (2, 3, 4):
                    # 읽지 못한 원래 값(None)을 기본값으로 바꿔 쓰지 않는다.
                    steps.append({"name": f"{svc} 복구(구버전 백업)", "ok": False,
                                  "detail": "백업에 원래 값이 없어 건드리지 않았습니다"})
                    continue
                ok, reason = system_state.restore_service_start(
                    svc, start, bool(saved.get("delayed")))
                steps.append({"name": f"{svc} 복구(구버전 백업)", "ok": ok, "detail": reason})
                if ok:
                    done.append(svc)
            if done:
                # 되돌린 항목만 지운다. 실패한 것은 남겨야 다시 시도할 수 있다.
                cfg = config_manager.load_config()
                b = cfg.get("service_start_backup") or {}
                for svc in done:
                    b.pop(svc, None)
                if b:
                    cfg["service_start_backup"] = b
                else:
                    cfg.pop("service_start_backup", None)
                config_manager.save_config(cfg)

        failed = [s for s in steps if not s["ok"]]
        if not steps:
            msg = "맞춤 튜닝이 바꾼 설정 기록이 없어 되돌릴 것이 없습니다."
        elif failed:
            msg = f"{len(steps)}개 중 {len(failed)}개를 되돌리지 못했습니다: {failed[0]['detail']}"
        else:
            msg = f"맞춤 튜닝 설정 {len(steps)}개를 원래대로 되돌렸습니다."
        return {"success": not failed, "steps": steps, "failedCount": len(failed),
                "restored": [s["name"] for s in steps if s["ok"]], "message": msg}
    except Exception as e:
        return {"success": False, "steps": steps, "message": "맞춤 튜닝 복구에 실패했습니다.",
                "error": str(e)}


def _service_step(svc, target, why):
    """서비스 하나의 시작 유형을 바꾸고 step 하나를 돌려준다."""
    name = f"{svc} 시작 유형 → {_SERVICE_START_LABEL[target]}"
    try:
        r = system_state.set_service_start(svc, target, HW_TUNING_GROUP, why=why)
    except Exception as e:
        r = {'ok': False, 'reason': str(e) or type(e).__name__}
    if not r.get('ok'):
        return {"name": name, "ok": False, "detail": r.get('reason') or "변경 실패"}
    if not r.get('changed'):
        return {"name": name, "ok": True, "detail": "이미 이 상태라 바꾸지 않았습니다"}
    before = _SERVICE_START_LABEL.get(r.get('before'), r.get('before'))
    return {"name": name, "ok": True, "detail": f"'{before}'에서 변경, 다음 부팅부터 반영"}


def apply_hardware_tailored_tuning(cpu_cores, ram_gb, consent=False):
    """사양에 맞춰 SysMain·WSearch 시작 유형과 전원 플랜을 조정한다.

    consent=False 는 '미리보기' 모드다. 실제로 아무것도 바꾸지 않고
    무엇이 바뀌는지 항목만 돌려준다. 프론트에서 사용자가
    항목을 확인하고 동의한 뒤 consent=True 로 다시 호출해야 적용된다.

    적용 결과는 항목별 steps 로 돌려준다. 하나라도 실패하면 success=False 다.
    """
    try:
        try:
            cpu_cores = int(cpu_cores)
            ram_gb = float(ram_gb)
        except (TypeError, ValueError):
            return {"success": False, "applied": False, "message": "하드웨어 정보를 읽지 못해 맞춤 튜닝을 적용할 수 없습니다."}

        is_low_end = (cpu_cores <= 4 or ram_gb < 8)
        tier = "LowEnd" if is_low_end else "HighEnd"

        # 사용자에게 그대로 보여줄 변경 항목 목록
        if is_low_end:
            changes = [
                "SysMain(수퍼패치) 서비스를 '사용 안 함'으로 변경합니다 — 다음 부팅부터 반영되고 재부팅 후에도 유지됩니다.",
                "Windows Search(WSearch) 서비스를 '사용 안 함'으로 변경합니다 — 다음 부팅부터 시작 메뉴 검색, 파일 탐색기 검색, Outlook 검색 색인이 중지됩니다.",
                "대기 메모리(Standby)를 한 번 비웁니다 — 일시적이며 실행 중인 프로그램은 건드리지 않습니다.",
                "전원 관리 프로필을 '균형 조정'으로 변경합니다.",
            ]
        else:
            changes = [
                "SysMain(수퍼패치) 서비스를 '자동 시작'으로 변경합니다 — 다음 부팅부터 반영됩니다.",
                "Windows Search(WSearch) 서비스를 '자동 시작'으로 변경합니다 — 이미 '자동(지연된 시작)'이면 그대로 둡니다.",
                "전원 관리 프로필을 '고성능'으로 변경합니다.",
            ]

        if not consent:
            # 미리보기: 시스템을 전혀 건드리지 않고 변경 예정 항목만 돌려준다
            return {
                "success": True,
                "applied": False,
                "tier": tier,
                "changes": changes,
                "message": "아래 항목이 바뀝니다. 복구 센터에서 되돌릴 수 있습니다. Windows Update 및 보안 관련 서비스는 변경하지 않습니다."
            }

        steps = []
        if is_low_end:
            for svc in _HW_TUNING_SERVICES:
                steps.append(_service_step(svc, 'disabled', f"저사양 맞춤 튜닝: {svc} 사용 안 함"))

            ram = purge_ram()
            if ram.get("success"):
                b, a = ram.get("standbyBeforeBytes"), ram.get("standbyAfterBytes")
                ram_detail = (f"대기 {b / 1024**3:.1f} GB → {a / 1024**3:.1f} GB"
                              if b is not None and a is not None else "전후 크기는 측정하지 못함")
            else:
                ram_detail = ram.get("message") or ram.get("error") or "관리자 권한이 필요할 수 있습니다"
            steps.append({"name": "대기 메모리 비우기", "ok": bool(ram.get("success")), "detail": ram_detail})

            plan_target, plan_label, plan_why = POWER_PLAN_BALANCED, "균형 조정", '저사양 맞춤 튜닝'
        else:
            for svc in _HW_TUNING_SERVICES:
                if system_state.service_start_type(svc) == 'delayed-auto':
                    # 지연된 시작도 자동 시작이다. '자동'으로 바꿔 부팅을 무겁게 만들지 않는다.
                    steps.append({"name": f"{svc} 시작 유형 → 자동", "ok": True,
                                  "detail": "이미 자동(지연된 시작)이라 바꾸지 않았습니다"})
                    continue
                steps.append(_service_step(svc, 'auto', f"고사양 맞춤 튜닝: {svc} 자동 시작"))
            plan_target, plan_label, plan_why = POWER_PLAN_HIGH_PERF, "고성능", '고사양 맞춤 튜닝'

        try:
            p = system_state.set_active_plan(plan_target, group=HW_TUNING_GROUP, why=plan_why) or {}
        except Exception as e:
            p = {'ok': False, 'reason': str(e) or type(e).__name__}
        steps.append({"name": f"전원 프로필 → {plan_label}", "ok": bool(p.get('ok')),
                      "detail": "" if p.get('ok') else (p.get('reason') or "변경 실패")})

        failed = [s for s in steps if not s["ok"]]
        label = "저사양" if is_low_end else "고사양"
        if not failed:
            msg = (f"{label} 맞춤 튜닝을 적용했습니다. 서비스 시작 유형은 다음 부팅부터 반영되며, "
                   "복구 센터에서 되돌릴 수 있습니다.")
        else:
            msg = (f"{label} 맞춤 튜닝 {len(steps)}개 항목 중 {len(failed)}개가 실패했습니다: "
                   f"{failed[0]['name']} — {failed[0]['detail']}")
        return {
            "success": not failed,
            "applied": any(s["ok"] for s in steps),
            "tier": tier,
            "changes": changes,
            "steps": steps,
            "failed": [s["name"] for s in failed],
            "failedCount": len(failed),
            "message": msg,
        }
    except Exception as e:
        return {"success": False, "applied": False, "message": "맞춤 튜닝 적용에 실패했습니다.", "error": str(e)}

# ─────────────────────────────────────────────
# Startup Manager (winreg)
# ─────────────────────────────────────────────
import winreg

def get_startup_apps():
    """Run 키에 등록된 시작 프로그램(켜짐)과 APEX CARE 가 꺼 둔 항목(꺼짐)을 돌려준다.

    레지스트리에서 읽은 사실만 담는다: 이름, 명령줄(command), 등록 위치(location), 켜짐 여부.
    예전에는 명령줄 길이로 '영향도' 와 '+1.4s' 같은 부팅 시간을 지어냈다. 측정값이 아니므로 뺐다.
    """
    apps = []
    app_id = 1

    def _clean(s):
        if isinstance(s, str): return s.replace('\x00', '').strip()
        return s

    registry_paths = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 'HKCU'),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", 'HKLM'),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", 'HKLM32')
    ]

    seen = set()

    for hkey, path, tag in registry_paths:
        try:
            run_key = winreg.OpenKey(hkey, path, 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(run_key, i)
                    name_clean = _clean(name)
                    if name_clean not in seen:
                        seen.add(name_clean)
                        apps.append({"id": app_id, "name": name_clean, "command": _clean(value),
                                     "location": tag, "enabled": True})
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
                    apps.append({"id": app_id, "name": name_clean, "command": _clean(value),
                                 "location": "disabled", "enabled": False})
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
    """시작 프로그램을 켜고 끈다.

    기존 구현의 문제:
      1. 항목을 어느 Run 키에서도 찾지 못해도 success=True 를 돌려줬다.
         found 플래그를 만들어 놓고 한 번도 검사하지 않았다.
         사용자는 '껐다' 고 생각하지만 실제로는 아무 일도 없었다.
      2. 다시 켤 때 무조건 HKCU 의 Run 키에 복원했다. 원래 HKLM(모든 사용자)에
         있던 항목이 HKCU(현재 사용자)로 옮겨져 적용 범위가 조용히 바뀐다.
      3. 복원 경로 전체가 except: pass 로 감싸여 실패해도 성공으로 보고됐다.

    이제 끌 때 '어느 하이브의 어느 경로에 있었는지' 를 함께 기록하고,
    켤 때 정확히 그 자리로 되돌린다.
    """
    RUN_LOCATIONS = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 'HKCU'),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", 'HKLM'),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", 'HKLM32'),
    ]
    HIVE_BY_TAG = {'HKCU': winreg.HKEY_CURRENT_USER,
                   'HKLM': winreg.HKEY_LOCAL_MACHINE,
                   'HKLM32': winreg.HKEY_LOCAL_MACHINE}
    BACKUP = r"Software\APEXCARE\DisabledStartup"
    ORIGIN = r"Software\APEXCARE\DisabledStartup\_origin"

    if not name or not isinstance(name, str):
        return {"success": False, "message": "프로그램 이름이 올바르지 않습니다."}

    try:
        if not enabled:
            # ── 끄기: 원래 위치를 기록한 뒤 Run 키에서 제거 ──
            for hive, path, tag in RUN_LOCATIONS:
                try:
                    with winreg.OpenKey(hive, path, 0, winreg.KEY_ALL_ACCESS) as run_key:
                        try:
                            val, vtype = winreg.QueryValueEx(run_key, name)
                        except FileNotFoundError:
                            continue
                        # 먼저 백업한다. 백업에 실패하면 삭제하지 않는다.
                        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, BACKUP, 0,
                                                winreg.KEY_SET_VALUE) as bk:
                            winreg.SetValueEx(bk, name, 0, vtype, val)
                        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ORIGIN, 0,
                                                winreg.KEY_SET_VALUE) as ok_:
                            winreg.SetValueEx(ok_, name, 0, winreg.REG_SZ, f"{tag}|{path}")
                        winreg.DeleteValue(run_key, name)
                        log.info(f"시작 프로그램 비활성화: {name} ({tag})")
                        return {"success": True, "enabled": False, "origin": tag,
                                "message": f"'{name}' 을 시작 프로그램에서 제외했습니다."}
                except PermissionError:
                    return {"success": False,
                            "message": f"'{name}' 은 관리자 권한이 있어야 끌 수 있습니다."}
                except FileNotFoundError:
                    continue
                except Exception as e:
                    log.debug(f"{tag} 확인 실패: {e}")

            # 어느 Run 키에도 없었다. 이것을 성공이라고 하면 안 된다.
            return {"success": False,
                    "message": f"'{name}' 을 시작 프로그램 목록에서 찾지 못했습니다. "
                               "이미 제거되었거나 다른 방식(작업 스케줄러 등)으로 "
                               "등록된 항목일 수 있습니다."}

        # ── 켜기: 기록해둔 원래 자리로 되돌린다 ──
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, BACKUP, 0, winreg.KEY_READ) as bk:
                val, vtype = winreg.QueryValueEx(bk, name)
        except FileNotFoundError:
            return {"success": False,
                    "message": f"'{name}' 의 백업을 찾지 못했습니다. "
                               "이 프로그램으로 끈 항목만 다시 켤 수 있습니다."}

        tag, path = 'HKCU', RUN_LOCATIONS[0][1]
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ORIGIN, 0, winreg.KEY_READ) as ok_:
                origin = winreg.QueryValueEx(ok_, name)[0]
                tag, path = origin.split('|', 1)
        except Exception:
            # 구버전에서 끈 항목은 출처 기록이 없다. HKCU 로 복원하고 그 사실을 알린다.
            pass

        hive = HIVE_BY_TAG.get(tag, winreg.HKEY_CURRENT_USER)
        access = winreg.KEY_SET_VALUE
        if tag == 'HKLM32':
            access |= winreg.KEY_WOW64_32KEY
        try:
            with winreg.CreateKeyEx(hive, path, 0, access) as run_key:
                winreg.SetValueEx(run_key, name, 0, vtype, val)
        except PermissionError:
            return {"success": False,
                    "message": f"'{name}' 을 원래 위치({tag})로 되돌리려면 관리자 권한이 필요합니다."}

        # 되읽어 확인한다
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | (winreg.KEY_WOW64_32KEY if tag == 'HKLM32' else 0)) as run_key:
                back = winreg.QueryValueEx(run_key, name)[0]
            if back != val:
                return {"success": False, "message": "복원 후 값이 일치하지 않습니다."}
        except Exception as e:
            return {"success": False, "message": f"복원 확인에 실패했습니다: {e}"}

        for key_path in (BACKUP, ORIGIN):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, name)
            except Exception:
                pass

        log.info(f"시작 프로그램 활성화: {name} -> {tag}")
        return {"success": True, "enabled": True, "origin": tag,
                "message": f"'{name}' 을 원래 위치({tag})로 되돌렸습니다."}

    except Exception as e:
        log.error(f"시작 프로그램 전환 실패 {name}: {e}")
        return {"success": False, "message": f"시작 프로그램 설정 변경에 실패했습니다: {e}"}
