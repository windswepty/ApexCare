"""
APEX CARE - Windows 기본 앱 제거 · 원격 분석 정책.

두 종류의 항목이 있다.
  - 정책(원격 분석, Cortana): 레지스트리·서비스 변경. system_state 저널을 거쳐
    원래 값을 기록하므로 복구 센터에서 되돌릴 수 있다.
  - 앱 제거(Appx): 되돌릴 수 없다. 다시 쓰려면 Microsoft Store 에서 설치해야 한다.
    UI 가 이 차이를 보여줄 수 있게 항목마다 reversible 을 둔다.

예전 구현은 정책 항목을 'reg add' 로 셸에서 바로 썼다. 원래 값이 기록되지 않아
되돌릴 방법이 없었고, 명령은 shell=True 로 실행됐다.
"""
import re
import subprocess
import threading
import logging

log = logging.getLogger('Debloater')
CREATE_NO_WINDOW = 0x08000000
DEBLOAT_GROUP = 'debloat'

_APPX_NOTE = '앱을 제거합니다. 되돌리려면 Microsoft Store 에서 다시 설치해야 합니다.'

DEBLOAT_SAFE_LIST = [
    {"id": "bing", "name": "Bing 앱 (뉴스, 날씨, 검색 등)", "pattern": "*bing*",
     "reversible": False, "note": _APPX_NOTE},
    {"id": "zune", "name": "미디어 플레이어 · 영화 및 TV (Zune)", "pattern": "*zune*",
     "reversible": False,
     "note": "Windows 11 의 기본 '미디어 플레이어' 앱도 함께 제거됩니다. " + _APPX_NOTE},
    {"id": "solitaire", "name": "Solitaire Collection", "pattern": "*solitaire*",
     "reversible": False, "note": _APPX_NOTE},
    {"id": "skype", "name": "Skype", "pattern": "*skypeapp*",
     "reversible": False, "note": _APPX_NOTE},
    {"id": "maps", "name": "Windows 지도", "pattern": "*windowsmaps*",
     "reversible": False, "note": _APPX_NOTE},
    {"id": "yourphone", "name": "휴대폰과 연결 (Phone Link)", "pattern": "*yourphone*",
     "reversible": False, "note": _APPX_NOTE},
    {"id": "3dbuilder", "name": "3D Builder", "pattern": "*3dbuilder*",
     "reversible": False, "note": _APPX_NOTE},
    {"id": "feedback", "name": "피드백 허브", "pattern": "*feedbackhub*",
     "reversible": False, "note": _APPX_NOTE},
    {"id": "xbox", "name": "Xbox 콘솔 도우미 (구 Xbox 앱)", "pattern": "*xboxapp*",
     "reversible": False, "note": "Xbox Game Bar 와 새 Xbox 앱은 건드리지 않습니다. " + _APPX_NOTE},
    {"id": "telemetry", "name": "Windows 원격 분석 (Telemetry) 줄이기", "pattern": "policy",
     "reversible": True,
     "note": "원격 분석 정책을 최소로 두고 DiagTrack 서비스를 '사용 안 함'으로 바꿉니다(다음 부팅부터). 복구 센터에서 되돌릴 수 있습니다."},
    {"id": "cortana", "name": "Cortana 끄기", "pattern": "policy",
     "reversible": True, "note": "Cortana 사용 안 함 정책을 켭니다. 복구 센터에서 되돌릴 수 있습니다."},
]

_debloat_state = {
    "running": False,
    "progress_pct": 0,
    "current_task": "",
    "error": None,
    "succeeded": [],
    "failed": []
}

# Appx 제거는 사용자 계정 수와 디스크 속도에 따라 1분을 넘기는 일이 흔하다.
# 30초는 정상 동작을 시간 초과로 오인하게 만든다.
APPX_TIMEOUT_SEC = 180

# 패턴은 위 목록의 상수뿐이지만, PowerShell 문자열에 들어가므로 모양을 한 번 더 확인한다.
_PATTERN_RE = re.compile(r'^\*?[a-z0-9.]+\*?$')


def _run_ps(ps_cmd, timeout):
    """PowerShell 명령을 실행한다. 셸을 거치지 않고 인자 리스트로 넘긴다."""
    return subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive',
         '-ExecutionPolicy', 'Bypass', '-Command', ps_cmd],
        shell=False, capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW, timeout=timeout
    )


def _count_appx(pattern):
    """패턴에 맞는 설치된 Appx 패키지 수. 조회 실패 시 None."""
    try:
        result = _run_ps(
            f"@(Get-AppxPackage -AllUsers '{pattern}').Count",
            timeout=60
        )
        if result.returncode != 0:
            return None
        return int((result.stdout or "").strip())
    except Exception as e:
        log.debug(f"Failed to count appx for {pattern}: {e}")
        return None


def _remove_appx(pattern):
    """Appx 패키지를 전 사용자/프로비저닝 양쪽에서 제거하고, 실제로 사라졌는지 확인한다."""
    if not _PATTERN_RE.match(pattern or ''):
        log.warning(f"허용되지 않는 패턴: {pattern!r}")
        return False
    ps_cmd = (
        f"Get-AppxPackage -AllUsers '{pattern}' | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue; "
        f"Get-AppxProvisionedPackage -Online | Where-Object {{ $_.DisplayName -like '{pattern}' }} | "
        f"Remove-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue"
    )
    _run_ps(ps_cmd, timeout=APPX_TIMEOUT_SEC)

    # -ErrorAction SilentlyContinue 때문에 반환 코드만으로는 성패를 알 수 없다.
    # 남아 있는지 직접 세어서 판단한다.
    remaining = _count_appx(pattern)
    if remaining is None:
        return False
    return remaining == 0


