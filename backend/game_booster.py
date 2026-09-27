"""
APEX CARE — 게임 부스터.

게임이 감지되면 사용자가 켜 둔 항목만 적용하고, 게임이 끝나면 그때 실제로 적용한 것만 되돌린다.

적용하는 것:
- 게임 프로세스 우선순위 '높음' (process_boost 경유, 원래 값 기록 → 복구)
- [선택] 바쁜 백그라운드 앱 양보: CPU 를 많이 쓰는 앱만 '낮은 편' + 효율 모드
  (게임·백신·통화·백업·인코더·런처·지금 보는 창 제외. process_boost 가 후보를 고른다)
- [선택] Nagle 끄기: 어댑터별 원래 값을 system_state 저널(그룹 'game_boost')에 기록하고 쓴다
- [선택] 게이밍 전원 모드: 게임이 끝나면 사용자가 고른 모드로 돌아간다

예전 구현에서 고친 것:
- 타이머 해상도 부스트 제거. Windows 10 2004 이후 NtSetTimerResolution/timeBeginPeriod 는
  호출한 프로세스에만 적용되어 게임에는 효과가 없고 전력만 쓴다.
- Nagle 복구가 원래 값을 모른 채 값을 지웠다. 이제 저널로 원래 값을 되살린다.
- 게임 종료 시 '종료 시점의 설정'을 보고 되돌려, 게임 중 옵션을 끄면 변경이 영구히 남았다.
- 게임 종료 시 사용자 모드와 상관없이 표준 모드를 적용했다.
- 리스트 별칭 버그로 복구 목록이 늘 비어 있어 효율 모드와 게임 HIGH 가 풀리지 않았다.
- 고정 앱 목록(카카오톡·슬랙·브라우저)을 CPU 와 무관하게 IDLE 로 내렸고, 설정을 꺼도 계속 내렸다.
- 게임 HIGH 가 process_guard 를 우회하고 원래 값을 기록하지 않아 되돌릴 수 없었다.
- SeDebugPrivilege 를 무조건 켰다. 쓰지 않던 Win32 폴백·일시정지·포그라운드 부스트 코드도 지웠다.
- 끄기와 앱 종료 때 정리를 데몬 스레드에 맡겨, 프로세스가 끝나면 정리가 실행되지 않았다.
"""
import ctypes
import ctypes.wintypes
import json
import logging
import os
import threading
import time
import winreg

import psutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='[GameBooster] %(message)s')
log = logging.getLogger('GameBooster')

# 자동 양보 기준: 전체 CPU 의 이 % 이상을 쓰는 백그라운드 프로세스만 건드린다.
# 게이밍 탭 프로세스 목록의 CPU 표시와 같은 단위다.
TAME_CPU_THRESHOLD = 3.0
TAME_PRIORITY = 'below_normal'
LOOP_INTERVAL_ACTIVE = 5
LOOP_INTERVAL_IDLE = 3

BOOST_GROUP = 'game_boost'          # system_state 저널 그룹
_TCPIP_IFACES = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
_NAGLE_VALUES = ('TcpAckFrequency', 'TCPNoDelay')

APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
# 게임 중 전원 모드를 바꿨다는 표시. 앱이 비정상 종료돼도 다음 실행 때 되돌리기 위해 남긴다.
SESSION_PATH = os.path.join(APPDATA_DIR, 'game_boost_session.json')

# 감지할 게임 실행 파일. javaw.exe 는 모든 Java 프로그램이 쓰는 이름이라 뺐다
# (Java 업무 프로그램·서버가 게임으로 잡혀 '높음' 우선순위가 걸렸다).
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
_GAME_RANK = {name: i for i, name in enumerate(GAMES_LIST)}

# UI 가 읽는 상태. 값은 통째로 바꿔 끼우고(리스트를 제자리에서 고치지 않는다),
# 읽을 때는 복사본을 준다.
_booster_state = {
    "enabled": False,
    "active": False,
    "detected_game": None,
    "boosted_pids": [],
    "boost_count": 0,
    "nagle_disabled": False,
    "appliedBoosts": [],     # 이번 게임에서 실제로 적용된 항목
    "boostFailures": [],     # 이번 게임에서 적용하지 못한 항목 [{item, reason}]
    "tamedCount": 0,
    "lastRestore": None,     # 마지막 되돌리기 결과 {at, reason, ok, restored, failed}
}
_state_lock = threading.Lock()

