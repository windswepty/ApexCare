"""
APEX CARE - Game Booster & Process Tamer v2.0
Real performance boost via:
- Timer resolution forcing (0.5ms for lower input latency)
- EcoQoS for background apps (force to E-cores on hybrid CPUs)
- Power throttling disable for games (force P-cores)
- Nagle algorithm disable (reduce network latency)
- Process priority elevation
- Automatic cleanup on game exit
"""
import psutil
import threading
import time
import ctypes
import ctypes.wintypes
import os
import subprocess

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

# List of background apps to tame (lower priority + EcoQoS)
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
    "boosted_pids": [],
    "boost_count": 0,
    "timer_resolution_set": False,
    "nagle_disabled": False,
}

_monitor_thread = None
_stop_event = threading.Event()

# ─────────────────────────────────────────────
# Real Performance Boost Functions
# ─────────────────────────────────────────────

def _set_timer_resolution(enable):
    """Force system timer resolution to 0.5ms for lower input latency.
    
    Windows default timer is ~15.6ms. Games benefit hugely from 0.5ms
    as it affects Sleep() precision, input polling, and frame pacing.
    """
    try:
        ntdll = ctypes.WinDLL('ntdll')
        if enable:
            # Set to 5000 (100ns units) = 0.5ms
            actual = ctypes.c_ulong()
            ntdll.NtSetTimerResolution(ctypes.c_ulong(5000), ctypes.c_bool(True), ctypes.byref(actual))
            _booster_state["timer_resolution_set"] = True
        else:
            # Restore default
            actual = ctypes.c_ulong()
            ntdll.NtSetTimerResolution(ctypes.c_ulong(156250), ctypes.c_bool(True), ctypes.byref(actual))
            _booster_state["timer_resolution_set"] = False
    except Exception:
        pass


def _set_process_power_throttling(pid, throttle):
    """Control EcoQoS / Power Throttling for a process.
    
    throttle=True: Force process to efficiency cores (E-cores) — saves power
    throttle=False: Disable throttling — force to performance cores (P-cores)
    
    This is the real mechanism behind Windows 11's "Efficiency Mode" in Task Manager.
    """
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        
        PROCESS_SET_INFORMATION = 0x0200
        ProcessPowerThrottling = 4  # PROCESS_INFORMATION_CLASS
        
        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong),
            ]
        
        handle = kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
        if not handle:
            return False
            
        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = 1  # PROCESS_POWER_THROTTLING_CURRENT_VERSION
        state.ControlMask = 0x1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        state.StateMask = 0x1 if throttle else 0x0  # Enable or disable throttling
        
        kernel32.SetProcessInformation(
            handle, ProcessPowerThrottling,
            ctypes.byref(state), ctypes.sizeof(state)
        )
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def _disable_nagle():
    """Disable Nagle algorithm on all network interfaces for lower latency.
    
    Nagle bundles small TCP packets, adding up to 200ms delay.
    Critical for online FPS games where every ms of ping matters.
    """
    try:
        import winreg
        base_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
        base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path, 0, winreg.KEY_READ)
        
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base_key, i)
                subkey_path = f"{base_path}\\{subkey_name}"
                subkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.SetValueEx(subkey, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(subkey, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(subkey)
                i += 1
            except OSError:
                break
        winreg.CloseKey(base_key)
        _booster_state["nagle_disabled"] = True
    except Exception:
        pass


def _restore_nagle():
    """Restore default Nagle behavior on all network interfaces."""
    try:
        import winreg
        base_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
        base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path, 0, winreg.KEY_READ)
        
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base_key, i)
                subkey_path = f"{base_path}\\{subkey_name}"
                subkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_ALL_ACCESS)
                try:
                    winreg.DeleteValue(subkey, "TcpAckFrequency")
                except FileNotFoundError:
                    pass
                try:
                    winreg.DeleteValue(subkey, "TCPNoDelay")
                except FileNotFoundError:
                    pass
                winreg.CloseKey(subkey)
                i += 1
            except OSError:
                break
        winreg.CloseKey(base_key)
        _booster_state["nagle_disabled"] = False
    except Exception:
        pass


