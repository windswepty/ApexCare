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
import logging
import sys
import stat
from backend import system_repair
from backend import system_state

log = logging.getLogger('Optimizer')

# ─────────────────────────────────────────────
# 보호 상수
# ─────────────────────────────────────────────
# 경로 경계 판정은 safe_delete(norm·is_inside·is_protected)로 한다. 예전의 부분 문자열
# 목록(PROTECTED_ROOTS)은 짧은 이름·정션을 못 막고 무관한 파일을 막아서 지웠다.

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


_REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _is_link_like(path):
    """심볼릭 링크·디렉터리 정션·기타 재분석 지점이면 True.

    os.walk(followlinks=False) 는 심볼릭 링크만 건너뛰고 정션은 따라 들어간다
    (DirEntry.is_symlink() 가 정션에 False). %TEMP% 안에 문서 폴더를 가리키는 정션이
    있으면 그 안의 파일이 '정크' 로 영구 삭제됐다. 판정하지 못하면 링크로 본다(안전 쪽).
    """
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, 'isjunction', None)       # Python 3.12+
        if isjunction and isjunction(path):
            return True
        return bool(getattr(os.lstat(path), 'st_file_attributes', 0) & _REPARSE_POINT)
    except OSError:
        return True


def _walk_junk_tree(root):
    """root 아래를 위에서부터 돈다. 링크·정션인 폴더는 들어가지 않는다.

    (dirpath, filenames) 를 내고, 다 돈 뒤 방문한 하위 폴더 목록(깊은 것부터)을 돌려준다.
    root 자체가 링크·정션이면 아무것도 돌지 않는다 — 어디로 이어지는지 모른다.
    """
    visited = []
    if not os.path.isdir(root) or _is_link_like(root):
        return visited, iter(())

    def gen():
        for dirpath, dirs, files in os.walk(root, topdown=True, followlinks=False):
            # 여기서 dirs 를 줄여야 os.walk 가 들어가지 않는다(topdown=True 일 때만 된다)
            dirs[:] = [d for d in dirs if not _is_link_like(os.path.join(dirpath, d))]
            if dirpath != root:
                visited.append(dirpath)
            yield dirpath, files
    return visited, gen()


def _junk_candidate(file_path, root_real):
    """정크로 영구 삭제해도 되는 파일인가. 스캔과 정리가 같은 기준을 쓴다.

    - 링크·재분석 지점 파일은 건너뛴다
    - 실경로(safe_delete.norm)가 정리 대상 루트 안에 있어야 한다. 정션을 놓쳐도
      실경로가 루트 밖이면 여기서 걸린다
    - safe_delete.is_protected 인 경로는 건너뛴다
    - 확장자: 위험 확장자 제외, 안전 확장자이거나 확장자 없음(Chrome 캐시)만
    """
    from backend import safe_delete
    name = os.path.basename(file_path)
    ext = os.path.splitext(name)[1].lower()
    if ext in DANGER_EXTS or (ext not in SAFE_JUNK_EXTS and ext != ''):
        return False
    if _is_link_like(file_path):
        return False
    real = safe_delete.norm(file_path)
    if not safe_delete.is_inside(real, root_real) or real == safe_delete.norm(root_real):
        return False
    if safe_delete.is_protected(real):
        return False
    return True


def _skipped_log_path():
    from backend import config_manager
    return os.path.join(config_manager.APPDATA_DIR, 'skipped_files.log')

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

# 원클릭이 정리하는 정크 분류(scan_junk_background 의 id). 1 = 임시 파일, 2 = Chrome 캐시.
# Windows Update 다운로드 캐시(3)와 Prefetch(4)는 뺐다. 업데이트가 받는 중에 캐시를 지우면 설치가 실패할 수
# 있고, Prefetch 는 저장공간 화면에서도 기본으로 꺼 둔 항목이다. 둘 다 저장공간 화면에서 직접 고를 때만 지운다.
DEEP_OPT_JUNK_CATEGORIES = (1, 2)
# 원클릭이 디스크 최적화 결과를 기다리는 시간. SSD TRIM 은 수 초면 끝난다. HDD 조각 모음은
# 이보다 오래 걸릴 수 있고, 그때는 '실패' 가 아니라 '진행 중' 으로 알리고 기다리기만 멈춘다.
TRIM_WAIT_SEC = 300