# 게임 세션 동안 부스터가 실제로 바꾼 것. _lock 안에서만 만진다.
_session = {
    "game_pids": {},         # pid -> create_time : 부스터가 '높음'으로 올린 게임
    "handled_games": set(),  # (pid, create_time) : 이미 처리한 게임(사용자가 되돌려도 다시 올리지 않는다)
    "tamed": {},             # pid -> create_time : 부스터가 양보시킨 백그라운드 앱
    "released": set(),       # (pid, create_time) : 사용자가 되돌린 앱. 이번 게임 동안 다시 건드리지 않는다
    "failures": [],
    "failed_keys": set(),
}
_lock = threading.RLock()

_monitor_thread = None
_loop_stop = None


def _publish(**kv):
    with _state_lock:
        _booster_state.update(kv)


def get_booster_status():
    with _state_lock:
        s = dict(_booster_state)
    for k in ("boosted_pids", "appliedBoosts", "boostFailures"):
        s[k] = list(s.get(k) or [])
    return s


def _load_cfg():
    try:
        from backend import config_manager
        return config_manager.load_config() or {}
    except Exception as e:
        log.warning(f"설정을 읽지 못해 부스트 항목을 모두 끈 것으로 봅니다: {e}")
        return {}


def _new_session():
    return {"game_pids": {}, "handled_games": set(), "tamed": {}, "released": set(),
            "failures": [], "failed_keys": set()}


def _note_failure(key, item, reason):
    """적용 실패를 한 번만 기록한다(5초마다 같은 실패가 쌓이지 않게)."""
    if key in _session["failed_keys"]:
        return
    _session["failed_keys"].add(key)
    _session["failures"].append({"item": item, "reason": reason or "알 수 없는 오류"})
    _publish(boostFailures=list(_session["failures"]))


def _get_foreground_pid():
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value or None
    except Exception as e:
        log.debug(f"Failed to get foreground PID: {e}")
    return None


# ─────────────────────────────────────────────
# Nagle (system_state 저널 경유)
# ─────────────────────────────────────────────

def _connected_interfaces():
    """IPv4 주소가 잡힌 어댑터의 인터페이스 키 이름. 읽기만 한다.

    예전에는 모든 인터페이스(가상·끊긴 어댑터 포함)에 썼고, 한 키에서 오류가 나면
    나머지를 건너뛰었다. 쓰는 범위를 실제로 통신 중인 어댑터로 줄인다.
    """
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _TCPIP_IFACES, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as base:
            i = 0
            while True:
                try:
                    names.append(winreg.EnumKey(base, i))
                except OSError:
                    break
                i += 1
    except OSError as e:
        log.warning(f"네트워크 인터페이스 목록을 읽지 못했습니다: {e}")
        return []

    out = []
    for n in names:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{_TCPIP_IFACES}\\{n}", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                if _has_ipv4(k):
                    out.append(n)
        except OSError:
            continue
    return out


def _has_ipv4(key):
    for value_name in ('DhcpIPAddress', 'IPAddress'):
        try:
            v, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue
        for addr in (v if isinstance(v, list) else [v]):
            if isinstance(addr, str) and addr.strip() and addr.strip() != '0.0.0.0':
                return True
    return False


def _journal_group_of(path, name):
    """이 값이 이미 저널에 있으면 그 그룹. 없으면 None."""
    try:
        from backend import system_state as ss
        e = ss.pending_changes().get(f"reg:HKLM\\{path}\\{name}")
        return e.get('group') if e else None
    except Exception:
        return None


