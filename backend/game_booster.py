"""
APEX CARE - 게임 부스트.

게임이 감지되면 사용자가 켜 둔 항목만 적용하고, 게임이 끝나거나 앱을 닫으면
적용한 것만 정확히 되돌린다.

  타이머 해상도 0.5ms      세션 한정. 우리 요청을 거두면 원래대로 돌아간다.
                           Windows 10 2004 이전에만 게임에 효과가 있어 그 버전에서만 적용한다.
  바쁜 백그라운드 앱 양보   CPU 를 많이 쓰는 백그라운드 앱만 우선순위를 낮춘다(원래 값 기록).
  게이밍 전원 모드 자동 전환 게임 동안만. 끝나면 사용자가 쓰던 모드로 돌아간다.
  Nagle 끄기               레지스트리. system_state 저널에 원래 값을 기록한다.

게임 프로세스 자체는 HIGH 우선순위로 올리고 EcoQoS 에서 빼 준다(원래 값 기록).
"""
import psutil
import threading
import ctypes
import ctypes.wintypes
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='[GameBooster] %(message)s')
log = logging.getLogger('GameBooster')

# 에코·부스트 억제 기준: 작업 관리자 기준으로 전체 CPU 의 이 % 이상을 쓰는 프로세스만 건드린다.
# 유휴 상태인 앱의 우선순위를 낮춰봐야 얻는 것은 없고, 그 앱이 깨어날 때 느려지기만 한다.
# 예전 값 5.0 은 코어 하나를 100% 로 보는 단위였다(16스레드 PC 에서 작업 관리자 0.3%).
ECO_CPU_THRESHOLD = 3.0
ECO_INTERVAL_SEC = 10

# system_state 저널에서 게임 부스트가 바꾼 레지스트리(Nagle)를 묶는 그룹
BOOST_GROUP = 'boost'
_NAGLE_BASE = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"

# process_boost 에 기록할 '누가 바꿨는가'. 게임이 끝날 때 부스트가 바꾼 것만 되돌린다.
OWNER = 'boost'

# List of popular game executables to detect
GAMES_LIST = [
    "tslgame.exe",             # PUBG
    "valorant-win64-shipping.exe", # Valorant
    "league of legends.exe",   # LoL
    "overwatch.exe",           # Overwatch
    "csgo.exe",                # CS:GO
    "cs2.exe",                 # CS2
    "apex.exe",                # Apex Legends
    "r5apex.exe",              # Apex Legends
    "gta5.exe",                # GTA V
    "dota2.exe",               # Dota 2
    "rainbowsix.exe",          # R6 Siege
    "cyberpunk2077.exe",       # Cyberpunk
    "javaw.exe",               # Minecraft Java
    "minecraft.windows.exe",   # Minecraft Bedrock
    "robloxplayerbeta.exe",    # Roblox
    "cod.exe",                 # Call of Duty
    "blackopscoldwar.exe",     # Call of Duty BOCW
    "modernwarfare.exe",       # Call of Duty MW
    "fortniteclient-win64-shipping.exe", # Fortnite
    "genshinimpact.exe",       # Genshin Impact
    "starrail.exe",            # Honkai: Star Rail
    "rustclient.exe",          # Rust
    "escapefromtarkov.exe",    # Escape from Tarkov
    "discovery.exe",           # The Finals
    "palworld-win64-shipping.exe", # Palworld
    "destiny2.exe",            # Destiny 2
    "wow.exe",                 # World of Warcraft
    "wow_classic.exe",         # WoW Classic
    "diablo iv.exe",           # Diablo IV
    "lostark.exe",             # Lost Ark
    "maplestory.exe",          # MapleStory
    "fc24.exe",                # EA Sports FC 24
    "eldenring.exe",           # Elden Ring
    "helldivers2.exe",         # Helldivers 2
    "wuthering waves.exe",     # Wuthering Waves (명조)
    "client-win64-shipping.exe", # Wuthering Waves Game Client
    "zenlesszonezero.exe",     # Zenless Zone Zero
    "bns.exe",                 # Blade & Soul
    "throneandliberty.exe"     # Throne & Liberty
]

