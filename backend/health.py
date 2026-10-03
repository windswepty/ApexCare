"""
APEX CARE — PC 건강 진단. 읽기만 한다. 아무것도 바꾸지 않는다.

- 디스크 건강: Windows 저장소 관리(Get-PhysicalDisk)의 상태와 신뢰성 카운터(수명 사용량·온도·사용 시간·오류).
  디스크가 알려 주지 않는 값은 None 으로 둔다(0 으로 지어내지 않는다). 많은 디스크가 일부 값을 알려 주지 않는다.
- 부팅 시간 기록: Windows 진단-성능 로그의 부팅 이벤트(ID 100)에 Windows 가 직접 잰 부팅 시간.
  시작 프로그램을 끈 뒤 부팅이 실제로 빨라졌는지 숫자로 볼 수 있다. 로그가 꺼져 있으면 빈 목록과 이유를 돌려준다.
"""

import logging

log = logging.getLogger('Health')

QUERY_TIMEOUT_SEC = 60

_PS_DISKS = r"""
foreach ($d in @(Get-PhysicalDisk)) {
  $r = $null
  try { $r = $d | Get-StorageReliabilityCounter -ErrorAction Stop } catch {}
  $letters = @()
  try {
    $letters = @(Get-Partition -DiskNumber ([int]$d.DeviceId) -ErrorAction Stop |
                 Where-Object { $_.DriveLetter } | ForEach-Object { "$($_.DriveLetter):" })
  } catch {}
  [void]$out.Add([ordered]@{
    id = [string]$d.DeviceId; name = [string]$d.FriendlyName; media = [string]$d.MediaType; bus = [string]$d.BusType
    sizeBytes = [double]$d.Size; health = [string]$d.HealthStatus; status = (@($d.OperationalStatus) -join ', ')
    letters = $letters
    temperature = $r.Temperature; temperatureMax = $r.TemperatureMax; wear = $r.Wear; powerOnHours = $r.PowerOnHours
    readErrors = $r.ReadErrorsUncorrected; writeErrors = $r.WriteErrorsUncorrected
  })
}
"""

_PS_BOOTS = r"""
$events = @()
try {
  $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-Diagnostics-Performance/Operational'; Id = 100 } `
              -MaxEvents ([int]$arg.count) -ErrorAction Stop)
} catch {
  if ($_.FullyQualifiedErrorId -notmatch 'NoMatchingEventsFound') { throw }
}
foreach ($e in $events) {
  $data = @{}
  foreach ($x in ([xml]$e.ToXml()).Event.EventData.Data) { $data[[string]$x.Name] = [string]$x.'#text' }
  [void]$out.Add([ordered]@{
    at = $e.TimeCreated.ToString('o'); bootMs = $data['BootTime']; mainPathMs = $data['MainPathBootTime']
    postBootMs = $data['BootPostBootTime']
  })
}
"""

_HEALTH_LABEL = {'healthy': '정상', 'warning': '주의', 'unhealthy': '위험'}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None           # NaN 제외


def _disk_row(r):
    media = (r.get('media') or '').upper()
    is_ssd = media == 'SSD'
    temp = _num(r.get('temperature'))
    hours = _num(r.get('powerOnHours'))
    wear = _num(r.get('wear'))
    size = _num(r.get('sizeBytes'))
    health = str(r.get('health') or '').strip().lower()
    return {
        'id': str(r.get('id') or ''),
        'name': str(r.get('name') or '이름 모름'),
        'media': 'SSD' if is_ssd else 'HDD' if media == 'HDD' else None,
        'bus': str(r.get('bus') or '') or None,
        'sizeGB': round(size / 1024 ** 3, 1) if size else None,
        'letters': [str(x) for x in (r.get('letters') or []) if isinstance(x, str)],
        'health': _HEALTH_LABEL.get(health, '알 수 없음'),
        'healthRaw': str(r.get('health') or ''),
        'status': str(r.get('status') or ''),
        # 0 도는 '알려 주지 않음' 이다(실제 0 도인 디스크는 없다)
        'temperatureC': temp if temp and 0 < temp < 150 else None,
        'temperatureMaxC': _num(r.get('temperatureMax')) or None,
        # 수명 사용량은 SSD 만 의미가 있다. HDD 가 0 을 돌려주면 '닳지 않음' 이 아니라 '모름' 이다
        'wearPct': wear if is_ssd and wear is not None and 0 <= wear <= 100 else None,
        'powerOnHours': hours if hours and hours > 0 else None,
        'readErrors': _num(r.get('readErrors')),
        'writeErrors': _num(r.get('writeErrors')),
    }


def disk_health():
    """{'ok', 'disks': [...], 'error'}"""
    from backend.debloater import _run_ps_json
    try:
        ok, rows, err = _run_ps_json(_PS_DISKS, {}, QUERY_TIMEOUT_SEC)
    except Exception as e:                       # 시간 초과 등
        return {'ok': False, 'disks': [], 'error': f'디스크 정보를 읽지 못했습니다: {e}'}
    if not ok:
        return {'ok': False, 'disks': [], 'error': f'디스크 정보를 읽지 못했습니다: {err}'}
    disks = sorted((_disk_row(r) for r in rows), key=lambda d: (d['id'].zfill(4), d['name']))
    return {'ok': True, 'disks': disks, 'error': None}


def boot_history(count=15):
    """최근 부팅 시간(초). {'ok', 'boots': [{'at', 'seconds', 'mainPathSeconds'}], 'error'} 새것부터."""
    from backend.debloater import _run_ps_json
    count = max(1, min(int(count), 50))
    try:
        ok, rows, err = _run_ps_json(_PS_BOOTS, {'count': count}, QUERY_TIMEOUT_SEC)
    except Exception as e:
        return {'ok': False, 'boots': [], 'error': f'부팅 기록을 읽지 못했습니다: {e}'}
    if not ok:
        return {'ok': False, 'boots': [], 'error': f'부팅 기록을 읽지 못했습니다: {err}'}
    boots = []
    for r in rows:
        ms = _num(r.get('bootMs'))
        if not ms or ms <= 0:
            continue
        main = _num(r.get('mainPathMs'))
        boots.append({'at': str(r.get('at') or ''), 'seconds': round(ms / 1000, 1),
                      'mainPathSeconds': round(main / 1000, 1) if main and main > 0 else None})
    if not boots:
        return {'ok': True, 'boots': [], 'error': None,
                'note': 'Windows 부팅 성능 기록이 없습니다(진단 로그가 꺼져 있거나 아직 기록된 부팅이 없음).'}
    return {'ok': True, 'boots': boots, 'error': None}
