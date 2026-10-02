"""process_boost: 원래 우선순위 기록·복구, PID 재사용, 사용자가 바꾼 것은 남긴다."""

from backend import game_booster, process_boost
from tests.fakewin import (BELOW_NORMAL_PRIORITY_CLASS, HIGH_PRIORITY_CLASS, IDLE_PRIORITY_CLASS,
                           NORMAL_PRIORITY_CLASS)


def test_restore_returns_exact_original_priority(procs):
    procs.add(100, 'render.exe', nice=BELOW_NORMAL_PRIORITY_CLASS)
    assert process_boost.set_priority(100, 'idle', owner='boost')['ok']
    assert procs.procs[100].nice == IDLE_PRIORITY_CLASS
    assert process_boost.restore(100)['ok']
    assert procs.procs[100].nice == BELOW_NORMAL_PRIORITY_CLASS     # NORMAL 이 아니라 원래 값


def test_pid_reuse_is_not_restored(procs):
    procs.add(100, 'app.exe', nice=NORMAL_PRIORITY_CLASS, created=1000.0)
    assert process_boost.set_priority(100, 'idle', owner='boost')['ok']

    # 앱이 끝나고 같은 PID 를 다른 프로세스가 물려받았다
    procs.remove(100)
    newcomer = procs.add(100, 'other.exe', nice=HIGH_PRIORITY_CLASS, created=2000.0)
    calls_before = list(procs.nice_calls)

    r = process_boost.restore(100)

    assert r['ok']
    assert newcomer.nice == HIGH_PRIORITY_CLASS
    assert procs.nice_calls == calls_before
    assert process_boost.adjusted_count() == 0


def test_snapshot_of_reused_pid_records_new_original(procs):
    procs.add(100, 'app.exe', nice=NORMAL_PRIORITY_CLASS, created=1000.0)
    process_boost.set_priority(100, 'idle', owner='boost')
    procs.remove(100)
    procs.add(100, 'other.exe', nice=HIGH_PRIORITY_CLASS, created=2000.0)
    # 새 프로세스에 대한 기록은 옛 프로세스의 원래 값(NORMAL)이 아니라 HIGH 여야 한다
    assert process_boost.set_priority(100, 'idle', owner='boost')['ok']
    process_boost.restore(100)
    assert procs.procs[100].nice == HIGH_PRIORITY_CLASS


def test_user_change_survives_game_end(procs):
    procs.add(200, 'chrome.exe', nice=NORMAL_PRIORITY_CLASS)
    procs.add(201, 'backup.exe', nice=BELOW_NORMAL_PRIORITY_CLASS)
    tamed = game_booster._tame_processes([200, 201])
    assert set(tamed) == {200, 201}
    game_booster._tamed_pids = set(tamed)

    # 게임 도중 사용자가 게이밍 탭에서 chrome 을 직접 '높음' 으로 바꿨다
    assert process_boost.set_priority(200, 'high', owner='user')['ok']
    assert process_boost.owner_of(200) == 'user'

    game_booster._teardown()

    assert procs.procs[200].nice == HIGH_PRIORITY_CLASS             # 사용자의 선택은 남는다
    assert procs.procs[201].nice == BELOW_NORMAL_PRIORITY_CLASS     # 부스트가 바꾼 것은 원래대로


def test_game_process_boost_is_undone(procs):
    procs.add(300, 'cs2.exe', nice=NORMAL_PRIORITY_CLASS)
    game_booster._booster_state['boosted_pids'] = [300]
    game_booster._booster_state['active'] = True
    assert game_booster._boost_game_processes([300]) == 1
    assert procs.procs[300].nice == HIGH_PRIORITY_CLASS
    game_booster._teardown()
    assert procs.procs[300].nice == NORMAL_PRIORITY_CLASS


def test_protected_and_own_processes_are_refused(procs):
    import os
    procs.add(400, 'csrss.exe')
    procs.add(os.getpid(), 'python.exe')
    assert process_boost.set_priority(400, 'idle')['ok'] is False
    assert process_boost.set_priority(os.getpid(), 'idle')['ok'] is False
    assert procs.nice_calls == []


def test_access_denied_is_reported_as_failure(procs):
    p = procs.add(500, 'app.exe')
    p.deny = True
    r = process_boost.set_priority(500, 'idle')
    assert r['ok'] is False and p.nice == NORMAL_PRIORITY_CLASS