# 화면에 보여 줄 게임 이름. 실행 파일 이름(tslgame.exe)만으로는 무슨 게임인지 알기 어렵다.
GAME_NAMES = {
    "tslgame.exe": "PUBG: BATTLEGROUNDS", "valorant-win64-shipping.exe": "VALORANT",
    "league of legends.exe": "리그 오브 레전드", "overwatch.exe": "오버워치",
    "csgo.exe": "CS:GO", "cs2.exe": "Counter-Strike 2", "apex.exe": "Apex Legends",
    "r5apex.exe": "Apex Legends", "gta5.exe": "GTA V", "dota2.exe": "Dota 2",
    "rainbowsix.exe": "레인보우 식스 시즈", "cyberpunk2077.exe": "사이버펑크 2077",
    "javaw.exe": "Minecraft (Java)", "minecraft.windows.exe": "Minecraft",
    "robloxplayerbeta.exe": "Roblox", "cod.exe": "Call of Duty",
    "blackopscoldwar.exe": "Call of Duty: Black Ops Cold War", "modernwarfare.exe": "Call of Duty: Modern Warfare",
    "fortniteclient-win64-shipping.exe": "Fortnite", "genshinimpact.exe": "원신",
    "starrail.exe": "붕괴: 스타레일", "rustclient.exe": "Rust", "escapefromtarkov.exe": "Escape from Tarkov",
    "discovery.exe": "THE FINALS", "palworld-win64-shipping.exe": "Palworld", "destiny2.exe": "Destiny 2",
    "wow.exe": "World of Warcraft", "wow_classic.exe": "World of Warcraft Classic",
    "diablo iv.exe": "디아블로 IV", "lostark.exe": "로스트아크", "maplestory.exe": "메이플스토리",
    "fc24.exe": "EA SPORTS FC 24", "eldenring.exe": "ELDEN RING", "helldivers2.exe": "HELLDIVERS 2",
    "wuthering waves.exe": "명조: 워더링 웨이브", "client-win64-shipping.exe": "명조: 워더링 웨이브",
    "zenlesszonezero.exe": "젠레스 존 제로", "bns.exe": "블레이드 & 소울",
    "throneandliberty.exe": "THRONE AND LIBERTY",
}


def game_label(exe_name):
    """'PUBG: BATTLEGROUNDS (tslgame.exe)' 처럼 사람이 알아볼 이름. 모르면 실행 파일 이름."""
    if not exe_name:
        return None
    name = GAME_NAMES.get(exe_name.lower())
    return f"{name} ({exe_name})" if name else exe_name


def _is_game_process(proc, name):
    """이 프로세스가 게임인가.

    javaw.exe 는 Minecraft 만 쓰는 이름이 아니다(개발 도구·사내 프로그램 등 자바 앱 전부).
    예전에는 이름만 봐서 자바 앱을 켜 두면 '게임 감지' 로 우선순위를 올리고 다른 앱을 낮췄다.
    javaw.exe 는 명령줄에 minecraft 가 있을 때만 게임으로 본다. 명령줄을 못 읽으면 게임이 아니다.
    """
    if name not in GAMES_LIST:
        return False
    if name != 'javaw.exe':
        return True
    try:
        return any('minecraft' in (part or '').lower() for part in proc.cmdline())
    except Exception:
        return False


def timer_request_effective():
    """이 Windows 에서 타이머 해상도 요청이 게임에 영향을 주는가.

    Windows 10 2004(빌드 19041)부터 타이머 해상도 요청은 요청한 프로세스에만 적용된다.
    APEX CARE 가 요청해도 게임의 타이머는 바뀌지 않으므로, 그 버전부터는 적용하지 않고 그 사실을 알린다.
    """
    try:
        import sys
        return sys.getwindowsversion().build < 19041
    except Exception:
        return False

_booster_state = {
    "enabled": False,
    "active": False,
    "detected_game": None,
    "boosted_pids": [],
    "boost_count": 0,
    "timer_resolution_set": False,
    "nagle_disabled": False,
    "appliedBoosts": [],
}

# 이번 게임 세션에서 '실제로 적용한 것'. 되돌릴 때는 지금 설정이 아니라 이것을 본다.
# 예전에는 종료 시점의 설정을 다시 읽었다. 게임 도중 사용자가 Nagle 설정을 끄면
# 켜 둔 Nagle 변경이 되돌려지지 않았고, 반대로 켜면 바꾼 적 없는 값을 지웠다.
_applied = {}
_tamed_pids = set()

_monitor_thread = None
_stop_event = threading.Event()
_teardown_lock = threading.RLock()
_admin_checked = False
_is_admin_cached = False

# ─────────────────────────────────────────────
# Admin Privilege Check & Enforcement
# ─────────────────────────────────────────────

def _is_admin():
    """Check if the current process is running with admin privileges."""
    global _admin_checked, _is_admin_cached
    if _admin_checked:
        return _is_admin_cached
    try:
        _is_admin_cached = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception as e:
        log.debug(f"IsAdmin check failed: {e}")
        _is_admin_cached = False
    _admin_checked = True
    if not _is_admin_cached:
        log.warning("⚠ NOT running as Administrator! Process priority/power control will be limited.")
    else:
        log.info("✓ Running as Administrator - full process control available.")
    return _is_admin_cached


