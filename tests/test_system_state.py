"""system_state: 원래 값 기록 → 변경 → 되읽기 확인 → 복구."""

import json

from backend import machine_store, system_state as ss
from tests import fakewin
from tests.fakewin import POWER, REGISTRY, SERVICES

KEY = r'SOFTWARE\ApexCareTest'
APPROVED = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'


def _journal():
    return ss.pending_changes()


def _machine_journal():
    raw = REGISTRY.value('HKLM', machine_store.KEY, 'Journal')
    return json.loads(raw) if raw else None


# ── 저널을 읽지 못할 때 ─────────────────────────────────────

def test_locked_account_journal_is_not_treated_as_corrupt_and_nothing_changes(monkeypatch):
    import os
    assert ss.set_registry('HKCU', APPROVED, 'First', b'\x02' * 12, group='t', vtype=fakewin.REG_BINARY)['ok']
    with open(ss.JOURNAL_PATH, encoding='utf-8') as f:
        before = f.read()
    real_open = open

    def locked_open(path, mode='r', *a, **kw):
        if os.path.normcase(str(path)) == os.path.normcase(ss.JOURNAL_PATH) and 'r' in mode:
            raise PermissionError(32, '다른 프로그램이 사용 중 (백신 검사)')
        return real_open(path, mode, *a, **kw)
    monkeypatch.setattr('builtins.open', locked_open)
    monkeypatch.setattr(ss, '_RETRY_WAIT', 0)

    r = ss.set_registry('HKLM', KEY, 'Second', 2, group='t')
    restored = ss.restore_group('t')
    monkeypatch.undo()

    # 예전에는 '깨짐' 으로 보고 옆으로 치운 뒤 새 기록만 남겨 First 의 원래 값 기록을 잃었다
    assert r['ok'] is False and REGISTRY.get('HKLM', KEY, 'Second') is None
    assert restored['ok'] is False and REGISTRY.value('HKCU', APPROVED, 'First') == b'\x02' * 12
    with open(ss.JOURNAL_PATH, encoding='utf-8') as f:
        assert f.read() == before
    assert not [n for n in os.listdir(ss.APPDATA_DIR) if '.corrupt' in n or n.endswith('.tmp')]


def test_unreadable_machine_journal_changes_nothing():
    assert ss.set_registry('HKLM', KEY, 'First', 1, group='t')['ok']
    before = REGISTRY.value('HKLM', machine_store.KEY, 'Journal')
    REGISTRY.deny_read_value('HKLM', machine_store.KEY, 'Journal')

    r = ss.set_registry('HKLM', KEY, 'Second', 2, group='t')
    restored = ss.restore_group('t')

    assert r['ok'] is False and REGISTRY.get('HKLM', KEY, 'Second') is None
    assert restored['ok'] is False and REGISTRY.value('HKLM', KEY, 'First') == 1
    assert REGISTRY.value('HKLM', machine_store.KEY, 'Journal') == before


# ── 저널 위치: PC 전체는 관리자만 쓰는 곳, 이 계정의 시작 프로그램 표시는 계정 파일 ──

def test_pc_wide_changes_are_journaled_where_only_admins_can_write():
    POWER.seed_value(fakewin.PLAN_BALANCED, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5)
    SERVICES.add('SysMain', 2)
    assert ss.set_registry('HKLM', KEY, 'V', 1, group='t')['ok']
    assert ss.set_active_plan(fakewin.PLAN_HIGH_PERF, group='t')['ok']
    assert ss.set_service_start('SysMain', 'disabled', 't')['ok']
    assert ss.set_registry('HKCU', APPROVED, 'App', b'\x03' * 12, group='u', vtype=fakewin.REG_BINARY)['ok']

    machine = _machine_journal()['entries']
    assert f'reg:HKLM\\{KEY}\\V' in machine and 'power:active_plan' in machine and 'svc:sysmain' in machine
    assert not [k for k in machine if k.startswith('reg:HKCU')]
    with open(ss.JOURNAL_PATH, encoding='utf-8') as f:
        assert list(json.load(f)['entries']) == [f'reg:HKCU\\{APPROVED}\\App']
    assert len(ss.pending_changes()) == 4
    assert ss.restore_all()['ok'] and ss.pending_changes() == {}


def _as_other_account(monkeypatch, tmp_path, sid):
    """다른 Windows 계정으로 앱을 켠 것처럼: 계정 파일 위치와 SID 만 다르고 PC(레지스트리·전원)는 같다."""
    d = tmp_path / sid
    d.mkdir()
    monkeypatch.setattr(ss, 'APPDATA_DIR', str(d))
    monkeypatch.setattr(ss, 'JOURNAL_PATH', str(d / 'system_state.json'))
    monkeypatch.setattr(ss, '_account_sid', lambda: sid)