def test_child_spawned_after_family_was_cached_is_still_own(procs):
    # 샌드박스 점검에서 찾은 틈: 가족 목록을 캐시한 뒤 2초 안에 생긴 자식을 자기 프로세스로 못 알아봤다
    import os
    from backend import process_guard
    me = os.getpid()
    procs.add(me, 'python.exe')
    procs.add(700, 'ping.exe')                                   # 남의 프로세스
    assert process_boost.set_priority(700, 'high')['ok']         # 이때 가족 목록이 캐시된다
    procs.add(701, 'ping.exe', ppid=me)                          # 캐시 뒤에 생긴 우리 자식
    procs.add(702, 'helper.exe', ppid=701)                       # 그 자식의 자식
    assert process_guard.is_own_process(701) and process_guard.is_own_process(702)
    assert process_boost.set_priority(701, 'high')['ok'] is False
    assert process_boost.set_priority(702, 'idle')['ok'] is False
    assert not process_guard.is_own_process(700)


# ── 감사에서 나온 것: CPU 기준·지금 쓰는 앱·사용자 선택·EcoQoS·비정상 종료 ─────────

def _candidates(procs, fg=None, seconds=2.0):
    process_boost.prime_cpu_measurement()
    procs.tick(seconds)
    return {c['pid'] for c in process_boost.find_throttle_candidates(fg, cpu_threshold=3.0)}


def test_busy_threshold_uses_task_manager_units(procs):
    procs.cpus = 16
    procs.add(800, 'idle_app.exe', cpu=0.3)        # 작업 관리자 0.3% (예전 기준이면 코어 단위 4.8% 로 '바쁨')
    procs.add(801, 'encoder.exe', cpu=6.0)         # 작업 관리자 6%
    assert _candidates(procs) == {801}


def test_first_short_sample_is_not_used(procs):
    procs.add(802, 'encoder.exe', cpu=50.0)
    assert _candidates(procs, seconds=0.2) == set()          # 1초도 안 된 구간으로 판정하지 않는다


def test_foreground_app_and_its_helpers_are_not_tamed(procs):
    procs.add(810, 'chrome.exe', cpu=1.0, exe=r'C:\Chrome\chrome.exe')            # 창을 가진 프로세스
    procs.add(811, 'chrome.exe', cpu=20.0, ppid=810, exe=r'C:\Chrome\chrome.exe')  # 렌더러(자식)
    procs.add(812, 'chrome.exe', cpu=20.0, exe=r'C:\Chrome\chrome.exe')            # GPU(같은 실행 파일)
    procs.add(813, 'other.exe', cpu=20.0, exe=r'C:\Other\other.exe')
    assert _candidates(procs, fg=810) == {813}


def test_user_choice_is_not_overridden_by_boost(procs):
    procs.add(820, 'render.exe', cpu=30.0)
    assert process_boost.set_priority(820, 'high', owner='user')['ok']
    assert 820 not in _candidates(procs)
    r = process_boost.set_priority(820, 'idle', owner='boost')
    assert r['ok'] is False and procs.procs[820].nice == HIGH_PRIORITY_CLASS


def test_refused_change_leaves_no_record_and_says_why(procs):
    p = procs.add(830, 'av.exe')
    p.deny = True
    r = process_boost.set_priority(830, 'idle', owner='boost')
    assert r['ok'] is False and '보호된 프로세스' in r['reason'] and '관리자 권한으로 실행' not in r['reason']
    assert process_boost.adjusted_count() == 0               # 예전에는 '조정된 프로세스 1개' 가 남았다


def test_restore_releases_ecoqos_only_for_the_same_process(procs, monkeypatch):
    calls = []
    monkeypatch.setattr(game_booster, '_set_process_power_throttling', lambda pid, v: calls.append((pid, v)) or True)
    procs.add(840, 'chrome.exe', created=1000.0)
    procs.add(841, 'backup.exe', created=1000.0)
    assert set(game_booster._tame_processes([840, 841])) == {840, 841}

    assert process_boost.restore_all()['restored'] == 2
    assert (840, None) in calls and (841, None) in calls      # '되돌리기' 가 효율 모드도 풀어 준다

    calls.clear()
    game_booster._tame_processes([840])
    procs.remove(840)
    procs.add(840, 'svchost.exe', created=2000.0, username='SYSTEM')   # PID 를 다른 프로세스가 물려받았다
    game_booster._restore_processes([840])
    assert (840, None) not in calls                           # 무관한 프로세스의 효율 모드를 건드리지 않는다