def _enable_debug_privilege():
    """Enable SeDebugPrivilege to allow controlling any process regardless of owner.
    
    This is the key privilege that allows us to modify system/service processes
    and processes owned by other users. Requires admin rights.
    """
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", ctypes.wintypes.DWORD), ("HighPart", ctypes.wintypes.LONG)]
        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", ctypes.wintypes.DWORD)]
        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", ctypes.wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]
        
        TOKEN_ADJUST_PRIVILEGES = 0x0020
        TOKEN_QUERY = 0x0008
        SE_PRIVILEGE_ENABLED = 0x00000002
        
        hToken = ctypes.wintypes.HANDLE()
        kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(hToken)):
            return False
        
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            kernel32.CloseHandle(hToken)
            return False
        
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        
        advapi32.AdjustTokenPrivileges(hToken, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
        success = ctypes.get_last_error() == 0
        kernel32.CloseHandle(hToken)
        
        if success:
            log.info("✓ SeDebugPrivilege enabled - can control all processes")
        else:
            log.warning("⚠ Failed to enable SeDebugPrivilege")
        return success
    except Exception as e:
        log.warning(f"⚠ SeDebugPrivilege error: {e}")
        return False




# ─────────────────────────────────────────────
# 타이머 해상도 · EcoQoS
# ─────────────────────────────────────────────

_TIMER_REQUEST = 5000        # 100ns 단위 = 0.5ms


def _set_timer_resolution(enable):
    """시스템 타이머 해상도를 0.5ms 로 요청하거나, 그 요청을 거둔다.

    되돌릴 때는 SetResolution=FALSE 로 '우리 요청을 철회' 해야 한다. 예전에는
    15.625ms 를 TRUE 로 다시 요청했는데, 그건 철회가 아니라 새 요청이다.
    """
    try:
        ntdll = ctypes.WinDLL('ntdll')
        actual = ctypes.c_ulong()
        status = ntdll.NtSetTimerResolution(ctypes.c_ulong(_TIMER_REQUEST),
                                            ctypes.c_bool(bool(enable)), ctypes.byref(actual))
        ok = (status == 0)
        _booster_state["timer_resolution_set"] = bool(enable) and ok
        if ok:
            log.info(f"✓ 타이머 해상도 {'0.5ms 요청' if enable else '요청 철회'} (현재 {actual.value/10000:.2f}ms)")
        else:
            log.warning(f"⚠ NtSetTimerResolution 실패 (0x{status & 0xFFFFFFFF:08X})")
        return ok
    except Exception as e:
        log.warning(f"⚠ Timer resolution error: {e}")
        return False


class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_ulong),
        ("ControlMask", ctypes.c_ulong),
        ("StateMask", ctypes.c_ulong),
    ]


def _set_process_power_throttling(pid, throttle):
    """EcoQoS(효율 모드)를 켜거나(True), 끄거나(False), 시스템에 맡긴다(None).

    None 이 '원래대로' 다. 예전에는 복구할 때 False(항상 끔)를 넣어서, 원래
    시스템이 관리하던 프로세스를 '절대 효율 모드로 가지 않는' 상태로 바꿔 놓았다.
    """
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        PROCESS_SET_INFORMATION = 0x0200
        ProcessPowerThrottling = 4  # PROCESS_INFORMATION_CLASS

        handle = kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
        if not handle:
            return False
        state = _PROCESS_POWER_THROTTLING_STATE()
        state.Version = 1  # PROCESS_POWER_THROTTLING_CURRENT_VERSION
        if throttle is None:
            state.ControlMask = 0x0   # 시스템이 관리 (기본값)
            state.StateMask = 0x0
        else:
            state.ControlMask = 0x1   # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
            state.StateMask = 0x1 if throttle else 0x0
        ok = bool(kernel32.SetProcessInformation(
            handle, ProcessPowerThrottling, ctypes.byref(state), ctypes.sizeof(state)))
        kernel32.CloseHandle(handle)
        return ok
    except Exception as e:
        log.debug(f"Power throttling error for PID {pid}: {e}")
        return False


# ─────────────────────────────────────────────
# Nagle (레지스트리 — system_state 저널 경유)
# ─────────────────────────────────────────────

def _nagle_interfaces():
    import winreg
    names = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NAGLE_BASE, 0, winreg.KEY_READ) as base:
        i = 0
        while True:
            try:
                names.append(winreg.EnumKey(base, i))
            except OSError:
                break
            i += 1
    return names