def get_deep_optimization_plan():
    """원클릭이 실제로 할 일. 대시보드가 실행 전에 이 목록을 보여 주고 확인을 받는다.

    _run_deep_optimization 과 같은 순서·같은 범위여야 한다(테스트가 확인한다).
    """
    return {
        "steps": [
            {"id": "junk", "name": "임시 파일·브라우저 캐시 정리",
             "detail": "%TEMP%·Windows\\Temp 의 임시 파일과 Chrome 캐시를 지웁니다. 휴지통을 거치지 않아 "
                       "되돌릴 수 없습니다. 사용 중인 파일은 건너뜁니다."},
            {"id": "ram", "name": "대기 메모리 비우기",
             "detail": "Windows 가 캐시로 잡아 둔 대기 메모리를 비웁니다. 실행 중인 프로그램은 건드리지 않습니다."},
            {"id": "dns", "name": "DNS 캐시 초기화",
             "detail": "저장된 DNS 조회 결과를 비웁니다."},
            {"id": "trim", "name": "디스크 최적화(TRIM)",
             "detail": "모든 드라이브에 Windows 디스크 최적화를 실행합니다(SSD 는 TRIM, HDD 는 조각 모음). "
                       "HDD 는 오래 걸릴 수 있고, 시작되면 끝날 때까지 진행됩니다."},
        ],
        "excluded": ["Windows Update 다운로드 캐시", "Prefetch", "휴지통"],
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
        _optimization_state["current_task"] = "임시 파일·브라우저 캐시 정리 중..."
        _optimization_state["eta_seconds"] = 10
        clean_junk_background(list(DEEP_OPT_JUNK_CATEGORIES), cancel_event=_cancel_event)
        # 실제 상태 키는 'freed_mb'. 예전엔 'freedMB' 를 읽어서 항상 0MB 로 보고됐다.
        freed = _junk_clean_state.get("freed_mb", 0)
        _optimization_state["freed_mb"] += freed
        junk_ok = _junk_clean_state.get("status") in ("success", "cancelled")
        steps.append({"name": "임시 파일·브라우저 캐시 정리", "ok": junk_ok,
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
        if not trim_res.get("success"):
            trim_detail = trim_res.get("message") or "시작하지 못했습니다"
        else:
            trim_detail = ""
            trim_deadline = time.time() + TRIM_WAIT_SEC
            while True:
                st = system_repair.get_trim_status()
                if st.get("status") != "running":
                    trim_ok = (st.get("status") == "success")
                    if not trim_ok:
                        trim_detail = system_repair.summarize_output(st.get("error")) or "실패"
                    break
                if _cancel_event.is_set() or time.time() >= trim_deadline:
                    # TRIM·조각 모음은 중간에 끊지 않는다(디스크 작업). 기다리기만 그만둔다.
                    # 실패가 아니라 '아직 진행 중' 이다. 그대로 알린다.
                    trim_detail = ("아직 진행 중입니다. 백그라운드에서 끝까지 진행되며, "
                                   "저장공간 → 디스크 최적화에서 결과를 확인할 수 있습니다")
                    break
                time.sleep(1)
        steps.append({"name": "디스크 최적화(TRIM)", "ok": trim_ok, "detail": trim_detail})
        if _cancel_event.is_set(): raise Exception("사용자에 의해 최적화가 취소되었습니다.")

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
    # 저장공간 화면의 정리와 같은 상태·같은 폴더를 쓴다. 겹쳐 돌면 서로의 결과를 덮어쓴다.
    if _junk_clean_state.get("status") == "running":
        return {"success": False,
                "message": "저장공간 화면에서 정크 정리가 진행 중입니다. 끝난 뒤 다시 시도해 주세요."}
    if system_repair.get_trim_status().get("status") == "running":
        return {"success": False,
                "message": "디스크 최적화가 이미 진행 중입니다. 끝난 뒤 다시 시도해 주세요."}

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
    """정리가 실제로 지울 파일의 크기만 더한다. 링크·정션은 따라가지 않는다.

    예전에는 폴더 안 모든 파일을 더해서, 정리 뒤 '건너뛴 용량' 이 부풀려졌고
    정션을 따라 Temp 밖의 폴더까지 셌다.
    """
    from backend import safe_delete
    total = 0
    file_count = 0
    start_time = time.time()
    root_real = safe_delete.norm(dir_path)
    _, tree = _walk_junk_tree(dir_path)
    try:
        for dirpath, files in tree:
            for f in files:
                fp = os.path.join(dirpath, f)
                try:
                    if not _junk_candidate(fp, root_real):
                        continue
                    total += os.path.getsize(fp)
                    file_count += 1
                except OSError:
                    pass
    except OSError:
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


def _recycle_bin_bytes():
    """모든 드라이브 휴지통의 크기(바이트). 읽지 못하면 None."""
    try:
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("i64Size", ctypes.c_int64),
                        ("i64NumItems", ctypes.c_int64)]
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return max(0, int(info.i64Size))
    except Exception as e:
        log.debug(f"휴지통 크기를 읽지 못했습니다: {e}")
    return None


def _empty_recycle_bin():
    """휴지통을 비운다. (비운 바이트, 실패 사유|None).

    예전에는 SHEmptyRecycleBinW 의 결과를 보지 않아, 실패해도 정리 결과에 드러나지 않았다.
    휴지통이 이미 비어 있으면 Windows 가 오류 코드를 돌려주므로, 비운 뒤 크기로 판단한다.
    """
    before = _recycle_bin_bytes()
    hr = None
    try:
        # 1 = SHERB_NOCONFIRMATION, 2 = SHERB_NOPROGRESSUI, 4 = SHERB_NOSOUND
        hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7) & 0xFFFFFFFF
    except Exception as e:
        return 0, f"휴지통을 비우지 못했습니다: {e}"
    after = _recycle_bin_bytes()
    freed = max(0, before - after) if (before is not None and after is not None) else 0
    if hr != 0 and not (after == 0):
        return freed, f"휴지통을 비우지 못했습니다 (코드 0x{hr:08X})"
    return freed, None

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
        
        rb = _recycle_bin_bytes()
        recycle_size = round(rb / (1024 * 1024), 2) if rb else 0.0

        _junk_scan_state["data"] = [
            {"id": 1, "name": "Windows 임시 파일 (%TEMP%, Windows\\Temp)", "sizeMB": temp_size, "category": "System", "selected": True, "description": "앱 설치·업데이트·실행 중에 만들어진 임시 파일. 사용 중인 파일은 건너뜁니다"},
            {"id": 2, "name": "웹 브라우저 캐시 (Chrome)", "sizeMB": cache_size, "category": "Browser", "selected": True, "description": "Chrome 브라우저가 저장한 이미지·스크립트 캐시. 쿠키와 로그인 정보는 지우지 않습니다"},
            # 기본 해제. 원클릭 최적화도 이 항목은 뺀다. 업데이트를 받는 중에 지우면 설치가 실패하거나
            # 처음부터 다시 받는다. 예전 설명('이미 설치 완료된 … 잔여물')은 사실이 아니었다.
            {"id": 3, "name": "Windows Update 다운로드 캐시", "sizeMB": soft_dist_size, "category": "System", "selected": False, "description": "Windows Update 가 내려받은 설치 파일. 설치가 끝난 파일은 필요 없지만, 받는 중이거나 설치 대기 중인 업데이트는 다시 내려받게 됩니다"},
            {"id": 4, "name": "Prefetch 데이터", "sizeMB": prefetch_size, "category": "System", "selected": False, "description": "앱을 빨리 띄우려고 Windows 가 기록해 둔 데이터. 지우면 다시 만들어지며, 그때까지 앱이 처음 한 번 느리게 켜질 수 있습니다"},
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
        _junk_scan_state["error"] = None
        _junk_scan_state["status"] = "success"
    except Exception as e:
        # 오류를 정리 항목처럼 목록에 끼워 넣지 않는다(예전에는 '에러 발생' 이 고를 수 있는 항목으로 보였다).
        log.warning(f"정크 검사 실패: {e}")
        _junk_scan_state["data"] = []
        _junk_scan_state["error"] = str(e) or type(e).__name__
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
    _junk_clean_state["files_done"] = 0
    _junk_clean_state["skipped_mb"] = 0.0
    _junk_clean_state["skipped_count"] = 0
    _junk_clean_state["warnings"] = []
    _junk_clean_state["skipped_log"] = None
    _junk_clean_state["eta_seconds"] = 0      # 남은 시간은 알 수 없다. 지어내지 않는다
    
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
        skipped_files_log = []

        def _clean_dir(path, max_files=5000):
            """정크 파일을 영구 삭제한다. 링크·정션은 따라가지도, 지우지도 않는다.

            파일마다 실경로가 정리 루트 안인지 삭제 직전에 확인한다(_junk_candidate).
            빈 폴더는 깊은 것부터 os.rmdir 로만 지운다(비어 있지 않으면 실패한다).
            """
            from backend import safe_delete
            nonlocal total_attempt_count, total_success_count, total_freed_bytes
            local_freed = 0
            file_count = 0
            start_time = time.time()
            root_real = safe_delete.norm(path)
            visited, tree = _walk_junk_tree(path)

            for dirpath, files in tree:
                if cancel_event and cancel_event.is_set():
                    break
                for name in files:
                    if cancel_event and cancel_event.is_set():
                        break
                    file_path = os.path.join(dirpath, name)
                    if not _junk_candidate(file_path, root_real):
                        continue

                    total_attempt_count += 1
                    try:
                        sz = os.path.getsize(file_path)
                        try:
                            os.remove(file_path)
                        except OSError:
                            try:
                                os.chmod(file_path, stat.S_IWRITE)
                                os.remove(file_path)
                            except Exception as e:
                                log.debug(f"[LOCKED/SKIPPED] {file_path} - {e}")
                                skipped_files_log.append({"path": file_path, "size_bytes": sz})
                                continue
                        local_freed += sz
                        total_freed_bytes += sz
                        file_count += 1
                        total_success_count += 1
                        # 실제로 지운 파일 수. 예전에는 임의의 '최대 파일 수'(2000)로 나눈 값을 진행률에 계속 더해
                        # 파일이 많으면 99% 에 멈추고 적으면 거의 안 움직이는, 의미 없는 % 를 보였다.
                        _junk_clean_state["files_done"] = _junk_clean_state.get("files_done", 0) + 1
                    except Exception as e:
                        log.debug(f"[LOCKED/SKIPPED] {file_path} - {e}")
                        skipped_files_log.append({"path": file_path, "size_bytes": 0})

            # 빈 폴더 정리: 깊은 것부터. 지우기 직전에 다시 확인한다.
            for dir_path in reversed(visited):
                if cancel_event and cancel_event.is_set():
                    break
                try:
                    if _is_link_like(dir_path):
                        continue
                    real = safe_delete.norm(dir_path)
                    if (not safe_delete.is_inside(real, root_real) or real == root_real
                            or safe_delete.is_protected(real)):
                        continue
                    os.rmdir(dir_path)
                except OSError:
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

        # 진행률 = 끝낸 정리 대상 수 / 전체 대상 수 (휴지통 비우기 포함). 실제로 끝낸 만큼만 오른다.
        steps_total = len(target_dirs) + (1 if 5 in category_ids else 0)
        for i, d in enumerate(target_dirs):
            if cancel_event and cancel_event.is_set():
                break
            _clean_dir(d)
            _junk_clean_state["progress"] = min(99, int((i + 1) * 100 / max(steps_total, 1)))

        warnings = []
        recycle_freed = 0
        if 5 in category_ids and not (cancel_event and cancel_event.is_set()):
            recycle_freed, why = _empty_recycle_bin()
            if why:
                log.warning(why)
                warnings.append(why)

        # 확보한 용량 = 실제로 지운 파일 크기 + 비운 휴지통 크기.
        # 예전에는 정리 전후 드라이브 여유 공간 차이를 썼다. 그 사이 다른 프로그램이 쓰거나 지운 것까지
        # 섞여서, 정리 중에 게임이 업데이트되면 0MB 로, 다운로드가 끝나 파일이 지워지면 부풀려 보였다.
        freed_total_mb = round((total_freed_bytes + recycle_freed) / (1024 * 1024), 2)
        # 건너뛴 용량 = 사용 중이라 지우지 못한 파일 크기의 합(추정이 아니라 파일마다 잰 값)
        skipped_mb = round(sum(x["size_bytes"] for x in skipped_files_log) / (1024 * 1024), 2)

        _junk_clean_state["freed_mb"] = freed_total_mb
        _junk_clean_state["skipped_mb"] = skipped_mb
        _junk_clean_state["skipped_count"] = len(skipped_files_log)
        _junk_clean_state["warnings"] = warnings
        _junk_clean_state["skipped_log"] = None
        
        if skipped_files_log:
            try:
                # 바탕화면이 아니라 앱 데이터 폴더에 쓴다. 묻지 않고 사용자 바탕화면에
                # 파일을 만들면 안 된다.
                log_path = _skipped_log_path()
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"\n=== APEX CARE: 스킵 파일 로그 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===\n")
                    skipped_files_log.sort(key=lambda x: x["size_bytes"], reverse=True)
                    for item in skipped_files_log:
                        mb = round(item["size_bytes"] / (1024 * 1024), 2)
                        f.write(f"[{mb} MB] {item['path']}\n")
                _junk_clean_state["skipped_log"] = log_path
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
_HW_TUNING_SERVICES = ('SysMain', 'WSearch')      # 이 기능이 건드린 적 있는 서비스(구버전 백업 복구 허용 목록)
# 저사양에서 끄는 서비스. WSearch 는 뺐다. 끄면 시작 메뉴·탐색기·Outlook 검색이 망가진다.
_LOW_END_DISABLE = ('SysMain',)
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


def has_legacy_service_backup():
    """구버전 service_start_backup 이 남아 있는지. 복구 센터 표시·전부 원래대로 판단용."""
    return bool(_legacy_service_backup())


def restore_legacy_service_backup():
    """전부 원래대로에서 부른다. 저널(hw_tuning)은 이미 restore_all 이 되돌렸으므로
    여기서는 restore_tailored_service_config 가 구버전 백업만 처리하게 된다."""
    return restore_tailored_service_config()


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
    """사양에 맞춰 서비스 시작 유형을 조정한다.

    저사양은 SysMain 만 끈다(WSearch 는 건드리지 않음). 고사양은 SysMain·WSearch 를 자동 시작으로 둔다.
    전원 플랜은 바꾸지 않는다. 플랜은 성능 모드(perf_modes.apply_mode)만 바꾼다. 예전에는 여기서도
    플랜을 바꿨는데, 저널의 플랜 기록이 하나뿐이라 성능 모드가 먼저 기록했으면 맞춤 튜닝을 되돌려도
    플랜이 돌아오지 않았고, 마법사가 곧이어 표준 모드를 적용해 바꾼 플랜을 바로 덮어썼다.

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
                "대기 메모리(Standby)를 한 번 비웁니다 — 일시적이며 실행 중인 프로그램은 건드리지 않습니다.",
            ]
        else:
            changes = [
                "SysMain(수퍼패치) 서비스를 '자동 시작'으로 변경합니다 — 다음 부팅부터 반영됩니다.",
                "Windows Search(WSearch) 서비스를 '자동 시작'으로 변경합니다 — 이미 '자동(지연된 시작)'이면 그대로 둡니다.",
            ]

        if not consent:
            # 미리보기: 시스템을 전혀 건드리지 않고 변경 예정 항목만 돌려준다
            return {
                "success": True,
                "applied": False,
                "tier": tier,
                "changes": changes,
                "message": "아래 항목이 바뀝니다. 복구 센터에서 되돌릴 수 있습니다. 전원 플랜은 바꾸지 않습니다(성능 모드에서 고릅니다). Windows Update 및 보안 관련 서비스는 변경하지 않습니다."
            }

        steps = []
        if is_low_end:
            for svc in _LOW_END_DISABLE:
                steps.append(_service_step(svc, 'disabled', f"저사양 맞춤 튜닝: {svc} 사용 안 함"))

            ram = purge_ram()
            if ram.get("success"):
                b, a = ram.get("standbyBeforeBytes"), ram.get("standbyAfterBytes")
                ram_detail = (f"대기 {b / 1024**3:.1f} GB → {a / 1024**3:.1f} GB"
                              if b is not None and a is not None else "전후 크기는 측정하지 못함")
            else:
                ram_detail = ram.get("message") or ram.get("error") or "관리자 권한이 필요할 수 있습니다"
            steps.append({"name": "대기 메모리 비우기", "ok": bool(ram.get("success")), "detail": ram_detail})
        else:
            for svc in _HW_TUNING_SERVICES:
                if system_state.service_start_type(svc) == 'delayed-auto':
                    # 지연된 시작도 자동 시작이다. '자동'으로 바꿔 부팅을 무겁게 만들지 않는다.
                    steps.append({"name": f"{svc} 시작 유형 → 자동", "ok": True,
                                  "detail": "이미 자동(지연된 시작)이라 바꾸지 않았습니다"})
                    continue
                steps.append(_service_step(svc, 'auto', f"고사양 맞춤 튜닝: {svc} 자동 시작"))

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
# 작업 관리자와 같은 방식으로 켜고 끈다. Run 값은 지우지 않고
# Explorer\StartupApproved\Run(/Run32) 의 표시만 system_state 를 거쳐 바꾼다(원래 값 기록 → 되읽기 확인).
# 그래서 끈 항목도 작업 관리자·Windows 설정에 그대로 보이고 거기서 다시 켤 수 있으며,
# 복구 센터의 '전부 원래대로' 와 APEX CARE 제거가 같은 저널로 되돌린다.
# 예전에는 Run 값을 지우고 HKCU\Software\APEXCARE\DisabledStartup 에만 숨겨 둬서, 앱을 지우면
# 되살릴 방법이 없었다. 그 기록('구버전에서 끈 항목')은 켤 때 원래 위치로 되살린다.
import winreg

_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"

# tag: (system_state 하이브 이름, winreg 하이브, Run 경로, StartupApproved 경로, 표시 이름)
RUN_LOCATIONS = {
    'HKCU': ('HKCU', winreg.HKEY_CURRENT_USER, _RUN, _APPROVED + r"\Run", '현재 사용자'),
    'HKLM': ('HKLM', winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run", '모든 사용자'),
    'HKLM32': ('HKLM', winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
               r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32", '모든 사용자 (32비트)'),
}

_LEGACY_BACKUP = r"Software\APEXCARE\DisabledStartup"
_LEGACY_ORIGIN = r"Software\APEXCARE\DisabledStartup\_origin"

# StartupApproved 값: 첫 바이트가 짝수면 켜짐, 홀수면 꺼짐(작업 관리자와 같은 판정). 뒤 8바이트는 끈 시각.
_APPROVED_ENABLED = b'\x02' + b'\x00' * 11


def _clean(s):
    return s.replace('\x00', '').strip() if isinstance(s, str) else s


def _reg_read(hive, path, name):
    """(있음, 값, 타입). 읽지 못하면 없음으로 본다(표시용)."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            v, t = winreg.QueryValueEx(k, name)
            return True, v, t
    except OSError:
        return False, None, None


def _reg_values(hive, path):
    out = []
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumValue(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def _approved_state(tag, name):
    """'enabled'·'disabled'·'none'(값 없음 = 켜짐)."""
    loc = RUN_LOCATIONS[tag]
    exists, val, _ = _reg_read(loc[1], loc[3], name)
    if not exists:
        return 'none'
    if isinstance(val, (bytes, bytearray)) and len(val) >= 1:
        return 'disabled' if (val[0] & 1) else 'enabled'
    return 'enabled'


def _approved_disabled_bytes():
    ft = int((time.time() + 11644473600) * 10 ** 7)          # 1601-01-01 기준 100ns (FILETIME)
    return b'\x03\x00\x00\x00' + ft.to_bytes(8, 'little')


def _make_id(tag, name):
    return f"{tag}:{name}"


def _parse_id(app_id):
    if not isinstance(app_id, str) or ':' not in app_id:
        return None, None
    tag, name = app_id.split(':', 1)
    if tag not in RUN_LOCATIONS and tag != 'LEGACY':
        return None, None
    return tag, name


def _legacy_entries():
    """구버전이 Run 에서 지우고 숨겨 둔 항목: [(이름, 값, 타입, 출처문자열|None)]"""
    origins = {n: v for n, v, _ in _reg_values(winreg.HKEY_CURRENT_USER, _LEGACY_ORIGIN)}
    return [(n, v, t, origins.get(n)) for n, v, t in _reg_values(winreg.HKEY_CURRENT_USER, _LEGACY_BACKUP)]


def _legacy_target(origin):
    """구버전 출처 기록을 RUN_LOCATIONS 로 검증한다. (tag, 출처를 아는가) 또는 (None, 이유).

    기록은 사용자 레지스트리에 있어 다른 프로그램이 고칠 수 있다. 허용된 Run 경로가 아니면 쓰지 않는다.
    """
    if origin is None:
        return 'HKCU', False                     # 출처 기록이 없는 아주 옛 항목은 현재 사용자로 되살린다
    if not isinstance(origin, str) or '|' not in origin:
        return None, '원래 위치 기록 형식이 올바르지 않습니다'
    tag, path = origin.split('|', 1)
    loc = RUN_LOCATIONS.get(tag)
    if not loc or path.strip().lower() != loc[2].lower():
        return None, '원래 위치 기록이 허용된 시작 프로그램 위치가 아닙니다'
    return tag, True


def get_startup_apps():
    """Run 키 3곳의 시작 프로그램과 켜짐/꺼짐 상태, 그리고 구버전에서 끈 항목.

    레지스트리에서 읽은 사실만 담는다. 같은 이름도 위치가 다르면 따로 보여 준다(id 로 구분).
    """
    apps = []
    for tag, loc in RUN_LOCATIONS.items():
        for raw_name, value, _ in _reg_values(loc[1], loc[2]):
            state = _approved_state(tag, raw_name)
            apps.append({
                "id": _make_id(tag, raw_name), "name": _clean(raw_name),
                "command": _clean(value) if isinstance(value, str) else str(value),
                "location": tag, "locationLabel": loc[4],
                "enabled": state != 'disabled', "legacy": False,
            })

    for raw_name, value, _, origin in _legacy_entries():
        tag, known = _legacy_target(origin)
        if tag and _reg_read(RUN_LOCATIONS[tag][1], RUN_LOCATIONS[tag][2], raw_name)[0]:
            continue                               # 프로그램이 스스로 다시 등록했다
        apps.append({
            "id": _make_id('LEGACY', raw_name), "name": _clean(raw_name),
            "command": _clean(value) if isinstance(value, str) else str(value),
            "location": 'LEGACY',
            "locationLabel": '예전 버전에서 끔' + ('' if known else ' (원래 위치 모름)'),
            "enabled": False, "legacy": True,
        })

    apps.sort(key=lambda a: (a["name"].lower(), a["location"]))
    return apps


def _startup_group(tag, name):
    return f"startup:{tag}:{name}"


def _journal_entry(group):
    for e in system_state.pending_changes().values():
        if e.get('group') == group and e.get('kind') == 'registry':
            return e
    return None


def _entry_original_enabled(e):
    """저널에 기록된 원래 StartupApproved 값이 '켜짐' 이었는가. 알 수 없으면 None."""
    if not e.get('existed'):
        return True
    b = system_state._dec(e.get('value'))
    if not isinstance(b, (bytes, bytearray)) or not b:
        return None
    return not (b[0] & 1)


def _set_approved(tag, name, enabled):
    """StartupApproved 표시를 system_state 로 바꾼다. 원래 상태로 돌아가는 거면 기록을 되돌린다. (ok, 이유)"""
    loc = RUN_LOCATIONS[tag]
    group = _startup_group(tag, name)
    entry = _journal_entry(group)
    if entry is not None and _entry_original_enabled(entry) == enabled:
        # 원래 상태로 되돌리는 것이다. 새 값을 쓰지 않고 기록한 원래 값을 되살린다.
        r = system_state.restore_group(group)
        reason = '; '.join(f.get('reason', '') for f in r.get('failed', [])) or '원래 값 복구 실패'
        return bool(r.get('ok')), ('' if r.get('ok') else reason)
    data = _APPROVED_ENABLED if enabled else _approved_disabled_bytes()
    r = system_state.set_registry(loc[0], loc[3], name, data, group, vtype=winreg.REG_BINARY,
                                  why=f"시작 프로그램 '{_clean(name)}' ({loc[4]}) {'켜기' if enabled else '끄기'}")
    return bool(r.get('ok')), r.get('reason', '')


def _drop_legacy_value(raw_name):
    """앱 자체 키(HKCU\\Software\\APEXCARE)의 구버전 기록을 지운다."""
    for path in (_LEGACY_BACKUP, _LEGACY_ORIGIN):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, raw_name)
        except OSError:
            pass


def _migrate_one_legacy(raw_name):
    """구버전이 숨긴 항목 하나를 원래 Run 위치에 되살리고 '꺼짐' 으로 표시한다(아직 켜지 않는다)."""
    match = [e for e in _legacy_entries() if e[0] == raw_name]
    if not match:
        return {'ok': False, 'reason': '구버전 기록을 찾지 못했습니다'}
    _, value, vtype, origin = match[0]
    tag, known = _legacy_target(origin)
    if tag is None:
        return {'ok': False, 'reason': known}
    if vtype not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str) or not value.strip():
        return {'ok': False, 'reason': '저장된 명령줄 형식이 올바르지 않습니다'}
    loc = RUN_LOCATIONS[tag]

    if _reg_read(loc[1], loc[2], raw_name)[0]:
        # 프로그램이 스스로 다시 등록했다. 지금 상태를 존중하고 구버전 기록만 정리한다.
        _drop_legacy_value(raw_name)
        return {'ok': True, 'tag': tag}

    # 1) 먼저 '꺼짐' 표시. 이게 안 되면 Run 을 되살리지 않는다(되살리는 순간 켜져 버린다).
    if _approved_state(tag, raw_name) != 'disabled':
        ok, why = _set_approved(tag, raw_name, False)
        if not ok or _approved_state(tag, raw_name) != 'disabled':
            return {'ok': False, 'reason': f"'꺼짐' 표시를 쓰지 못했습니다: {why}"}

    # 2) Run 값을 되살린다. 새 변경이 아니라 구버전이 지운 사용자 값의 복원이라 저널에 넣지 않는다
    #    (넣으면 '전부 원래대로' 가 이 값을 다시 지운다).
    try:
        with winreg.CreateKeyEx(loc[1], loc[2], 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, raw_name, 0, vtype, value)
    except PermissionError:
        return {'ok': False, 'reason': f'{loc[4]} 위치에 쓰려면 관리자 권한이 필요합니다'}
    except OSError as e:
        return {'ok': False, 'reason': str(e)}
    exists, back, _ = _reg_read(loc[1], loc[2], raw_name)
    if not exists or back != value:
        return {'ok': False, 'reason': '되살린 값을 다시 읽으니 다릅니다'}

    _drop_legacy_value(raw_name)
    return {'ok': True, 'tag': tag}


