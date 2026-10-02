"""
APEX CARE - System Repair and Advanced Disk Ops
Runs long-running commands like SFC, DISM, Defrag, and Network optimization in hidden subprocesses with full logging and error handling.
"""
import os
import re
import subprocess
import threading
import logging

log = logging.getLogger('SystemRepair')
CREATE_NO_WINDOW = 0x08000000


def sys_tool(name):
    """Windows 도구의 절대 경로(%SystemRoot%\\System32\\name). 32비트로 돌면 Sysnative 로 64비트 쪽을 쓴다.

    이 앱은 관리자 권한으로 돈다. 'sfc.exe' 처럼 이름만 넘기면 CreateProcess 가 실행 파일 폴더와 '현재 폴더' 를
    System32 보다 먼저 찾아, 사용자가 쓸 수 있는 현재 폴더에 같은 이름의 exe 를 심으면 그것이 관리자 권한으로 돌았다.
    """
    sysroot = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or r'C:\Windows'
    native = os.path.join(sysroot, 'Sysnative', name)
    if os.path.exists(native):
        return native
    return os.path.join(sysroot, 'System32', name)

def _run_hidden_cmd(args, timeout=120):
    """명령을 창 없이 실행한다. 인자 리스트만 받는다(shell=False).

    예전에는 리스트를 공백으로 이어 붙여 shell=True 로 넘겼다. 이 앱은 관리자
    권한으로 돌기 때문에 인자에 셸 메타문자가 섞이면 그대로 관리자 명령이 된다.
    """
    if not isinstance(args, (list, tuple)) or not args:
        return {"success": False, "error": "명령은 인자 리스트로만 실행합니다."}
    if not os.path.isabs(str(args[0])):
        return {"success": False, "error": "실행 파일은 절대 경로로만 실행합니다."}
    try:
        result = subprocess.run(
            [str(a) for a in args],
            shell=False,
            capture_output=True,        # 바이트로 받는다. 콘솔 도구는 OEM 코드 페이지로 출력한다
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout
        )
        out = decode_console_output(result.stdout)
        if result.returncode == 0:
            return {"success": True, "message": "성공적으로 완료되었습니다.", "output": out}
        err = decode_console_output(result.stderr)
        return {"success": False, "message": f"작업 실패 (코드: {result.returncode})",
                "error": summarize_output(err) or summarize_output(out) or f"종료 코드 {result.returncode}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# Background task state dictionaries
# ─────────────────────────────────────────────

_sfc_state = {"status": "idle", "output": "", "error": None, "summary": ""}
_dism_state = {"status": "idle", "output": "", "error": None, "summary": ""}
_trim_state = {"status": "idle", "output": "", "error": None, "summary": ""}

# 디스크 최적화 시간 제한. 시간이 지나면 subprocess 가 defrag 를 강제로 끝낸다.
# 예전에는 300초였는데, HDD 조각 모음은 수십 분 걸려 늘 도중에 끊기고 '실패' 로 보였다.
TRIM_TIMEOUT_SEC = 3 * 3600

# 진행 표시 줄(검증 45% 완료, [=====  20.0%  ])은 결과가 아니다. 요약에서 뺀다.
_PROGRESS_LINE = re.compile(r'\d+(?:[.,]\d+)?\s*%')


def decode_console_output(data):
    """콘솔 도구의 출력 바이트를 글자로 바꾼다.

    sfc.exe 는 출력을 파일·파이프로 보내면 UTF-16 으로 쓴다. 예전에는 이것을 코드 페이지로 읽어
    글자 사이마다 NUL 이 끼어 알아볼 수 없었다. dism·defrag 는 OEM 코드 페이지로 쓴다.
    """
    if not data:
        return ''
    if isinstance(data, str):
        return data
    # 코드 페이지 출력에는 NUL 바이트가 나오지 않는다. UTF-16 은 줄바꿈·공백·숫자 같은 ASCII 마다 NUL 이 붙는다.
    # (한글만 보면 NUL 이 없어 비율로는 못 가린다.)
    if data[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\x00' in data[:4096]:
        text = data.decode('utf-16-le', errors='replace')
        return text.lstrip('﻿').replace('\x00', '')
    for enc in ('oem', 'mbcs', 'utf-8'):
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode('utf-8', errors='replace')


def _meaningful(ln):
    return bool(ln) and not _PROGRESS_LINE.search(ln) and not set(ln) <= set('=-_*. ')


def summarize_output(text, max_lines=3, max_chars=400):
    """명령 출력의 마지막 결과 문단(빈 줄로 나뉜 덩어리) 전체. 진행률 줄은 뺀다. 없으면 ''.

    예전에는 마지막 3줄만 남겼다. SFC 의 결과 메시지('손상 파일을 찾아 복구함', '일부를 복구하지 못함',
    '무결성 위반을 찾음')는 결과 한 줄 + CBS.log 안내 3줄이라, 늘 안내 3줄만 남아 세 결과가 똑같이 보였다.
    문단을 찾지 못하면(빈 줄 없는 긴 출력) 예전처럼 마지막 max_lines 줄을 쓴다.
    """
    if not text:
        return ''
    norm = str(text).replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = []
    for block in re.split(r'\n\s*\n', norm):
        lines = [ln.strip() for ln in block.split('\n')]
        lines = [ln for ln in lines if _meaningful(ln)]
        if lines:
            paragraphs.append(lines)
    if not paragraphs:
        return ''
    last = paragraphs[-1]
    if len(paragraphs) == 1 and len(last) > max_lines + 1:
        last = last[-max_lines:]                   # 문단 구분이 없는 긴 출력은 끝부분만
    out = ' '.join(last)
    # 결과 문장은 문단 첫 줄이다. 길면 앞부분(결과)을 남기고 뒤(안내)를 줄인다.
    return out if len(out) <= max_chars else out[:max_chars] + '…'


def _run_hidden_cmd_bg(args, state_dict, timeout_sec=600):
    cmd_str = " ".join(str(a) for a in args)        # 로그 표시용. 실행에는 쓰지 않는다.
    if not args or not os.path.isabs(str(args[0])):
        state_dict["status"] = "error"
        state_dict["error"] = "실행 파일은 절대 경로로만 실행합니다."
        return
    try:
        log.info(f"Starting background command: {cmd_str}")
        result = subprocess.run(
            [str(a) for a in args],
            shell=False,
            capture_output=True,        # 바이트로 받아 도구마다 맞는 인코딩으로 푼다(decode_console_output)
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout_sec
        )
        out = decode_console_output(result.stdout)
        err = decode_console_output(result.stderr)
        state_dict["output"] = out
        # 도구가 마지막에 쓴 결과 문장(예: '무결성 위반을 찾지 못했습니다')을 화면에 그대로 보여 준다.
        # 종료 코드 0 은 '검사를 마쳤다' 는 뜻이지 '손상이 없다·다 고쳤다' 는 뜻이 아니다.
        state_dict["summary"] = summarize_output(out)
        if result.returncode == 0:
            state_dict["status"] = "success"
            log.info(f"✓ Command succeeded: {cmd_str}")
        else:
            state_dict["status"] = "error"
            state_dict["error"] = (summarize_output(err) or summarize_output(out)
                                   or f"종료 코드 {result.returncode}")
            log.warning(f"✗ Command failed (code {result.returncode}): {cmd_str} -> {err or out}")
    except subprocess.TimeoutExpired:
        state_dict["status"] = "error"
        state_dict["error"] = f"{timeout_sec // 60}분 안에 끝나지 않아 중단했습니다."
        log.warning(f"⚠ Command timed out: {cmd_str}")
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
    _trim_state["summary"] = ""
    t = threading.Thread(target=_run_hidden_cmd_bg,
                         args=([sys_tool("defrag.exe"), "/C", "/O"], _trim_state, TRIM_TIMEOUT_SEC), daemon=True)
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
    _sfc_state["summary"] = ""
    # 타임아웃은 subprocess 를 '강제 종료'시킨다. sfc /scannow 를 중간에 죽이면
    # 복구가 반쯤 적용된 상태로 남을 수 있으므로 넉넉하게 잡는다(느린 HDD 기준).
    t = threading.Thread(target=_run_hidden_cmd_bg, args=([sys_tool("sfc.exe"), "/scannow"], _sfc_state, 3600), daemon=True)
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
    _dism_state["summary"] = ""
    # DISM /RestoreHealth 를 중간에 죽이면 구성 요소 저장소(WinSxS)가 손상될 수 있다.
    # 느린 회선에서 Windows Update 로 원본을 받아오면 1시간을 넘기도 하므로 2시간으로 잡는다.
    t = threading.Thread(target=_run_hidden_cmd_bg, args=([sys_tool("dism.exe"), "/Online", "/Cleanup-image", "/Restorehealth"], _dism_state, 7200), daemon=True)
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
    return _run_hidden_cmd([sys_tool("ipconfig.exe"), "/flushdns"])


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
            r = _run_hidden_cmd([sys_tool("netsh.exe"), "int", "tcp", "set", "global", f"autotuninglevel={lv}"])
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

    def keep_remaining(c):
        # 처음에 읽은 설정을 통째로 저장하지 않는다. 그 사이 바뀐 다른 값이 사라진다.
        if retryable:
            c["network_tweak_backup"] = remaining
        else:
            c.pop("network_tweak_backup", None)
    if not config_manager.update_config(keep_remaining):
        log.warning("구버전 네트워크 튜닝 백업 기록을 갱신하지 못했습니다")

    msg = f"구버전 네트워크 튜닝 복구: {', '.join(restored) if restored else '없음'}"
    if failed:
        msg += f" / {len(failed)}개 실패"
    msg += (" 재부팅해야 완전히 적용됩니다. Winsock 초기화는 되돌릴 수 없으며, 그때 사라진 "
            "VPN·보안 프로그램의 네트워크 구성 요소는 해당 프로그램을 다시 설치해야 복구됩니다.")
    return {"success": not retryable, "restored": restored, "failed": failed, "message": msg}
