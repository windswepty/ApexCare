"""
APEX CARE — 시스템을 바꾸기 전에 Windows 복원 지점을 만든다.

이 앱은 바꾸기 전 원래 값을 저널에 기록해 되돌린다(system_state). 복원 지점은 그와 별개로 Windows 가 관리하는
안전망이다. 앱이 지워졌거나 저널로 되돌릴 수 없는 일이 생겨도 Windows 의 '시스템 복원' 으로 돌아갈 수 있다.

- 만들기 전후의 복원 지점 목록을 읽어 실제로 새로 생겼는지 확인한다(명령의 성공 여부를 믿지 않는다).
- Windows 는 기본 설정으로 24시간에 한 번만 복원 지점을 만든다. 그때는 만들지 않았다고, 가장 최근 지점과 함께 알린다.
- 시스템 보호가 꺼져 있으면 만들 수 없다. 켜지 않는다(디스크 공간을 쓰는 시스템 설정이라 사용자가 정한다). 그 사실만 알린다.
- 실패해도 앱의 변경은 계속한다. 앱 자체의 되돌리기(저널)는 그대로 있다. 결과는 화면에 그대로 보여 준다.
"""

import logging
import subprocess
import threading

log = logging.getLogger('RestorePoint')

TIMEOUT_SEC = 240           # 처음 만들 때는 볼륨 섀도 복사본을 만드느라 1분 넘게 걸리기도 한다
CONFIG_KEY = 'restore_point_before_changes'
_lock = threading.Lock()    # 둘이 동시에 만들지 않게(성능 모드와 기본 앱 정리를 연달아 누른 경우)

# Get-ComputerRestorePoint·Checkpoint-Computer 는 Windows PowerShell 5.1 에 있다. 설명은 환경 변수(JSON)로 넘긴다.
_PS = r"""
function Points {
  try { return @(Get-ComputerRestorePoint -ErrorAction Stop | ForEach-Object { $_ }) } catch { return @() }
}
$before = Points
$maxBefore = 0
foreach ($p in $before) { if ([int64]$p.SequenceNumber -gt $maxBefore) { $maxBefore = [int64]$p.SequenceNumber } }
$w = @(); $err = $null
try {
  Checkpoint-Computer -Description ([string]$arg.desc) -RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop `
    -WarningVariable w -WarningAction SilentlyContinue
} catch { $err = [string]$_.Exception.Message }
$after = Points
$newest = $after | Sort-Object { [int64]$_.SequenceNumber } -Descending | Select-Object -First 1
$at = $null
if ($newest) { try { $at = $newest.ConvertToDateTime($newest.CreationTime).ToString('o') } catch {} }
[void]$out.Add([ordered]@{
  maxBefore = $maxBefore; count = $after.Count
  newestSeq = $(if ($newest) { [int64]$newest.SequenceNumber } else { $null })
  newestAt = $at; newestDesc = $(if ($newest) { [string]$newest.Description } else { $null })
  warning = ((@($w) | ForEach-Object { [string]$_ }) -join ' ')
  error = $err
})
"""


def enabled():
    from backend import config_manager
    return config_manager.load_config().get(CONFIG_KEY, True) is not False


def set_enabled(value):
    from backend import config_manager
    if not isinstance(value, bool):
        return {'success': False, 'message': f'켜기·끄기 값이 아닙니다: {value}'}
    if (not config_manager.update_config(lambda c: c.__setitem__(CONFIG_KEY, value))
            or config_manager.load_config().get(CONFIG_KEY) is not value):
        return {'success': False, 'message': '설정 파일에 저장하지 못했습니다.'}
    return {'success': True, 'enabled': value}


def _date(iso):
    return (iso or '')[:16].replace('T', ' ') or '알 수 없음'


def interpret(row, timed_out=False):
    """PowerShell 결과 한 줄을 화면에 보일 결과로. {'ok', 'created', 'message', 'at'}"""
    if timed_out:
        return {'ok': False, 'created': False, 'at': None,
                'message': f'복원 지점을 {TIMEOUT_SEC}초 안에 만들지 못했습니다. Windows 가 뒤에서 계속 만들고 있을 수 있습니다.'}
    if not isinstance(row, dict):
        return {'ok': False, 'created': False, 'at': None, 'message': '복원 지점을 만들었는지 확인하지 못했습니다.'}
    seq, before = row.get('newestSeq'), row.get('maxBefore') or 0
    at = row.get('newestAt')
    if isinstance(seq, int) and seq > before:
        return {'ok': True, 'created': True, 'at': at,
                'message': f'Windows 복원 지점을 만들었습니다({_date(at)}).'}
    err = (row.get('error') or '').strip()
    if err:
        return {'ok': False, 'created': False, 'at': None,
                'message': f'Windows 복원 지점을 만들지 못했습니다: {err[:200]} '
                           '(시스템 보호가 꺼져 있으면 만들 수 없습니다. 제어판 → 시스템 → 시스템 보호에서 켤 수 있습니다.)'}
    warn = (row.get('warning') or '').strip()
    recent = f' 가장 최근 복원 지점: {_date(at)}.' if at else ''
    return {'ok': True, 'created': False, 'at': at,
            'message': ('새 복원 지점은 만들지 않았습니다'
                        + (f'(Windows: {warn[:200]})' if warn else '') + '.' + recent)}


def _create(desc):
    """(ok, rows, error). 테스트는 이것을 가짜로 바꾼다(진짜 복원 지점을 만들지 않게)."""
    from backend.debloater import _run_ps_json
    return _run_ps_json(_PS, {'desc': desc}, TIMEOUT_SEC)


def before_change(what):
    """바꾸기 전에 복원 지점을 만든다. 설정에서 껐으면 None(아무것도 하지 않음)."""
    if not enabled():
        return None
    desc = f'APEX CARE: {what}'[:200]
    with _lock:
        try:
            ok, rows, err = _create(desc)
        except subprocess.TimeoutExpired:
            return interpret(None, timed_out=True)
        except Exception as e:
            return {'ok': False, 'created': False, 'at': None, 'message': f'복원 지점을 만들지 못했습니다: {e}'}
    if not ok:
        return {'ok': False, 'created': False, 'at': None, 'message': f'복원 지점을 만들지 못했습니다: {err}'}
    result = interpret(rows[0] if rows else None)
    log.info(result['message'])
    return result
