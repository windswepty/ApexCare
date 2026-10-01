"""optimizer 하드웨어 맞춤 튜닝과 구버전 service_start_backup 복구."""

import pytest

from backend import config_manager, optimizer
from backend import system_state as ss
from tests import fakewin
from tests.fakewin import POWER, REGISTRY, SERVICES

LOW_END = (4, 8)          # 코어 4개 → 저사양
HIGH_END = (8, 16)


@pytest.fixture
def ram_ok(monkeypatch):
    """purge_ram 은 진짜 NtSetSystemInformation 을 부른다. 성공한 척만 한다."""
    calls = []

    def fake():
        calls.append(1)
        return {'success': True, 'standbyBeforeBytes': 2 * 1024**3, 'standbyAfterBytes': 1024**3}
    monkeypatch.setattr(optimizer, 'purge_ram', fake)
    return calls


def _services():
    SERVICES.add('SysMain', 2)
    SERVICES.add('WSearch', 2, delayed=1)


def test_preview_changes_nothing(ram_ok):
    _services()
    for spec in (LOW_END, HIGH_END):
        r = optimizer.apply_hardware_tailored_tuning(*spec, consent=False)
        assert r['success'] and r['applied'] is False and r['changes']
    assert REGISTRY.writes == [] and SERVICES.calls == []
    assert POWER.activations == [] and ram_ok == []
    assert ss.pending_changes() == {}



@pytest.mark.parametrize('spec', [(0, 16), (8, 0), (None, 16), (8, None), (-2, 16), (8, float('nan')),
                                  (True, 16), ('', 16)])
def test_unknown_specs_are_refused_not_judged_low_end(ram_ok, spec):
    # 사양을 읽지 못해 0·None 이 오면 '저사양' 으로 판정해 SysMain 을 끄면 안 된다
    _services()
    for consent in (False, True):
        r = optimizer.apply_hardware_tailored_tuning(*spec, consent=consent)
        assert r['success'] is False and 'tier' not in r and '읽지 못해' in r['message']
    assert SERVICES.calls == [] and ram_ok == [] and ss.pending_changes() == {}

def test_low_end_only_disables_sysmain(ram_ok):
    _services()
    POWER.active = fakewin.PLAN_HIGH_PERF

    r = optimizer.apply_hardware_tailored_tuning(*LOW_END, consent=True)

    assert r['success'], r
    assert SERVICES.start_of('SysMain')[0] == 4
    assert SERVICES.start_of('WSearch') == (2, 1)                 # 검색은 건드리지 않는다
    assert [c[0] for c in SERVICES.calls] == ['SysMain']
    assert POWER.active == fakewin.PLAN_HIGH_PERF and POWER.activations == []
    assert set(ss.pending_changes()) == {'svc:sysmain'}
    assert ss.pending_changes()['svc:sysmain']['group'] == optimizer.HW_TUNING_GROUP

    back = optimizer.restore_tailored_service_config()
    assert back['success'], back
    assert SERVICES.start_of('SysMain')[0] == 2


def test_high_end_keeps_delayed_auto(ram_ok):
    _services()
    SERVICES.add('SysMain', 4)
    r = optimizer.apply_hardware_tailored_tuning(*HIGH_END, consent=True)
    assert r['success'], r
    assert SERVICES.start_of('SysMain')[0] == 2
    assert SERVICES.start_of('WSearch') == (2, 1)                 # 지연된 시작 그대로
    assert [c[0] for c in SERVICES.calls] == ['SysMain']


def test_partial_failure_is_not_success(ram_ok):
    _services()
    SERVICES.fail.add('SysMain')
    r = optimizer.apply_hardware_tailored_tuning(*LOW_END, consent=True)
    assert r['success'] is False
    assert r['failedCount'] == 1 and r['applied'] is True         # 메모리 비우기는 됐다


def test_ram_failure_alone_is_not_success(monkeypatch):
    _services()
    monkeypatch.setattr(optimizer, 'purge_ram',
                        lambda: {'success': False, 'error': 'UAC_REQUIRED', 'message': '권한 필요'})
    r = optimizer.apply_hardware_tailored_tuning(*LOW_END, consent=True)
    assert r['success'] is False and r['failedCount'] == 1


def test_real_purge_ram_is_blocked_and_reported_as_failure():
    # purge_ram 을 막지 않으면 Win32 호출이 막혀 '관리자 아님' 으로 실패해야 한다
    r = optimizer.purge_ram()
    assert r['success'] is False


def _legacy_backup(backup):
    cfg = config_manager.load_config()
    cfg['service_start_backup'] = backup
    config_manager.save_config(cfg)


def test_legacy_backup_restores_only_recorded_values():
    SERVICES.add('SysMain', 4)
    SERVICES.add('WSearch', 4)
    _legacy_backup({'SysMain': {'start': 2, 'delayed': 0},
                    'WSearch': {'start': None}})             # 구버전이 읽지 못한 값

    r = optimizer.restore_tailored_service_config()

    assert SERVICES.start_of('SysMain')[0] == 2
    assert SERVICES.start_of('WSearch')[0] == 4                   # 추측한 기본값을 쓰지 않는다
    assert [c[0] for c in SERVICES.calls] == ['SysMain']
    assert r['success'] is False                                  # 되돌리지 못한 항목이 있다
    left = config_manager.load_config().get('service_start_backup')
    assert left == {'WSearch': {'start': None}}


def test_legacy_backup_kept_when_restore_fails():
    SERVICES.add('SysMain', 4)
    SERVICES.add('WSearch', 4)
    _legacy_backup({'SysMain': {'start': 2, 'delayed': 0}, 'WSearch': {'start': 3}})
    SERVICES.fail.add('SysMain')

    r = optimizer.restore_tailored_service_config()

    assert r['success'] is False
    assert ss.service_start_type('WSearch') == 'demand'
    assert config_manager.load_config()['service_start_backup'] == {'SysMain': {'start': 2, 'delayed': 0}}


def test_legacy_backup_ignores_services_this_feature_never_touched():
    SERVICES.add('wuauserv', 4)
    _legacy_backup({'wuauserv': {'start': 2}})
    optimizer.restore_tailored_service_config()
    assert SERVICES.calls == [] and SERVICES.start_of('wuauserv')[0] == 4


def test_no_backup_and_no_journal_changes_nothing():
    SERVICES.add('SysMain', 4)
    SERVICES.add('WSearch', 4)
    r = optimizer.restore_tailored_service_config()
    assert r['success'] and r['steps'] == []
    assert SERVICES.calls == [] and REGISTRY.writes == []