def _apply_telemetry_policy():
    """원격 분석 정책 + DiagTrack 서비스. 모두 저널에 원래 값을 기록한다. (ok, 사유)"""
    from backend import system_state as ss
    reasons = []
    r = ss.set_registry('HKLM', r'SOFTWARE\Policies\Microsoft\Windows\DataCollection',
                        'AllowTelemetry', 0, group=DEBLOAT_GROUP,
                        why='디블로터: 원격 분석 수준 최소화 정책 (AllowTelemetry=0)')
    if not r.get('ok'):
        reasons.append(f"정책: {r.get('reason')}")
    # 서비스는 시작 유형만 바꾼다(다음 부팅부터 반영). 실행 중인 서비스를 즉시 멈추면
    # 그 상태는 기록·복구할 수 없다. 이 PC 에 없는 서비스면 건너뛴다.
    if ss.service_start_type('DiagTrack') is not None:
        r = ss.set_service_start('DiagTrack', 'disabled', DEBLOAT_GROUP,
                                 why="디블로터: 원격 분석 서비스(DiagTrack) '사용 안 함'")
        if not r.get('ok'):
            reasons.append(f"DiagTrack: {r.get('reason')}")
    return (not reasons), '; '.join(reasons)


def _apply_cortana_policy():
    from backend import system_state as ss
    r = ss.set_registry('HKLM', r'SOFTWARE\Policies\Microsoft\Windows\Windows Search',
                        'AllowCortana', 0, group=DEBLOAT_GROUP,
                        why='디블로터: Cortana 사용 안 함 정책 (AllowCortana=0)')
    return bool(r.get('ok')), r.get('reason', '')

def get_debloat_list():
    return DEBLOAT_SAFE_LIST

def get_debloat_status():
    return _debloat_state

def _run_debloater(selected_ids):
    global _debloat_state
    _debloat_state = {
        "running": True,
        "progress_pct": 0,
        "current_task": "디블로팅 시작 중...",
        "error": None,
        "succeeded": [],
        "failed": []
    }
    
    try:
        total_items = len(selected_ids)
        if total_items == 0:
            _debloat_state["progress_pct"] = 100
            _debloat_state["current_task"] = "선택된 항목이 없습니다."
            return

        succeeded = []
        failed = []

        for i, item_id in enumerate(selected_ids):
            item = next((x for x in DEBLOAT_SAFE_LIST if x["id"] == item_id), None)
            if not item: continue

            _debloat_state["current_task"] = f"{item['name']} 제거 중..."
            log.info(f"Debloating: {item['name']} (ID: {item_id})")

            # 항목 하나가 실패하거나 시간을 초과해도 나머지 항목은 계속 처리한다.
            # 예전에는 여기서 예외가 나면 루프 전체가 중단됐다.
            try:
                reason = ''
                if item_id == "telemetry":
                    ok, reason = _apply_telemetry_policy()
                elif item_id == "cortana":
                    ok, reason = _apply_cortana_policy()
                else:
                    ok = _remove_appx(item["pattern"])

                if ok:
                    succeeded.append(item["name"])
                else:
                    failed.append(f"{item['name']} ({reason})" if reason else item["name"])

            except subprocess.TimeoutExpired:
                log.warning(f"✗ Debloat timeout: {item['name']}")
                failed.append(f"{item['name']} (시간 초과)")
            except Exception as e:
                log.warning(f"✗ Debloat failed: {item['name']} -> {e}")
                failed.append(item["name"])

            pct = int(((i + 1) / total_items) * 100)
            _debloat_state["progress_pct"] = pct

        _debloat_state["progress_pct"] = 100
        _debloat_state["succeeded"] = succeeded
        _debloat_state["failed"] = failed

        # 실제 결과를 그대로 보고한다. 예전에는 하나도 못 지워도 '완료'라고 표시했다.
        if failed and succeeded:
            _debloat_state["current_task"] = (
                f"{len(succeeded)}개 제거 완료, {len(failed)}개 실패: {', '.join(failed)}"
            )
        elif failed:
            _debloat_state["current_task"] = (
                f"제거하지 못했습니다: {', '.join(failed)} "
                "(관리자 권한이 필요하거나 이미 제거된 항목일 수 있습니다.)"
            )
        else:
            _debloat_state["current_task"] = f"완료! {len(succeeded)}개 항목을 제거했습니다."
        log.info(f"Debloater finished. ok={len(succeeded)} failed={len(failed)}")

    except Exception as e:
        _debloat_state["error"] = str(e)
        _debloat_state["current_task"] = f"오류 발생: {str(e)}"
        log.warning(f"⚠ Debloater exception: {e}")
    finally:
        _debloat_state["running"] = False

def start_debloater(selected_ids):
    if _debloat_state["running"]:
        return {"success": False, "message": "이미 디블로팅이 실행 중입니다."}
        
    t = threading.Thread(target=_run_debloater, args=(selected_ids,), daemon=True)
    t.start()
    return {"success": True}
