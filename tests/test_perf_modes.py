"""perf_modes: 모드 전환은 '이전 모드 되돌리기 → 새 모드 적용', 표준은 되돌리기만."""

import pytest

from backend import config_manager, perf_modes
from backend import system_state as ss
from tests import fakewin
from tests.fakewin import POWER, REGISTRY, SERVICES

pytestmark = pytest.mark.usefixtures('as_admin')

MM = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'
POWER_SETTINGS = [(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN), (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX),
                  (ss.SUB_PROCESSOR, ss.CPMINCORES), (ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND)]


def _seed_plans():
    """사용자가 직접 조정한 플랜이라고 치고 '기본값' 과 다른 값을 넣는다."""
    for plan in (fakewin.PLAN_BALANCED, fakewin.PLAN_HIGH_PERF, fakewin.PLAN_POWER_SAVER):
        for i, (sub, setting) in enumerate(POWER_SETTINGS):
            POWER.seed_value(plan, sub, setting, 11 + i, dc_value=21 + i)
    REGISTRY.seed('HKLM', MM, 'SystemResponsiveness', 20)     # NetworkThrottlingIndex 는 원래 없음


def _snapshot():
    return (POWER.active, dict(POWER.values),
            REGISTRY.get('HKLM', MM, 'SystemResponsiveness'),
            REGISTRY.get('HKLM', MM, 'NetworkThrottlingIndex'))


def test_standard_does_not_change_power_plan():
    _seed_plans()
    POWER.active = fakewin.PLAN_HIGH_PERF              # 사용자가 원래 고성능을 쓰고 있었다
    before = _snapshot()

    r = perf_modes.apply_mode('standard')

    assert r['success'], r
    assert POWER.activations == []
    assert _snapshot() == before
    assert REGISTRY.writes == []


def test_gaming_then_standard_returns_to_original_state():
    _seed_plans()
    before = _snapshot()

    g = perf_modes.apply_mode('gaming')
    assert g['success'], g
    assert POWER.active == fakewin.PLAN_HIGH_PERF
    assert POWER.get(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 'dc') == 100
    assert REGISTRY.value('HKLM', MM, 'NetworkThrottlingIndex') == 0xFFFFFFFF

    s = perf_modes.apply_mode('standard')

    assert s['success'], s
    assert _snapshot() == before
    assert REGISTRY.get('HKLM', MM, 'NetworkThrottlingIndex') is None    # 원래 없던 값은 지운다
    assert ss.pending_changes() == {}
    assert config_manager.get_optimization_mode() == 'standard'


def test_switching_modes_does_not_stack():
    _seed_plans()
    before = _snapshot()
    assert perf_modes.apply_mode('gaming')['success']
    assert perf_modes.apply_mode('eco')['success']
    # 에코로 바꿨으면 게이밍이 켠 레지스트리는 사라져야 한다
    assert REGISTRY.value('HKLM', MM, 'SystemResponsiveness') == 20
    assert REGISTRY.get('HKLM', MM, 'NetworkThrottlingIndex') is None
    assert POWER.get(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 'ac') == 11
    assert perf_modes.apply_mode('standard')['success']
    assert _snapshot() == before


def test_persist_false_keeps_saved_mode():
    _seed_plans()
    config_manager.set_optimization_mode('eco', user_set=True)

    r = perf_modes.apply_mode('gaming', user_set=False, persist=False)

    assert r['success']
    assert config_manager.get_optimization_mode() == 'eco'
    assert config_manager.get_optimization_mode_user_set() is True


def test_failed_step_is_reported_not_hidden():
    _seed_plans()
    REGISTRY.deny_write_value('HKLM', MM)
    r = perf_modes.apply_mode('gaming')
    assert r['success'] is False and r['partial'] is True
    assert r['failedCount'] == 2
    assert all(not s['ok'] for s in r['steps'] if 'MMCSS' in s['name'] or '스로틀링' in s['name'])


def test_revert_everything_without_legacy_backups_writes_nothing():
    _seed_plans()
    # 사용자가 일부러 꺼 둔 서비스. 앱이 바꾼 적이 없으니 되돌리기가 켜면 안 된다.
    SERVICES.add('SysMain', 4)
    SERVICES.add('WSearch', 4)
    before = _snapshot()

    r = perf_modes.revert_everything()

    assert r['success'], r
    assert REGISTRY.writes == []
    assert SERVICES.calls == []
    assert POWER.activations == []
    assert _snapshot() == before
    assert SERVICES.start_of('SysMain')[0] == 4 and SERVICES.start_of('WSearch')[0] == 4


def test_revert_everything_restores_journal_then_legacy_backup():
    _seed_plans()
    SERVICES.add('SysMain', 4)
    before = _snapshot()
    assert perf_modes.apply_mode('gaming')['success']
    cfg = config_manager.load_config()
    cfg['service_start_backup'] = {'SysMain': {'start': 2, 'delayed': 1}}
    config_manager.save_config(cfg)

    r = perf_modes.revert_everything()

    assert r['success'], r
    assert _snapshot() == before
    assert ss.service_start_type('SysMain') == 'delayed-auto'
    assert 'service_start_backup' not in config_manager.load_config()
    assert ss.pending_changes() == {}
