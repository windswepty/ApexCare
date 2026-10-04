"""
APEX CARE — PC 건강 진단. 읽기만 한다. 아무것도 바꾸지 않는다.

- 디스크 건강: Windows 저장소 관리(Get-PhysicalDisk)의 상태와 신뢰성 카운터(수명 사용량·온도·사용 시간·오류).
  디스크가 알려 주지 않는 값은 None 으로 둔다(0 으로 지어내지 않는다). 많은 디스크가 일부 값을 알려 주지 않는다.
  NVMe 디스크는 디스크가 직접 기록한 건강 기록(SMART/Health 로그)을 읽어 그 값을 쓴다. Windows 신뢰성 카운터는
  NVMe 의 사용 시간·오류를 비워 두고 수명 사용량을 0 으로 돌려주는 일이 있었다(실측: 디스크 기록 13% ↔ 카운터 0%).
- 부팅 시간 기록: Windows 진단-성능 로그의 부팅 이벤트(ID 100)에 Windows 가 직접 잰 부팅 시간.
  시작 프로그램을 끈 뒤 부팅이 실제로 빨라졌는지 숫자로 볼 수 있다. 로그가 꺼져 있으면 빈 목록과 이유를 돌려준다.
  마지막 기록이 실제 마지막 부팅보다 오래됐으면(기록이 멈춤) 그 사실과 진단 정책 서비스 상태를 함께 알린다.
"""

