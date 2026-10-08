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
    # 성능 모드(optimization_mode·optimization_mode_user_set)와 게임 전 모드(boost_restore_mode)는 PC 전체 설정이라
    # 여기가 아니라 machine_store 에 둔다(아래 '_machine_settings').
    # 구버전이 중지시킨 Windows Update 서비스 1회 복구 완료 플래그
    "wu_recovery_done": False,

    # ── 게임 부스트가 무엇을 해도 되는지 ────────────────────────
    # 기본값 원칙: 되돌릴 수 있고 세션 한정인 것만 켜둔다.
    # 영구 변경(레지스트리)과 OS 설정 변경은 사용자가 직접 켜야 한다.
    # 예전에는 게임이 감지되면 이 셋을 고지 없이 한꺼번에 적용했다.
    "boost_timer_resolution": True,    # 0.5ms 타이머. 세션 한정, 종료 시 자동 복귀
    "boost_disable_nagle": False,      # 게임 동안만 레지스트리에 기록, 끝나면 원래대로(재연결 뒤 반영)
    "boost_auto_power_mode": False,    # 게임 감지 시 게이밍 전원 모드로 자동 전환
    "boost_tame_background": True,     # 바쁜 백그라운드 앱 우선순위 낮춤(복구됨)

    # UI 색 조합. 목록은 src/theme.js 의 THEMES 와 같아야 한다.
    "ui_theme": "cyan",
    # 직접 고른 강조색("#rrggbb"). 빈 문자열이면 색 조합의 기본 강조색을 쓴다.
    # 대비 검사는 UI(src/theme.js)가 한다. 읽기 어려운 값이 들어 있으면 UI 가 쓰지 않는다.
    "ui_accent": "",
    # 직접 고른 배경색("#rrggbb"). 색상·채도만 쓰고 밝기는 어두운 화면 기준으로 맞춘다(src/theme.js). 빈 문자열이면 색 조합 그대로.
    "ui_background": "",
    # 글자·화면 크기(%). UI_SCALES 중 하나.
    "ui_scale": 100,
    # 움직임 줄이기(애니메이션·부드러운 스크롤 끄기)
    "ui_reduce_motion": False,
    # 앱 아이콘 색: "" 기본 | "accent" 강조색 | "dark" 어두운 바탕 | "#rrggbb" 직접 고른 바탕색
    "ui_icon": "",
    # 화면 밝기: "dark" 어둡게 | "light" 밝게
    "ui_mode": "dark",
    # 초기 설정 마법사를 한 번 닫았는지. 예전에는 앱을 켤 때마다 마법사가 떴다.
    "setup_wizard_done": False,
}

UI_THEMES = ('cyan', 'graphite', 'stone', 'midnight', 'violet')
UI_SCALES = (90, 100, 110, 125)          # src/theme.js 의 UI_SCALES 와 같아야 한다

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


# ── PC 전체에 하나뿐인 설정 ─────────────────────────────────
# 성능 모드는 전원 플랜·HKLM 을 바꾸므로 PC 에 하나다. 계정마다 따로 두면 계정 B 의 화면이 계정 A 가 켠 게이밍을
# '표준' 으로 보여 주고, 앱을 켤 때 서로 다른 모드를 다시 적용한다. machine_store(HKLM, 관리자만 씀)에 둔다.
# 처음에는(예전 버전에서 올라옴) 이 계정의 settings.json 값을 한 번 가져오고 그 파일에서는 지운다. 남겨 두면
# 제거할 때 PC 쪽 기록을 지운 뒤 다시 설치했을 때, 그 사이 바뀐 적 없는 옛 모드(예: 게이밍)를 다시 가져와 적용한다.
# 신규 설치 기본값은 반드시 '표준', '사용자가 고른 적 없음'(앱을 켤 때 모드를 다시 적용하지 않음)이다.
_MACHINE_VALUE = 'Settings'
_MACHINE_KEYS = ('optimization_mode', 'optimization_mode_user_set', 'boost_restore_mode')


