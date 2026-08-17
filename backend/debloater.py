"""
APEX CARE - Windows Deep Debloater
Removes bloatware UWP apps safely using PowerShell and direct Registry policy modifications.
"""
import subprocess
import threading
import logging

log = logging.getLogger('Debloater')
CREATE_NO_WINDOW = 0x08000000

DEBLOAT_SAFE_LIST = [
    {"id": "bing", "name": "Bing 앱 (News, Weather)", "pattern": "*bing*"},
    {"id": "zune", "name": "Zune 미디어 (Video, Music)", "pattern": "*zune*"},
    {"id": "solitaire", "name": "Solitaire Collection", "pattern": "*solitaire*"},
    {"id": "skype", "name": "Skype", "pattern": "*skypeapp*"},
    {"id": "maps", "name": "Windows Maps", "pattern": "*windowsmaps*"},
    {"id": "yourphone", "name": "휴대폰과 연결 (Your Phone)", "pattern": "*yourphone*"},
    {"id": "3dbuilder", "name": "3D Builder", "pattern": "*3dbuilder*"},
    {"id": "feedback", "name": "피드백 허브", "pattern": "*feedbackhub*"},
    {"id": "xbox", "name": "Xbox 관련 앱", "pattern": "*xboxapp*"},
    {"id": "telemetry", "name": "Windows 원격 분석 (Telemetry) 차단", "pattern": "telemetry"},
    {"id": "cortana", "name": "Cortana 비활성화", "pattern": "cortana"}
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


def _run_ps(ps_cmd, timeout):
    """PowerShell 한 줄을 실행하고 CompletedProcess 를 돌려준다."""
    return subprocess.run(
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{ps_cmd}"',
        shell=True, capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW, timeout=timeout
    )


def _run_all(cmds, timeout):
    """cmds 를 모두 실행하고 전부 성공했을 때만 True. 반환 코드를 실제로 확인한다."""
    ok = True
    for c in cmds:
        result = subprocess.run(
            c, shell=True, capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=timeout
        )
        if result.returncode != 0:
            log.warning(f"Command failed (code {result.returncode}): {c} -> {result.stderr.strip()}")
            ok = False
    return ok


def _count_appx(pattern):
    """패턴에 맞는 설치된 Appx 패키지 수. 조회 실패 시 None."""
    try:
        result = _run_ps(
            f'@(Get-AppxPackage -AllUsers \'{pattern}\').Count',
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
                if item_id == "telemetry":
                    # Disable Telemetry via CMD reg add directly (faster & 100% reliable)
                    cmds = [
                        r'reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection" /v AllowTelemetry /t REG_DWORD /d 0 /f',
                        r'reg add "HKLM\SYSTEM\CurrentControlSet\Services\DiagTrack" /v Start /t REG_DWORD /d 4 /f',
                        r'sc stop DiagTrack'
                    ]
                    # sc stop 은 이미 멈춰 있으면 실패한다. 정책 레지스트리 2건만 성패로 본다.
                    ok = _run_all(cmds[:2], timeout=15)
                    _run_all(cmds[2:], timeout=15)

                elif item_id == "cortana":
                    ok = _run_all(
                        [r'reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Windows Search" /v AllowCortana /t REG_DWORD /d 0 /f'],
                        timeout=15
                    )

                else:
                    ok = _remove_appx(item["pattern"])

                if ok:
                    succeeded.append(item["name"])
                else:
                    failed.append(item["name"])

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
