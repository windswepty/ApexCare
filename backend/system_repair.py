"""
APEX CARE - System Repair and Advanced Disk Ops
Runs long-running commands like SFC, DISM, Defrag, and Network optimization in hidden subprocesses with full logging and error handling.
"""
import subprocess
import threading
import logging

log = logging.getLogger('SystemRepair')
CREATE_NO_WINDOW = 0x08000000

def _run_hidden_cmd(cmd_list):
    """Run system command with shell=True and return detailed output."""
    try:
        cmd_str = " ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=120
        )
        if result.returncode == 0:
            return {"success": True, "message": "성공적으로 완료되었습니다.", "output": result.stdout}
        else:
            return {"success": False, "message": f"작업 실패 (코드: {result.returncode})", "error": result.stderr or result.stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# Background task state dictionaries
# ─────────────────────────────────────────────

_sfc_state = {"status": "idle", "output": "", "error": None}
_dism_state = {"status": "idle", "output": "", "error": None}
_trim_state = {"status": "idle", "output": "", "error": None}
_network_state = {"status": "idle", "message": "", "details": []}

def _run_hidden_cmd_bg(cmd_list, state_dict, timeout_sec=600):
    # cmd_str 을 try 밖에서, 그리고 절대 예외를 던지지 않는 방식으로 만든다.
    # try 안에서 만들면 join 이 실패했을 때 except 절의 f-string 이
    # 미정의 이름을 참조해 NameError 로 연쇄 붕괴한다.
    cmd_str = " ".join(str(c) for c in cmd_list) if isinstance(cmd_list, list) else str(cmd_list)
    try:
        log.info(f"Starting background command: {cmd_str}")
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout_sec
        )
        state_dict["output"] = result.stdout
        if result.returncode == 0:
            state_dict["status"] = "success"
            log.info(f"✓ Command succeeded: {cmd_str}")
        else:
            state_dict["status"] = "error"
            state_dict["error"] = result.stderr or result.stdout
            log.warning(f"✗ Command failed (code {result.returncode}): {cmd_str} -> {state_dict['error']}")
    except Exception as e:
        state_dict["status"] = "error"
        state_dict["error"] = str(e)
        log.warning(f"⚠ Command exception: {cmd_str} -> {e}")

# ─────────────────────────────────────────────
# TRIM / Disk Optimization (async)
# ─────────────────────────────────────────────

def run_trim():
    """Run disk optimization and TRIM on ALL volumes asynchronously."""
    global _trim_state
    if _trim_state["status"] == "running":
        return {"success": False, "message": "이미 디스크 최적화가 실행 중입니다."}
    _trim_state["status"] = "running"
    _trim_state["error"] = None
    _trim_state["output"] = ""
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["defrag.exe", "/C", "/O"], _trim_state, 300), daemon=True)
    t.start()
    return {"success": True}

def get_trim_status():
    return _trim_state

# ─────────────────────────────────────────────
# SFC (async)
# ─────────────────────────────────────────────

def run_sfc():
    """Run System File Checker asynchronously."""
    global _sfc_state
    if _sfc_state["status"] == "running":
        return {"success": False, "message": "이미 SFC 무결성 검사가 실행 중입니다."}
    _sfc_state["status"] = "running"
    _sfc_state["error"] = None
    _sfc_state["output"] = ""
    # 타임아웃은 subprocess 를 '강제 종료'시킨다. sfc /scannow 를 중간에 죽이면
    # 복구가 반쯤 적용된 상태로 남을 수 있으므로 넉넉하게 잡는다(느린 HDD 기준).
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["sfc.exe", "/scannow"], _sfc_state, 3600), daemon=True)
    t.start()
    return {"success": True}

def get_sfc_status():
    return _sfc_state

# ─────────────────────────────────────────────
# DISM (async)
# ─────────────────────────────────────────────

def run_dism():
    """Run DISM RestoreHealth asynchronously."""
    global _dism_state
    if _dism_state["status"] == "running":
        return {"success": False, "message": "이미 DISM 복구 작업이 실행 중입니다."}
    _dism_state["status"] = "running"
    _dism_state["error"] = None
    _dism_state["output"] = ""
    # DISM /RestoreHealth 를 중간에 죽이면 구성 요소 저장소(WinSxS)가 손상될 수 있다.
    # 느린 회선에서 Windows Update 로 원본을 받아오면 1시간을 넘기도 하므로 2시간으로 잡는다.
    t = threading.Thread(target=_run_hidden_cmd_bg, args=(["dism.exe", "/Online", "/Cleanup-image", "/Restorehealth"], _dism_state, 7200), daemon=True)
    t.start()
    return {"success": True}