def _disable_nagle():
    """IP 가 잡힌 어댑터에 TcpAckFrequency/TCPNoDelay=1 을 쓴다.

    값마다 system_state.set_registry 로 원래 값을 한 번만 기록하고 쓴 뒤 되읽어 확인한다.
    이미 1 인 값은 건드리지 않는다(원래 값 기록도 하지 않는다).
    다른 기능(예: 네트워크 최적화)이 저널에 먼저 기록한 값도 건드리지 않는다.
    """
    from backend import system_state as ss
    ifaces = _connected_interfaces()
    if not ifaces:
        return {'changed': 0, 'already': 0,
                'failed': [{'item': 'Nagle 끄기', 'reason': 'IP 가 잡힌 네트워크 어댑터를 찾지 못했습니다.'}]}

    changed, already, failed = 0, 0, []
    for iface in ifaces:
        path = f"{_TCPIP_IFACES}\\{iface}"
        for name in _NAGLE_VALUES:
            existed, cur, _ = ss.read_registry('HKLM', path, name)
            if existed and cur == 1:
                already += 1
                continue
            other = _journal_group_of(path, name)
            if other and other != BOOST_GROUP:
                failed.append({'item': f'Nagle 끄기 ({name})',
                               'reason': f"다른 기능('{other}')이 관리 중인 값이라 건드리지 않았습니다."})
                continue
            r = ss.set_registry('HKLM', path, name, 1, group=BOOST_GROUP,
                                why=f'게임 부스트: Nagle 끄기 ({name})')
            if r.get('ok'):
                changed += 1
            else:
                failed.append({'item': f'Nagle 끄기 ({name})',
                               'reason': r.get('reason') or r.get('error') or '쓰기 실패'})
    log.info(f"Nagle 끄기: 변경 {changed}, 이미 적용 {already}, 실패 {len(failed)}")
    return {'changed': changed, 'already': already, 'failed': failed}


def _boost_journal_pending():
    try:
        from backend import system_state as ss
        return sum(1 for e in ss.pending_changes().values() if e.get('group') == BOOST_GROUP)
    except Exception:
        return 0


# ─────────────────────────────────────────────
# 전원 모드 (게임 중에만 게이밍)
# ─────────────────────────────────────────────

def _read_session_marker():
    try:
        with open(SESSION_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning(f"부스트 세션 기록을 읽지 못했습니다: {e}")
        return {}


def _write_session_marker(data):
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        tmp = SESSION_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SESSION_PATH)
        return True
    except Exception as e:
        log.warning(f"부스트 세션 기록 저장 실패: {e}")
        return False


def _user_mode(fallback=None):
    """사용자가 직접 고른 성능 모드. 게임 중 자동 전환은 이 값을 바꾸지 않는다."""
    try:
        from backend import config_manager
        if hasattr(config_manager, 'get_user_mode'):
            m = config_manager.get_user_mode()
            if m in ('standard', 'gaming', 'eco'):
                return m
        elif fallback in ('standard', 'gaming', 'eco'):
            return fallback
        else:
            # 구버전 설정: 사용자가 고른 적이 없으면 표준
            if config_manager.get_optimization_mode_user_set():
                m = config_manager.get_optimization_mode()
                if m in ('standard', 'gaming', 'eco'):
                    return m
    except Exception as e:
        log.warning(f"사용자 모드를 읽지 못했습니다: {e}")
    return fallback if fallback in ('standard', 'gaming', 'eco') else 'standard'


