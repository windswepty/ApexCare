"""system_state: 원래 값 기록 → 변경 → 되읽기 확인 → 복구."""

import json

from backend import system_state as ss
from tests import fakewin
from tests.fakewin import POWER, REGISTRY, SERVICES

KEY = r'SOFTWARE\ApexCareTest'


def _journal():
    return ss.pending_changes()


# ── 레지스트리 ────────────────────────────────────────────

def test_value_that_did_not_exist_is_deleted_on_restore():
    r = ss.set_registry('HKLM', KEY, 'NewValue', 7, group='t')
    assert r['ok'] and REGISTRY.value('HKLM', KEY, 'NewValue') == 7

    res = ss.restore_group('t')

    assert res['ok'] and res['failed'] == []
    # '기본값' 을 써 넣는 게 아니라 값이 아예 없어야 한다
    assert REGISTRY.get('HKLM', KEY, 'NewValue') is None
    assert _journal() == {}


def test_existing_value_is_restored_with_original_value_and_type():
    REGISTRY.seed('HKLM', KEY, 'Old', 'hello', fakewin.REG_SZ)
    assert ss.set_registry('HKLM', KEY, 'Old', 'changed', group='t', vtype=fakewin.REG_SZ)['ok']
    assert ss.restore_group('t')['ok']
    assert REGISTRY.get('HKLM', KEY, 'Old') == ('hello', fakewin.REG_SZ)


def test_original_is_recorded_once_and_never_overwritten():
    REGISTRY.seed('HKLM', KEY, 'V', 1)
    ss.set_registry('HKLM', KEY, 'V', 2, group='t')
    ss.set_registry('HKLM', KEY, 'V', 3, group='t')     # 두 번째 기록이 '원래 값=2' 가 되면 안 된다
    ss.restore_group('t')
    assert REGISTRY.value('HKLM', KEY, 'V') == 1


def test_unreadable_original_means_no_change():
    REGISTRY.seed('HKLM', KEY, 'Locked', 1)
    REGISTRY.deny_read_value('HKLM', KEY, 'Locked')

    r = ss.set_registry('HKLM', KEY, 'Locked', 0, group='t')

    assert r['ok'] is False
    assert REGISTRY.writes == []
    assert _journal() == {}


def test_journal_save_failure_means_no_change(monkeypatch):
    REGISTRY.seed('HKLM', KEY, 'V', 1)
    SERVICES.add('SysMain', 2)
    POWER.seed_value(fakewin.PLAN_BALANCED, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5)
    monkeypatch.setattr(ss, '_save', lambda data: False)

    assert ss.set_registry('HKLM', KEY, 'V', 0, group='t')['ok'] is False
    assert ss.set_active_plan(fakewin.PLAN_HIGH_PERF, group='t')['ok'] is False
    assert ss.set_service_start('SysMain', 'disabled', 't')['ok'] is False
    assert ss.set_power_value(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 100, group='t')['ok'] is False

    assert REGISTRY.writes == []
    assert REGISTRY.value('HKLM', KEY, 'V') == 1
    # set_power_value 는 끝에 '지금 활성 플랜' 을 다시 활성화한다. 같은 플랜이라 바뀌는 것은 없다.
    assert POWER.active == fakewin.PLAN_BALANCED
    assert set(POWER.activations) <= {fakewin.PLAN_BALANCED}
    assert POWER.get(fakewin.PLAN_BALANCED, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN) == 5
    assert SERVICES.calls == [] and SERVICES.start_of('SysMain') == (2, None)


def test_write_that_does_not_stick_is_reported_as_failure():
    REGISTRY.ignore_write_value('HKLM', KEY, 'Sticky')
    r = ss.set_registry('HKLM', KEY, 'Sticky', 5, group='t')
    assert r['ok'] is False and r['verified'] is False


def test_restore_keeps_journal_when_readback_differs():
    REGISTRY.seed('HKLM', KEY, 'A', 1)
    ss.set_registry('HKLM', KEY, 'A', 9, group='t')      # 원래 1
    ss.set_registry('HKLM', KEY, 'B', 9, group='t')      # 원래 없음
    # 되돌릴 때 쓰기가 먹지 않는다(다른 프로그램이 되돌려 놓는 경우)
    REGISTRY.ignore_write_value('HKLM', KEY, 'A')
    REGISTRY.ignore_write_value('HKLM', KEY, 'B')

    res = ss.restore_group('t')

    assert res['ok'] is False
    assert {f['key'] for f in res['failed']} == {f'reg:HKLM\\{KEY}\\A', f'reg:HKLM\\{KEY}\\B'}
    # 실패한 기록은 남아야 다시 시도할 수 있다
    assert set(_journal()) == {f'reg:HKLM\\{KEY}\\A', f'reg:HKLM\\{KEY}\\B'}

    REGISTRY.ignore_writes.clear()
    assert ss.restore_group('t')['ok']
    assert REGISTRY.value('HKLM', KEY, 'A') == 1 and REGISTRY.get('HKLM', KEY, 'B') is None
    assert _journal() == {}


