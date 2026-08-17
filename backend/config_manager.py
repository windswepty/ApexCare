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
    "wu_recovery_done": False
}

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
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception:
        pass

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
