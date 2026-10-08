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

import json
import logging
import os
import struct
import tempfile
import threading
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
    letters = $letters; serial = ([string]$d.SerialNumber).Trim(); logicalSector = [int64]$d.LogicalSectorSize
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


def _protocol_query(disk_number, protocol, data_type, value, sub_value, length=_LOG_LEN):
    r"""\\.\PhysicalDriveN 에 프로토콜별 정보(로그 페이지 등)를 묻는다. 받은 바이트 또는 None.

    IOCTL_STORAGE_QUERY_PROPERTY(StorageDeviceProtocolSpecificProperty)는 정보를 묻기만 한다. 디스크는 접근 권한 0 으로 연다.
    """
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
            buf = ctypes.create_string_buffer(8 + 40 + length)
            struct.pack_into('<II', buf, 0, _PROTOCOL_PROPERTY, 0)          # PropertyStandardQuery
            struct.pack_into('<IIIIIIIIII', buf, 8, protocol, data_type, value, sub_value, 40, length, 0, 0, 0, 0)
            got = wt.DWORD()
            if not k.DeviceIoControl(h, _IOCTL_STORAGE_QUERY_PROPERTY, buf, len(buf), buf, len(buf),
                                     ctypes.byref(got), None):
                return None
        finally:
            k.CloseHandle(h)
        offset, got_len = struct.unpack_from('<II', buf, 8 + 16)
        if offset != 40 or got_len < 192 or got.value < 8 + offset + 192:
            return None
        return buf.raw[8 + offset: 8 + offset + min(got_len, length)]
    except Exception as e:
        log.info(f'디스크 {disk_number} 의 정보를 읽지 못했습니다: {e}')
        return None


def _nvme_log(disk_number):
    """NVMe 건강 기록. 읽지 못하면 None(그때는 Windows 카운터 값만 쓴다)."""
    return parse_nvme_health(_protocol_query(disk_number, _NVME, _NVME_LOG_PAGE, _HEALTH_LOG, 0))


# ── SATA(ATA) 장치 통계(Device Statistics 로그, 로그 주소 04h) ──────────
# ACS 표준 로그라 제조사마다 뜻이 다른 SMART 속성과 달리 항목 위치·단위가 정해져 있다. 항목마다 '지원함'(63번 비트)과
# '값이 유효함'(62번 비트)이 붙어 있어, 둘 다 켜진 값만 쓴다. 페이지 머리의 페이지 번호가 요청과 다르면 쓰지 않는다.
_ATA, _ATA_LOG_PAGE, _DEVICE_STATS = 2, 2, 0x04
_ATA_PAGES = (1, 3, 4, 5, 7)


def _stat(page, offset, bits=48, signed=False):
    """장치 통계 항목 하나(8바이트). 지원하지 않거나 값이 유효하지 않으면 None."""
    if not page or offset + 8 > len(page):
        return None
    q = int.from_bytes(page[offset:offset + 8], 'little')
    if not (q >> 63) & 1 or not (q >> 62) & 1:
        return None
    v = q & ((1 << bits) - 1)
    if signed and v >= 1 << (bits - 1):
        v -= 1 << bits
    return v


def _page_ok(page, number):
    """페이지 머리: 0~1바이트 개정 번호(1), 2바이트 페이지 번호."""
    return (isinstance(page, (bytes, bytearray)) and len(page) >= 16
            and int.from_bytes(page[0:2], 'little') == 1 and page[2] == number)


def parse_ata_stats(pages, sector_bytes=512):
    """{페이지 번호: 512바이트} → 값. 쓸 수 있는 페이지가 없으면 None."""
    p = {n: d for n, d in (pages or {}).items() if _page_ok(d, n)}
    if not p:
        return None
    sector = sector_bytes if isinstance(sector_bytes, int) and sector_bytes in (512, 4096) else None
    written, read = _stat(p.get(1), 0x18), _stat(p.get(1), 0x28)
    temp = _stat(p.get(5), 0x08, bits=8, signed=True)
    temp_max = _stat(p.get(5), 0x58, bits=8, signed=True)
    used = _stat(p.get(7), 0x08, bits=8)
    realloc, pending = _stat(p.get(3), 0x20, bits=32), _stat(p.get(3), 0x38, bits=32)
    warnings = []
    if realloc:
        warnings.append((f'손상된 영역 {realloc:,}곳을 예비 영역으로 바꿨습니다(재할당 섹터)', '주의'))
    if pending:
        warnings.append((f'읽기 어려운 영역 {pending:,}곳이 재할당을 기다립니다(대기 섹터)', '주의'))
    return {
        'powerCycles': _stat(p.get(1), 0x08, bits=32),
        'powerOnHours': _stat(p.get(1), 0x10, bits=32),
        'dataWrittenBytes': written * sector if written is not None and sector else None,
        'dataReadBytes': read * sector if read is not None and sector else None,
        'reallocatedSectors': realloc,
        'pendingSectors': pending,
        'mediaErrors': _stat(p.get(4), 0x08, bits=32),         # 보고된 복구 불가 오류 수
        'temperatureC': temp if temp is not None and -40 < temp < 150 else None,
        'temperatureMaxC': temp_max if temp_max is not None and 0 < temp_max < 150 else None,
        'percentUsed': used if used is not None and used <= 255 else None,
        'warnings': warnings,
    }


