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
    "boosted_pids": [], # Track boosted game PIDs to restore them later
    "boost_count": 0
}

_monitor_thread = None
_stop_event = threading.Event()

def get_booster_status():
    return _booster_state

def _tame_processes(pids):
    tamed_count = 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
            if p.nice() != psutil.IDLE_PRIORITY_CLASS:
                p.nice(psutil.IDLE_PRIORITY_CLASS)
                tamed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return tamed_count

def _boost_game_processes(pids):
    for pid in pids:
        try:
            p = psutil.Process(pid)
            # Elevate the game to HIGH priority to ensure maximum CPU allocation
            if p.nice() != psutil.HIGH_PRIORITY_CLASS:
                p.nice(psutil.HIGH_PRIORITY_CLASS)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def _restore_processes(pids):
    for pid in pids:
        try:
            p = psutil.Process(pid)
            if p.nice() == psutil.IDLE_PRIORITY_CLASS:
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def _booster_loop():
    global _booster_state
    
    last_tamable_pids = []
    
    while not _stop_event.is_set():
        if not _booster_state["enabled"]:
            if _booster_state["active"]:
                _restore_processes(last_tamable_pids)
                _restore_processes(_booster_state["boosted_pids"])
                _booster_state["active"] = False
                _booster_state["detected_game"] = None
                _booster_state["boosted_pids"] = []
                last_tamable_pids = []
            time.sleep(2)
            continue
            
        # Single pass scan for games and tamable apps
        found_games = []
        current_game_pids = []
        current_tamable_pids = []
        
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info.get('name')
                if not name: continue
                name = name.lower()
                
                if name in GAMES_LIST:
                    found_games.append(name)
                    current_game_pids.append(proc.pid)
                elif name in APPS_TO_TAME:
                    current_tamable_pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        if found_games:
            # Sort by priority in GAMES_LIST (index 0 is highest priority)
            found_games.sort(key=lambda x: GAMES_LIST.index(x))
            game_found = found_games[0]
            
            if not _booster_state["active"]:
                # Just entered boost mode
                _booster_state["active"] = True
                _booster_state["detected_game"] = game_found
                _booster_state["boosted_pids"] = current_game_pids
                _booster_state["boost_count"] += 1
                _boost_game_processes(current_game_pids)
                _tame_processes(current_tamable_pids)
            elif _booster_state["detected_game"] != game_found:
                # Game changed
                _restore_processes(_booster_state["boosted_pids"])
                _booster_state["detected_game"] = game_found
                _booster_state["boosted_pids"] = current_game_pids
                _boost_game_processes(current_game_pids)
                _tame_processes(current_tamable_pids)
            else:
                # Still running, update PIDs in case the game spawned new processes
                new_game_pids = list(set(current_game_pids) - set(_booster_state["boosted_pids"]))
                if new_game_pids:
                    _boost_game_processes(new_game_pids)
                    _booster_state["boosted_pids"].extend(new_game_pids)
                _tame_processes(current_tamable_pids)
                
            last_tamable_pids = current_tamable_pids
            time.sleep(5) # Check every 5 seconds to ensure strict enforcement
        else:
            if _booster_state["active"]:
                # Game exited
                _restore_processes(last_tamable_pids)
                _restore_processes(_booster_state["boosted_pids"])
                _booster_state["active"] = False
                _booster_state["detected_game"] = None
                _booster_state["boosted_pids"] = []
                last_tamable_pids = []
                
            time.sleep(3) # Check more frequently when waiting for a game

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
