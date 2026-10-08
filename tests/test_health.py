"""PC 건강 진단·네트워크 속도: 읽기만 하고, Windows 가 알려 주지 않은 값은 지어내지 않는다."""

import os
import re
import types

import pytest

from backend import debloater, health, system_monitor
from tests.conftest import ROOT


def test_scripts_only_read():
    for body in (health._PS_DISKS, health._PS_BOOTS):
        assert not re.search(r'\b(Set|Remove|New|Clear|Reset|Repair|Optimize|Initialize|Format)-', body)


def test_disk_values_the_disk_does_not_report_stay_unknown(monkeypatch):
    rows = [
        {'id': '1', 'name': 'WD Blue', 'media': 'HDD', 'bus': 'SATA', 'sizeBytes': 1000204886016, 'health': 'Healthy',
         'status': 'OK', 'letters': ['D:'], 'temperature': 0, 'wear': 0, 'powerOnHours': 0,
         'readErrors': None, 'writeErrors': None},
        {'id': '0', 'name': 'Samsung 980', 'media': 'SSD', 'bus': 'NVMe', 'sizeBytes': 500107862016, 'health': 'Warning',
         'status': 'Degraded', 'letters': ['C:'], 'temperature': 41, 'temperatureMax': 82, 'wear': 7,
         'powerOnHours': 4321, 'readErrors': 0, 'writeErrors': 2},
    ]
    monkeypatch.setattr(debloater, '_run_ps_json', lambda body, arg, timeout: (True, rows, None))
    r = health.disk_health()
    assert r['ok'] and [d['id'] for d in r['disks']] == ['0', '1']              # 디스크 번호 순
    ssd, hdd = r['disks']
    assert ssd['health'] == '주의' and ssd['wearPct'] == 7 and ssd['temperatureC'] == 41 and ssd['writeErrors'] == 2
    assert ssd['powerOnHours'] == 4321 and ssd['letters'] == ['C:'] and ssd['sizeGB'] == 465.8
    # HDD 의 0 은 '닳지 않음·0도·0시간' 이 아니라 '알려 주지 않음'
    assert hdd['wearPct'] is None and hdd['temperatureC'] is None and hdd['powerOnHours'] is None
    assert hdd['readErrors'] is None and hdd['health'] == '정상'


def test_disk_query_failure_is_reported_not_hidden(monkeypatch):
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (False, [], '권한이 없습니다'))
    r = health.disk_health()
    assert r['ok'] is False and '권한이 없습니다' in r['error'] and r['disks'] == []

    def slow(*a):
        import subprocess
        raise subprocess.TimeoutExpired('powershell', 60)
    monkeypatch.setattr(debloater, '_run_ps_json', slow)
    assert health.disk_health()['ok'] is False


def test_boot_history_uses_windows_measurements(monkeypatch):
    seen = {}

    def fake(body, arg, timeout):
        seen.update(arg)
        return True, [{'at': '2026-10-03T09:00:00', 'bootMs': '23456', 'mainPathMs': '15000'},
                      {'at': '2026-10-02T09:00:00', 'bootMs': '0'},                      # 잘못 기록된 부팅
                      {'at': '2026-10-01T09:00:00', 'bootMs': '31000', 'mainPathMs': None}], None
    monkeypatch.setattr(debloater, '_run_ps_json', fake)
    r = health.boot_history(count=999)
    assert seen == {'count': 50}                                               # 너무 많이 묻지 않는다
    assert [b['seconds'] for b in r['boots']] == [23.5, 31.0] and r['boots'][0]['mainPathSeconds'] == 15.0

    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (True, [], None))
    r = health.boot_history()
    assert r['ok'] and r['boots'] == [] and '기록이 없습니다' in r['note']        # 없다고 말한다(0초로 그리지 않는다)


