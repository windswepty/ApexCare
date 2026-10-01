"""perf_modes: 모드 전환은 '이전 모드 되돌리기 → 새 모드 적용', 표준은 되돌리기만."""

import pytest

from backend import config_manager, perf_modes
from backend import system_state as ss
from tests import fakewin
from tests.fakewin import POWER, REGISTRY, SERVICES

pytestmark = pytest.mark.usefixtures('as_admin')

MM = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'
POWER_SETTINGS = [(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN), (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX),
                  (ss.SUB_PROCESSOR, ss.CPMINCORES), (ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND),
                  (ss.SUB_PROCESSOR, ss.PERFBOOSTMODE), (ss.SUB_PROCESSOR, ss.PERFEPP),
                  (ss.SUB_PCIEXPRESS, ss.PCIE_ASPM)]


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


def test_gaming_and_eco_change_boost_epp_and_pcie_then_standard_restores():
    # 모드 차이가 실제로 나는 설정들: 부스트 모드, EPP, PCIe 절전
    _seed_plans()
    before = _snapshot()
    hp, ps = fakewin.PLAN_HIGH_PERF, fakewin.PLAN_POWER_SAVER

    g = perf_modes.apply_mode('gaming')
    assert g['success'], g
    for side in ('ac', 'dc'):
        assert POWER.get(hp, ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, side) == 2
        assert POWER.get(hp, ss.SUB_PROCESSOR, ss.PERFEPP, side) == 0
        assert POWER.get(hp, ss.SUB_PCIEXPRESS, ss.PCIE_ASPM, side) == 0

    e = perf_modes.apply_mode('eco')
    assert e['success'], e
    assert POWER.get(hp, ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, 'ac') == 15     # 게이밍이 바꾼 것은 되돌렸다
    for side in ('ac', 'dc'):
        assert POWER.get(ps, ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, side) == 0  # 부스트 끔
        assert POWER.get(ps, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX, side) == 70
        assert POWER.get(ps, ss.SUB_PCIEXPRESS, ss.PCIE_ASPM, side) == 2

    assert perf_modes.apply_mode('standard')['success']
    assert _snapshot() == before
    assert ss.pending_changes() == {}


def test_step_shows_before_and_after_in_words():
    _seed_plans()
    POWER.seed_value(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, 1)
    r = perf_modes.apply_mode('gaming')
    step = next(s for s in r['steps'] if s['name'].startswith('CPU 부스트'))
    assert step['detail'] == '켬 → 공격적'
    step = next(s for s in r['steps'] if s['name'].startswith('CPU 최소 속도'))
    assert step['detail'] == '11% → 100%'


def test_setting_missing_on_this_pc_is_skipped_not_failed():
    # 가상 머신 등에는 PCIe 절전 항목이 없다. 바꾼 게 없으니 실패로 세지도, 기록하지도 않는다.
    _seed_plans()
    for plan in (fakewin.PLAN_BALANCED, fakewin.PLAN_HIGH_PERF, fakewin.PLAN_POWER_SAVER):
        for side in ('ac', 'dc'):
            POWER.values.pop((plan, ss.SUB_PCIEXPRESS, ss.PCIE_ASPM, side))
    before = _snapshot()

    r = perf_modes.apply_mode('gaming')

    assert r['success'] and r['failedCount'] == 0 and r['skippedCount'] == 1, r
    step = next(s for s in r['steps'] if 'PCIe' in s['name'])
    assert step['skipped'] and step['ok']
    assert '건너뜀' in r['message']
    assert not any(ss.PCIE_ASPM in k for k in ss.pending_changes())
    assert perf_modes.apply_mode('standard')['success']
    assert _snapshot() == before


def test_unreadable_setting_is_a_failure_not_a_skip():
    # 항목은 있는데 읽기가 막힌 것(권한 등)은 '없는 설정' 과 다르다. 실패로 알린다.
    _seed_plans()
    POWER.fail_read.add((fakewin.PLAN_HIGH_PERF, ss.PERFBOOSTMODE, 'ac'))
    POWER.fail_read.add((fakewin.PLAN_HIGH_PERF, ss.PERFBOOSTMODE, 'dc'))
    r = perf_modes.apply_mode('gaming')
    step = next(s for s in r['steps'] if s['name'].startswith('CPU 부스트'))
    assert step['ok'] is False and not step.get('skipped')
    assert r['partial'] is True and r['failedCount'] == 1


# ── 화면에 보이는 전원 플랜 이름과 어긋남 이유 ─────────────────
VENDOR_PLAN = '11111111-2222-3333-4444-555555555555'


def test_custom_plan_shows_its_real_name_not_unknown():
    # 제조사·사용자 플랜도 이 PC 에 등록된 이름 그대로 보인다(예전에는 '알 수 없음')
    POWER.plans[VENDOR_PLAN] = 'ASUS 터보'
    POWER.active = VENDOR_PLAN
    config_manager.set_optimization_mode('gaming', user_set=True)

    info = perf_modes.get_mode()

    assert info['activePlanName'] == 'ASUS 터보'
    assert info['expectedPlanName'] == '고성능'
    assert info['inSync'] is False and info['outOfSync'] == 'plan'


def test_standard_out_of_sync_is_leftover_settings_not_power_plan():
    _seed_plans()
    assert perf_modes.apply_mode('gaming')['success']
    # 표준으로 되돌리다 한 값이 실패했다고 치자: 성능 모드 설정이 남는다
    POWER.fail_write.add((fakewin.PLAN_HIGH_PERF, ss.PROCTHROTTLEMIN, 'ac'))
    perf_modes.apply_mode('standard')

    info = perf_modes.get_mode()

    assert info['mode'] == 'standard'
    assert info['outOfSync'] == 'leftover' and info['leftoverModeChanges'] >= 1
    assert info['expectedPlanName'] is None


def test_in_sync_has_no_reason():
    _seed_plans()
    assert perf_modes.apply_mode('eco')['success']
    info = perf_modes.get_mode()
    assert info['inSync'] is True and info['outOfSync'] is None
    assert info['activePlanName'] == '절전'


def test_mode_cards_use_registered_plan_names():
    POWER.plans[fakewin.PLAN_HIGH_PERF] = '고성능 (사용자 지정)'
    cards = {m['id']: m for m in perf_modes.list_modes()}
    assert cards['gaming']['planName'] == '고성능 (사용자 지정)'
    assert cards['standard']['planName'] == '원래 플랜 유지'