def _enter_power_mode(applied):
    """게이밍 모드로 바꾼다. 사용자가 이미 게이밍 모드면 아무것도 하지 않는다."""
    marker = _read_session_marker()
    if marker.get('power_mode_applied'):
        # 지난 실행이 남긴 게이밍 모드가 아직 걸려 있다. 다시 걸지 않고 이어서 관리한다.
        applied.append('게이밍 전원 모드')
        return
    prev = _user_mode()
    if prev == 'gaming':
        applied.append('게이밍 전원 모드 (이미 사용 중)')
        return
    try:
        from backend import perf_modes
    except Exception as e:
        _note_failure('power', '게이밍 전원 모드', str(e))
        return
    # 먼저 표시를 남긴다. 전환 도중 앱이 죽어도 다음 실행에서 되돌릴 수 있게.
    if not _write_session_marker({'power_mode_applied': True, 'restore_to': prev, 'ts': time.time()}):
        _note_failure('power', '게이밍 전원 모드',
                      '되돌리기 정보를 저장하지 못해 전원 모드를 바꾸지 않았습니다.')
        return
    try:
        res = perf_modes.apply_mode('gaming', user_set=False) or {}
    except Exception as e:
        res = {'success': False, 'message': str(e)}
    if res.get('error') in ('UAC_REQUIRED', 'UNKNOWN_MODE'):
        _write_session_marker({})       # 아무것도 바뀌지 않았다
        _note_failure('power', '게이밍 전원 모드', res.get('message'))
        return
    if res.get('success'):
        applied.append('게이밍 전원 모드')
    elif res.get('partial'):
        applied.append('게이밍 전원 모드 (일부 실패)')
        _note_failure('power_partial', '게이밍 전원 모드 일부', res.get('message'))
    else:
        _note_failure('power', '게이밍 전원 모드', res.get('message'))


def _restore_power_mode(restored, failed):
    """게이밍 모드로 바꿨었다면 사용자가 고른 모드로 되돌린다."""
    marker = _read_session_marker()
    if not marker.get('power_mode_applied'):
        return
    target = _user_mode(fallback=marker.get('restore_to'))
    if target == 'gaming':
        # 사용자가 게임 도중 게이밍 모드를 직접 골랐다. 지금 상태가 사용자의 선택이다.
        _write_session_marker({})
        return
    try:
        from backend import perf_modes
        res = perf_modes.apply_mode(target, user_set=False) or {}
    except Exception as e:
        res = {'success': False, 'message': str(e)}
    label = {'standard': '표준', 'eco': '에코'}.get(target, target)
    if res.get('success'):
        restored.append(f'전원 모드 ({label})')
        _write_session_marker({})
    else:
        # 표시를 남겨 둬야 다음에 다시 시도할 수 있다
        failed.append({'item': f'전원 모드 ({label}) 복귀',
                       'reason': res.get('message') or '전원 모드를 되돌리지 못했습니다.'})


# ─────────────────────────────────────────────
# 게임 세션
# ─────────────────────────────────────────────

def _scan_games():
    """실행 중인 게임 {pid: (이름, 생성 시각)}."""
    found = {}
    for p in psutil.process_iter(['name', 'create_time']):
        try:
            name = (p.info.get('name') or '').lower()
            if name in _GAME_RANK:
                found[p.pid] = (name, p.info.get('create_time'))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return found


def _boost_games(games):
    """아직 처리하지 않은 게임 프로세스를 '높음'으로 올린다."""
    from backend import process_boost
    for pid, (name, ct) in games.items():
        key = (pid, ct)
        if key in _session["handled_games"]:
            continue
        _session["handled_games"].add(key)
        if process_boost.is_adjusted(pid):
            continue                     # 사용자가 직접 바꿔 둔 프로세스는 건드리지 않는다
        r = process_boost.set_priority(pid, 'high', reason='(게임 부스트)', owner='booster')
        if r.get('ok'):
            _session["game_pids"][pid] = ct
        else:
            _note_failure(('game', pid), f'{name} 우선순위 높임', r.get('reason'))
    # 끝난 게임 프로세스는 목록에서 뺀다(원래 값 기록은 process_boost 가 정리한다)
    for pid in [p for p in _session["game_pids"] if p not in games]:
        _session["game_pids"].pop(pid, None)


def _release_tamed(pids, restored=None, failed=None):
    from backend import process_boost
    for pid in pids:
        _session["tamed"].pop(pid, None)
        r = process_boost.restore(pid)
        if r.get('ok'):
            if restored is not None and not r.get('ended'):
                restored.append(r.get('name') or str(pid))
        elif 'reason' in r and r.get('reason') != '기록된 원래 값이 없습니다.':
            if failed is not None:
                failed.append({'item': f"{r.get('name') or pid} 우선순위", 'reason': r['reason']})


