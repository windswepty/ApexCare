import json
import os

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
}

UI_THEMES = ('cyan', 'graphite', 'stone', 'midnight', 'violet')

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge defaults for any missing keys
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(config):
    """설정을 쓴다. 성공 여부를 돌려준다(기존 호출부는 무시해도 된다)."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return True
    except Exception:
        return False

def get_booster_state():
    return load_config().get("booster_enabled", True)

def set_booster_state(state):
    config = load_config()
    config["booster_enabled"] = bool(state)
    save_config(config)

def get_eula_accepted():
    return load_config().get("eula_accepted", False)

def set_eula_accepted(state):
    config = load_config()
    config["eula_accepted"] = bool(state)
    save_config(config)

def get_optimization_mode():
    return load_config().get("optimization_mode", "standard")

def set_optimization_mode(mode, user_set=True):
    config = load_config()
    config["optimization_mode"] = str(mode)
    # 게임 자동감지 등 내부 호출(user_set=False)은 '사용자가 고른 모드'로 기록하지 않는다
    if user_set:
        config["optimization_mode_user_set"] = True
    save_config(config)

def get_optimization_mode_user_set():
    return load_config().get("optimization_mode_user_set", False)

def get_wu_recovery_done():
    return load_config().get("wu_recovery_done", False)

def set_wu_recovery_done(state):
    config = load_config()
    config["wu_recovery_done"] = bool(state)
    save_config(config)


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
    c = load_config()
    c[key] = bool(value)
    save_config(c)
    return {"success": True, "key": key, "value": bool(value)}


def get_ui_theme():
    """저장된 UI 색 조합. 알 수 없는 값이면 기본값을 돌려준다."""
    theme = load_config().get("ui_theme", DEFAULT_CONFIG["ui_theme"])
    return theme if theme in UI_THEMES else DEFAULT_CONFIG["ui_theme"]


def set_ui_theme(theme):
    """UI 색 조합을 저장하고, 다시 읽어 저장됐는지 확인한다."""
    if theme not in UI_THEMES:
        return {"success": False, "message": f"알 수 없는 색 조합입니다: {theme}"}
    c = load_config()
    c["ui_theme"] = theme
    if not save_config(c) or load_config().get("ui_theme") != theme:
        return {"success": False, "message": "설정 파일에 저장하지 못했습니다. 다음 실행 때는 이전 색 조합으로 열립니다."}
    return {"success": True, "theme": theme}