def _machine_settings():
    """PC 전체 설정 dict. 읽지 못하면 None."""
    from backend import machine_store
    with _lock:
        try:
            data = machine_store.read(_MACHINE_VALUE)
        except machine_store.Unreadable:
            return None
        if isinstance(data, dict):
            _drop_account_copy()
            return data
        cfg = load_config()
        if is_unreadable(cfg):
            return None
        data = {k: cfg[k] for k in _MACHINE_KEYS if k in cfg}
        if machine_store.write(_MACHINE_VALUE, data) and data:
            update_config(lambda c: [c.pop(k, None) for k in _MACHINE_KEYS])
        return data                                      # 못 썼으면 이번에는 이 값을 쓰고 다음에 다시 가져온다


_dropped = [False]


def _drop_account_copy():
    """PC 쪽 설정이 이미 있으면 이 계정 파일에 남은 옛 모드 값을 지운다(가져오지는 않는다). 실행마다 한 번.
    남겨 두면 제거(PC 쪽 기록 삭제) 뒤 다시 설치했을 때 이 계정이 먼저 켜면 옛 게이밍 모드를 가져와 적용했다."""
    if _dropped[0]:
        return
    cfg = load_config()
    if is_unreadable(cfg):
        return
    _dropped[0] = True
    if any(k in cfg for k in _MACHINE_KEYS):
        update_config(lambda c: [c.pop(k, None) for k in _MACHINE_KEYS])


def _machine_get(key, default):
    data = _machine_settings()
    if data is None:
        return load_config().get(key, default)          # 관리자 권한이 아니면 읽지 못한다(그때는 바꾸지도 못한다)
    return data.get(key, default)


def _machine_update(change):
    """PC 전체 설정을 고쳐 저장한다. 저장했으면 True."""
    from backend import machine_store
    with _lock:
        data = _machine_settings()
        if data is None:
            return False
        data = dict(data)
        change(data)
        return machine_store.write(_MACHINE_VALUE, data)


def get_boost_restore_mode():
    """게임 부스트가 게이밍 전원 모드를 켜기 전에 쓰던 모드. 없으면 None.

    게임이 끝나면 지워진다. 앱을 다시 켰는데 남아 있으면 게임 도중 비정상 종료된 것이다.
    """
    return _machine_get("boost_restore_mode", None)


def set_boost_restore_mode(mode):
    def change(c):
        if mode is None:
            c.pop("boost_restore_mode", None)
        else:
            c["boost_restore_mode"] = str(mode)
    return _machine_update(change)

def get_eula_accepted():
    return load_config().get("eula_accepted", False)

def set_eula_accepted(state):
    return update_config(lambda c: c.__setitem__("eula_accepted", bool(state)))

def get_optimization_mode():
    return _machine_get("optimization_mode", "standard")

def set_optimization_mode(mode, user_set=True):
    """저장했으면 True."""
    def change(c):
        c["optimization_mode"] = str(mode)
        # 게임 자동감지 등 내부 호출(user_set=False)은 '사용자가 고른 모드'로 기록하지 않는다
        if user_set:
            c["optimization_mode_user_set"] = True
    return _machine_update(change)

def get_optimization_mode_user_set():
    return bool(_machine_get("optimization_mode_user_set", False))

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


def get_ui_background():
    """직접 고른 배경색. 없거나 형식이 틀리면 None."""
    value = load_config().get("ui_background") or ""
    return value.lower() if isinstance(value, str) and _HEX_RE.match(value) else None


def set_ui_background(value):
    """배경색을 저장한다. None 이나 빈 문자열이면 지정을 해제한다. 다시 읽어 확인한다."""
    if value in (None, ""):
        value = ""
    elif not (isinstance(value, str) and _HEX_RE.match(value)):
        return {"success": False, "message": f"색 형식이 올바르지 않습니다: {value}"}
    value = value.lower()
    if not update_config(lambda c: c.__setitem__("ui_background", value)) or load_config().get("ui_background") != value:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 배경색으로 열립니다."}
    return {"success": True, "background": value or None}