def get_dism_status():
    return _dism_state

# ─────────────────────────────────────────────
# Network Optimization (async + sync)
# ─────────────────────────────────────────────

# 사용자에게 그대로 보여줄 '영구 변경' 항목 목록.
# 여기 있는 항목은 재부팅 후에도 유지되고, 일부는 네트워크 연결 자체를 끊을 수 있다.
NETWORK_PERMANENT_CHANGES = [
    "Winsock 카탈로그를 초기화합니다 — 재부팅이 필요하며, VPN·프록시·일부 보안 프로그램이 "
    "등록한 네트워크 계층(LSP)이 함께 제거되어 해당 프로그램의 재설치가 필요할 수 있습니다.",
    "TCP 수신 창 자동 튜닝을 끕니다 — 재부팅 후에도 유지됩니다. 지연이 큰 회선이나 "
    "고속 회선에서는 오히려 다운로드 속도가 느려질 수 있습니다.",
    "모든 네트워크 어댑터에서 Nagle 알고리즘을 끕니다(TcpAckFrequency/TCPNoDelay 레지스트리) — "
    "게임 응답성은 좋아지지만 패킷 수가 늘어납니다.",
    "네트워크 스로틀링을 해제합니다(NetworkThrottlingIndex) — 멀티미디어 재생 중 "
    "네트워크 우선순위 제한이 사라집니다."
]

_NAGLE_BASE = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
_THROTTLE_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"


def flush_dns():
    """DNS 캐시만 비운다. 캐시라서 되돌릴 필요가 없는 유일한 안전 항목."""
    return _run_hidden_cmd(["ipconfig", "/flushdns"])


