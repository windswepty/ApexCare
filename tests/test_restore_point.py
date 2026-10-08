"""변경 전 Windows 복원 지점: 실제로 새로 생겼는지 목록으로 확인하고, 만들지 않았거나 못 만들었으면 그대로 말한다."""

import os
import subprocess

from backend import config_manager, debloater, optimizer, perf_modes, restore_point
from backend.api import Api
from tests.conftest import ROOT


def test_created_only_when_a_newer_point_appears():
    r = restore_point.interpret({'maxBefore': 7, 'newestSeq': 8, 'newestAt': '2026-10-08T10:15:00+09:00'})
    assert r['ok'] and r['created'] and '2026-10-08 10:15' in r['message']
    # 24시간 안에 만든 지점이 있어 Windows 가 만들지 않음(경고만): 성공했다고 하지 않는다
    r = restore_point.interpret({'maxBefore': 8, 'newestSeq': 8, 'newestAt': '2026-10-07T21:00:00+09:00',
                                 'warning': '1440분 안에 이미 만들어진 복원 지점이 있어 새로 만들 수 없습니다'})
    assert r['ok'] and not r['created'] and '만들지 않았습니다' in r['message'] and '2026-10-07 21:00' in r['message']
    # 시스템 보호 꺼짐 등 오류
    r = restore_point.interpret({'maxBefore': 0, 'newestSeq': None, 'error': '시스템 복원이 꺼져 있습니다'})
    assert not r['ok'] and not r['created'] and '시스템 보호' in r['message']
    assert restore_point.interpret(None, timed_out=True)['ok'] is False
    assert restore_point.interpret(None)['ok'] is False


def test_setting_turns_it_off_and_is_validated(restore_points):
    assert restore_point.enabled() is True                                     # 기본은 켜짐
    assert restore_point.set_enabled('no')['success'] is False
    assert restore_point.set_enabled(False)['success']
    assert restore_point.before_change('x') is None and restore_points['calls'] == []
    assert restore_point.set_enabled(True)['success'] and restore_point.enabled()


def test_timeout_is_reported_not_hidden(monkeypatch):
    def slow(desc):
        raise subprocess.TimeoutExpired('powershell', 240)
    monkeypatch.setattr(restore_point, '_create', slow)
    r = restore_point.before_change('x')
    assert r['ok'] is False and '초 안에' in r['message']


def test_mode_change_makes_a_point_first_but_standard_does_not(restore_points, monkeypatch, as_admin):
    order = []
    monkeypatch.setattr(perf_modes, 'apply_mode', lambda mode, **kw: order.append(mode) or {'success': True})
    real = restore_point._create
    monkeypatch.setattr(restore_point, '_create', lambda d: order.append('rp') or real(d))
    api = object.__new__(Api)
    res = api.setOptimizationMode('gaming')
    assert order == ['rp', 'gaming'] and res['restorePoint']['ok'] is False      # 못 만들어도 모드는 적용하고 알린다
    assert '게이밍' in restore_points['calls'][0]
    order.clear()
    assert 'restorePoint' not in api.setOptimizationMode('standard') and order == ['standard']


def test_debloat_and_tuning_make_a_point_before_changing(restore_points, monkeypatch):
    monkeypatch.setattr(debloater, '_apply_telemetry_policy', lambda: (True, ''))
    monkeypatch.setattr(debloater, '_current_account', lambda: 'me')
    debloater._debloat_state = debloater._idle_state()
    debloater._run_debloater(['telemetry'])
    assert debloater._debloat_state['restore_point']['ok'] is False and restore_points['calls'] == ['APEX CARE: Windows 기본 앱 정리 전']

    monkeypatch.setattr(optimizer, '_service_step', lambda *a: {'name': 's', 'ok': True, 'detail': ''})
    r = optimizer.apply_hardware_tailored_tuning(8, 16, consent=True)
    assert 'restorePoint' in r and len(restore_points['calls']) == 2
    optimizer.apply_hardware_tailored_tuning(8, 16, consent=False)             # 미리보기는 만들지 않는다
    assert len(restore_points['calls']) == 2


def test_wiring():
    spec = open(os.path.join(ROOT, 'APEX CARE Payload.spec'), encoding='utf-8').read()
    assert "'backend.restore_point'" in spec
    assert 'Enable-ComputerRestore' not in restore_point._PS                    # 시스템 보호를 켜지 않는다
    assert config_manager.DEFAULT_CONFIG.get(restore_point.CONFIG_KEY, True) is True