def _disable_nagle():
    """모든 네트워크 어댑터에서 Nagle 을 끈다. 원래 값은 저널에 기록된다.

    예전 구현은 원래 값을 기록하지 않았고, 되돌릴 때 모든 어댑터의 값을 지웠다.
    사용자나 다른 프로그램이 직접 넣어 둔 값까지 사라졌다. 또 어댑터 하나에서
    권한 오류가 나면 반복문 전체가 멈췄다.
    """
    from backend import system_state as ss
    try:
        ifaces = _nagle_interfaces()
    except Exception as e:
        return {'ok': False, 'changed': 0, 'failed': [f'어댑터 목록을 읽지 못했습니다: {e}']}
    changed, failed = 0, []
    for iface in ifaces:
        path = f"{_NAGLE_BASE}\\{iface}"
        for name in ("TcpAckFrequency", "TCPNoDelay"):
            r = ss.set_registry('HKLM', path, name, 1, group=BOOST_GROUP,
                                why=f"게임 부스트: Nagle 끄기 — {name} (어댑터 {iface})")
            if r.get('ok'):
                changed += 1
            else:
                failed.append(f"{iface} {name}: {r.get('reason', '실패')}")
    _booster_state["nagle_disabled"] = changed > 0
    if failed:
        log.warning(f"⚠ Nagle 끄기 실패 {len(failed)}건: {failed[:3]}")
    return {'ok': changed > 0 and not failed, 'changed': changed, 'failed': failed}


def _restore_nagle():
    """저널에 기록한 원래 값으로 되돌린다. 실패한 항목은 저널에 남아 다시 시도할 수 있다."""
    from backend import system_state as ss
    r = ss.restore_group(BOOST_GROUP)
    _booster_state["nagle_disabled"] = not r['ok']
    if r['failed']:
        log.warning(f"⚠ Nagle 복구 실패 {len(r['failed'])}건 — '변경 내역 · 되돌리기' 에서 다시 시도할 수 있습니다")
    return r


# ─────────────────────────────────────────────
# 프로세스 우선순위 (process_boost 경유 — 원래 값 기록)
# ─────────────────────────────────────────────

def get_booster_status():
    st = dict(_booster_state)
    st['detected_game_label'] = game_label(_booster_state.get('detected_game'))
    st['timer_effective'] = timer_request_effective()
    return st


def _boost_game_processes(pids):
    """게임을 HIGH 우선순위로 올리고 EcoQoS 에서 뺀다.

    예전에는 psutil 로 직접 올리고 원래 값을 기록하지 않았다. 그래서 게임 도중
    부스터를 끄면 게임이 HIGH 로 남았다. 이제 process_boost 가 원래 값을 기록한다.
    """
    from backend import process_boost
    boosted = 0
    for pid in pids:
        r = process_boost.set_priority(pid, 'high', reason='(게임 부스트)', owner=OWNER)
        if r.get('ok'):
            boosted += 1
            if _set_process_power_throttling(pid, False):
                process_boost.mark_ecoqos(pid)          # 되돌릴 때 시스템 관리로 돌려준다
        else:
            log.warning(f"  ✗ 게임 우선순위를 올리지 못했습니다 (PID {pid}): {r.get('reason')}")
    return boosted


def _tame_processes(pids, owner=OWNER):
    """백그라운드 앱의 우선순위를 낮추고 EcoQoS 를 켠다. 원래 우선순위는 기록된다."""
    from backend import process_boost
    tamed = []
    for pid in pids:
        r = process_boost.set_priority(pid, 'idle', reason='(부스트 억제)', owner=owner)
        if r.get('ok'):
            tamed.append(pid)
            if _set_process_power_throttling(pid, True):
                process_boost.mark_ecoqos(pid)
    if tamed:
        log.info(f"백그라운드 프로세스 {len(tamed)}개의 우선순위를 낮췄습니다")
    return tamed


def _restore_processes(pids, owner=OWNER):
    """기록해둔 원래 우선순위로 되돌리고 EcoQoS 는 시스템에 맡긴다. 되돌리지 못한 것의 설명 목록을 돌려준다.

    사용자가 그 사이 게이밍 탭에서 직접 바꾼 프로세스는 건드리지 않는다.
    EcoQoS 는 process_boost.restore 가 같은 프로세스(생성 시각 확인)일 때만 되돌린다. 예전에는 여기서
    PID 만 보고 되돌려, 끝난 앱의 PID 를 물려받은 다른 프로세스(시스템 서비스 포함)의 효율 모드를 바꿨다.
    """
    from backend import process_boost
    failed = []
    for pid in pids:
        if process_boost.owner_of(pid) != owner:
            continue
        r = process_boost.restore(pid)
        if not r.get('ok'):
            failed.append(f"{r.get('name', pid)}: {r.get('reason', '실패')}")
    return failed


