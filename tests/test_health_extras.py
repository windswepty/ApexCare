"""PC 건강 진단의 추가 기능: 디스크 수명 추세·배터리·시작 프로그램 변경 전후 부팅 시간·보고서. 모두 읽기만 한다."""

import json
import os

from backend import config_manager, debloater, health, optimizer, report
from backend.api import Api
from tests.conftest import ROOT


def test_trend_needs_enough_days_and_a_real_wear_change():
    assert health.trend_of([]) is None
    t = health.trend_of([{'date': '2026-10-01', 'written': 100, 'used': 13}, {'date': '2026-10-02', 'written': 200, 'used': 13}])
    assert t['enough'] is False and t['writtenPerDayBytes'] is None                  # 하루로는 평균을 내지 않는다
    tb = 1e12
    t = health.trend_of([{'date': '2026-01-01', 'written': 50 * tb, 'used': 10},
                         {'date': '2026-01-11', 'written': 51 * tb, 'used': 10}])
    assert t['enough'] and t['writtenPerDayBytes'] == 0.1 * tb and t['yearsTo100'] is None   # 수명이 그대로면 남은 기간 없음
    t = health.trend_of([{'date': '2025-01-01', 'written': 0, 'used': 10},
                         {'date': '2026-01-01', 'written': 0, 'used': 12}])
    assert t['yearsTo100'] == round(88 / (2 / 365) / 365, 1)                          # 1년에 2% → 약 44년
    t = health.trend_of([{'date': '2026-01-01', 'used': 10}, {'date': '2026-01-20', 'used': 11}])
    assert t['yearsTo100'] is None                                                    # 30일이 안 되면 계산하지 않는다


def test_history_keeps_one_entry_per_day_per_disk(monkeypatch):
    disks = [{'serial': 'S1', 'wearPct': 13, 'powerOnHours': 10, 'nvme': {'dataWrittenBytes': 1000}},
             {'serial': None, 'wearPct': 5},                                    # 일련번호가 없으면 남기지 않는다
             {'serial': 'S2', 'wearPct': None, 'nvme': None, 'ata': None}]     # 남길 값이 없다
    health._attach_trends(disks, today='2026-10-01')
    disks[0]['nvme']['dataWrittenBytes'] = 2000
    health._attach_trends(disks, today='2026-10-01')                           # 같은 날 다시: 덮어쓴다
    health._attach_trends(disks, today='2026-10-05')
    data = json.load(open(health._history_path(), encoding='utf-8'))
    assert list(data) == ['S1'] and [e['date'] for e in data['S1']] == ['2026-10-01', '2026-10-05']
    assert data['S1'][0]['written'] == 2000 and disks[0]['trend']['days'] == 4 and disks[0]['trend']['enough']
    assert 'trend' not in disks[1]


def test_battery_values_are_only_what_the_battery_reports(monkeypatch):
    rows = [{'name': 'DELL 1VX1H', 'maker': 'SMP', 'designed': 56000, 'full': 47600, 'cycles': 312, 'charge': 81},
            {'name': '', 'designed': 0, 'full': 40000, 'cycles': 0, 'charge': None}]
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (True, rows, None))
    b1, b2 = health.battery()['batteries']
    assert b1['healthPct'] == 85 and b1['cycles'] == 312 and b1['chargePct'] == 81
    assert b2['healthPct'] is None and b2['cycles'] is None and b2['name'] == '배터리'   # 0 은 '모름'
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (True, [], None))
    assert health.battery() == {'ok': True, 'batteries': [], 'error': None}        # 배터리 없는 PC
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (False, [], '거부'))
    assert health.battery()['ok'] is False


def test_boot_time_before_and_after_the_last_startup_change():
    boots = [{'at': '2026-10-07T09:00:00+09:00', 'seconds': 40.0},
             {'at': '2026-10-06T09:00:00+09:00', 'seconds': 50.0},
             {'at': '2026-10-04T09:00:00+09:00', 'seconds': 80.0},
             {'at': '2026-10-03T09:00:00+09:00', 'seconds': 70.0}]
    changes = [{'at': '2026-10-05T10:00:00+09:00', 'name': 'A', 'enabled': False},
               {'at': '2026-10-05T10:05:00+09:00', 'name': 'B', 'enabled': False}]
    e = health.startup_effect(boots, changes)
    assert e['count'] == 2 and e['disabled'] == 2 and e['beforeAvg'] == 75.0 and e['afterAvg'] == 45.0
    assert e['beforeN'] == 2 and e['afterN'] == 2
    e = health.startup_effect(boots[2:], changes)                       # 바꾼 뒤 아직 기록된 부팅이 없다
    assert e['afterN'] == 0 and e['afterAvg'] is None
    assert health.startup_effect(boots, []) is None
    assert health.startup_effect(boots[:2], changes) is None            # 바꾸기 전 기록이 없으면 비교하지 않는다


def test_startup_toggle_records_the_time(monkeypatch):
    monkeypatch.setattr(optimizer, '_parse_id', lambda i: ('HKCU', 'App'))
    monkeypatch.setattr(optimizer, '_entry_exists', lambda t, n: True)
    state = {'on': True}
    monkeypatch.setattr(optimizer, '_approved_state', lambda t, n: 'enabled' if state['on'] else 'disabled')
    monkeypatch.setattr(optimizer, '_set_approved', lambda t, n, en: state.update(on=en) or (True, ''))
    assert optimizer.toggle_startup_app('HKCU:App', False)['success']
    log = config_manager.load_config()[health.STARTUP_LOG_KEY]
    assert log[-1]['name'] == 'App' and log[-1]['enabled'] is False and log[-1]['at']


def test_report_escapes_and_says_what_is_unknown():
    html = report.build_html({
        'stats': {'cpuModel': '<img src=x onerror=alert(1)>', 'drives': []},
        'disks': {'ok': False, 'error': '권한 없음'}, 'boots': {'boots': [], 'note': '기록 없음'},
        'battery': None, 'changes': {'k': {'why': '성능 모드 <b>'}}})
    assert '<img' not in html and '&lt;img' in html and '권한 없음' in html and '기록 없음' in html
    assert '성능 모드 &lt;b&gt;' in html and '알 수 없음' in html
    assert 'http' not in html.replace('lang="ko"', '')                  # 외부 자원 없이 한 파일
    assert '변경 기록을 읽지 못했습니다' in report.build_html({'changes': None})


def test_report_save_is_cancellable_and_writes_html(monkeypatch, tmp_path):
    import sys
    import types
    fake_webview = types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=30))
    monkeypatch.setitem(sys.modules, 'webview', fake_webview)
    monkeypatch.setattr(report, 'collect', lambda: {})

    class Win:
        def __init__(self, result):
            self.result = result

        def create_file_dialog(self, *a, **kw):
            return self.result
    assert report.save(Win(None))['cancelled'] is True
    out = tmp_path / 'r'
    r = report.save(Win((str(out),)))
    assert r['success'] and r['path'].endswith('r.html') and os.path.isfile(r['path'])
    assert report.save(None)['success'] is False


def test_services_button_only_opens_the_app(monkeypatch):
    opened = []
    monkeypatch.setattr(os, 'startfile', lambda p: opened.append(p), raising=False)
    api = object.__new__(Api)
    assert api.openServicesApp()['success'] and opened[0].lower().endswith('services.msc')
    spec = open(os.path.join(ROOT, 'APEX CARE Payload.spec'), encoding='utf-8').read()
    assert "'backend.report'" in spec
