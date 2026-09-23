"""
APEX CARE — 저장공간 현황.

정크 정리·대용량 탐색·디스크 최적화가 흩어져 있어서 사용자가 '지금 내 디스크가
어떤 상태인지' 한눈에 볼 방법이 없었다. 이 모듈은 읽기만 한다. 아무것도 바꾸지 않는다.
"""

import logging
import os

import psutil

log = logging.getLogger('Storage')


# 매체 종류는 바뀌지 않는다. PowerShell 호출이 드라이브당 4초 가까이 걸려서
# 매번 조회하면 화면을 여는 데만 8초가 든다. 프로세스 수명 동안 캐시한다.
_media_cache = {}


def _media_type(mountpoint):
    """SSD 인지 HDD 인지 추정한다.

    조각모음은 HDD 에만 의미가 있고 SSD 에는 TRIM 이 맞다.
    Windows 의 defrag /O 는 알아서 구분하지만, 사용자에게도 알려줘야
    '왜 조각모음이 금방 끝났지?' 하는 오해가 없다.
    """
    if mountpoint in _media_cache:
        return _media_cache[mountpoint]
    result = _probe_media_type(mountpoint)
    _media_cache[mountpoint] = result
    return result


def _probe_media_type(mountpoint):
    try:
        import subprocess
        letter = os.path.splitdrive(mountpoint)[0].rstrip(':')
        if not letter:
            return 'unknown'
        # PowerShell 의 MSFT_PhysicalDisk 가 가장 정확하다
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f"(Get-Partition -DriveLetter {letter} -ErrorAction SilentlyContinue | "
             f"Get-Disk | Get-PhysicalDisk).MediaType"],
            capture_output=True, text=True, timeout=12,
            creationflags=0x08000000,
        )
        out = (r.stdout or '').strip().lower()
        if 'ssd' in out:
            return 'ssd'
        if 'hdd' in out:
            return 'hdd'
        if 'unspecified' in out:
            return 'unknown'
    except Exception as e:
        log.debug(f"매체 종류 조회 실패 {mountpoint}: {e}")
    return 'unknown'


def get_drives(detect_media=True):
    """로컬 드라이브별 용량. 네트워크·CD 드라이브는 제외한다."""
    drives = []
    for part in psutil.disk_partitions(all=False):
        try:
            if not part.fstype or 'cdrom' in (part.opts or ''):
                continue
            usage = psutil.disk_usage(part.mountpoint)
            drives.append({
                'mount': part.mountpoint,
                'label': os.path.splitdrive(part.mountpoint)[0] or part.mountpoint,
                'fstype': part.fstype,
                'totalGB': round(usage.total / 1024 ** 3, 1),
                'usedGB': round(usage.used / 1024 ** 3, 1),
                'freeGB': round(usage.free / 1024 ** 3, 1),
                'percent': usage.percent,
                'mediaType': _media_type(part.mountpoint) if detect_media else 'unknown',
                # 여유 공간이 10% 미만이면 Windows 자체가 느려지기 시작한다
                'low': usage.percent >= 90,
            })
        except PermissionError:
            continue
        except Exception as e:
            log.debug(f"드라이브 정보 실패 {part.mountpoint}: {e}")
    return drives


def get_overview():
    """저장공간 탭 상단에 띄울 요약."""
    drives = get_drives()
    total = sum(d['totalGB'] for d in drives)
    free = sum(d['freeGB'] for d in drives)
    return {
        'drives': drives,
        'totalGB': round(total, 1),
        'freeGB': round(free, 1),
        'usedGB': round(total - free, 1),
        'percent': round((total - free) / total * 100, 1) if total else 0,
        'lowDrives': [d['label'] for d in drives if d['low']],
    }