def _pick_tame_targets(exclude_pids):
    """'바쁜 백그라운드 앱 양보시키기' 대상. 설명대로 CPU 를 많이 쓰는 것만 고른다.

    예전에는 설정과 무관하게 크롬·엣지·카카오톡 등 고정 목록을 CPU 사용량과
    상관없이 낮췄다. 화면의 설명('CPU 를 많이 쓰는 백그라운드 앱', '끄고 켤 수 있음')과
    실제 동작이 달랐다.
    """
    from backend import process_boost
    candidates = process_boost.find_throttle_candidates(
        foreground_pid=_get_foreground_pid(), cpu_threshold=ECO_CPU_THRESHOLD)
    return [c['pid'] for c in candidates if c['pid'] not in exclude_pids]


# ─────────────────────────────────────────────
# 부스트 진입 / 해제
# ─────────────────────────────────────────────

def _enter_boost_mode():
    """게임이 감지됐을 때 사용자가 켜 둔 항목만 적용한다. 적용한 것은 _applied 에 남긴다."""
    from backend import config_manager
    cfg = config_manager.load_config()
    labels = []
    if config_manager.is_unreadable(cfg):
        # 사용자가 켜 둔 항목이 무엇인지 모른다. 기본값으로 적용하면 사용자가 끈 항목(양보 등)이 켜진다.
        log.warning("설정 파일을 읽지 못해 이번 게임에는 부스트를 적용하지 않았습니다")
        _booster_state['appliedBoosts'] = []
        return

    # 타이머 해상도: 세션 한정. 우리 요청을 거두면 원래대로 돌아간다.
    # Windows 10 2004 부터는 요청한 프로세스에만 적용돼 게임에는 효과가 없다. 그때는 요청하지 않는다.
    if cfg.get('boost_timer_resolution', True) and timer_request_effective():
        if _set_timer_resolution(True):
            _applied['timer'] = True
            labels.append('타이머 해상도 0.5ms')

    # 바쁜 백그라운드 앱 양보: 대상은 루프가 5초마다 고른다(CPU 측정에 기준점이 필요하다).
    if cfg.get('boost_tame_background', True):
        from backend import process_boost
        process_boost.prime_cpu_measurement()
        _applied['tame'] = True
        labels.append('바쁜 백그라운드 앱 양보')

    # Nagle: 레지스트리 변경이라 기본값은 꺼져 있다.
    if cfg.get('boost_disable_nagle', False):
        r = _disable_nagle()
        if r['changed']:
            _applied['nagle'] = True
            labels.append('Nagle 끄기' + ('' if r['ok'] else ' (일부 실패)'))

    # 게이밍 전원 모드: 게임 동안만. 끝나면 사용자가 쓰던 모드로 돌아간다.
    if cfg.get('boost_auto_power_mode', False):
        _apply_gaming_power_mode(labels)

    _booster_state['appliedBoosts'] = labels
    log.info(f"부스트 진입: {', '.join(labels) if labels else '적용 항목 없음'}")


def _apply_gaming_power_mode(labels):
    """게이밍 전원 모드를 '저장하지 않고' 적용한다.

    예전에는 게임이 끝나면 무조건 표준 모드를 적용했고, 그 과정에서 저장된 모드도
    덮어썼다. 에코 모드를 쓰던 사용자는 게임 한 판 뒤 표준 모드가 됐고, 다음 실행
    때도 표준으로 시작했다.
    """
    from backend import config_manager, perf_modes
    prev = config_manager.get_optimization_mode()
    if prev == 'gaming':
        return                                  # 이미 게이밍 모드다. 바꿀 것도 되돌릴 것도 없다.
    # apply_mode 는 먼저 이전 모드를 되돌린다. 적용이 실패해도 이전 모드는 이미
    # 풀렸을 수 있으므로, 결과와 상관없이 '돌아갈 모드' 를 먼저 기록한다.
    _applied['power_mode_prev'] = prev
    config_manager.set_boost_restore_mode(prev)     # 앱이 비정상 종료돼도 다음 실행 때 되돌린다
    try:
        res = perf_modes.apply_mode('gaming', user_set=False, persist=False)
        if res.get('success') or res.get('partial'):
            labels.append('게이밍 전원 모드' + ('' if res.get('success') else ' (일부 실패)'))
        else:
            log.warning(f"게이밍 전원 모드 전환 실패: {res.get('message')}")
    except Exception as e:
        log.warning(f"전원 모드 전환 실패: {e}")


def _restore_power_mode():
    from backend import config_manager, perf_modes
    prev = _applied.pop('power_mode_prev', None)
    if prev is None:
        return
    try:
        res = perf_modes.apply_mode(prev, user_set=False, persist=False)
        if res.get('success'):
            config_manager.set_boost_restore_mode(None)
        else:
            log.warning(f"게임 전 모드({prev})로 되돌리지 못했습니다: {res.get('message')}")
    except Exception as e:
        log.warning(f"전원 모드 복구 실패: {e}")