def test_network_speed_is_measured_between_samples(monkeypatch):
    t = [100.0]
    counters = {'이더넷': types.SimpleNamespace(bytes_recv=1000, bytes_sent=500),
                'Loopback Pseudo-Interface 1': types.SimpleNamespace(bytes_recv=10 ** 9, bytes_sent=10 ** 9)}
    monkeypatch.setattr(system_monitor.time, 'monotonic', lambda: t[0])
    monkeypatch.setattr(system_monitor.psutil, 'net_io_counters', lambda pernic=False: dict(counters))
    monkeypatch.setattr(system_monitor, '_net_last', {})

    assert system_monitor.net_rates() == (None, None)                          # 첫 표본: 아직 모른다
    counters['이더넷'] = types.SimpleNamespace(bytes_recv=1000 + 4 * 1024 ** 2, bytes_sent=500 + 2048)
    counters['Loopback Pseudo-Interface 1'] = types.SimpleNamespace(bytes_recv=2 * 10 ** 9, bytes_sent=2 * 10 ** 9)
    t[0] = 102.0
    down, up = system_monitor.net_rates()
    assert down == 2 * 1024 ** 2 and up == 1024                                # 루프백은 빼고 2초로 나눈다
    t[0] = 102.2                                                               # 너무 짧은 간격: 직전 값
    assert system_monitor.net_rates() == (down, up)
    counters['이더넷'] = types.SimpleNamespace(bytes_recv=0, bytes_sent=0)      # 어댑터가 빠져 카운터가 줄었다
    t[0] = 104.0
    assert system_monitor.net_rates() == (0, 0)


def test_health_tab_and_network_chip_are_on_screen():
    side = open(os.path.join(ROOT, 'src', 'components', 'Sidebar.jsx'), encoding='utf-8').read()
    app = open(os.path.join(ROOT, 'src', 'App.jsx'), encoding='utf-8').read()
    hc = open(os.path.join(ROOT, 'src', 'components', 'HealthCenter.jsx'), encoding='utf-8').read()
    hdr = open(os.path.join(ROOT, 'src', 'components', 'Header.jsx'), encoding='utf-8').read()
    assert "id: 'health'" in side and '<HealthCenter active=' in app
    assert '디스크가 알려 주지 않음' in hc and 'getDiskHealth' in hc and 'getBootHistory' in hc
    assert 'stats.netDownBps' in hdr and "'측정 중'" in hdr
    spec = open(os.path.join(ROOT, 'APEX CARE Payload.spec'), encoding='utf-8').read()
    assert "'backend.health'" in spec and "'backend.window_icon'" in spec


def _nvme_log_bytes(warn=0, kelvin=310, spare=100, threshold=10, used=13, written=119159289, hours=29372,
                    cycles=1305, unsafe=23, media=0, errlog=1):
    d = bytearray(512)
    d[0] = warn
    d[1:3] = kelvin.to_bytes(2, 'little')
    d[3], d[4], d[5] = spare, threshold, used
    for off, v in ((48, written), (112, cycles), (128, hours), (144, unsafe), (160, media), (176, errlog)):
        d[off:off + 16] = v.to_bytes(16, 'little')
    return bytes(d)


def test_nvme_health_log_is_decoded_as_the_disk_recorded_it():
    # 실측(WDC SN570, 2026-10-04): Windows 카운터는 수명 0%·사용 시간·오류 없음, 디스크 기록은 13%·29372시간·0건
    n = health.parse_nvme_health(_nvme_log_bytes())
    assert n['percentUsed'] == 13 and n['powerOnHours'] == 29372 and n['temperatureC'] == 37
    assert n['dataWrittenBytes'] == 119159289 * 512000 and n['powerCycles'] == 1305 and n['unsafeShutdowns'] == 23
    assert n['mediaErrors'] == 0 and n['errorLogEntries'] == 1 and n['warnings'] == []
    assert health.parse_nvme_health(b'\x00' * 100) is None
    assert health.parse_nvme_health(_nvme_log_bytes(kelvin=0))['temperatureC'] is None     # 0K = 알려 주지 않음
    w = health.parse_nvme_health(_nvme_log_bytes(warn=0b1100))['warnings']
    assert [lvl for _, lvl in w] == ['위험', '위험']