def toggle_startup_app(app_id, enabled):
    """시작 프로그램을 켜고 끈다. app_id 는 get_startup_apps 의 id('HKCU:이름' 등).

    Run 값은 지우지 않는다. 같은 이름이 여러 위치에 있어도 id 로 정확히 하나만 바꾼다.
    이름만 넘어오면(구 호출) 같은 이름이 하나뿐일 때만 받는다. 바꾼 뒤 다시 읽어 확인한다.
    """
    enabled = bool(enabled)
    tag, name = _parse_id(app_id)
    if tag is None:
        if not isinstance(app_id, str) or not app_id.strip():
            return {"success": False, "message": "프로그램 이름이 올바르지 않습니다."}
        same = [a for a in get_startup_apps() if a["name"] == _clean(app_id)]
        if len(same) != 1:
            return {"success": False,
                    "message": ("같은 이름이 여러 위치에 있어 어느 항목인지 알 수 없습니다."
                                if same else f"'{app_id}' 을 시작 프로그램 목록에서 찾지 못했습니다.")}
        tag, name = _parse_id(same[0]["id"])

    shown = _clean(name)
    try:
        if tag == 'LEGACY':
            if not enabled:
                return {"success": True, "enabled": False, "message": f"'{shown}' 은 이미 꺼져 있습니다."}
            m = _migrate_one_legacy(name)
            if not m.get('ok'):
                return {"success": False, "message": f"'{shown}' 을 되살리지 못했습니다: {m.get('reason')}"}
            tag = m['tag']

        loc = RUN_LOCATIONS[tag]
        if not _reg_read(loc[1], loc[2], name)[0]:
            return {"success": False,
                    "message": f"'{shown}' 을 {loc[4]} 시작 프로그램에서 찾지 못했습니다. 이미 제거되었을 수 있습니다."}

        if (_approved_state(tag, name) != 'disabled') == enabled:
            return {"success": True, "enabled": enabled, "id": _make_id(tag, name), "origin": tag,
                    "message": f"'{shown}' 은 이미 {'켜져' if enabled else '꺼져'} 있습니다."}

        ok, why = _set_approved(tag, name, enabled)
        after = _approved_state(tag, name) != 'disabled'
        if not ok or after != enabled:
            return {"success": False, "enabled": after, "id": _make_id(tag, name),
                    "message": f"'{shown}' 설정을 바꾸지 못했습니다" + (f": {why}" if why else ".")}
        log.info(f"시작 프로그램 {'켜기' if enabled else '끄기'}: {shown} ({tag})")
        return {"success": True, "enabled": enabled, "id": _make_id(tag, name), "origin": tag,
                "message": f"'{shown}' 을 {'켰' if enabled else '껐'}습니다. 다음 로그인부터 적용됩니다."}
    except Exception as e:
        log.error(f"시작 프로그램 전환 실패 {shown}: {e}")
        return {"success": False, "message": f"시작 프로그램 설정 변경에 실패했습니다: {e}"}