def _drop_label(prefix):
    _booster_state['appliedBoosts'] = [x for x in _booster_state.get('appliedBoosts', [])
                                       if not str(x).startswith(prefix)]


def forget_power_mode_restore():
    """사용자가 게임 도중 직접 성능 모드를 고르면 부른다.

    그 뒤에 게임이 끝났다고 게임 전 모드로 되돌리면 사용자의 선택을 덮어쓴다.
    화면의 '적용 중' 목록에서도 뺀다. 예전에는 사용자가 모드를 바꾼 뒤에도 '게이밍 전원 모드' 가 계속 보였다.
    """
    _applied.pop('power_mode_prev', None)
    _drop_label('게이밍 전원 모드')
    try:
        from backend import config_manager
        config_manager.set_boost_restore_mode(None)
    except Exception:
        pass


def after_external_revert():
    """'전부 원래대로' 가 저널을 되돌린 뒤 부른다. 부스트의 Nagle 기록이 모두 되돌려졌을 때만 '적용 중' 에서 뺀다."""
    from backend import system_state as ss
    if any(e.get('group') == BOOST_GROUP for e in ss.pending_changes().values()):
        return                      # 일부가 남았다. 게임이 끝날 때 다시 되돌리도록 그대로 둔다
    _applied.pop('nagle', None)
    _booster_state["nagle_disabled"] = False
    _drop_label('Nagle 끄기')


def power_mode_overridden():
    """게임 부스트가 지금 게이밍 전원 모드를 임시로 적용 중인지. UI 설명용."""
    return 'power_mode_prev' in _applied


def _exit_boost_mode():
    """부스트에서 '실제로 적용한 것' 만 되돌린다. 되돌리지 못한 것의 설명 목록을 돌려준다."""
    failed = []
    if _applied.pop('timer', False):
        _set_timer_resolution(False)
    if _applied.pop('nagle', False):
        r = _restore_nagle()
        failed += [f"Nagle: {f.get('reason', '실패')}" for f in (r.get('failed') or [])]
    if 'power_mode_prev' in _applied:
        prev = _applied.get('power_mode_prev')
        _restore_power_mode()
        if 'power_mode_prev' not in _applied:
            try:
                from backend import config_manager
                if config_manager.get_boost_restore_mode():
                    failed.append(f"게임 전 성능 모드({prev})로 되돌리지 못했습니다")
            except Exception:
                pass
    _applied.pop('tame', None)
    _booster_state['appliedBoosts'] = []
    log.info("부스트 종료: 적용했던 설정을 되돌렸습니다" + (f" (실패 {len(failed)}건)" if failed else ""))
    return failed


def _teardown():
    """게임 세션을 끝낸다. 루프, 부스터 끄기, 앱 종료가 모두 이 한 곳을 쓴다. 되돌리지 못한 것의 목록을 돌려준다."""
    global _tamed_pids
    with _teardown_lock:
        failed = _restore_processes(list(_tamed_pids))
        _tamed_pids = set()
        failed += _restore_processes(_booster_state["boosted_pids"])
        failed += _exit_boost_mode()
        _booster_state["active"] = False
        _booster_state["detected_game"] = None
        _booster_state["boosted_pids"] = []
        return failed


# ─────────────────────────────────────────────
# Main Monitoring Loop
# ─────────────────────────────────────────────