def get_ui_scale():
    value = load_config().get("ui_scale", DEFAULT_CONFIG["ui_scale"])
    return value if value in UI_SCALES else DEFAULT_CONFIG["ui_scale"]


def set_ui_scale(value):
    """글자·화면 크기(%)를 저장한다. 정해 둔 값만 받는다."""
    if isinstance(value, bool) or value not in UI_SCALES:
        return {"success": False, "message": f"지원하지 않는 크기입니다: {value}"}
    if not update_config(lambda c: c.__setitem__("ui_scale", value)) or load_config().get("ui_scale") != value:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 크기로 열립니다."}
    return {"success": True, "scale": value}


def get_ui_reduce_motion():
    return load_config().get("ui_reduce_motion") is True


def set_ui_reduce_motion(value):
    if not isinstance(value, bool):
        return {"success": False, "message": f"켜기·끄기 값이 아닙니다: {value}"}
    if not update_config(lambda c: c.__setitem__("ui_reduce_motion", value)) or load_config().get("ui_reduce_motion") is not value:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 설정으로 열립니다."}
    return {"success": True, "reduceMotion": value}


_ICON_PRESETS = ("", "accent", "dark")


def get_ui_icon():
    value = load_config().get("ui_icon") or ""
    if value in _ICON_PRESETS:
        return value
    return value.lower() if isinstance(value, str) and _HEX_RE.match(value) else ""


def set_ui_icon(value):
    """앱 아이콘 색을 저장한다. 정해 둔 값이나 #rrggbb 만 받는다. 다시 읽어 확인한다."""
    if value is None:
        value = ""
    if not isinstance(value, str) or not (value in _ICON_PRESETS or _HEX_RE.match(value)):
        return {"success": False, "message": f"아이콘 색 값이 올바르지 않습니다: {value}"}
    value = value.lower()
    if not update_config(lambda c: c.__setitem__("ui_icon", value)) or load_config().get("ui_icon") != value:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 아이콘 색으로 열립니다."}
    return {"success": True, "icon": value}


UI_MODES = ("dark", "light")


def get_ui_mode():
    value = load_config().get("ui_mode")
    return value if value in UI_MODES else DEFAULT_CONFIG["ui_mode"]


def set_ui_mode(value):
    """화면 밝기('dark'·'light')를 저장한다. 다시 읽어 확인한다."""
    if value not in UI_MODES:
        return {"success": False, "message": f"알 수 없는 화면 밝기입니다: {value}"}
    if not update_config(lambda c: c.__setitem__("ui_mode", value)) or load_config().get("ui_mode") != value:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 밝기로 열립니다."}
    return {"success": True, "mode": value}


def get_ui_appearance():
    """화면 설정 전부(색 조합·강조색·배경색·크기·움직임 줄이기·아이콘 색)."""
    return {"theme": get_ui_theme(), "accent": get_ui_accent(), "background": get_ui_background(),
            "scale": get_ui_scale(), "reduceMotion": get_ui_reduce_motion(), "icon": get_ui_icon(),
            "mode": get_ui_mode()}


_UI_DEFAULTS = {k: DEFAULT_CONFIG[k] for k in ("ui_theme", "ui_accent", "ui_background", "ui_scale",
                                               "ui_reduce_motion", "ui_icon", "ui_mode")}


def reset_ui_appearance():
    """화면 설정을 한 번에 기본값으로 되돌린다(하나만 바뀐 채 남지 않게 한 번에 쓴다). 다시 읽어 확인한다."""
    if not update_config(lambda c: c.update(_UI_DEFAULTS)):
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다."}
    cfg = load_config()
    if any(cfg.get(k) != v for k, v in _UI_DEFAULTS.items()):
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다."}
    return {"success": True, **get_ui_appearance()}


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