import logging
import struct
from datetime import datetime, timedelta, timezone

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
$meta = [ordered]@{ kind = 'meta'; lastBoot = $null; dps = $null }
try { $meta.lastBoot = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToString('o') } catch {}
try { $meta.dps = [string](Get-Service -Name DPS -ErrorAction Stop).Status } catch {}
[void]$out.Add($meta)
foreach ($e in $events) {
  $data = @{}
  foreach ($x in ([xml]$e.ToXml()).Event.EventData.Data) { $data[[string]$x.Name] = [string]$x.'#text' }
  [void]$out.Add([ordered]@{
    kind = 'boot'; at = $e.TimeCreated.ToString('o'); bootMs = $data['BootTime']; mainPathMs = $data['MainPathBootTime']
    postBootMs = $data['BootPostBootTime']
  })
}
"""

_HEALTH_LABEL = {'healthy': '정상', 'warning': '주의', 'unhealthy': '위험'}

# ── NVMe 건강 기록(SMART/Health 로그, 로그 페이지 2) ──────────
# IOCTL_STORAGE_QUERY_PROPERTY 는 정보를 묻기만 하는 요청이다. 디스크는 접근 권한 0(읽기·쓰기 없이)으로 연다.
_IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
_PROTOCOL_PROPERTY, _NVME, _NVME_LOG_PAGE, _HEALTH_LOG = 50, 3, 2, 2
_LOG_LEN = 512
_UNIT_BYTES = 512 * 1000                       # NVMe '데이터 단위' 하나 = 512바이트 × 1000
_CRITICAL_BITS = (
    (0, '예비 공간이 기준 아래로 줄었습니다', '주의'),
    (1, '온도가 기준을 벗어났습니다', '주의'),
    (2, '디스크가 신뢰성이 떨어졌다고 보고했습니다', '위험'),
    (3, '디스크가 읽기 전용으로 바뀌었습니다', '위험'),
    (4, '전원 손실 대비 백업 장치에 문제가 있습니다', '주의'),
)


def parse_nvme_health(d):
    """NVMe SMART/Health 로그(앞 192바이트 이상)를 값으로. 형식이 틀리면 None."""
    if not isinstance(d, (bytes, bytearray)) or len(d) < 192:
        return None

    def u128(o):
        return int.from_bytes(d[o:o + 16], 'little')
    kelvin = struct.unpack_from('<H', d, 1)[0]
    warn = d[0]
    return {
        'criticalWarning': warn,
        'warnings': [(text, level) for bit, text, level in _CRITICAL_BITS if warn & (1 << bit)],
        'temperatureC': kelvin - 273 if 273 < kelvin < 273 + 150 else None,
        'availableSparePct': d[3] if d[3] <= 100 else None,
        'spareThresholdPct': d[4] if d[4] <= 100 else None,
        'percentUsed': d[5],                     # 100 을 넘을 수 있다(예상 수명을 넘겨 쓴 경우, 최대 255)
        'dataReadBytes': u128(32) * _UNIT_BYTES,
        'dataWrittenBytes': u128(48) * _UNIT_BYTES,
        'powerCycles': u128(112),
        'powerOnHours': u128(128),
        'unsafeShutdowns': u128(144),
        'mediaErrors': u128(160),
        'errorLogEntries': u128(176),
    }


def _nvme_log(disk_number):
    r"""\\.\PhysicalDriveN 의 NVMe 건강 기록. 읽지 못하면 None(그때는 Windows 카운터 값만 쓴다)."""
    if not (isinstance(disk_number, str) and disk_number.isdigit() and int(disk_number) < 128):
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateFileW.restype = wt.HANDLE
        k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
        k.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, wt.LPVOID, wt.DWORD, wt.LPVOID, wt.DWORD,
                                      ctypes.POINTER(wt.DWORD), wt.LPVOID]
        k.CloseHandle.argtypes = [wt.HANDLE]
        # 접근 권한 0: 읽기·쓰기 권한 없이 정보만 묻는다. 공유 읽기·쓰기(3), OPEN_EXISTING(3)
        h = k.CreateFileW('\\\\.\\PhysicalDrive%d' % int(disk_number), 0, 3, None, 3, 0, None)
        if not h or h == wt.HANDLE(-1).value:
            return None
        try:
            buf = ctypes.create_string_buffer(8 + 40 + _LOG_LEN)
            struct.pack_into('<II', buf, 0, _PROTOCOL_PROPERTY, 0)          # PropertyStandardQuery
            struct.pack_into('<IIIIIIIIII', buf, 8, _NVME, _NVME_LOG_PAGE, _HEALTH_LOG, 0, 40, _LOG_LEN, 0, 0, 0, 0)
            got = wt.DWORD()
            if not k.DeviceIoControl(h, _IOCTL_STORAGE_QUERY_PROPERTY, buf, len(buf), buf, len(buf),
                                     ctypes.byref(got), None):
                return None
        finally:
            k.CloseHandle(h)
        offset, length = struct.unpack_from('<II', buf, 8 + 16)
        if offset != 40 or length < 192 or got.value < 8 + offset + 192:
            return None
        return parse_nvme_health(buf.raw[8 + offset: 8 + offset + min(length, _LOG_LEN)])
    except Exception as e:
        log.info(f'NVMe 건강 기록을 읽지 못했습니다(디스크 {disk_number}): {e}')
        return None


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
        'mediaErrors': None,
        'nvme': None,
        'warnings': [],
        'source': 'windows',
    }


_RANK = {'정상': 0, '알 수 없음': 0, '주의': 1, '위험': 2}


def _merge_nvme(row, n):
    """디스크가 직접 기록한 값으로 채운다(Windows 카운터가 비웠거나 다르게 준 값보다 정확하다)."""
    if not n:
        return row
    row['source'] = 'nvme'
    row['media'] = row['media'] or 'SSD'
    row['wearPct'] = n['percentUsed']
    row['powerOnHours'] = n['powerOnHours']
    if n['temperatureC'] is not None:
        row['temperatureC'] = n['temperatureC']
    row['mediaErrors'] = n['mediaErrors']
    row['readErrors'] = row['writeErrors'] = None     # 오류는 디스크 기록(복구하지 못한 데이터 오류) 하나로 본다
    row['warnings'] = [text for text, _ in n['warnings']]
    for _, level in n['warnings']:                     # 디스크가 경고를 켰으면 Windows 표시보다 낮게 두지 않는다
        if _RANK[level] > _RANK.get(row['health'], 0):
            row['health'] = level
    row['nvme'] = {k: n[k] for k in ('availableSparePct', 'spareThresholdPct', 'dataReadBytes', 'dataWrittenBytes',
                                     'powerCycles', 'unsafeShutdowns', 'errorLogEntries')}
    return row


def disk_health():
    """{'ok', 'disks': [...], 'error'}"""
    from backend.debloater import _run_ps_json
    try:
        ok, rows, err = _run_ps_json(_PS_DISKS, {}, QUERY_TIMEOUT_SEC)
    except Exception as e:                       # 시간 초과 등
        return {'ok': False, 'disks': [], 'error': f'디스크 정보를 읽지 못했습니다: {e}'}
    if not ok:
        return {'ok': False, 'disks': [], 'error': f'디스크 정보를 읽지 못했습니다: {err}'}
    disks = []
    for r in rows:
        row = _disk_row(r)
        if str(r.get('bus') or '').lower() == 'nvme':
            row = _merge_nvme(row, _nvme_log(row['id']))
        disks.append(row)
    disks.sort(key=lambda d: (d['id'].zfill(4), d['name']))
    return {'ok': True, 'disks': disks, 'error': None}


STALE_AFTER = timedelta(hours=1)        # 부팅 직후에는 Windows 가 아직 기록 중일 수 있다


def _parse_time(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def _dps_note(dps):
    return (f"부팅 시간은 Windows 의 '진단 정책 서비스(DPS)' 가 기록합니다. 이 서비스가 지금 실행 중이 아닙니다(상태: {dps}). "
            "Windows 의 서비스 앱(services.msc)에서 이 서비스를 시작하면 그 뒤 부팅부터 다시 기록됩니다.")


def _stale_note(newest, last_boot, dps, now=None):
    """마지막 기록 뒤에 기록되지 않은 부팅이 있으면 그 사실. 없으면 None."""
    if not newest or not last_boot:
        return None
    now = now or datetime.now(timezone.utc)
    if last_boot <= newest or now - last_boot < STALE_AFTER:
        return None
    text = (f"마지막 부팅({last_boot.astimezone().strftime('%Y-%m-%d %H:%M')})은 기록되지 않았습니다. "
            f"Windows 의 마지막 기록은 {newest.astimezone().strftime('%Y-%m-%d %H:%M')} 입니다.")
    if dps and dps.lower() != 'running':
        text += ' ' + _dps_note(dps)
    return text


def boot_history(count=15):
    """최근 부팅 시간(초). {'ok', 'boots': [{'at', 'seconds', 'mainPathSeconds'}], 'lastBoot', 'dps', 'stale', 'error'}
    새것부터. stale: 기록이 멈췄으면 그 사실(문장), 아니면 None."""
    from backend.debloater import _run_ps_json
    count = max(1, min(int(count), 50))
    try:
        ok, rows, err = _run_ps_json(_PS_BOOTS, {'count': count}, QUERY_TIMEOUT_SEC)
    except Exception as e:
        return {'ok': False, 'boots': [], 'error': f'부팅 기록을 읽지 못했습니다: {e}'}
    if not ok:
        return {'ok': False, 'boots': [], 'error': f'부팅 기록을 읽지 못했습니다: {err}'}
    meta = next((r for r in rows if r.get('kind') == 'meta'), {})
    boots = []
    for r in rows:
        if r.get('kind') == 'meta':
            continue
        ms = _num(r.get('bootMs'))
        if not ms or ms <= 0:
            continue
        main = _num(r.get('mainPathMs'))
        boots.append({'at': str(r.get('at') or ''), 'seconds': round(ms / 1000, 1),
                      'mainPathSeconds': round(main / 1000, 1) if main and main > 0 else None})
    last_boot = _parse_time(meta.get('lastBoot'))
    dps = str(meta.get('dps') or '') or None
    if boots:
        stale = _stale_note(_parse_time(boots[0]['at']), last_boot, dps)
    else:
        stale = _dps_note(dps) if dps and dps.lower() != 'running' else None
    out = {'ok': True, 'boots': boots, 'error': None, 'lastBoot': meta.get('lastBoot') or None,
           'dps': dps, 'stale': stale}
    if not boots:
        out['note'] = 'Windows 부팅 성능 기록이 없습니다(진단 로그가 꺼져 있거나 아직 기록된 부팅이 없음).'
    return out
