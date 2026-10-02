import json
import os
import re
import tempfile
import threading
import time

APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
os.makedirs(APPDATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(APPDATA_DIR, "settings.json")

DEFAULT_CONFIG = {
    "booster_enabled": True,
    "eula_accepted": False,
    # 신규 설치 기본값은 반드시 'standard'. 동의 없이 공격적 튜닝을 적용하지 않는다.
    "optimization_mode": "standard",
    # 사용자가 UI에서 직접 모드를 고른 적이 있는지 여부.
    # False면 앱 시작 시 저장된 모드를 자동 적용하지 않는다.
    "optimization_mode_user_set": False,
    # 구버전이 중지시킨 Windows Update 서비스 1회 복구 완료 플래그
    "wu_recovery_done": False,

    # ── 게임 부스트가 무엇을 해도 되는지 ────────────────────────
    # 기본값 원칙: 되돌릴 수 있고 세션 한정인 것만 켜둔다.
    # 영구 변경(레지스트리)과 OS 설정 변경은 사용자가 직접 켜야 한다.
    # 예전에는 게임이 감지되면 이 셋을 고지 없이 한꺼번에 적용했다.
    "boost_timer_resolution": True,    # 0.5ms 타이머. 세션 한정, 종료 시 자동 복귀
    "boost_disable_nagle": False,      # 레지스트리 영구 변경. 복구 함수는 있음
    "boost_auto_power_mode": False,    # 게임 감지 시 게이밍 전원 모드로 자동 전환
    "boost_tame_background": True,     # 바쁜 백그라운드 앱 우선순위 낮춤(복구됨)

    # UI 색 조합. 목록은 src/theme.js 의 THEMES 와 같아야 한다.
    "ui_theme": "cyan",
    # 직접 고른 강조색("#rrggbb"). 빈 문자열이면 색 조합의 기본 강조색을 쓴다.
    # 대비 검사는 UI(src/theme.js)가 한다. 읽기 어려운 값이 들어 있으면 UI 가 쓰지 않는다.
    "ui_accent": "",
    # 초기 설정 마법사를 한 번 닫았는지. 예전에는 앱을 켤 때마다 마법사가 떴다.
    "setup_wizard_done": False,
}

UI_THEMES = ('cyan', 'graphite', 'stone', 'midnight', 'violet')

# pywebview 는 JS 호출마다 새 스레드를 쓰고, 게임 부스터 감시도 따로 돈다. 읽고-고치고-쓰기를
# 한 번에 하나만 하게 한다. 예전에는 두 스레드가 같은 임시 파일에 동시에 써서 파일이 깨질 수 있었고,
# 깨진 파일은 기본값으로 바뀌며 구버전 복구 백업까지 사라졌다. 늦게 저장한 쪽이 먼저 저장한 값을
# 덮어쓰는 일(예: 색 설정을 바꾸는 사이 부스트가 저장한 값이 사라짐)도 있었다.
_lock = threading.RLock()

_READ_RETRIES = 3          # 백신 검사 등으로 잠깐 잠긴 파일을 다시 읽어 볼 횟수
_RETRY_WAIT = 0.15


class _ReadError(Exception):
    """파일은 있는데 읽지 못했다(잠김·권한). 내용이 깨진 것과 다르다."""


class _Unreadable(dict):
    """읽지 못해 기본값으로 대신한 설정. 이것을 저장하면 멀쩡한 파일을 기본값으로 덮어쓰게 된다."""


def _move_aside():
    stamp = time.strftime('%Y%m%d-%H%M%S')
    try:
        os.replace(CONFIG_FILE, f"{CONFIG_FILE}.corrupt-{stamp}")
    except Exception:
        pass


def _read_once():
    try:
        with open(CONFIG_FILE, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return DEFAULT_CONFIG.copy()
    except OSError as e:
        raise _ReadError(e)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("설정 파일의 최상위가 객체가 아닙니다")
    except ValueError:
        # 내용이 깨졌다. 다음 저장이 덮어쓰면 그 안의 복구 백업도 사라지므로 옆으로 옮겨 둔다.
        _move_aside()
        return DEFAULT_CONFIG.copy()
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(data)
    return cfg


def _read_strict():
    for attempt in range(_READ_RETRIES):
        try:
            return _read_once()
        except _ReadError:
            if attempt == _READ_RETRIES - 1:
                raise
            time.sleep(_RETRY_WAIT)


def load_config():
    """설정을 읽는다. 파일이 잠겨 읽지 못하면 기본값을 돌려주되, 그 값은 저장되지 않는다."""
    with _lock:
        try:
            return _read_strict()
        except _ReadError:
            return _Unreadable(DEFAULT_CONFIG)


def save_config(config):
    """원자적으로 저장한다. 성공하면 True.

    예전에는 파일을 그 자리에서 덮어쓰고 실패를 삼켰다. 쓰는 도중 죽으면 설정이
    반쯤 쓰인 채 깨지고, load_config 가 조용히 기본값으로 돌아가 구버전 복구 백업
    (network_tweak_backup, service_start_backup)까지 사라졌다.
    읽지 못해 대신 쓴 기본값(_Unreadable)은 저장하지 않는다.
    """
    if isinstance(config, _Unreadable):
        return False
    with _lock:
        tmp = None
        try:
            os.makedirs(APPDATA_DIR, exist_ok=True)
            # 쓸 때마다 다른 임시 파일. 같은 이름을 함께 쓰면 서로의 내용을 잘라 먹는다.
            fd, tmp = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=APPDATA_DIR)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(_READ_RETRIES):
                try:
                    os.replace(tmp, CONFIG_FILE)
                    tmp = None
                    return True
                except PermissionError:
                    # 백신이 잠깐 잡고 있으면 바꿔 넣기가 거부된다
                    if attempt == _READ_RETRIES - 1:
                        raise
                    time.sleep(_RETRY_WAIT)
        except Exception:
            return False
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def update_config(change):
    """읽고 → change(cfg) 로 고치고 → 저장을 한 번에 한다. 저장했으면 True.

    오래 걸리는 작업 전에 읽어 둔 설정을 통째로 다시 저장하면, 그 사이 다른 곳이 바꾼 값이 사라진다.
    바꾸는 쪽은 자기 키만 고치도록 이 함수를 쓴다. 파일을 읽지 못하면 아무것도 쓰지 않는다.
    """
    with _lock:
        try:
            cfg = _read_strict()
        except _ReadError:
            return False
        change(cfg)
        return save_config(cfg)


def is_unreadable(cfg):
    """load_config() 가 파일을 읽지 못해 기본값으로 대신한 설정인가. 이 값으로 무언가를 켜거나 바꾸면 안 된다."""
    return isinstance(cfg, _Unreadable)


def get_booster_state():
    """부스터를 켜 둘지. 설정을 읽지 못하면 None(모름) — 기본값 '켜짐' 으로 부스터를 켜지 않는다.

    예전에는 백신 검사로 파일을 잠깐 못 읽으면 기본값 True 로 부스터가 켜지고 그 상태가 저장됐다.
    """
    cfg = load_config()
    if is_unreadable(cfg):
        return None
    return cfg.get("booster_enabled", True)

def set_booster_state(state):
    return update_config(lambda c: c.__setitem__("booster_enabled", bool(state)))


def get_boost_restore_mode():
    """게임 부스트가 게이밍 전원 모드를 켜기 전에 쓰던 모드. 없으면 None.

    게임이 끝나면 지워진다. 앱을 다시 켰는데 남아 있으면 게임 도중 비정상 종료된 것이다.
    """
    return load_config().get("boost_restore_mode")


def set_boost_restore_mode(mode):
    def change(c):
        if mode is None:
            c.pop("boost_restore_mode", None)
        else:
            c["boost_restore_mode"] = str(mode)
    return update_config(change)

def get_eula_accepted():
    return load_config().get("eula_accepted", False)

def set_eula_accepted(state):
    return update_config(lambda c: c.__setitem__("eula_accepted", bool(state)))

def get_optimization_mode():
    return load_config().get("optimization_mode", "standard")

def set_optimization_mode(mode, user_set=True):
    """저장했으면 True."""
    def change(c):
        c["optimization_mode"] = str(mode)
        # 게임 자동감지 등 내부 호출(user_set=False)은 '사용자가 고른 모드'로 기록하지 않는다
        if user_set:
            c["optimization_mode_user_set"] = True
    return update_config(change)

def get_optimization_mode_user_set():
    return load_config().get("optimization_mode_user_set", False)

def get_wu_recovery_done():
    return load_config().get("wu_recovery_done", False)

def set_wu_recovery_done(state):
    return update_config(lambda c: c.__setitem__("wu_recovery_done", bool(state)))


def get_boost_settings():
    """게임 부스트 설정. UI 가 토글을 그리는 데 쓴다."""
    c = load_config()
    return {k: c.get(k, DEFAULT_CONFIG[k]) for k in (
        'boost_timer_resolution', 'boost_disable_nagle',
        'boost_auto_power_mode', 'boost_tame_background')}


def set_boost_setting(key, value):
    """부스트 설정 하나를 바꾼다. 알 수 없는 키는 거부한다."""
    allowed = {'boost_timer_resolution', 'boost_disable_nagle',
               'boost_auto_power_mode', 'boost_tame_background'}
    if key not in allowed:
        return {"success": False, "message": f"알 수 없는 설정입니다: {key}"}
    if not update_config(lambda c: c.__setitem__(key, bool(value))):
        return {"success": False, "message": "설정을 저장하지 못했습니다."}
    return {"success": True, "key": key, "value": bool(value)}


def get_ui_theme():
    """저장된 UI 색 조합. 알 수 없는 값이면 기본값을 돌려준다."""
    theme = load_config().get("ui_theme", DEFAULT_CONFIG["ui_theme"])
    return theme if theme in UI_THEMES else DEFAULT_CONFIG["ui_theme"]


def set_ui_theme(theme):
    """UI 색 조합을 저장하고, 다시 읽어 저장됐는지 확인한다."""
    if theme not in UI_THEMES:
        return {"success": False, "message": f"알 수 없는 색 조합입니다: {theme}"}
    if not update_config(lambda c: c.__setitem__("ui_theme", theme)) or load_config().get("ui_theme") != theme:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 색 조합으로 열립니다."}
    return {"success": True, "theme": theme}


_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def get_ui_accent():
    """직접 고른 강조색. 없거나 형식이 틀리면 None."""
    value = load_config().get("ui_accent") or ""
    return value.lower() if isinstance(value, str) and _HEX_RE.match(value) else None


def set_ui_accent(value):
    """강조색을 저장한다. None 이나 빈 문자열이면 지정을 해제한다. 다시 읽어 확인한다."""
    if value in (None, ""):
        value = ""
    elif not (isinstance(value, str) and _HEX_RE.match(value)):
        return {"success": False, "message": f"색 형식이 올바르지 않습니다: {value}"}
    value = value.lower()
    if not update_config(lambda c: c.__setitem__("ui_accent", value)) or load_config().get("ui_accent") != value:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 색으로 열립니다."}
    return {"success": True, "accent": value or None}


def get_setup_wizard_done():
    """마법사를 닫은 적이 있는지. 설정을 읽지 못하면 None(모름) — 화면은 그때 마법사를 띄우지 않는다."""
    cfg = load_config()
    if is_unreadable(cfg):
        return None
    return bool(cfg.get("setup_wizard_done", False))


def set_setup_wizard_done():
    """마법사를 닫았다고 기록한다. 다시 읽어 저장됐는지 확인한다."""
    if (not update_config(lambda c: c.__setitem__("setup_wizard_done", True))
            or load_config().get("setup_wizard_done") is not True):
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때 마법사가 다시 뜰 수 있습니다."}
    return {"success": True}