def test_second_account_does_not_record_first_accounts_values_as_original(monkeypatch, tmp_path):
    REGISTRY.seed('HKLM', KEY, 'SystemResponsiveness', 20)
    assert ss.set_registry('HKLM', KEY, 'SystemResponsiveness', 10, group='perf_mode')['ok']   # 계정 A: 게이밍

    _as_other_account(monkeypatch, tmp_path, 'S-1-5-21-9-9-9-1002')                           # 계정 B
    assert ss.pending_changes()                     # B 도 A 가 바꾼 것을 본다
    assert ss.set_registry('HKLM', KEY, 'SystemResponsiveness', 10, group='perf_mode')['ok']
    assert ss.restore_group('perf_mode')['ok']      # B 가 표준으로

    # 예전에는 B 가 A 의 게이밍 값 10 을 원래 값으로 기록해, B 의 되돌리기가 10 을 다시 썼다
    assert REGISTRY.value('HKLM', KEY, 'SystemResponsiveness') == 20


def _write_account_journal(entries):
    import os
    os.makedirs(ss.APPDATA_DIR, exist_ok=True)
    with open(ss.JOURNAL_PATH, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'entries': entries}, f)


def _reg_entry(hive, path, name, value, vtype=fakewin.REG_DWORD):
    return {'kind': 'registry', 'group': 't', 'hive': hive, 'path': path, 'name': name,
            'existed': True, 'value': value, 'type': vtype, 'created_keys': []}


def test_old_journal_is_moved_to_the_pc_once_and_later_writes_to_the_account_file_are_ignored():
    REGISTRY.seed('HKLM', KEY, 'Tuned', 1)
    _write_account_journal({f'reg:HKLM\\{KEY}\\Tuned': _reg_entry('HKLM', KEY, 'Tuned', 7)})

    assert f'reg:HKLM\\{KEY}\\Tuned' in ss.pending_changes()                 # 예전 기록을 옮겨 이어 쓴다
    assert f'reg:HKLM\\{KEY}\\Tuned' in _machine_journal()['entries']
    with open(ss.JOURNAL_PATH, encoding='utf-8') as f:
        assert json.load(f)['entries'] == {}

    # 옮긴 뒤 같은 계정의 일반 권한 프로그램이 계정 파일에 PC 쪽 기록을 써 넣는다
    evil = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
    _write_account_journal({f'reg:HKLM\\{evil}\\x': _reg_entry('HKLM', evil, 'x', r'C:\evil.exe', fakewin.REG_SZ)})
    assert f'reg:HKLM\\{evil}\\x' not in ss.pending_changes()
    assert ss.restore_all()['ok']
    assert REGISTRY.get('HKLM', evil, 'x') is None                    # 관리자 권한으로 쓰지 않는다
    assert REGISTRY.value('HKLM', KEY, 'Tuned') == 7                  # 진짜 예전 기록은 되돌렸다


def test_account_file_entries_outside_startup_approval_are_not_used():
    policies = r'Software\Policies\Microsoft\Windows\System'
    _write_account_journal({f'reg:HKCU\\{policies}\\DisableCMD': _reg_entry('HKCU', policies, 'DisableCMD', 0)})
    REGISTRY.seed('HKCU', policies, 'DisableCMD', 1)

    assert ss.pending_changes() == {}
    assert ss.restore_all()['ok']
    assert REGISTRY.value('HKCU', policies, 'DisableCMD') == 1


def test_corrupt_machine_journal_is_kept_aside():
    REGISTRY.seed('HKLM', machine_store.KEY, 'Journal', '{깨짐', fakewin.REG_SZ)
    assert ss.pending_changes() == {}
    values = REGISTRY._find(fakewin.HKEY_LOCAL_MACHINE, ['SOFTWARE', 'APEX CARE']).values
    assert len([n for n in values if n.startswith('journal.corrupt-')]) == 1 and 'journal' not in values


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


# ── 이 앱이 만든 키 (샌드박스 점검에서 찾은 문제: 원래 없던 키가 빈 채로 남았다) ──

NEW = r'SOFTWARE\ApexCareNew\Deeper'


def test_keys_created_for_a_value_are_removed_on_restore():
    REGISTRY.seed_key('HKLM', 'SOFTWARE')
    assert ss.set_registry('HKLM', NEW, 'V', 1, group='t')['ok']
    assert ss.pending_changes()[rf'reg:HKLM\{NEW}\V']['created_keys'] == [NEW, r'SOFTWARE\ApexCareNew']

    assert ss.restore_group('t')['ok']

    assert not REGISTRY.has_key('HKLM', r'SOFTWARE\ApexCareNew')      # 만든 키는 깊은 것부터 사라진다
    assert REGISTRY.has_key('HKLM', 'SOFTWARE')                       # 원래 있던 키는 남는다


