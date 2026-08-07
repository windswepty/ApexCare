"""
APEX CARE - Game Booster & Process Tamer
Monitors running processes and lowers priority of background apps when a game is detected.
"""
import psutil
import threading
import time

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
]

# List of background apps to tame (lower priority)
APPS_TO_TAME = [
    "chrome.exe",
    "discord.exe",
    "msedge.exe",
    "spotify.exe",
    "slack.exe",
    "kakao.exe",
    "kakaotalk.exe",
    "whale.exe",
    "steamwebhelper.exe",
    "epicgameslauncher.exe",
    "battlenet.exe"
]

_booster_state = {
    "enabled": False,
    "active": False,
    "detected_game": None,
    "boost_count": 0
}

_monitor_thread = None
_stop_event = threading.Event()

def get_booster_status():
    return _booster_state

def _tame_processes():
    tamed_count = 0
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info['name']
            if name and name.lower() in APPS_TO_TAME:
                p = psutil.Process(proc.pid)
                # Set priority to IDLE (low)
                if p.nice() != psutil.IDLE_PRIORITY_CLASS:
                    p.nice(psutil.IDLE_PRIORITY_CLASS)
                    tamed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return tamed_count

def _restore_processes():
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info['name']
            if name and name.lower() in APPS_TO_TAME:
                p = psutil.Process(proc.pid)
                # Set priority back to NORMAL
                if p.nice() == psutil.IDLE_PRIORITY_CLASS:
                    p.nice(psutil.NORMAL_PRIORITY_CLASS)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def _booster_loop():
    global _booster_state
    
    while not _stop_event.is_set():
        if not _booster_state["enabled"]:
            if _booster_state["active"]:
                _restore_processes()
                _booster_state["active"] = False
                _booster_state["detected_game"] = None
            time.sleep(2)
            continue
            
        # Scan for games
        game_found = None
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info['name']
                if name and name.lower() in GAMES_LIST:
                    game_found = name
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        if game_found:
            if not _booster_state["active"]:
                # Just entered boost mode
                _booster_state["active"] = True
                _booster_state["detected_game"] = game_found
                _booster_state["boost_count"] += 1
                _tame_processes()
            elif _booster_state["detected_game"] != game_found:
                # Game changed
                _booster_state["detected_game"] = game_found
        else:
            if _booster_state["active"]:
                # Game exited
                _restore_processes()
                _booster_state["active"] = False
                _booster_state["detected_game"] = None
                
        # Sleep for 5 seconds between checks to save CPU
        time.sleep(5)

def toggle_booster(enabled):
    global _monitor_thread, _stop_event
    _booster_state["enabled"] = enabled
    
    if enabled and (_monitor_thread is None or not _monitor_thread.is_alive()):
        _stop_event.clear()
        _monitor_thread = threading.Thread(target=_booster_loop, daemon=True)
        _monitor_thread.start()
        
    if not enabled and _booster_state["active"]:
        _restore_processes()
        _booster_state["active"] = False
        _booster_state["detected_game"] = None
        
    return {"success": True, "enabled": enabled}

# Auto-start the loop in disabled mode if imported
if _monitor_thread is None:
    _stop_event.clear()
    _monitor_thread = threading.Thread(target=_booster_loop, daemon=True)
    _monitor_thread.start()
