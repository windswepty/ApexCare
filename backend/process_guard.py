"""
APEX CARE - Process Guard
Single gate that decides whether a user-initiated request may kill or
re-prioritize a given PID. Zero backend dependencies (stdlib + psutil only)
so this module can never take part in an import cycle.
"""
import os
import sys
import time
import psutil
import logging

log = logging.getLogger('ProcessGuard')

# 보호 대상 목록. psutil.Process.name() 이 돌려주는 실제 문자열을 소문자로 적는다.
# (작업관리자의 "Memory Compression" 은 psutil 에서 "MemCompression" 이다)
# game_booster.WHITELIST 와 목적이 다르다: 저쪽은 "자동으로 길들이지 말 것"(steam/discord 포함),
# 여기는 "사용자가 절대 죽이거나 우선순위를 바꾸면 안 되는 것"이다.
PROTECTED_PROCESSES = {
    # --- 커널 / 세션 코어 : 종료 시 BSOD(CRITICAL_PROCESS_DIED) 또는 즉시 재부팅 ---
    "system idle process",          # PID 0
    "system",                       # PID 4
    "registry",
    "secure system",
    "memcompression",
    "memory compression",           # 표기 변형 방어
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "lsaiso.exe",
    "svchost.exe",
    # --- 데스크톱 / 입력 / 사운드 : 종료 시 화면·키보드·소리가 사라짐 ---
    "dwm.exe",
    "fontdrvhost.exe",
    "explorer.exe",
    "sihost.exe",
    "ctfmon.exe",
    "taskhostw.exe",
    "audiodg.exe",
    "conhost.exe",
    "dllhost.exe",
    "wudfhost.exe",
    "spoolsv.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "textinputhost.exe",
    "applicationframehost.exe",
    # --- 보안 (PPL 이라 어차피 제어 불가 → 지저분한 실패 대신 명확한 안내) ---
    "msmpeng.exe",
    "mpdefendercoreservice.exe",
    "nissrv.exe",
    "securityhealthservice.exe",
    "securityhealthsystray.exe",
    # --- APEX CARE 자신 (이름 기반 1차 방어. PID 기반은 get_own_pid_family) ---
    "apex care payload.exe",
    "apex care.exe",                # 설치 마법사가 Payload 를 이 이름으로 복사한다
    "apex care uninstaller.exe",
}

# 프론트 노출 API 가 허용하는 우선순위. 'realtime' 은 의도적으로 제외한다.
# REALTIME_PRIORITY_CLASS 는 csrss.exe 와 입력 스택보다 위에서 스케줄되므로
# 대상 앱이 바쁘게 돌면 마우스·키보드까지 멈춘다 (전원 강제 종료 외 복구 불가).
ALLOWED_PRIORITIES = {"low", "normal", "high"}

_MAX_PID = 0xFFFFFFFF

# 자기 가족 PID 캐시 (자식 PID 는 계속 바뀌므로 짧은 TTL 만 준다)
_family_cache = {"pids": None, "ts": 0.0}
_FAMILY_TTL_SEC = 2.0


def normalize_pid(pid):
    """Coerce a PID that arrived from JS into a safe positive int, or None.

    pywebview 는 JS 값을 그대로 넘기므로 float / str / bool 이 들어올 수 있다.
    정수화에 실패한 값은 반드시 버린다. PID 는 Win32 호출과 taskkill 인자로 그대로 쓰인다.
    """
    if isinstance(pid, bool):          # bool 은 int 의 서브클래스라 먼저 걸러야 한다
        return None
    if isinstance(pid, int):
        value = pid
    elif isinstance(pid, float):
        if not pid.is_integer():
            return None
        value = int(pid)
    elif isinstance(pid, str):
        text = pid.strip()
        if not text.isdigit():
            return None
        value = int(text)
    else:
        return None
    if value < 1 or value > _MAX_PID:   # PID 0 = System Idle Process
        return None
    return value


