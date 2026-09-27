"""
APEX CARE - System Repair and Advanced Disk Ops
Runs long-running commands like SFC, DISM, Defrag, and Network optimization in hidden subprocesses with full logging and error handling.
"""
import subprocess
import threading
import logging

log = logging.getLogger('SystemRepair')
CREATE_NO_WINDOW = 0x08000000

def _run_hidden_cmd(args, timeout=120):
    """명령을 창 없이 실행한다. 인자 리스트만 받는다(shell=False).

    예전에는 리스트를 공백으로 이어 붙여 shell=True 로 넘겼다. 이 앱은 관리자
    권한으로 돌기 때문에 인자에 셸 메타문자가 섞이면 그대로 관리자 명령이 된다.
    """
    if not isinstance(args, (list, tuple)) or not args:
        return {"success": False, "error": "명령은 인자 리스트로만 실행합니다."}
    try:
        result = subprocess.run(
            [str(a) for a in args],
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",           # 콘솔 도구는 OEM 코드 페이지로 출력한다. 못 읽는 바이트로 읽기 스레드가 죽지 않게
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout
        )
        if result.returncode == 0:
            return {"success": True, "message": "성공적으로 완료되었습니다.", "output": result.stdout}
        return {"success": False, "message": f"작업 실패 (코드: {result.returncode})",
                "error": result.stderr or result.stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# Background task state dictionaries
# ─────────────────────────────────────────────

_sfc_state = {"status": "idle", "output": "", "error": None}
_dism_state = {"status": "idle", "output": "", "error": None}
_trim_state = {"status": "idle", "output": "", "error": None}

def _run_hidden_cmd_bg(args, state_dict, timeout_sec=600):
    cmd_str = " ".join(str(a) for a in args)        # 로그 표시용. 실행에는 쓰지 않는다.
    try:
        log.info(f"Starting background command: {cmd_str}")
        result = subprocess.run(
            [str(a) for a in args],
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",           # 콘솔 도구는 OEM 코드 페이지로 출력한다. 못 읽는 바이트로 읽기 스레드가 죽지 않게
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
# 네트워크
# ─────────────────────────────────────────────
# 원클릭 최적화가 부르는 것은 DNS 캐시 비우기뿐이다(캐시라 되돌릴 필요가 없다).
#
# 예전에는 여기에 '네트워크 영구 최적화' 가 있었다: Winsock 카탈로그 초기화,
# TCP 자동 튜닝 끄기, 모든 어댑터의 Nagle 끄기, 네트워크 스로틀링 해제.
# 지웠다. 이유:
#   - Winsock 초기화는 되돌릴 수 없고, VPN·보안 프로그램이 등록한 네트워크 계층을
#     함께 지운다. '컴퓨터에 손상이 가면 안 된다' 는 조건과 정면으로 부딪친다.
#   - 자동 튜닝을 끄면 고속·고지연 회선에서 다운로드가 오히려 느려진다.
#   - 프론트엔드 어디에서도 호출되지 않았다. 쓰이지 않는 위험한 경로를 남겨두면
#     나중에 누군가 다시 연결한다.
# 게임용 Nagle 끄기는 게이밍 탭의 선택 항목으로 남아 있고, system_state 저널을 거친다.
#
# 구버전이 이미 적용해 버린 사용자를 위해 '되돌리기' 만 남긴다.

_NAGLE_BASE = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
_THROTTLE_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"

# netsh 가 받는 자동 튜닝 수준. Get-NetTCPSetting 이 돌려주는 이름을 소문자로 바꾼 것.
_AUTOTUNING_LEVELS = {"normal", "disabled", "highlyrestricted", "restricted", "experimental"}


def flush_dns():
    """DNS 캐시만 비운다. 캐시라서 되돌릴 필요가 없는 유일한 안전 항목."""
    return _run_hidden_cmd(["ipconfig", "/flushdns"])


def run_network_optimization_sync():
    """딥 최적화가 호출하는 안전 경로. DNS 캐시만 비운다."""
    r = flush_dns()
    ok = r.get("success", False)
    return {"success": ok,
            "message": "DNS 캐시를 초기화했습니다." if ok else "DNS 캐시 초기화에 실패했습니다.",
            "details": [("DNS Flush", ok)]}


def has_legacy_network_backup():
    """구버전 네트워크 튜닝의 백업이 settings.json 에 남아 있는지."""
    try:
        from backend import config_manager
        return bool(config_manager.load_config().get("network_tweak_backup"))
    except Exception:
        return False


def _restore_dword(path, name, original):
    """원래 값으로 되돌리고 되읽어 확인한다. original 이 None 이면 '원래 없던 값' 이라 지운다.

    실패 사유를 문자열로, 성공이면 None.
    """
    import winreg
    from backend import system_state as ss
    try:
        if original is None:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                    winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                    winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        else:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(original))
        existed, now, _ = ss.read_registry_strict('HKLM', path, name)
    except FileNotFoundError:
        return None if original is None else '레지스트리 키가 없습니다'
    except PermissionError:
        return '권한 부족(관리자 권한 필요)'
    except Exception as e:
        return str(e)
    if original is None:
        return '지운 뒤에도 값이 남아 있습니다' if existed else None
    return None if (existed and now == int(original)) else f'기대 {original}, 실제 {now}'


def restore_network_tweaks():
    """구버전 '네트워크 영구 최적화' 가 바꾼 것을 settings.json 의 백업대로 되돌린다.

    - 백업이 없으면 아무것도 하지 않는다. 예전에는 '윈도우 기본값' 을 추측해 써넣고
      모든 어댑터의 Nagle 값을 지웠다. 이 기능을 쓴 적 없는 사용자의 설정까지 바뀌었다.
    - 하나라도 실패하면 백업을 지우지 않는다. 다시 시도할 수 있어야 한다.
    - Winsock 초기화는 되돌릴 방법이 없다. 그 사실을 알린다.
    """
    from backend import config_manager
    cfg = config_manager.load_config()
    backup = cfg.get("network_tweak_backup")
    if not backup or not isinstance(backup, dict):
        return {"success": True, "restored": [], "failed": [],
                "message": "되돌릴 네트워크 튜닝 기록이 없습니다."}

    restored, failed = [], []
    remaining = dict(backup)

    # TCP 자동 튜닝
    level = backup.get("autotuning")
    if level is None:
        failed.append({"item": "TCP 자동 튜닝",
                       "reason": "원래 값이 기록되지 않아 되돌리지 않았습니다. 필요하면 관리자 명령 프롬프트에서 "
                                 "'netsh int tcp set global autotuninglevel=normal' 을 실행하세요."})
        remaining.pop("autotuning", None)       # 다시 시도해도 알 수 없는 값이다
    else:
        lv = str(level).strip().lower()
        if lv not in _AUTOTUNING_LEVELS:
            failed.append({"item": "TCP 자동 튜닝", "reason": f"알 수 없는 기록값 '{level}'"})
            remaining.pop("autotuning", None)
        else:
            r = _run_hidden_cmd(["netsh", "int", "tcp", "set", "global", f"autotuninglevel={lv}"])
            if r.get("success"):
                restored.append("TCP 자동 튜닝")
                remaining.pop("autotuning", None)
            else:
                failed.append({"item": "TCP 자동 튜닝", "reason": r.get("error") or r.get("message", "실패")})

    # 네트워크 스로틀링 (None = 원래 없던 값)
    if "throttling_index" in backup:
        reason = _restore_dword(_THROTTLE_KEY, "NetworkThrottlingIndex", backup.get("throttling_index"))
        if reason:
            failed.append({"item": "네트워크 스로틀링", "reason": reason})
        else:
            restored.append("네트워크 스로틀링")
            remaining.pop("throttling_index", None)

    # 어댑터별 Nagle
    interfaces = backup.get("interfaces") or {}
    left = {}
    for iface, values in interfaces.items():
        path = f"{_NAGLE_BASE}\\{iface}"
        errs = []
        for value_name in ("TcpAckFrequency", "TCPNoDelay"):
            reason = _restore_dword(path, value_name, (values or {}).get(value_name))
            if reason == '레지스트리 키가 없습니다':
                continue                     # 어댑터가 사라졌다. 되돌릴 대상이 없다.
            if reason:
                errs.append(f"{value_name}: {reason}")
        if errs:
            left[iface] = values
            failed.append({"item": f"Nagle ({iface})", "reason": "; ".join(errs)})
    if interfaces:
        if left:
            remaining["interfaces"] = left
        else:
            restored.append("Nagle")
            remaining.pop("interfaces", None)

    retryable = bool(set(remaining) & {"autotuning", "throttling_index", "interfaces"})
    if retryable:
        cfg["network_tweak_backup"] = remaining
    else:
        cfg.pop("network_tweak_backup", None)
    config_manager.save_config(cfg)

    msg = f"구버전 네트워크 튜닝 복구: {', '.join(restored) if restored else '없음'}"
    if failed:
        msg += f" / {len(failed)}개 실패"
    msg += (" 재부팅해야 완전히 적용됩니다. Winsock 초기화는 되돌릴 수 없으며, 그때 사라진 "
            "VPN·보안 프로그램의 네트워크 구성 요소는 해당 프로그램을 다시 설치해야 복구됩니다.")
    return {"success": not retryable, "restored": restored, "failed": failed, "message": msg}