def _tame_background(cfg, games):
    """CPU 를 많이 쓰는 백그라운드 앱을 양보시킨다. 설정이 꺼져 있으면 즉시 되돌린다."""
    from backend import process_boost
    if not cfg.get('boost_tame_background', False):
        # 게임 중에 사용자가 이 항목을 껐다. 다음 게임까지 기다리지 않고 바로 되돌린다.
        if _session["tamed"]:
            failed = []
            _release_tamed(list(_session["tamed"]), None, failed)
            for f in failed:
                _note_failure(('untame', f['item']), f['item'] + ' 복구', f['reason'])
        _publish(tamedCount=0)
        return

    fg = _get_foreground_pid()
    exclude = set(process_boost.process_tree(fg))
    for pid in games:
        exclude |= process_boost.process_tree(pid)

    for pid, ct in list(_session["tamed"].items()):
        if not process_boost.is_adjusted(pid, ct):
            # 사용자가 되돌렸거나 끝났다. 이번 게임 동안 다시 건드리지 않는다.
            _session["tamed"].pop(pid, None)
            _session["released"].add((pid, ct))
        elif pid in exclude:
            # 사용자가 그 창으로 전환했다. 바로 원래대로.
            _release_tamed([pid])

    candidates = process_boost.find_throttle_candidates(
        foreground_pid=fg, cpu_threshold=TAME_CPU_THRESHOLD, exclude_pids=exclude)
    for c in candidates:
        pid, ct = c['pid'], c.get('create_time')
        if pid in _session["tamed"] or (pid, ct) in _session["released"]:
            continue
        if process_boost.is_adjusted(pid):
            continue                     # 사용자가 직접 바꾼 것은 건드리지 않는다
        r = process_boost.set_priority(pid, TAME_PRIORITY, reason='(게임 중 백그라운드 양보)',
                                       ecoqos=True, owner='booster')
        if r.get('ok'):
            _session["tamed"][pid] = ct
    _publish(tamedCount=len(_session["tamed"]))


def _start_session(games, cfg):
    global _session
    _session = _new_session()
    applied = []

    if cfg.get('boost_disable_nagle', False):
        r = _disable_nagle()
        for f in r['failed']:
            _note_failure(('nagle', f['item']), f['item'], f['reason'])
        if r['changed'] or r['already']:
            applied.append('Nagle 끄기' + (' (일부 실패)' if r['failed'] else ''))
        _publish(nagle_disabled=bool(r['changed'] or r['already']))

    if cfg.get('boost_auto_power_mode', False):
        _enter_power_mode(applied)

    _publish(active=True, appliedBoosts=applied, boostFailures=list(_session["failures"]),
             boost_count=_booster_state.get('boost_count', 0) + 1)
    log.info(f"부스트 진입: {', '.join(applied) if applied else '선택 항목 없음'}")


def _update_session(games, cfg):
    if not _booster_state.get('active'):
        _start_session(games, cfg)

    _boost_games(games)
    _tame_background(cfg, games)

    top = min(games.values(), key=lambda v: _GAME_RANK.get(v[0], 999))[0]
    applied = [a for a in _booster_state.get('appliedBoosts') or [] if not a.startswith('게임 우선순위')]
    if _session["game_pids"]:
        applied.insert(0, f"게임 우선순위 높음 ({len(_session['game_pids'])}개)")
    _publish(detected_game=top, boosted_pids=sorted(_session["game_pids"]), appliedBoosts=applied)


