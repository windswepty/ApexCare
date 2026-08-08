import json
import os

APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
os.makedirs(APPDATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(APPDATA_DIR, "settings.json")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {
            "booster_enabled": True,
            "eula_accepted": False
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return {
                "booster_enabled": True,
                "eula_accepted": False
            }

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

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

def get_ai_api_key():
    return load_config().get("ai_api_key", "")

def set_ai_api_key(key):
    config = load_config()
    config["ai_api_key"] = str(key)
    save_config(config)
