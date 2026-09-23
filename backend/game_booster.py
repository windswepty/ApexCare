"""
APEX CARE - Game Booster & Process Tamer v3.0 (Hardened)
Real performance boost via:
- Timer resolution forcing (0.5ms for lower input latency)
- EcoQoS for background apps (force to E-cores on hybrid CPUs)
- Power throttling disable for games (force P-cores)
- Nagle algorithm disable (reduce network latency)
- Process priority elevation (with admin privilege enforcement)
- Automatic cleanup on game exit
"""
import psutil
import threading
import time
import ctypes
import ctypes.wintypes
import gc
import os
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='[GameBooster] %(message)s')
log = logging.getLogger('GameBooster')

# 에코 억제 기준: 이 % 이상 CPU 를 쓰는 프로세스만 건드린다.
# 유휴 상태인 앱의 우선순위를 낮춰봐야 얻는 것은 없고,
# 그 앱이 깨어날 때 느려지기만 한다.
ECO_CPU_THRESHOLD = 5.0
ECO_INTERVAL_SEC = 10

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
    "msedge.exe",
    "spotify.exe",
    "slack.exe",
    "kakao.exe",
    "kakaotalk.exe",
    "whale.exe"
]

# Strict Whitelist: NEVER touch these processes (System Core & Game Launchers)
WHITELIST = [
    "explorer.exe",
    "svchost.exe",
    "steam.exe",
    "steamservice.exe",
    "steamwebhelper.exe",
    "epicgameslauncher.exe",
    "battlenet.exe",
    "battle.net.exe",
    "discord.exe",
    "csrss.exe",
    "winlogon.exe",
    "lsass.exe",
    "services.exe",
    "smss.exe",
    "wininit.exe",
    "dwm.exe",
    "fontdrvhost.exe"
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
_admin_checked = False
_is_admin_cached = False

# ─────────────────────────────────────────────
# Admin Privilege Check & Enforcement
# ─────────────────────────────────────────────

def _is_admin():
    """Check if the current process is running with admin privileges."""
    global _admin_checked, _is_admin_cached
    if _admin_checked:
        return _is_admin_cached
    try:
        _is_admin_cached = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception as e:
        log.debug(f"IsAdmin check failed: {e}")
        _is_admin_cached = False
    _admin_checked = True
    if not _is_admin_cached:
        log.warning("⚠ NOT running as Administrator! Process priority/power control will be limited.")
    else:
        log.info("✓ Running as Administrator - full process control available.")
    return _is_admin_cached


def _enable_debug_privilege():
    """Enable SeDebugPrivilege to allow controlling any process regardless of owner.
    
    This is the key privilege that allows us to modify system/service processes
    and processes owned by other users. Requires admin rights.
    """
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", ctypes.wintypes.DWORD), ("HighPart", ctypes.wintypes.LONG)]
        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", ctypes.wintypes.DWORD)]
        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", ctypes.wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]
        
        TOKEN_ADJUST_PRIVILEGES = 0x0020
        TOKEN_QUERY = 0x0008
        SE_PRIVILEGE_ENABLED = 0x00000002
        
        hToken = ctypes.wintypes.HANDLE()
        kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(hToken)):
            return False
        
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            kernel32.CloseHandle(hToken)
            return False
        
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        
        advapi32.AdjustTokenPrivileges(hToken, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
        success = ctypes.get_last_error() == 0
        kernel32.CloseHandle(hToken)
        
        if success:
            log.info("✓ SeDebugPrivilege enabled - can control all processes")
        else:
            log.warning("⚠ Failed to enable SeDebugPrivilege")
        return success
    except Exception as e:
        log.warning(f"⚠ SeDebugPrivilege error: {e}")
        return False


# ─────────────────────────────────────────────
# Win32 API Direct Priority Control (Fallback)
# ─────────────────────────────────────────────

# Priority class constants
IDLE_PRIORITY_CLASS = 0x0040
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
NORMAL_PRIORITY_CLASS = 0x0020
ABOVE_NORMAL_PRIORITY_CLASS = 0x8000
HIGH_PRIORITY_CLASS = 0x0080
REALTIME_PRIORITY_CLASS = 0x0100

PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_ALL_ACCESS = 0x001FFFFF


def _set_priority_via_win32(pid, priority_class):
    """Directly set process priority via Win32 API (bypasses psutil AccessDenied).
    
    Uses OpenProcess with PROCESS_SET_INFORMATION access right.
    With SeDebugPrivilege enabled, this works even for system processes.
    """
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            log.warning(f"  OpenProcess failed for PID {pid} (error={error})")
            return False
        
        result = kernel32.SetPriorityClass(handle, priority_class)
        kernel32.CloseHandle(handle)
        
        if result:
            return True
        else:
            error = ctypes.get_last_error()
            log.warning(f"  SetPriorityClass failed for PID {pid} (error={error})")
            return False
    except Exception as e:
        log.warning(f"  Win32 priority set error for PID {pid}: {e}")
        return False


def _suspend_process_via_win32(pid):
    """Suspend a process via NtSuspendProcess for aggressive background suppression."""
    try:
        ntdll = ctypes.WinDLL('ntdll')
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not handle:
            return False
        result = ntdll.NtSuspendProcess(handle)
        kernel32.CloseHandle(handle)
        return result == 0
    except Exception as e:
        log.debug(f"Suspend process failed for PID {pid}: {e}")
        return False


def _resume_process_via_win32(pid):
    """Resume a suspended process via NtResumeProcess."""
    try:
        ntdll = ctypes.WinDLL('ntdll')
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not handle:
            return False
        result = ntdll.NtResumeProcess(handle)
        kernel32.CloseHandle(handle)
        return result == 0
    except Exception as e:
        log.debug(f"Resume process failed for PID {pid}: {e}")
        return False


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
            log.info(f"✓ Timer resolution set to 0.5ms (actual: {actual.value/10000:.2f}ms)")
        else:
            # Restore default
            actual = ctypes.c_ulong()
            ntdll.NtSetTimerResolution(ctypes.c_ulong(156250), ctypes.c_bool(True), ctypes.byref(actual))
            _booster_state["timer_resolution_set"] = False
            log.info("✓ Timer resolution restored to default")
    except Exception as e:
        log.warning(f"⚠ Timer resolution error: {e}")


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
    except Exception as e:
        log.debug(f"Power throttling error for PID {pid}: {e}")
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
        modified_count = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base_key, i)
                subkey_path = f"{base_path}\\{subkey_name}"
                subkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.SetValueEx(subkey, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(subkey, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(subkey)
                modified_count += 1
                i += 1
            except OSError:
                break
        winreg.CloseKey(base_key)
        _booster_state["nagle_disabled"] = True
        log.info(f"✓ Nagle disabled on {modified_count} network interfaces")
    except Exception as e:
        log.warning(f"⚠ Nagle disable error: {e}")


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
        log.info("✓ Nagle restored to default")
    except Exception as e:
        log.warning(f"⚠ Nagle restore error: {e}")


# ─────────────────────────────────────────────
# Process Priority / Taming (Hardened with fallback)
# ─────────────────────────────────────────────

def get_booster_status():
    return _booster_state

def _is_safe_to_tame(proc_name, pid=None):
    """Pre-Check Safety Routine: Verify process is not in whitelist, game list, or foreground.
    
    Zero-Risk Shield: This function is the SINGLE gate that decides whether a process
    can have its priority lowered. If it returns False, the process is UNTOUCHABLE.
    """
    if not proc_name:
        return False
    proc_name = proc_name.lower()
    
    # 1. Whitelist Check — system core & game launchers
    if proc_name in WHITELIST:
        return False
    
    # 2. Game Process Check — NEVER tame running games
    if proc_name in GAMES_LIST:
        return False
        
    # 3. Foreground / UI Check (Basic heuristic: if it's a known system app)
    # GetForegroundWindow check could be added here if needed, but whitelist covers most.
    return True

def _tame_processes(pids):
    """백그라운드 앱의 우선순위를 낮춘다.

    실제 작업은 process_boost 가 한다. 그쪽이 바꾸기 전 원래 우선순위를 기록하므로
    복구할 때 정확히 그 값으로 되돌릴 수 있다. 예전에는 무조건 NORMAL 로 되돌려
    원래 BELOW_NORMAL 이던 프로세스의 설정을 잃었다.
    """
    from backend import process_boost
    tamed = 0
    for pid in pids:
        r = process_boost.set_priority(pid, 'idle', reason='(에코/부스트 억제)')
        if r.get('ok'):
            tamed += 1
            # EcoQoS 는 세션 한정이고 프로세스가 끝나면 사라진다
            _set_process_power_throttling(pid, True)
    if tamed:
        log.info(f"백그라운드 프로세스 {tamed}개의 우선순위를 낮췄습니다")
    return tamed


def _boost_game_processes(pids):
    """Elevate game to HIGH priority + disable power throttling (force P-cores).
    
    Uses psutil first, falls back to Win32 API on AccessDenied.
    """
    boosted_count = 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
            proc_name = p.name().lower()
            
            # Strict Whitelist Check (just in case we accidentally targeted a system app)
            if not _is_safe_to_tame(proc_name, pid) and proc_name not in GAMES_LIST:
                continue
            
            # Try psutil first
            try:
                if p.nice() != psutil.HIGH_PRIORITY_CLASS:
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                boosted_count += 1
                log.info(f"  ✓ Boosted {proc_name} (PID {pid}) to HIGH priority via psutil")
            except psutil.AccessDenied:
                # Fallback: Win32 API direct call
                if _set_priority_via_win32(pid, HIGH_PRIORITY_CLASS):
                    log.info(f"  ✓ Boosted {proc_name} (PID {pid}) to HIGH priority via Win32 API")
                    boosted_count += 1
                else:
                    log.warning(f"  ✗ Failed to boost {proc_name} (PID {pid}) - AccessDenied even with Win32")
            
            # Disable EcoQoS so game gets performance cores
            _set_process_power_throttling(pid, False)
            
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            pass
        except Exception as e:
            log.warning(f"  ✗ Boost error for PID {pid}: {e}")
    
    return boosted_count

def _restore_processes(pids):
    """기록해둔 원래 우선순위로 되돌린다."""
    from backend import process_boost
    for pid in pids:
        _set_process_power_throttling(pid, False)
        process_boost.restore(pid)


def _enter_boost_mode():
    """게임이 감지됐을 때 부스트를 적용한다.

    예전에는 감지되자마자 타이머 해상도, Nagle 레지스트리, 전체 게이밍 모드를
    한꺼번에 바꿨다. 사용자는 무엇이 바뀌는지 알 수 없었고 Nagle 은 영구
    레지스트리 변경이었다. 이제 각 항목을 설정으로 끄고 켤 수 있고,
    기본값은 '되돌릴 수 있는 것만 켜짐' 이다.
    """
    from backend import config_manager
    cfg = config_manager.load_config()
    applied = []

    # 타이머 해상도: 세션 한정. 프로세스가 끝나면 원래대로 돌아간다.
    if cfg.get('boost_timer_resolution', True):
        _set_timer_resolution(True)
        applied.append('타이머 해상도 0.5ms')

    # Nagle 비활성화: 레지스트리 영구 변경이므로 기본값을 꺼둔다.
    if cfg.get('boost_disable_nagle', False):
        _disable_nagle()
        applied.append('Nagle 알고리즘 비활성화')

    # 전원 모드 전환: OS 설정을 바꾸므로 기본값을 꺼둔다.
    if cfg.get('boost_auto_power_mode', False):
        try:
            from backend import perf_modes
            res = perf_modes.apply_mode('gaming', user_set=False)
            if res.get('success') or res.get('partial'):
                applied.append('게이밍 전원 모드')
        except Exception as e:
            log.warning(f"전원 모드 전환 실패: {e}")

    _booster_state['appliedBoosts'] = applied
    log.info(f"부스트 진입: {', '.join(applied) if applied else '적용 항목 없음'}")


def _exit_boost_mode():
    """게임이 끝나면 부스트에서 적용한 것을 되돌린다."""
    from backend import config_manager
    cfg = config_manager.load_config()

    if cfg.get('boost_timer_resolution', True):
        _set_timer_resolution(False)
    if cfg.get('boost_disable_nagle', False):
        _restore_nagle()
    if cfg.get('boost_auto_power_mode', False):
        try:
            from backend import perf_modes
            perf_modes.apply_mode('standard', user_set=False)
        except Exception as e:
            log.warning(f"전원 모드 복구 실패: {e}")

    # 우선순위를 낮췄던 프로세스를 전부 원래대로
    try:
        from backend import process_boost
        process_boost.restore_all()
    except Exception as e:
        log.warning(f"프로세스 우선순위 복구 실패: {e}")

    _booster_state['appliedBoosts'] = []
    log.info("부스트 종료: 적용했던 설정을 되돌렸습니다")


# ─────────────────────────────────────────────
# Main Monitoring Loop
# ─────────────────────────────────────────────

def _booster_loop():
    global _booster_state
    
    # Enable SeDebugPrivilege at thread start for maximum process control
    if _is_admin():
        _enable_debug_privilege()
    
    last_tamable_pids = []
    
    while not _stop_event.is_set():
        try:
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
                    
                    log.info(f"🎮 Game detected: {game_found} (PIDs: {current_game_pids})")
                    
                    # Apply all system-wide boosts
                    _enter_boost_mode()
                    _boost_game_processes(current_game_pids)
                    _tame_processes(current_tamable_pids)
                    
                elif _booster_state["detected_game"] != game_found:
                    # Game changed
                    log.info(f"🎮 Game switched to: {game_found}")
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
                    
                    # Prevent Memory Leak: explicitly reassign to currently alive PIDs only
                    _booster_state["boosted_pids"] = current_game_pids
                    _tame_processes(current_tamable_pids)
                    
                last_tamable_pids = current_tamable_pids
                
                found_games.clear()
                current_game_pids.clear()
                current_tamable_pids.clear()
                gc.collect()
                time.sleep(5)
            else:
                if _booster_state["active"]:
                    # Game exited — restore everything
                    log.info("🎮 Game exited - restoring all processes")
                    _restore_processes(last_tamable_pids)
                    _restore_processes(_booster_state["boosted_pids"])
                    _exit_boost_mode()
                    _booster_state["active"] = False
                    _booster_state["detected_game"] = None
                    _booster_state["boosted_pids"] = []
                    _booster_state["boosted_pids"] = []
                    last_tamable_pids = []
                    
                gc.collect()
                time.sleep(3)
        except Exception as e:
            log.error(f"Booster loop crash: {e}")
            time.sleep(5)

def toggle_booster(enabled):
    global _monitor_thread, _stop_event
    _booster_state["enabled"] = enabled
    
    try:
        from backend import config_manager
        config_manager.set_booster_state(enabled)
    except Exception as e:
        log.warning(f"Failed to save booster state: {e}")
    
    if enabled and (_monitor_thread is None or not _monitor_thread.is_alive()):
        _stop_event.clear()
        _monitor_thread = threading.Thread(target=_booster_loop, daemon=True)
        _monitor_thread.start()
        log.info("✓ Game Booster ENABLED - monitoring for games...")
        
    if not enabled:
        log.info("✓ Game Booster DISABLED - delegating teardown to background thread...")
    return {"success": True, "enabled": enabled}

def init_booster():
    """Auto-start booster on application launch if saved state is enabled."""
    try:
        from backend import config_manager
        saved_state = config_manager.get_booster_state()
        if saved_state:
            toggle_booster(True)
    except Exception as e:
        log.warning(f"Failed to auto-init booster: {e}")

# ─────────────────────────────────────────────
# Eco Mode Background Suppression
# ─────────────────────────────────────────────

_eco_suppression_thread = None
_eco_stop_event = threading.Event()
_eco_tamed_pids = set()

def _get_foreground_pid():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value
    except Exception as e:
        log.debug(f"Failed to get foreground PID: {e}")
    return None

def _eco_suppression_thread_func():
    """에코 모드에서 바쁜 백그라운드 앱의 우선순위를 낮춘다.

    예전에는 포그라운드가 아닌 '모든' 사용자 프로세스를 IDLE 로 내렸다.
    변수 이름은 current_heavy_pids 였지만 CPU 임계값이 없어서, 백신·백업·
    음악 재생·컴파일까지 전부 굼떠졌다. 실행 중인 게임도 대상이었다
    (CPU 를 가장 많이 쓰므로 사실상 1순위였다).

    이제 process_boost.find_throttle_candidates 가 고른 것만 건드린다.
    CPU 임계값을 넘고, 게임이 아니고, 보호 목록에 없고, process_guard 를
    통과한 프로세스만 후보가 된다.
    """
    global _eco_tamed_pids
    from backend import process_boost

    log.info("에코 억제 루프 시작")
    process_boost.prime_cpu_measurement()   # cpu_percent 기준점 잡기

    while not _eco_stop_event.is_set():
        try:
            fg_pid = _get_foreground_pid()
            candidates = process_boost.find_throttle_candidates(
                foreground_pid=fg_pid, cpu_threshold=ECO_CPU_THRESHOLD)
            pids = {c['pid'] for c in candidates}

            new_pids = pids - _eco_tamed_pids
            if new_pids:
                _tame_processes(list(new_pids))
                _eco_tamed_pids.update(new_pids)

            # 더 이상 바쁘지 않거나 종료된 프로세스는 원래대로 돌려준다.
            # 예전에는 목록에서 빼기만 하고 복구하지 않아, 한 번 낮춘 우선순위가
            # 에코 모드를 끌 때까지 그대로 유지됐다.
            gone = _eco_tamed_pids - pids
            if gone:
                _restore_processes(list(gone))
                _eco_tamed_pids -= gone

            gc.collect()
        except Exception as e:
            log.warning(f"에코 억제 루프 오류: {e}")

        for _ in range(ECO_INTERVAL_SEC):
            if _eco_stop_event.is_set():
                break
            time.sleep(1)


def start_eco_suppression_loop():
    global _eco_suppression_thread, _eco_stop_event
    _eco_stop_event.clear()
    if _eco_suppression_thread is None or not _eco_suppression_thread.is_alive():
        _eco_suppression_thread = threading.Thread(target=_eco_suppression_thread_func, daemon=True)
        _eco_suppression_thread.start()

def stop_eco_suppression_loop():
    global _eco_stop_event
    _eco_stop_event.set()

def restore_background_apps():
    global _eco_tamed_pids
    if _eco_tamed_pids:
        log.info("Restoring priority for Eco-tamed background apps...")
        _restore_processes(list(_eco_tamed_pids))
        _eco_tamed_pids.clear()

# ─────────────────────────────────────────────
# Foreground App Boosting (Gaming Ultra Mode)
# ─────────────────────────────────────────────
_fg_boosted_pid = None

def boost_foreground_app():
    global _fg_boosted_pid
    pid = _get_foreground_pid()
    if pid:
        _boost_game_processes([pid])
        _fg_boosted_pid = pid
        log.info(f"Foreground app (PID: {pid}) boosted to HIGH priority for Gaming Ultra Mode.")

def restore_foreground_app():
    global _fg_boosted_pid
    if _fg_boosted_pid:
        _restore_processes([_fg_boosted_pid])
        log.info(f"Foreground app (PID: {_fg_boosted_pid}) restored to NORMAL priority.")
        _fg_boosted_pid = None