def _end_session(reason):
    """부스터가 바꾼 것을 되돌린다. {ok, restored:[], failed:[]}.

    이번 세션이 실제로 바꾼 것만 되돌린다. 설정 파일의 현재 값은 보지 않는다
    (게임 중 옵션을 끄면 복구가 건너뛰어져 변경이 영구히 남던 문제).
    """
    from backend import process_boost
    restored, failed = [], []

    # 1. 프로세스 우선순위: 부스터가 바꾼 것만(사용자가 직접 바꾼 것은 사용자 몫)
    names = []
    _release_tamed(list(_session["tamed"]), names, failed)
    for pid in list(_session["game_pids"]):
        r = process_boost.restore(pid)
        if r.get('ok'):
            if not r.get('ended'):
                names.append(r.get('name') or str(pid))
        elif r.get('reason') != '기록된 원래 값이 없습니다.':
            failed.append({'item': f"{r.get('name') or pid} 우선순위", 'reason': r.get('reason')})
    # 세션이 놓친 부스터 기록(비정상 종료 뒤 복구 등)도 함께
    rest = process_boost.restore_all(owner='booster')
    for f in rest.get('failed') or []:
        failed.append({'item': f"{f.get('name') or f.get('pid')} 우선순위", 'reason': f.get('reason')})
    count = len(names) + max(0, rest.get('restored', 0) - rest.get('ended', 0))
    if count:
        restored.append(f'프로세스 우선순위 {count}개')

    # 2. Nagle: 저널의 원래 값으로. 그룹은 부스터 전용이라 남아 있는 것은 모두 부스터가 쓴 것이다.
    if _boost_journal_pending():
        try:
            from backend import system_state as ss
            r = ss.restore_group(BOOST_GROUP)
            if r.get('restored'):
                restored.append(f"Nagle 설정 {r['restored']}개 값")
            for f in r.get('failed') or []:
                failed.append({'item': f"Nagle 설정 ({f.get('key')})", 'reason': f.get('reason')})
        except Exception as e:
            failed.append({'item': 'Nagle 설정', 'reason': str(e)})

    # 3. 전원 모드
    _restore_power_mode(restored, failed)

    _session.update(_new_session())
    result = {'ok': not failed, 'restored': restored, 'failed': failed}
    _publish(active=False, detected_game=None, boosted_pids=[], appliedBoosts=[],
             boostFailures=[], tamedCount=0, nagle_disabled=False,
             lastRestore={'at': time.time(), 'reason': reason, **result})
    log.info(f"부스트 종료({reason}): 되돌림 {restored or '없음'}, 실패 {len(failed)}")
    return result


def _has_leftovers():
    return bool(_boost_journal_pending() or _read_session_marker().get('power_mode_applied'))


# ─────────────────────────────────────────────
# 감시 루프
# ─────────────────────────────────────────────

def _booster_loop(stop):
    from backend import process_boost
    process_boost.prime_cpu_measurement()   # cpu_percent 기준점 잡기
    while not stop.is_set():
        interval = LOOP_INTERVAL_IDLE
        try:
            with _lock:
                if stop.is_set():
                    break
                games = _scan_games()
                if games:
                    _update_session(games, _load_cfg())
                    interval = LOOP_INTERVAL_ACTIVE
                elif _booster_state.get('active'):
                    _end_session('게임 종료')
        except Exception as e:
            log.error(f"Booster loop error: {e}")
            interval = LOOP_INTERVAL_ACTIVE
        stop.wait(interval)


def _start_loop():
    global _monitor_thread, _loop_stop
    if _monitor_thread is not None and _monitor_thread.is_alive():
        if _loop_stop is not None and not _loop_stop.is_set():
            return True                  # 이미 돌고 있다
        _monitor_thread.join(2.0)        # 멈추는 중인 이전 루프를 기다린다
        if _monitor_thread.is_alive():
            return False
    _loop_stop = threading.Event()       # 루프마다 자기 이벤트. 이전 루프의 정지 신호를 지우지 않는다
    _monitor_thread = threading.Thread(target=_booster_loop, args=(_loop_stop,),
                                       daemon=True, name='GameBooster')
    _monitor_thread.start()
    log.info("게임 감시 시작")
    return True