def _ata_stats(disk_number, sector_bytes=512):
    """SATA 디스크의 장치 통계. 읽지 못하면 None."""
    head = _protocol_query(disk_number, _ATA, _ATA_LOG_PAGE, _DEVICE_STATS, 0)
    if not _page_ok(head, 0):
        return None
    count = head[8]
    listed = set(head[9:9 + count])                        # 지원하는 페이지 번호 목록
    pages = {}
    for n in _ATA_PAGES:
        if n in listed:
            pages[n] = _protocol_query(disk_number, _ATA, _ATA_LOG_PAGE, _DEVICE_STATS, n)
    return parse_ata_stats(pages, sector_bytes)


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
        'ata': None,
        'warnings': [],
        'source': 'windows',
        'serial': str(r.get('serial') or '').strip() or None,
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


def _merge_ata(row, a):
    """SATA 디스크의 장치 통계로 채운다. 디스크가 알려 준 항목만 바꾼다(없는 항목은 Windows 값 그대로)."""
    if not a:
        return row
    row['source'] = 'ata'
    if a['powerOnHours'] is not None:
        row['powerOnHours'] = a['powerOnHours']
    if a['temperatureC'] is not None:
        row['temperatureC'] = a['temperatureC']
    if a['temperatureMaxC'] is not None:
        row['temperatureMaxC'] = a['temperatureMaxC']
    if a['percentUsed'] is not None and row['media'] != 'HDD':
        row['wearPct'] = a['percentUsed']
        row['media'] = row['media'] or 'SSD'
    if a['mediaErrors'] is not None:
        row['mediaErrors'] = a['mediaErrors']
        row['readErrors'] = row['writeErrors'] = None
    row['warnings'] = [text for text, _ in a['warnings']]
    for _, level in a['warnings']:
        if _RANK[level] > _RANK.get(row['health'], 0):
            row['health'] = level
    row['ata'] = {k: a[k] for k in ('powerCycles', 'dataWrittenBytes', 'dataReadBytes',
                                    'reallocatedSectors', 'pendingSectors')}
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
        bus = str(r.get('bus') or '').lower()
        if bus == 'nvme':
            row = _merge_nvme(row, _nvme_log(row['id']))
        elif bus in ('sata', 'ata'):
            sector = r.get('logicalSector') if isinstance(r.get('logicalSector'), int) else 512
            row = _merge_ata(row, _ata_stats(row['id'], sector))
        disks.append(row)
    disks.sort(key=lambda d: (d['id'].zfill(4), d['name']))
    try:
        _attach_trends(disks)
    except Exception as e:                       # 추세는 덧붙이는 정보다. 못 붙여도 건강 값은 그대로 보여 준다
        log.warning(f'디스크 기록을 남기거나 읽지 못했습니다: {e}')
    return {'ok': True, 'disks': disks, 'error': None}


# ── 디스크 수명 추세 ─────────────────────────────────
# 하루에 한 번 디스크(일련번호로 구분)의 쓴 양·수명 사용량·사용 시간을 남겨, 기록 기간 동안 하루 평균 쓴 양과
# 수명 사용량 변화를 보여 준다. 수명 사용량이 1% 이상 오르기 전에는 남은 기간을 계산하지 않는다(1% 단위라 짧은 기간은 의미가 없다).
HISTORY_NAME = 'disk_history.json'
HISTORY_MAX = 400                     # 디스크마다 최대 날짜 수
TREND_MIN_DAYS = 3
WEAR_MIN_DAYS = 30
_history_lock = threading.Lock()