def test_nvme_disks_use_the_disk_record_over_windows_counters(monkeypatch):
    rows = [{'id': '1', 'name': 'WDC', 'media': 'SSD', 'bus': 'NVMe', 'sizeBytes': 500107862016, 'health': 'Healthy',
             'letters': ['C:'], 'temperature': 38, 'temperatureMax': 80, 'wear': 0, 'powerOnHours': None,
             'readErrors': None, 'writeErrors': None},
            {'id': '2', 'name': 'NVMe 읽기 실패', 'media': 'SSD', 'bus': 'NVMe', 'health': 'Healthy', 'wear': 4},
            {'id': '3', 'name': '경고 켠 디스크', 'media': 'SSD', 'bus': 'NVMe', 'health': 'Healthy'}]
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (True, rows, None))
    logs = {'1': health.parse_nvme_health(_nvme_log_bytes()), '2': None,
            '3': health.parse_nvme_health(_nvme_log_bytes(warn=0b1000))}
    asked = []
    monkeypatch.setattr(health, '_nvme_log', lambda n: asked.append(n) or logs[n])
    d1, d2, d3 = health.disk_health()['disks']
    assert asked == ['1', '2', '3']
    assert d1['source'] == 'nvme' and d1['wearPct'] == 13 and d1['powerOnHours'] == 29372 and d1['mediaErrors'] == 0
    assert d1['nvme']['unsafeShutdowns'] == 23 and d1['health'] == '정상'
    # 디스크 기록을 못 읽으면 Windows 값 그대로(지어내지 않는다)
    assert d2['source'] == 'windows' and d2['wearPct'] == 4 and d2['powerOnHours'] is None and d2['mediaErrors'] is None
    # 디스크가 읽기 전용 경고를 켰으면 Windows 가 '정상' 이라 해도 위험으로 보인다
    assert d3['health'] == '위험' and d3['warnings'] == ['디스크가 읽기 전용으로 바뀌었습니다']


def test_nvme_reader_refuses_odd_disk_numbers_and_survives_blocked_calls():
    assert health._nvme_log('../x') is None and health._nvme_log('999') is None
    assert health._nvme_log('0') is None                          # fakewin 이 ctypes 를 막는다 → 예외 없이 None
    assert 'GENERIC_WRITE' not in open(health.__file__, encoding='utf-8').read()


def test_boot_log_that_stopped_recording_is_said_out_loud(monkeypatch):
    # 실측(2026-10-04): 마지막 기록 7월 17일, 마지막 부팅 10월 3일, 진단 정책 서비스(DPS) 중지
    rows = [{'kind': 'meta', 'lastBoot': '2026-10-03T14:41:00+09:00', 'dps': 'Stopped'},
            {'kind': 'boot', 'at': '2026-07-17T11:49:00+09:00', 'bootMs': '73100'}]
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (True, rows, None))
    r = health.boot_history()
    assert [b['seconds'] for b in r['boots']] == [73.1]                   # meta 줄은 부팅이 아니다
    assert '2026-10-03' in r['stale'] and '2026-07-17' in r['stale'] and '진단 정책 서비스' in r['stale']
    assert r['dps'] == 'Stopped'

    rows[0].update(lastBoot='2026-07-17T11:40:00+09:00', dps='Running')    # 기록된 부팅이 마지막 부팅
    assert health.boot_history()['stale'] is None

    rows[0].update(lastBoot='2026-10-03T14:41:00+09:00')                    # 서비스는 도는데 기록이 빠짐
    r = health.boot_history()
    assert '기록되지 않았습니다' in r['stale'] and '진단 정책 서비스' not in r['stale']

    # 방금 부팅했으면 Windows 가 아직 기록 중일 수 있다
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 3, 5, 50, tzinfo=timezone.utc)
    assert health._stale_note(health._parse_time('2026-07-17T11:49:00+09:00'),
                              health._parse_time('2026-10-03T14:41:00+09:00'), 'Running', now=now) is None
    assert health._stale_note(None, now, 'Stopped') is None

    rows[:] = [{'kind': 'meta', 'lastBoot': None, 'dps': 'Stopped'}]       # 기록이 하나도 없고 서비스가 멈춤
    r = health.boot_history()
    assert r['boots'] == [] and '진단 정책 서비스' in r['stale'] and r['note']


