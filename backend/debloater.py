"""
APEX CARE - Windows Deep Debloater
Removes bloatware UWP apps safely using PowerShell.
"""
import subprocess
import threading
import time

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
            # Find item config
            item = next((x for x in DEBLOAT_SAFE_LIST if x["id"] == item_id), None)
            if not item: continue
            
            _debloat_state["current_task"] = f"{item['name']} 제거 중..."
            
            if item_id == "telemetry":
                # Disable telemetry via Registry
                cmd = 'Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection" -Name "AllowTelemetry" -Type DWord -Value 0 -Force -ErrorAction SilentlyContinue'
                subprocess.run(["powershell", "-Command", cmd], creationflags=0x08000000)
            elif item_id == "cortana":
                # Disable Cortana via Registry
                cmd = 'Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\Windows Search" -Name "AllowCortana" -Type DWord -Value 0 -Force -ErrorAction SilentlyContinue'
                subprocess.run(["powershell", "-Command", cmd], creationflags=0x08000000)
            else:
                # Remove AppxPackage
                pattern = item["pattern"]
                cmd = f'Get-AppxPackage {pattern} | Remove-AppxPackage -ErrorAction SilentlyContinue'
                subprocess.run(["powershell", "-Command", cmd], creationflags=0x08000000)
                
            # Update progress
            pct = int(((i + 1) / total_items) * 100)
            _debloat_state["progress_pct"] = pct
            time.sleep(1) # Slight UI breathing room
            
        _debloat_state["progress_pct"] = 100
        _debloat_state["current_task"] = "완료! 윈도우 순정화가 끝났습니다."
        
    except Exception as e:
        _debloat_state["error"] = str(e)
        _debloat_state["current_task"] = f"오류 발생: {str(e)}"
    finally:
        _debloat_state["running"] = False

def start_debloater(selected_ids):
    if _debloat_state["running"]:
        return {"success": False, "message": "이미 실행 중입니다."}
        
    t = threading.Thread(target=_run_debloater, args=(selected_ids,), daemon=True)
    t.start()
    return {"success": True}