def _history_path():
    from backend import config_manager
    return os.path.join(config_manager.APPDATA_DIR, HISTORY_NAME)


def _load_history():
    try:
        with open(_history_path(), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_history(data):
    path = _history_path()
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix='disk_history.', suffix='.tmp', dir=os.path.dirname(path))
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)                    # 이 함수가 만든 임시 파일만 지운다


def _written_of(d):
    for k in ('nvme', 'ata'):
        v = (d.get(k) or {}).get('dataWrittenBytes')
        if isinstance(v, (int, float)):
            return v
    return None


def trend_of(entries):
    """[{date, written, used, hours}] (날짜 순) → 추세. 기록이 짧으면 {'since', 'days', 'enough': False}."""
    entries = [e for e in entries if isinstance(e, dict) and isinstance(e.get('date'), str)]
    if not entries:
        return None
    first, last = entries[0], entries[-1]
    try:
        days = (datetime.fromisoformat(last['date']) - datetime.fromisoformat(first['date'])).days
    except ValueError:
        return None
    out = {'since': first['date'], 'days': days, 'enough': days >= TREND_MIN_DAYS,
           'writtenPerDayBytes': None, 'usedFrom': first.get('used'), 'usedTo': last.get('used'), 'yearsTo100': None}
    if not out['enough']:
        return out
    w0, w1 = first.get('written'), last.get('written')
    if isinstance(w0, (int, float)) and isinstance(w1, (int, float)) and w1 >= w0:
        out['writtenPerDayBytes'] = (w1 - w0) / days
    u0, u1 = first.get('used'), last.get('used')
    if isinstance(u0, (int, float)) and isinstance(u1, (int, float)) and u1 > u0 and days >= WEAR_MIN_DAYS and u1 < 100:
        per_day = (u1 - u0) / days
        out['yearsTo100'] = round((100 - u1) / per_day / 365, 1)
    return out


def _attach_trends(disks, today=None):
    today = today or datetime.now().date().isoformat()
    with _history_lock:
        data = _load_history()
        changed = False
        for d in disks:
            key = d.get('serial')
            if not key:
                continue
            entry = {'date': today, 'written': _written_of(d), 'used': d.get('wearPct'), 'hours': d.get('powerOnHours')}
            if entry['written'] is None and entry['used'] is None:
                continue                              # 남길 값이 없다(Windows 카운터만 있는 디스크)
            rows = [e for e in data.get(key, []) if isinstance(e, dict)]
            if rows and rows[-1].get('date') == today:
                rows[-1] = entry                      # 하루에 하나(그날의 마지막 값)
            else:
                rows.append(entry)
            rows = rows[-HISTORY_MAX:]
            if data.get(key) != rows:
                data[key] = rows
                changed = True
            d['trend'] = trend_of(rows)
        if changed:
            _save_history(data)


# ── 노트북 배터리 ─────────────────────────────────────
# Windows 가 배터리에서 읽은 설계 용량·완전 충전 용량·충전 횟수(WMI root\wmi). 읽기만 한다.
_PS_BATTERY = r"""
$present = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
$static = @(); $full = @(); $cycle = @()
try { $static = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData -ErrorAction Stop) } catch {}
try { $full = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity -ErrorAction Stop) } catch {}
try { $cycle = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryCycleCount -ErrorAction Stop) } catch {}
$n = [Math]::Max($present.Count, $static.Count)
for ($i = 0; $i -lt $n; $i++) {
  [void]$out.Add([ordered]@{
    name = $(if ($i -lt $static.Count) { [string]$static[$i].DeviceName } elseif ($i -lt $present.Count) { [string]$present[$i].Name } else { '' })
    maker = $(if ($i -lt $static.Count) { [string]$static[$i].ManufactureName } else { '' })
    designed = $(if ($i -lt $static.Count) { [int64]$static[$i].DesignedCapacity } else { $null })
    full = $(if ($i -lt $full.Count) { [int64]$full[$i].FullChargedCapacity } else { $null })
    cycles = $(if ($i -lt $cycle.Count) { [int64]$cycle[$i].CycleCount } else { $null })
    charge = $(if ($i -lt $present.Count) { $present[$i].EstimatedChargeRemaining } else { $null })
  })
}
"""