def get_own_pid_family():
    """Return the PID set belonging to APEX CARE itself.

    self + (PyInstaller onefile 부트로더인) 같은 exe 경로의 부모 + 모든 자식.
    pywebview 가 띄우는 msedgewebview2.exe 렌더러들이 자식으로 잡힌다.
    """
    now = time.time()
    cached = _family_cache.get("pids")
    if cached is not None and (now - _family_cache.get("ts", 0.0)) < _FAMILY_TTL_SEC:
        return cached

    own_pid = os.getpid()
    family = {own_pid}
    try:
        own_exe = os.path.normcase(sys.executable or "")
    except Exception:
        own_exe = ""

    try:
        me = psutil.Process(own_pid)

        # 부모 체인: 우리와 exe 경로가 같을 때만 포함한다.
        # (조건 없이 부모를 보호하면 개발 실행 시 explorer.exe 까지 보호돼 버린다)
        if own_exe:
            walker = me.parent()
            for _ in range(3):
                if walker is None:
                    break
                try:
                    if os.path.normcase(walker.exe()) != own_exe:
                        break
                except Exception:
                    break
                family.add(walker.pid)
                walker = walker.parent()

        # 자식 체인: WebView2 렌더러 등
        for child in me.children(recursive=True):
            family.add(child.pid)
    except Exception as e:
        log.debug(f"get_own_pid_family error: {e}")

    _family_cache["pids"] = family
    _family_cache["ts"] = now
    return family


def is_own_process(pid):
    """True if pid belongs to APEX CARE (self / bootloader parent / child)."""
    try:
        return pid in get_own_pid_family()
    except Exception as e:
        log.debug(f"is_own_process error for PID {pid}: {e}")
        return False


def is_protected_name(proc_name):
    """True if the process name must never be killed or re-prioritized.

    부분 문자열 매칭이 아니라 정확히 일치하는 이름만 막는다
    (사용자 게임이 'mysystem.exe' 라고 해서 막히면 안 된다).
    """
    if not proc_name:
        return True   # 이름을 못 읽는 프로세스는 보호 대상으로 간주 (fail-safe)
    return proc_name.strip().lower() in PROTECTED_PROCESSES


def check_controllable(pid, action="kill"):
    """Zero-Risk Shield: the SINGLE gate for user-initiated process control.

    Returns (ok, safe_pid, proc_name, error).
    error 는 사용자에게 그대로 보여줄 한국어 문자열이다.
    action: "kill" | "priority"
    """
    safe_pid = normalize_pid(pid)
    if safe_pid is None:
        return False, None, None, "잘못된 프로세스 ID입니다. 목록을 새로고침한 뒤 다시 시도해 주세요."

    try:
        proc_name = psutil.Process(safe_pid).name()
    except psutil.NoSuchProcess:
        return False, safe_pid, None, "해당 프로세스를 찾을 수 없습니다. 이미 종료되었을 수 있습니다."
    except Exception:
        return False, safe_pid, None, "프로세스 정보를 읽을 수 없어 안전을 위해 차단했습니다. (보호된 시스템 프로세스일 수 있습니다)"

    if is_own_process(safe_pid):
        return False, safe_pid, proc_name, "APEX CARE 자신 또는 APEX CARE가 사용 중인 프로세스는 제어할 수 없습니다."

    if is_protected_name(proc_name):
        if action == "kill":
            return False, safe_pid, proc_name, (
                f"'{proc_name}'은(는) Windows 시스템 필수 프로세스입니다. "
                "강제 종료하면 블루스크린이 발생하거나 PC가 즉시 재부팅될 수 있어 APEX CARE가 차단했습니다."
            )
        return False, safe_pid, proc_name, (
            f"'{proc_name}'은(는) Windows 시스템 필수 프로세스입니다. "
            "우선순위를 변경하면 시스템 전체가 불안정해질 수 있어 APEX CARE가 차단했습니다."
        )

    return True, safe_pid, proc_name, None