def test_restore_failure_by_permission_keeps_journal():
    ss.set_registry('HKLM', KEY, 'P', 3, group='t')
    REGISTRY.deny_write_value('HKLM', KEY)
    res = ss.restore_group('t')
    assert res['ok'] is False and set(_journal()) == {f'reg:HKLM\\{KEY}\\P'}


def test_restore_group_only_touches_that_group():
    ss.set_registry('HKLM', KEY, 'Mine', 1, group='a')
    ss.set_registry('HKLM', KEY, 'Other', 1, group='b')
    ss.restore_group('a')
    assert REGISTRY.get('HKLM', KEY, 'Mine') is None
    assert REGISTRY.value('HKLM', KEY, 'Other') == 1
    assert set(_journal()) == {f'reg:HKLM\\{KEY}\\Other'}


# ── 전원 ──────────────────────────────────────────────────

def test_power_plan_restore_ends_on_original_plan():
    POWER.seed_value(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5)
    assert ss.set_active_plan(fakewin.PLAN_HIGH_PERF, group='t')['ok']
    # 고성능 플랜의 세부값도 바꾼다. 복구 때 이 플랜을 다시 켜면 안 된다.
    assert ss.set_power_value(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 100, group='t',
                              plan=fakewin.PLAN_HIGH_PERF)['ok']
    assert POWER.active == fakewin.PLAN_HIGH_PERF

    res = ss.restore_group('t')

    assert res['ok'], res
    assert POWER.active == fakewin.PLAN_BALANCED
    assert POWER.activations[-1] == fakewin.PLAN_BALANCED
    assert POWER.get(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 'ac') == 5
    assert POWER.get(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 'dc') == 5
    assert _journal() == {}


def test_power_plan_ownership_moves_to_latest_group():
    # 다른 기능이 먼저 플랜을 바꿨어도, 마지막으로 바꾼 기능을 되돌리면 원래 플랜으로 간다
    assert ss.set_active_plan(fakewin.PLAN_POWER_SAVER, group='hw_tuning')['ok']
    assert ss.set_active_plan(fakewin.PLAN_HIGH_PERF, group='perf_mode')['ok']
    assert ss.restore_group('perf_mode')['ok']
    assert POWER.active == fakewin.PLAN_BALANCED


def test_unreadable_power_value_is_not_changed():
    POWER.seed_value(fakewin.PLAN_BALANCED, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5)
    POWER.fail_read.add((fakewin.PLAN_BALANCED, ss.PROCTHROTTLEMIN, 'dc'))
    r = ss.set_power_value(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 100, group='t')
    assert r['ok'] is False
    assert POWER.get(fakewin.PLAN_BALANCED, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 'dc') == 5


def test_missing_plan_is_not_activated():
    r = ss.set_active_plan(fakewin.PLAN_ULTIMATE, group='t')
    assert r['ok'] is False and POWER.activations == []


# ── 서비스 ────────────────────────────────────────────────

def test_service_start_type_recorded_and_restored():
    SERVICES.add('SysMain', 2, delayed=1)           # 자동(지연된 시작)
    r = ss.set_service_start('SysMain', 'disabled', 't')
    assert r['ok'] and r['changed'] and r['before'] == 'delayed-auto'
    assert SERVICES.start_of('SysMain')[0] == 4
    assert _journal()['svc:sysmain']['start'] == 2

    assert ss.restore_group('t')['ok']
    assert SERVICES.start_of('SysMain') == (2, 1)
    assert ss.service_start_type('SysMain') == 'delayed-auto'
    assert _journal() == {}


def test_service_restore_reads_pre_merge_journal_format():
    # 병합 전 브랜치는 {'value': {'start', 'delayed'}} 로 기록했다
    SERVICES.add('WSearch', 4)
    SERVICES.add('SysMain', 4)
    with open(ss.JOURNAL_PATH, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'entries': {
            'svc:wsearch': {'kind': 'service', 'group': 'hw_tuning', 'service': 'WSearch',
                            'value': {'start': 2, 'delayed': 1}},
            'svc:sysmain': {'kind': 'service', 'group': 'hw_tuning', 'service': 'SysMain',
                            'value': {'start': 3, 'delayed': None}},
        }}, f)

    res = ss.restore_group('hw_tuning')

    assert res['ok'], res
    assert ss.service_start_type('WSearch') == 'delayed-auto'
    assert ss.service_start_type('SysMain') == 'demand'
    assert _journal() == {}


def test_service_sc_failure_is_reported_and_journal_kept_for_retry():
    SERVICES.add('SysMain', 2)
    SERVICES.fail.add('SysMain')
    r = ss.set_service_start('SysMain', 'disabled', 't')
    assert r['ok'] is False and SERVICES.start_of('SysMain')[0] == 2

    SERVICES.fail.clear()
    assert ss.set_service_start('SysMain', 'disabled', 't')['ok']
    SERVICES.fail.add('SysMain')
    res = ss.restore_group('t')
    assert res['ok'] is False and 'svc:sysmain' in _journal()


def test_unusual_service_start_type_is_left_alone():
    SERVICES.add('Weird', 1)                        # 'system' 시작 — 이 앱이 건드리지 않는다
    r = ss.set_service_start('Weird', 'disabled', 't')
    assert r['ok'] is False and SERVICES.calls == []
