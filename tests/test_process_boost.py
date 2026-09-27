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