def test_health_tab_shows_disk_record_facts_and_stale_boot_log():
    hc = open(os.path.join(ROOT, 'src', 'components', 'HealthCenter.jsx'), encoding='utf-8').read()
    assert 'd.mediaErrors' in hc and 'n.unsafeShutdowns' in hc and 'boots.stale' in hc
    assert "'기록된 마지막 부팅'" in hc and '디스크 경고' in hc


def _ata_page(number, entries):
    """장치 통계 페이지 하나. entries: {오프셋: 값 또는 (값, 지원, 유효)}"""
    d = bytearray(512)
    d[0:2] = (1).to_bytes(2, 'little')
    d[2] = number
    for off, v in entries.items():
        value, supported, valid = (v if isinstance(v, tuple) else (v, True, True))
        q = (value & ((1 << 48) - 1)) | (int(supported) << 63) | (int(valid) << 62)
        d[off:off + 8] = q.to_bytes(8, 'little')
    return bytes(d)


def test_ata_device_statistics_are_read_only_when_supported_and_valid():
    pages = {
        1: _ata_page(1, {0x08: 812, 0x10: 15321, 0x18: 2_000_000_000, 0x28: (5, True, False)}),   # 읽은 양: 유효하지 않음
        3: _ata_page(3, {0x20: 8, 0x38: 0}),
        4: _ata_page(4, {0x08: 2}),
        5: _ata_page(5, {0x08: 0xFE, 0x58: 60}),       # -2 °C 가 아니라 부호 있는 8비트: 0xFE = -2
        7: _ata_page(7, {0x08: (0, False, False)}),     # SSD 수명: 지원하지 않음(HDD)
    }
    a = health.parse_ata_stats(pages, sector_bytes=512)
    assert a['powerCycles'] == 812 and a['powerOnHours'] == 15321
    assert a['dataWrittenBytes'] == 2_000_000_000 * 512 and a['dataReadBytes'] is None
    assert a['reallocatedSectors'] == 8 and a['pendingSectors'] == 0 and a['mediaErrors'] == 2
    assert a['temperatureC'] == -2 and a['temperatureMaxC'] == 60 and a['percentUsed'] is None
    assert [lvl for _, lvl in a['warnings']] == ['주의'] and '재할당' in a['warnings'][0][0]
    # 페이지 번호가 요청과 다르거나 개정 번호가 틀리면 그 페이지는 쓰지 않는다
    bad = dict(pages)
    bad[1] = _ata_page(2, {0x10: 99})
    assert health.parse_ata_stats(bad)['powerOnHours'] is None
    assert health.parse_ata_stats({}) is None and health.parse_ata_stats({1: b'\x00' * 512}) is None
    # 섹터 크기를 모르면 쓴 양을 지어내지 않는다
    assert health.parse_ata_stats(pages, sector_bytes=None)['dataWrittenBytes'] is None


def test_sata_disks_use_device_statistics(monkeypatch):
    rows = [{'id': '2', 'name': 'WDC WD20EZRZ', 'media': 'HDD', 'bus': 'SATA', 'health': 'Healthy',
             'logicalSector': 512, 'serial': ' WD-123 ', 'wear': 0, 'powerOnHours': None}]
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (True, rows, None))
    stats = health.parse_ata_stats({1: _ata_page(1, {0x10: 40000}), 3: _ata_page(3, {0x20: 3, 0x38: 1}),
                                    4: _ata_page(4, {0x08: 0}), 7: _ata_page(7, {0x08: 50})})
    asked = []
    monkeypatch.setattr(health, '_ata_stats', lambda n, s: asked.append((n, s)) or stats)
    d = health.disk_health()['disks'][0]
    assert asked == [('2', 512)] and d['source'] == 'ata' and d['serial'] == 'WD-123'
    assert d['powerOnHours'] == 40000 and d['mediaErrors'] == 0
    assert d['wearPct'] is None                                   # HDD 에 SSD 수명 값이 와도 쓰지 않는다
    assert d['health'] == '주의' and len(d['warnings']) == 2 and d['ata']['reallocatedSectors'] == 3
