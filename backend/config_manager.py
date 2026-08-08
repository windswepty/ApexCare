import json
import os

APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
os.makedirs(APPDATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(APPDATA_DIR, "settings.json")

DEFAULT_CONFIG = {
    "booster_enabled": True,
    "eula_accepted": False,
    "optimization_mode": "gaming"
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
    return load_config().get("optimization_mode", "gaming")

def set_optimization_mode(mode):
    config = load_config()
    config["optimization_mode"] = str(mode)
    save_config(config)