def test_crash_leftovers_are_restored_on_next_start(procs, monkeypatch):
    monkeypatch.setattr(game_booster, '_set_process_power_throttling', lambda pid, v: True)
    procs.add(850, 'chrome.exe', nice=BELOW_NORMAL_PRIORITY_CLASS)
    game_booster._tame_processes([850])
    assert procs.procs[850].nice == IDLE_PRIORITY_CLASS

    process_boost._original.clear()                           # 앱이 비정상 종료됐다(메모리 기록이 사라짐)
    n, bad = process_boost.recover_after_crash()

    assert n == 1 and bad == []
    assert procs.procs[850].nice == BELOW_NORMAL_PRIORITY_CLASS   # IDLE 이 '원래 값' 으로 굳지 않는다
    assert process_boost.recover_after_crash() == (0, [])     # 기록은 정리됐다


def test_messenger_call_apps_are_never_tamed(procs):
    procs.add(860, 'KakaoTalk.exe', cpu=40.0)
    procs.add(861, 'Telegram.exe', cpu=40.0)
    assert _candidates(procs) == set()


def test_guard_runs_only_for_busy_apps(procs, monkeypatch):
    # 관문은 부모 프로세스를 거슬러 올라가며 프로세스 목록 전체를 다시 읽는다. 바쁘지 않은 앱마다 부르면 게임 중
    # 5초마다 몇 초씩 CPU 를 썼다.
    from backend import process_guard
    checked = []
    real = process_guard.check_controllable
    monkeypatch.setattr(process_guard, 'check_controllable',
                        lambda pid, action='kill': checked.append(pid) or real(pid, action))
    for pid in range(870, 880):
        procs.add(pid, f'quiet{pid}.exe', cpu=0.1)
    procs.add(880, 'encoder.exe', cpu=20.0)
    assert _candidates(procs) == {880}
    assert checked == [880]


def test_user_choice_on_a_tamed_app_also_releases_efficiency_mode(procs, monkeypatch):
    calls = []
    monkeypatch.setattr(game_booster, '_set_process_power_throttling', lambda pid, v: calls.append((pid, v)) or True)
    procs.add(890, 'chrome.exe', created=1000.0)
    assert game_booster._tame_processes([890]) == [890]
    calls.clear()

    assert process_boost.set_priority(890, 'high', owner='user')['ok']     # 사용자가 게이밍 탭에서 '높음'

    assert (890, None) in calls                                # 예전에는 효율 모드에 묶인 채 남았다
    assert not process_boost._original[890].get('ecoqos')


def test_tampered_crash_record_is_not_applied(procs, monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(game_booster, '_set_process_power_throttling', lambda pid, v: True)
    procs.add(900, 'busy.exe', created=1000.0)
    procs.add(901, 'dwm.exe', created=1000.0)
    procs.add(902, 'app.exe', nice=IDLE_PRIORITY_CLASS, created=1000.0)
    path = process_boost._state_path()
    with open(path, 'w', encoding='utf-8') as f:
        # 같은 계정의 일반 권한 프로그램이 써 넣은 기록: 실시간 우선순위, 보호된 시스템 프로세스, 사용자 기록
        json.dump({'900': {'priority': 0x100, 'created': 1000.0, 'name': 'busy.exe', 'owner': 'boost'},
                   '901': {'priority': IDLE_PRIORITY_CLASS, 'created': 1000.0, 'name': 'dwm.exe', 'owner': 'boost'},
                   '902': {'priority': HIGH_PRIORITY_CLASS, 'created': 1000.0, 'name': 'app.exe', 'owner': 'user'}}, f)

    n, bad = process_boost.recover_after_crash()

    assert n == 0 and len(bad) == 3
    assert procs.nice_calls == []                              # 관리자 권한으로 아무것도 바꾸지 않았다


def test_priority_change_is_refused_when_listed_process_was_replaced(procs):
    procs.add(910, 'build.exe', created=1000.0)
    procs.remove(910)
    procs.add(910, 'other.exe', created=2000.0)                # 목록을 본 뒤 같은 번호를 다른 프로그램이 받았다

    r = process_boost.set_priority(910, 'idle', owner='user', created=1000.0)

    assert r['ok'] is False and '같은 번호' in r['reason'] and procs.nice_calls == []
    assert process_boost.set_priority(910, 'idle', owner='user', created=2000.0)['ok']