def test_created_key_is_kept_if_something_else_is_inside():
    REGISTRY.seed_key('HKLM', 'SOFTWARE')
    ss.set_registry('HKLM', NEW, 'V', 1, group='t')
    REGISTRY.seed('HKLM', NEW, 'OtherProgram', 5)                    # 그 사이 다른 프로그램이 값을 넣었다
    assert ss.restore_group('t')['ok']
    assert REGISTRY.value('HKLM', NEW, 'OtherProgram') == 5


def test_created_key_is_removed_only_after_all_its_values_are_restored():
    REGISTRY.seed_key('HKLM', 'SOFTWARE')
    ss.set_registry('HKLM', NEW, 'A', 1, group='t')                   # 이 기록이 키를 만들었다
    ss.set_registry('HKLM', NEW, 'B', 1, group='t')                   # 이 기록 때는 키가 이미 있었다
    assert ss.restore_group('t')['ok']
    assert not REGISTRY.has_key('HKLM', r'SOFTWARE\ApexCareNew')


def test_created_key_goes_away_when_values_are_restored_one_group_at_a_time():
    # 시작 프로그램처럼 항목마다 그룹이 다르고 하나씩 되돌리는 경우. 키를 만든 A 를 먼저 되돌리면 B 값 때문에
    # 키를 못 지우고, 예전에는 '이 앱이 만든 키' 라는 기록이 A 와 함께 사라져 B 뒤에 빈 키가 남았다.
    REGISTRY.seed_key('HKLM', 'SOFTWARE')
    ss.set_registry('HKLM', NEW, 'A', 1, group='startup:A')
    ss.set_registry('HKLM', NEW, 'B', 1, group='startup:B')
    assert ss.restore_group('startup:A')['ok']
    assert REGISTRY.has_key('HKLM', r'SOFTWARE\ApexCareNew')          # B 값이 남아 있다
    assert ss.restore_group('startup:B')['ok']
    assert not REGISTRY.has_key('HKLM', r'SOFTWARE\ApexCareNew')
    assert ss.pending_changes() == {}


# ── 전원 플랜이 지워졌거나 전환이 막혔을 때 ─────────────────────

def test_deleted_original_plan_asks_once_then_lets_go_when_user_picks_a_plan():
    custom = '11111111-2222-3333-4444-555555555555'
    POWER.plans[custom] = '내 플랜'
    POWER.active = custom
    assert ss.set_active_plan(fakewin.PLAN_HIGH_PERF, group='t')['ok']
    del POWER.plans[custom]                                     # 제어판에서 지움

    r = ss.restore_group('t')
    assert r['ok'] is False and '삭제' in r['failed'][0]['reason']   # 이 앱이 켠 고성능이 그대로라 안내한다
    POWER.active = fakewin.PLAN_POWER_SAVER                       # 안내대로 사용자가 고름
    assert ss.restore_group('t')['ok'] and _journal() == {}     # 예전에는 영원히 실패로 남았다
    assert POWER.active == fakewin.PLAN_POWER_SAVER


def test_values_written_to_a_plan_that_was_later_deleted_are_let_go():
    POWER.seed_value(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5)
    assert ss.set_power_value(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 100, group='t',
                              plan=fakewin.PLAN_HIGH_PERF)['ok']
    del POWER.plans[fakewin.PLAN_HIGH_PERF]
    assert ss.restore_group('t')['ok'] and _journal() == {}


def test_failed_plan_switch_leaves_no_record():
    POWER.fail_set_active = True                                # 정책·제조사 도구가 플랜 전환을 막는다
    assert ss.set_active_plan(fakewin.PLAN_HIGH_PERF, group='perf_mode')['ok'] is False
    assert _journal() == {}                                     # 예전에는 '되돌리지 못한 설정 1개' 가 남았다
    assert ss.set_active_plan('99999999-9999-9999-9999-999999999999', group='perf_mode')['ok'] is False
    assert _journal() == {}


def test_plan_already_back_is_not_switched_again():
    assert ss.set_active_plan(fakewin.PLAN_HIGH_PERF, group='t')['ok']
    POWER.active = fakewin.PLAN_BALANCED                        # 사용자가 Windows 에서 직접 되돌림
    POWER.fail_set_active = True
    assert ss.restore_group('t')['ok'] and _journal() == {}


def test_values_written_to_the_active_plan_take_effect_and_are_undone():
    # Windows 는 활성 플랜에 쓴 세부값을 그 플랜을 다시 켜야 적용한다. 다시 켜지 않으면 화면은 '적용·검증됨' 인데
    # 실제로는 걸리지 않고, 되돌린 뒤에도 바뀐 값이 계속 걸려 있다
    POWER.seed_value(fakewin.PLAN_BALANCED, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 5)
    assert ss.set_power_value(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 100, group='t')['ok']
    assert POWER.effective(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN) == 100
    assert ss.restore_group('t')['ok']
    assert POWER.effective(ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN) == 5