def _read_dword(root_path, value_name):
    """레지스트리 DWORD 를 읽는다. 값이 없으면 None (= '원래 없었음')."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path, 0, winreg.KEY_READ)
        try:
            value, _ = winreg.QueryValueEx(key, value_name)
            return int(value)
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def _get_autotuning_level():
    """자동 튜닝 수준을 로케일 독립적으로 읽는다. netsh 출력은 한글판에서 라벨이 번역돼 파싱이 깨진다."""
    try:
        result = subprocess.run(
            'powershell -NoProfile -ExecutionPolicy Bypass -Command '
            '"(Get-NetTCPSetting -SettingName Internet).AutoTuningLevelLocal"',
            shell=True, capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=30
        )
        level = (result.stdout or "").strip()
        return level if level else None
    except Exception as e:
        log.debug(f"Failed to read TCP autotuning level: {e}")
        return None


def _backup_network_settings():
    """영구 변경 전 원래 값을 config 에 저장한다. 값이 없던 항목은 None 으로 기록해
    복구 시 '값을 되돌리는' 게 아니라 '값을 지우는' 것으로 처리한다."""
    backup = {
        "autotuning": _get_autotuning_level(),
        "throttling_index": _read_dword(_THROTTLE_KEY, "NetworkThrottlingIndex"),
        "interfaces": {}
    }
    try:
        import winreg
        base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NAGLE_BASE, 0, winreg.KEY_READ)
        try:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base_key, i)
                except OSError:
                    break
                subkey_path = f"{_NAGLE_BASE}\\{subkey_name}"
                backup["interfaces"][subkey_name] = {
                    "TcpAckFrequency": _read_dword(subkey_path, "TcpAckFrequency"),
                    "TCPNoDelay": _read_dword(subkey_path, "TCPNoDelay")
                }
                i += 1
        finally:
            winreg.CloseKey(base_key)
    except Exception as e:
        log.warning(f"[Network Opt] Failed to enumerate interfaces for backup: {e}")

    try:
        from backend import config_manager
        cfg = config_manager.load_config()
        # 이미 백업이 있으면 덮어쓰지 않는다. 두 번 적용하면 '이미 변경된 값'이 원본으로 굳어버린다.
        if not cfg.get("network_tweak_backup"):
            cfg["network_tweak_backup"] = backup
            config_manager.save_config(cfg)
    except Exception as e:
        log.warning(f"[Network Opt] Failed to persist network backup: {e}")

    return backup


def _apply_network_tweaks_internal():
    """실제 영구 변경. 반드시 동의를 받은 뒤에만 호출된다."""
    results = []

    _backup_network_settings()

    r = _run_hidden_cmd(["netsh", "winsock", "reset"])
    results.append(("Winsock Reset", r.get("success", False)))

    r = _run_hidden_cmd(["netsh", "int", "tcp", "set", "global", "autotuninglevel=disabled"])
    results.append(("TCP AutoTuning Disabled", r.get("success", False)))

    try:
        import winreg
        base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NAGLE_BASE, 0, winreg.KEY_READ)
        try:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base_key, i)
                except OSError:
                    break
                i += 1
                try:
                    subkey = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        f"{_NAGLE_BASE}\\{subkey_name}", 0, winreg.KEY_SET_VALUE
                    )
                    try:
                        winreg.SetValueEx(subkey, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                        winreg.SetValueEx(subkey, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                    finally:
                        winreg.CloseKey(subkey)
                except Exception as e:
                    # 어댑터 하나가 실패해도 나머지는 계속 처리한다
                    log.debug(f"[Network Opt] Nagle skip {subkey_name}: {e}")
        finally:
            winreg.CloseKey(base_key)
        results.append(("Nagle Disabled", True))
    except Exception as e:
        log.warning(f"[Network Opt] Failed to disable Nagle: {e}")
        results.append(("Nagle Disabled", False))

    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _THROTTLE_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(key, "NetworkThrottlingIndex", 0, winreg.REG_DWORD, 0xFFFFFFFF)
        finally:
            winreg.CloseKey(key)
        results.append(("Network Throttling Disabled", True))
    except Exception as e:
        log.warning(f"[Network Opt] Failed to disable Network Throttling: {e}")
        results.append(("Network Throttling Disabled", False))

    return results


def restore_network_tweaks():
    """apply_network_tweaks 가 만든 영구 변경을 되돌린다."""
    try:
        import winreg
        from backend import config_manager
        cfg = config_manager.load_config()
        backup = cfg.get("network_tweak_backup") or {}
        used_default = not backup

        restored = []

        # 자동 튜닝: 백업이 없으면 Windows 기본값 normal
        level = backup.get("autotuning") or "normal"
        r = _run_hidden_cmd(["netsh", "int", "tcp", "set", "global", f"autotuninglevel={str(level).lower()}"])
        if r.get("success"):
            restored.append("TCP AutoTuning")

        # 스로틀링 인덱스: 원래 값이 없었으면 값을 지운다(= Windows 기본 동작)
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _THROTTLE_KEY, 0, winreg.KEY_SET_VALUE)
            try:
                original = backup.get("throttling_index") if backup else 10
                if original is None:
                    try:
                        winreg.DeleteValue(key, "NetworkThrottlingIndex")
                    except FileNotFoundError:
                        pass
                else:
                    winreg.SetValueEx(key, "NetworkThrottlingIndex", 0, winreg.REG_DWORD, int(original))
                restored.append("Network Throttling")
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            log.warning(f"[Network Opt] Failed to restore throttling index: {e}")

        # Nagle: 어댑터별로 원래 값 복구, 원래 없던 값은 삭제
        interfaces = backup.get("interfaces") or {}
        nagle_ok = False
        for subkey_name, values in interfaces.items():
            try:
                subkey = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    f"{_NAGLE_BASE}\\{subkey_name}", 0, winreg.KEY_SET_VALUE
                )
                try:
                    for value_name in ("TcpAckFrequency", "TCPNoDelay"):
                        original = values.get(value_name)
                        if original is None:
                            try:
                                winreg.DeleteValue(subkey, value_name)
                            except FileNotFoundError:
                                pass
                        else:
                            winreg.SetValueEx(subkey, value_name, 0, winreg.REG_DWORD, int(original))
                    nagle_ok = True
                finally:
                    winreg.CloseKey(subkey)
            except Exception as e:
                log.debug(f"[Network Opt] Nagle restore skip {subkey_name}: {e}")

        if not interfaces:
            # 백업이 없는 구버전 사용자: 현재 어댑터 전부에서 값을 지워 Windows 기본 동작으로 되돌린다
            try:
                base_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NAGLE_BASE, 0, winreg.KEY_READ)
                try:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(base_key, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            subkey = winreg.OpenKey(
                                winreg.HKEY_LOCAL_MACHINE,
                                f"{_NAGLE_BASE}\\{subkey_name}", 0, winreg.KEY_SET_VALUE
                            )
                            try:
                                for value_name in ("TcpAckFrequency", "TCPNoDelay"):
                                    try:
                                        winreg.DeleteValue(subkey, value_name)
                                    except FileNotFoundError:
                                        pass
                                nagle_ok = True
                            finally:
                                winreg.CloseKey(subkey)
                        except Exception as e:
                            log.debug(f"[Network Opt] Nagle default-restore skip {subkey_name}: {e}")
                finally:
                    winreg.CloseKey(base_key)
            except Exception as e:
                log.warning(f"[Network Opt] Failed to enumerate interfaces for restore: {e}")

        if nagle_ok:
            restored.append("Nagle")

        cfg.pop("network_tweak_backup", None)
        config_manager.save_config(cfg)

        msg = f"네트워크 설정을 복구했습니다: {', '.join(restored) if restored else '없음'}"
        if used_default:
            msg += " (백업 정보가 없어 Windows 기본값으로 복구했습니다.)"
        msg += " 변경 사항을 완전히 적용하려면 재부팅이 필요합니다."
        # Winsock 카탈로그는 reset 으로 이미 초기화됐고 되돌릴 원본이 없다.
        msg += " (Winsock 초기화는 되돌릴 수 없으며, 제거된 VPN/보안 프로그램 계층은 해당 프로그램 재설치로 복구해야 합니다.)"
        return {"success": True, "restored": restored, "message": msg}
    except Exception as e:
        return {"success": False, "message": "네트워크 설정 복구에 실패했습니다.", "error": str(e)}


def run_network_optimization_sync():
    """딥 최적화가 호출하는 안전 경로. DNS 캐시만 비운다.

    이전 버전은 여기서 Winsock 초기화와 TCP/레지스트리 영구 변경까지 했다.
    UI 에는 'DNS 초기화'라고만 표시됐으므로 사용자가 알 수 없는 영구 변경이었다.
    영구 변경이 필요하면 apply_network_tweaks(consent=True) 를 따로 호출해야 한다.
    """
    r = flush_dns()
    ok = r.get("success", False)
    _network_state["status"] = "success" if ok else "error"
    _network_state["message"] = "DNS 캐시를 초기화했습니다." if ok else "DNS 캐시 초기화에 실패했습니다."
    _network_state["details"] = [("DNS Flush", ok)]
    return {"success": ok, "message": _network_state["message"], "details": _network_state["details"]}


def _run_network_bg():
    """Background thread wrapper for the consented permanent tweaks."""
    global _network_state
    try:
        results = _apply_network_tweaks_internal()
        success_count = sum(1 for _, s in results if s)
        _network_state["status"] = "success"
        _network_state["message"] = (
            f"네트워크 최적화 완료 ({success_count}/{len(results)}개 항목 적용). "
            "Winsock 초기화를 반영하려면 재부팅이 필요합니다."
        )
        _network_state["details"] = results
    except Exception as e:
        _network_state["status"] = "error"
        _network_state["message"] = str(e)


def apply_network_tweaks(consent=False):
    """네트워크 영구 최적화.

    consent=False 는 '미리보기' 모드다. 시스템을 전혀 건드리지 않고 무엇이
    영구적으로 바뀌는지 항목만 돌려준다. 프론트에서 사용자가 항목을 확인하고
    동의한 뒤 consent=True 로 다시 호출해야 실제로 적용된다.
    """
    if not consent:
        return {
            "success": True,
            "applied": False,
            "requires_consent": True,
            "requires_reboot": True,
            "permanent_changes": NETWORK_PERMANENT_CHANGES,
            "message": "아래 항목은 재부팅 후에도 유지되는 영구 변경입니다. 동의해야 적용됩니다."
        }

    global _network_state
    if _network_state["status"] == "running":
        return {"success": False, "applied": False, "message": "이미 네트워크 최적화가 실행 중입니다."}
    _network_state["status"] = "running"
    _network_state["message"] = ""
    _network_state["details"] = []
    t = threading.Thread(target=_run_network_bg, daemon=True)
    t.start()
    return {"success": True, "applied": True}


def optimize_network(consent=False):
    """하위 호환 별칭. 기본값이 consent=False 라 옛 프론트가 호출해도 미리보기만 반환한다."""
    return apply_network_tweaks(consent=consent)


def get_network_status():
    return _network_state