def _booster_loop():
    global _tamed_pids

    # Enable SeDebugPrivilege at thread start for maximum process control
    if _is_admin():
        _enable_debug_privilege()

    while not _stop_event.is_set():
        try:
            if not _booster_state["enabled"]:
                if _booster_state["active"]:
                    _teardown()
                _stop_event.wait(2)
                continue

            found_games = []
            current_game_pids = []
            for proc in psutil.process_iter(['name']):
                try:
                    name = (proc.info.get('name') or '').lower()
                    if _is_game_process(proc, name):
                        found_games.append(name)
                        current_game_pids.append(proc.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

            if found_games:
                found_games.sort(key=lambda x: GAMES_LIST.index(x))
                game_found = found_games[0]

                with _teardown_lock:
                    if not _booster_state["enabled"]:
                        # 검사하는 사이에 사용자가 부스터를 껐다. 다시 적용하지 않는다.
                        continue
                    if not _booster_state["active"]:
                        _booster_state["active"] = True
                        _booster_state["detected_game"] = game_found
                        _booster_state["boosted_pids"] = current_game_pids
                        _booster_state["boost_count"] += 1
                        log.info(f"🎮 Game detected: {game_found} (PIDs: {current_game_pids})")
                        _enter_boost_mode()
                        _boost_game_processes(current_game_pids)
                    else:
                        if _booster_state["detected_game"] != game_found:
                            log.info(f"🎮 Game switched to: {game_found}")
                            _booster_state["detected_game"] = game_found
                        # 새로 뜬 게임 프로세스만 올리고, 끝난 것은 기록에서 뺀다
                        new_pids = [p for p in current_game_pids if p not in _booster_state["boosted_pids"]]
                        gone = [p for p in _booster_state["boosted_pids"] if p not in current_game_pids]
                        if gone:
                            _restore_processes(gone)
                        if new_pids:
                            _boost_game_processes(new_pids)
                        _booster_state["boosted_pids"] = current_game_pids

                    if _applied.get('tame'):
                        from backend import config_manager, process_boost
                        cfg = config_manager.load_config()
                        if not config_manager.is_unreadable(cfg) and not cfg.get('boost_tame_background', True):
                            # 게임 도중 사용자가 '양보시키기' 를 껐다. 예전에는 게임이 끝날 때까지 계속 낮췄다.
                            _restore_processes(list(_tamed_pids))
                            _tamed_pids = set()
                            _applied.pop('tame', None)
                            _drop_label('바쁜 백그라운드 앱 양보')
                        else:
                            # 낮춘 앱이 지금 쓰는 창이 되면 바로 돌려준다(게임이 끝날 때까지 기다리지 않는다)
                            back = _tamed_pids & process_boost.foreground_group(_get_foreground_pid())
                            if back:
                                _restore_processes(list(back))
                                _tamed_pids -= back
                            targets = _pick_tame_targets(set(current_game_pids) | _tamed_pids)
                            _tamed_pids |= set(_tame_processes(targets))

                _stop_event.wait(5)
            else:
                if _booster_state["active"]:
                    log.info("🎮 Game exited - restoring all processes")
                    _teardown()
                _stop_event.wait(3)
        except Exception as e:
            log.error(f"Booster loop crash: {e}")
            _stop_event.wait(5)


def toggle_booster(enabled):
    """게임 자동 감지를 켜고 끈다(사용자 설정으로 저장된다).

    끌 때는 루프가 2초 안에 적용했던 것을 되돌린다.
    """
    global _monitor_thread
    enabled = bool(enabled)
    _booster_state["enabled"] = enabled

    saved = True
    try:
        from backend import config_manager
        saved = config_manager.set_booster_state(enabled)
    except Exception as e:
        saved = False
        log.warning(f"Failed to save booster state: {e}")

    if enabled and (_monitor_thread is None or not _monitor_thread.is_alive()):
        _stop_event.clear()
        _monitor_thread = threading.Thread(target=_booster_loop, daemon=True)
        _monitor_thread.start()
        log.info("✓ Game Booster ENABLED - monitoring for games...")

    reverted = False
    revert_failed = []
    if not enabled:
        # 루프에 맡기지 않고 지금 되돌린다. 그래야 '되돌렸습니다' 가 사실이 된다.
        with _teardown_lock:
            if _booster_state["active"] or _applied or _tamed_pids:
                revert_failed = _teardown()
                reverted = True
        log.info("✓ Game Booster DISABLED")

    if enabled:
        msg = "게임 자동 감지를 켰습니다."
    elif reverted and revert_failed:
        msg = (f"게임 자동 감지를 껐습니다. 게임 동안 적용했던 설정 중 {len(revert_failed)}개를 되돌리지 못했습니다: "
               f"{revert_failed[0]}")
    elif reverted:
        msg = "게임 자동 감지를 껐습니다. 게임 동안 적용했던 설정을 되돌렸습니다."
    else:
        msg = "게임 자동 감지를 껐습니다."
    if not saved:
        msg += " 설정 파일에 저장하지 못해 다음 실행 때는 이전 상태로 시작합니다."
    return {"success": not revert_failed, "enabled": enabled, "saved": saved, "reverted": reverted,
            "revertFailed": revert_failed, "message": msg}


def _recover_after_crash():
    """지난번에 게임 도중 앱이 비정상 종료됐다면, 그때 적용한 것을 되돌린다.

    부스트는 세션 한정이 원칙인데 Nagle(레지스트리)과 전원 모드는 프로세스가
    죽어도 남는다. 앱을 막 켠 시점에는 게임 세션이 없으므로 남은 것은 전부 잔여물이다.
    """
    from backend import config_manager, process_boost, system_state as ss
    # 낮춰 둔 백그라운드 앱·올려 둔 게임의 우선순위와 효율 모드. 예전에는 메모리에만 기록해 남았고,
    # 다시 켜면 그 IDLE 이 '원래 값' 으로 굳었다.
    n, bad = process_boost.recover_after_crash()
    if n or bad:
        log.info(f"지난 세션의 프로세스 우선순위 복구: {n}건" + (f", 실패 {len(bad)}건" if bad else ""))
    prev = config_manager.get_boost_restore_mode()
    if prev:
        try:
            from backend import perf_modes
            res = perf_modes.apply_mode(prev, user_set=False, persist=False)
            if res.get('success'):
                config_manager.set_boost_restore_mode(None)
            log.info(f"지난 게임 세션의 전원 모드를 '{prev}' 로 되돌림: {res.get('message')}")
        except Exception as e:
            log.warning(f"지난 세션 전원 모드 복구 실패: {e}")
    if any(e.get('group') == BOOST_GROUP for e in ss.pending_changes().values()):
        r = ss.restore_group(BOOST_GROUP)
        log.info(f"지난 게임 세션의 Nagle 변경 복구: {r['restored']}건, 실패 {len(r['failed'])}건")


def init_booster():
    """앱 시작 시: 지난 세션 잔여물 정리 → 저장된 설정이 켜짐이면 감지 시작."""
    try:
        _recover_after_crash()
    except Exception as e:
        log.warning(f"지난 세션 정리 실패: {e}")
    try:
        from backend import config_manager
        state = config_manager.get_booster_state()
        if state is None:
            log.warning("설정 파일을 읽지 못해 게임 부스터를 켜지 않았습니다(저장된 상태를 모름)")
        elif state:
            toggle_booster(True)
    except Exception as e:
        log.warning(f"Failed to auto-init booster: {e}")


def shutdown(timeout=8.0):
    """앱을 닫을 때 부른다. 적용한 것을 '지금 이 스레드에서' 되돌린다.

    예전에는 종료 경로가 toggle_booster(False) 를 불렀다. 그 결과
    (1) booster_enabled=False 가 저장돼 다음 실행부터 게임 부스트가 꺼져 있었고,
    (2) 되돌리기를 데몬 스레드에 맡겼는데 창이 닫히며 프로세스가 끝나 그 스레드도
        같이 죽었다. 게임 도중 앱을 닫으면 Nagle·전원 모드가 그대로 남았다.
    """
    _stop_event.set()
    t = _monitor_thread
    if t is not None and t.is_alive() and t is not threading.current_thread():
        t.join(timeout)
    stop_eco_suppression_loop()
    restore_background_apps()
    if _booster_state["active"] or _applied or _tamed_pids:
        _teardown()
    return {"success": True}


# ─────────────────────────────────────────────
# Eco Mode Background Suppression
# ─────────────────────────────────────────────

_eco_suppression_thread = None
_eco_stop_event = threading.Event()
_eco_tamed_pids = set()
ECO_OWNER = 'eco'


def _get_foreground_pid():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value
    except Exception as e:
        log.debug(f"Failed to get foreground PID: {e}")
    return None


def _eco_suppression_thread_func():
    """에코 모드에서 바쁜 백그라운드 앱의 우선순위를 낮춘다.

    process_boost.find_throttle_candidates 가 고른 것만 건드린다.
    CPU 임계값을 넘고, 게임이 아니고, 보호 목록에 없고, process_guard 를
    통과한 프로세스만 후보가 된다.
    """
    global _eco_tamed_pids
    from backend import process_boost

    log.info("에코 억제 루프 시작")
    process_boost.prime_cpu_measurement()   # cpu_percent 기준점 잡기

    while not _eco_stop_event.is_set():
        try:
            fg_pid = _get_foreground_pid()
            candidates = process_boost.find_throttle_candidates(
                foreground_pid=fg_pid, cpu_threshold=ECO_CPU_THRESHOLD)
            pids = {c['pid'] for c in candidates}

            new_pids = pids - _eco_tamed_pids
            if new_pids:
                _eco_tamed_pids.update(_tame_processes(list(new_pids), owner=ECO_OWNER))

            # 더 이상 바쁘지 않거나 종료된 프로세스는 원래대로 돌려준다.
            gone = _eco_tamed_pids - pids
            if gone:
                _restore_processes(list(gone), owner=ECO_OWNER)
                _eco_tamed_pids -= gone

        except Exception as e:
            log.warning(f"에코 억제 루프 오류: {e}")

        _eco_stop_event.wait(ECO_INTERVAL_SEC)


def start_eco_suppression_loop():
    global _eco_suppression_thread
    _eco_stop_event.clear()
    if _eco_suppression_thread is None or not _eco_suppression_thread.is_alive():
        _eco_suppression_thread = threading.Thread(target=_eco_suppression_thread_func, daemon=True)
        _eco_suppression_thread.start()


def stop_eco_suppression_loop():
    _eco_stop_event.set()


def restore_background_apps():
    global _eco_tamed_pids
    if _eco_tamed_pids:
        log.info("Restoring priority for Eco-tamed background apps...")
        _restore_processes(list(_eco_tamed_pids), owner=ECO_OWNER)
        _eco_tamed_pids = set()
