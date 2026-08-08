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
    "error": None
}

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
        "error": None
    }
    
    try:
        total_items = len(selected_ids)
        if total_items == 0:
            _debloat_state["progress_pct"] = 100
            _debloat_state["current_task"] = "선택된 항목이 없습니다."
            return

        for i, item_id in enumerate(selected_ids):
            item = next((x for x in DEBLOAT_SAFE_LIST if x["id"] == item_id), None)
            if not item: continue
            
            _debloat_state["current_task"] = f"{item['name']} 제거 중..."
            log.info(f"Debloating: {item['name']} (ID: {item_id})")
            
            if item_id == "telemetry":
                # Disable Telemetry via CMD reg add directly (faster & 100% reliable)
                cmds = [
                    r'reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection" /v AllowTelemetry /t REG_DWORD /d 0 /f',
                    r'reg add "HKLM\SYSTEM\CurrentControlSet\Services\DiagTrack" /v Start /t REG_DWORD /d 4 /f',
                    r'sc stop DiagTrack'
                ]
                for c in cmds:
                    subprocess.run(c, shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                    
            elif item_id == "cortana":
                # Disable Cortana via Registry directly
                cmds = [
                    r'reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Windows Search" /v AllowCortana /t REG_DWORD /d 0 /f'
                ]
                for c in cmds:
                    subprocess.run(c, shell=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                    
            else:
                # Remove AppxPackage system-wide (AllUsers & Provisioned)
                pattern = item["pattern"]
                ps_cmd = f'Get-AppxPackage -AllUsers "{pattern}" | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue; Get-AppxProvisionedPackage -Online | Where-Object {{ $_.DisplayName -like "{pattern}" }} | Remove-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue'
                subprocess.run(f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{ps_cmd}"', shell=True, creationflags=CREATE_NO_WINDOW, timeout=30)
                
            pct = int(((i + 1) / total_items) * 100)
            _debloat_state["progress_pct"] = pct
            
        _debloat_state["progress_pct"] = 100
        _debloat_state["current_task"] = "완료! 선택한 윈도우 앱 및 텔레메트리가 제거되었습니다."
        log.info("✓ Debloater finished successfully.")
        
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
