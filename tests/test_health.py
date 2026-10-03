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