def _battery_row(r):
    designed, full = _num(r.get('designed')), _num(r.get('full'))
    cycles, charge = _num(r.get('cycles')), _num(r.get('charge'))
    health = None
    if designed and full and designed > 0 and 0 < full <= designed * 1.5:
        health = round(full / designed * 100)
    return {
        'name': str(r.get('name') or '').strip() or '배터리',
        'maker': str(r.get('maker') or '').strip() or None,
        'designedMWh': int(designed) if designed else None,
        'fullMWh': int(full) if full else None,
        'healthPct': health,
        # 0 회는 새 배터리일 수도 있지만, 많은 배터리가 알려 주지 않을 때 0 을 준다. 모른다고 둔다.
        'cycles': int(cycles) if cycles and cycles > 0 else None,
        'chargePct': int(charge) if charge is not None and 0 <= charge <= 100 else None,
    }


def battery():
    """{'ok', 'batteries': [...], 'error'}. 배터리가 없는 PC 는 빈 목록."""
    from backend.debloater import _run_ps_json
    try:
        ok, rows, err = _run_ps_json(_PS_BATTERY, {}, QUERY_TIMEOUT_SEC)
    except Exception as e:
        return {'ok': False, 'batteries': [], 'error': f'배터리 정보를 읽지 못했습니다: {e}'}
    if not ok:
        return {'ok': False, 'batteries': [], 'error': f'배터리 정보를 읽지 못했습니다: {err}'}
    return {'ok': True, 'batteries': [_battery_row(r) for r in rows], 'error': None}


# ── 시작 프로그램을 바꾼 뒤 부팅 시간 ──────────────────
STARTUP_LOG_KEY = 'startup_changes'
STARTUP_LOG_MAX = 50


def record_startup_change(name, enabled):
    """시작 프로그램을 켜고 끈 시각을 남긴다(부팅 시간 비교용). 실패해도 켜고 끈 결과에는 영향이 없다."""
    from backend import config_manager
    entry = {'at': datetime.now().astimezone().isoformat(timespec='seconds'), 'name': str(name)[:200],
             'enabled': bool(enabled)}

    def add(c):
        log_ = c.get(STARTUP_LOG_KEY)
        log_ = [x for x in log_ if isinstance(x, dict)] if isinstance(log_, list) else []
        c[STARTUP_LOG_KEY] = (log_ + [entry])[-STARTUP_LOG_MAX:]
    return config_manager.update_config(add)


def startup_effect(boots, changes):
    """마지막 시작 프로그램 변경 전후의 부팅 시간 평균. 비교할 수 없으면 None.

    boots: [{'at', 'seconds'}] 새것부터. changes: record_startup_change 기록(오래된 것부터).
    마지막 변경 직전 묶음(같은 날 여러 번 바꾼 것)을 한 번의 변경으로 본다.
    """
    times = [(_parse_time(c.get('at')), c) for c in changes or [] if isinstance(c, dict)]
    times = [(t, c) for t, c in times if t]
    if not times:
        return None
    last_t = max(t for t, _ in times)
    batch = [c for t, c in times if last_t - t <= timedelta(hours=12)]
    first_t = min(t for t, c in times if last_t - t <= timedelta(hours=12))
    timed = [(_parse_time(b.get('at')), b.get('seconds')) for b in boots or []]
    before = [s for t, s in timed if t and t < first_t and isinstance(s, (int, float))][:5]
    after = [s for t, s in timed if t and t > last_t and isinstance(s, (int, float))]
    out = {'changedAt': last_t.isoformat(), 'count': len(batch),
           'disabled': sum(1 for c in batch if not c.get('enabled')),
           'enabled': sum(1 for c in batch if c.get('enabled')),
           'beforeN': len(before), 'afterN': len(after),
           'beforeAvg': round(sum(before) / len(before), 1) if before else None,
           'afterAvg': round(sum(after) / len(after), 1) if after else None}
    return out if before else None


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
    try:
        from backend import config_manager
        changes = config_manager.load_config().get(STARTUP_LOG_KEY)
        effect = startup_effect(boots, changes if isinstance(changes, list) else [])
    except Exception as e:
        log.info(f'시작 프로그램 변경 기록을 읽지 못했습니다: {e}')
        effect = None
    out = {'ok': True, 'boots': boots, 'error': None, 'lastBoot': meta.get('lastBoot') or None,
           'dps': dps, 'stale': stale, 'startupEffect': effect}
    if not boots:
        out['note'] = 'Windows 부팅 성능 기록이 없습니다(진단 로그가 꺼져 있거나 아직 기록된 부팅이 없음).'
    return out