def _stop_and_restore(reason, timeout):
    """루프를 멈추고, 부스터가 바꾼 것을 호출한 스레드에서 직접 되돌린다."""
    global _monitor_thread
    deadline = time.monotonic() + max(0.5, float(timeout or 0))
    t, ev = _monitor_thread, _loop_stop
    if ev is not None:
        ev.set()
    if t is not None and t is not threading.current_thread():
        t.join(max(0.0, deadline - time.monotonic()))
        if not t.is_alive():
            _monitor_thread = None

    if not _lock.acquire(timeout=max(0.5, deadline - time.monotonic())):
        return {'ok': False, 'restored': [],
                'failed': [{'item': '게임 부스터',
                            'reason': '진행 중인 부스트 작업이 끝나지 않아 되돌리지 못했습니다. 잠시 후 다시 시도해 주세요.'}]}
    try:
        if _booster_state.get('active') or _session["tamed"] or _session["game_pids"] or _has_leftovers():
            return _end_session(reason)
        # 세션 밖에서 남은 부스터 우선순위 기록(있다면)
        from backend import process_boost
        rest = process_boost.restore_all(owner='booster')
        failed = [{'item': f"{f.get('name') or f.get('pid')} 우선순위", 'reason': f.get('reason')}
                  for f in rest.get('failed') or []]
        n = rest.get('restored', 0) - rest.get('ended', 0)
        return {'ok': not failed, 'restored': [f'프로세스 우선순위 {n}개'] if n > 0 else [],
                'failed': failed}
    finally:
        _lock.release()


# ─────────────────────────────────────────────
# 공개 함수
# ─────────────────────────────────────────────

def toggle_booster(enabled):
    """사용자가 자동 감지를 켜고 끈다. 끌 때는 정리를 끝낸 뒤 실제 결과를 돌려준다."""
    enabled = bool(enabled)
    saved = True
    try:
        from backend import config_manager
        r = config_manager.set_booster_state(enabled)
        if r is False:
            saved = False
    except Exception as e:
        log.warning(f"Failed to save booster state: {e}")
        saved = False

    if enabled:
        _publish(enabled=True)
        if not _start_loop():
            _publish(enabled=False)
            return {'success': False, 'enabled': False, 'saved': saved,
                    'message': '이전 감시가 아직 끝나지 않았습니다. 잠시 후 다시 시도해 주세요.'}
        return {'success': True, 'enabled': True, 'saved': saved}

    _publish(enabled=False)
    res = _stop_and_restore('자동 감지 끔', timeout=5.0)
    return {'success': res['ok'], 'enabled': False, 'saved': saved,
            'restored': res['restored'], 'failed': res['failed']}


def shutdown(timeout=5.0):
    """앱 종료용 동기 정리. 루프를 멈추고 부스터가 바꾼 것을 모두 되돌린다.

    booster_enabled 설정은 저장하지 않는다(창을 닫았다고 사용자 설정이 꺼지면 안 된다).
    여러 번 불러도 된다.
    """
    _publish(enabled=False)
    try:
        return _stop_and_restore('앱 종료', timeout)
    except Exception as e:
        log.warning(f"부스터 종료 정리 실패: {e}")
        return {'ok': False, 'restored': [], 'failed': [{'item': '게임 부스터', 'reason': str(e)}]}


def init_booster():
    """앱 시작 시: 지난 실행이 남긴 부스트를 되돌리고, 사용자가 켜 둔 경우에만 감시를 시작한다."""
    enabled = False
    try:
        from backend import config_manager
        enabled = config_manager.load_config().get('booster_enabled') is True
    except Exception as e:
        log.warning(f"Failed to read booster state: {e}")

    # 지난 실행이 강제 종료됐다면 우선순위 원래 값이 디스크에 남아 있다
    try:
        from backend import process_boost
        process_boost.recover_previous_session()
    except Exception as e:
        log.warning(f"지난 우선순위 복구 실패: {e}")

    # 저널에 남은 부스트(Nagle)·게임 중 전원 모드. 게임이 돌고 있고 감시가 켜져 있으면
    # 그 게임이 끝날 때 되돌리고, 아니면 지금 되돌린다.
    try:
        if _has_leftovers() and (not enabled or not _scan_games()):
            with _lock:
                res = _end_session('지난 실행에서 남은 부스트 복구')
            if res['failed']:
                log.warning(f"남은 부스트 복구 실패: {res['failed']}")
    except Exception as e:
        log.warning(f"남은 부스트 복구 중 오류: {e}")

    if enabled:
        _publish(enabled=True)
        _start_loop()