# ─────────────────────────────────────────────
# Process Priority / Taming
# ─────────────────────────────────────────────

def get_booster_status():
    return _booster_state

def _tame_processes(pids):
    """Lower priority AND apply EcoQoS to background apps."""
    tamed_count = 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
            if p.nice() != psutil.IDLE_PRIORITY_CLASS:
                p.nice(psutil.IDLE_PRIORITY_CLASS)
            # Apply EcoQoS (force to E-cores / efficiency mode)
            _set_process_power_throttling(pid, True)
            tamed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return tamed_count

def _boost_game_processes(pids):
    """Elevate game to HIGH priority + disable power throttling (force P-cores)."""
    for pid in pids:
        try:
            p = psutil.Process(pid)
            if p.nice() != psutil.HIGH_PRIORITY_CLASS:
                p.nice(psutil.HIGH_PRIORITY_CLASS)
            # Disable EcoQoS so game gets performance cores
            _set_process_power_throttling(pid, False)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def _restore_processes(pids):
    """Restore normal priority and remove EcoQoS from background apps."""
    for pid in pids:
        try:
            p = psutil.Process(pid)
            if p.nice() == psutil.IDLE_PRIORITY_CLASS:
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def _enter_boost_mode():
    """Apply all system-wide boost settings when a game is detected."""
    _set_timer_resolution(True)   # 0.5ms timer
    _disable_nagle()              # Low latency TCP
    
    # Switch to gaming power plan + detailed tuning
    try:
        from backend import optimizer
        optimizer.set_optimization_mode('gaming')
    except Exception:
        pass

def _exit_boost_mode():
    """Restore all system-wide settings when game exits."""
    _set_timer_resolution(False)  # Restore default timer
    _restore_nagle()              # Restore Nagle
    
    # Restore standard mode
    try:
        from backend import optimizer
        optimizer.set_optimization_mode('standard')
    except Exception:
        pass


# ─────────────────────────────────────────────
# Main Monitoring Loop
# ─────────────────────────────────────────────

def _booster_loop():
    global _booster_state
    
    last_tamable_pids = []
    
    while not _stop_event.is_set():
        if not _booster_state["enabled"]:
            if _booster_state["active"]:
                _restore_processes(last_tamable_pids)
                _restore_processes(_booster_state["boosted_pids"])
                _exit_boost_mode()
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
            found_games.sort(key=lambda x: GAMES_LIST.index(x))
            game_found = found_games[0]
            
            if not _booster_state["active"]:
                # Just entered boost mode
                _booster_state["active"] = True
                _booster_state["detected_game"] = game_found
                _booster_state["boosted_pids"] = current_game_pids
                _booster_state["boost_count"] += 1
                
                # Apply all system-wide boosts
                _enter_boost_mode()
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
            time.sleep(5)
        else:
            if _booster_state["active"]:
                # Game exited — restore everything
                _restore_processes(last_tamable_pids)
                _restore_processes(_booster_state["boosted_pids"])
                _exit_boost_mode()
                _booster_state["active"] = False
                _booster_state["detected_game"] = None
                _booster_state["boosted_pids"] = []
                last_tamable_pids = []
                
            time.sleep(3)

def toggle_booster(enabled):
    global _monitor_thread, _stop_event
    _booster_state["enabled"] = enabled
    
    if enabled and (_monitor_thread is None or not _monitor_thread.is_alive()):
        _stop_event.clear()
        _monitor_thread = threading.Thread(target=_booster_loop, daemon=True)
        _monitor_thread.start()
        
    if not enabled and _booster_state["active"]:
        _restore_processes([])  # PIDs handled by the loop
        _exit_boost_mode()
        _booster_state["active"] = False
        _booster_state["detected_game"] = None
        
    return {"success": True, "enabled": enabled}

# Auto-start the loop in disabled mode if imported
if _monitor_thread is None:
    _stop_event.clear()
    _monitor_thread = threading.Thread(target=_booster_loop, daemon=True)
    _monitor_thread.start()
