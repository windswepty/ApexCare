"""원클릭 최적화: 실행 전에 보여 주는 계획과 실제로 하는 일이 같고, 되돌릴 수 없는 삭제 전에 확인을 받는다."""

import os
import re

import pytest

from backend import optimizer, system_repair
from tests.conftest import ROOT


@pytest.fixture
def recorded(monkeypatch):
    """원클릭의 각 단계를 실제로 돌리지 않고 기록만 한다."""
    calls = {}

    def clean(categories, cancel_event=None):
        calls['junk'] = list(categories)
        optimizer._junk_clean_state.update(status='success', freed_mb=1.5)
    monkeypatch.setattr(optimizer, 'clean_junk_background', clean)
    monkeypatch.setattr(optimizer, 'purge_ram', lambda: calls.setdefault('ram', True) and {'success': True})
    monkeypatch.setattr(system_repair, 'run_network_optimization_sync',
                        lambda: calls.setdefault('dns', True) and {'success': True})
    monkeypatch.setattr(system_repair, 'run_trim', lambda: calls.setdefault('trim', True) and {'success': False})
    monkeypatch.setattr(system_repair, 'get_trim_status', lambda: {'status': 'error', 'error': '테스트'})
    return calls


def test_one_click_does_exactly_what_the_plan_says(recorded):
    plan = optimizer.get_deep_optimization_plan()

    optimizer._run_deep_optimization()

    st = optimizer.get_deep_optimization_status()
    assert [s['name'] for s in st['steps']] == [p['name'] for p in plan['steps']]
    assert set(recorded) == {p['id'] for p in plan['steps']}


def test_one_click_skips_windows_update_cache_and_prefetch(recorded):
    optimizer._run_deep_optimization()
    # 1 = 임시 파일, 2 = Chrome 캐시. 3(Windows Update 캐시)·4(Prefetch)·5(휴지통)는 저장공간 화면에서만
    assert recorded['junk'] == [1, 2]
    excluded = optimizer.get_deep_optimization_plan()['excluded']
    assert {'Windows Update 다운로드 캐시', 'Prefetch', '휴지통'} <= set(excluded)


def test_dashboard_asks_before_starting():
    with open(os.path.join(ROOT, 'src', 'components', 'Dashboard.jsx'), encoding='utf-8') as f:
        src = f.read()
    body = src[src.index('const startMasterOptimization'):]
    body = body[:body.index('\n  };\n')]
    assert 'getDeepOptimizationPlan' in body
    confirm_at = body.index('window.confirm(')
    assert confirm_at < body.index('startDeepOptimization()')
    # 확인을 거절하면 시작하지 않는다
    assert re.search(r'if \(!window\.confirm\([^;]*\)\) return;', body, re.S)
    # 확인 창을 기다리는 동안 두 번째 클릭은 들어오지 않고, '이미 실행 중' 은 실패가 아니라 진행 화면을 따라간다
    run = src[src.index('const runMasterOptimization'):]
    run = run[:run.index('\n  };\n')]
    assert 'startingRef.current) return;' in run and 'startMasterOptimization()' in run
    assert body.index('res?.busy') < body.index("title: '시작 실패'")


def test_stopping_keeps_finished_steps_and_freed_space(recorded, monkeypatch):
    # 정크 정리를 마친 뒤 중지했다. 예전에는 예외 문자열만 남고 지운 용량·단계가 사라졌다.
    def clean(categories, cancel_event=None):
        optimizer._junk_clean_state.update(status='success', freed_mb=12.5)
        optimizer._cancel_event.set()
    monkeypatch.setattr(optimizer, 'clean_junk_background', clean)

    optimizer._run_deep_optimization()

    st = optimizer.get_deep_optimization_status()
    assert st['cancelled'] is True and st['error'] is None and st['running'] is False
    assert [s['name'] for s in st['steps']] == ['임시 파일·브라우저 캐시 정리']
    assert st['freed_mb'] == 12.5
    assert '중지됨' in st['current_task'] and '되돌아오지 않습니다' in st['current_task']


def test_disk_optimization_still_running_is_not_counted_as_failure(recorded, monkeypatch):
    monkeypatch.setattr(system_repair, 'run_trim', lambda: {'success': True})
    monkeypatch.setattr(system_repair, 'get_trim_status', lambda: {'status': 'running', 'error': None})
    monkeypatch.setattr(optimizer, 'TRIM_WAIT_SEC', 0)

    optimizer._run_deep_optimization()

    st = optimizer.get_deep_optimization_status()
    trim = st['steps'][-1]
    assert trim['ok'] is False and trim['pending'] is True        # 성공으로 보이지도, 실패로 세지도 않는다
    assert st['failedCount'] == 0 and st['pendingCount'] == 1
    assert '실패' not in st['current_task'] and '진행 중' in st['current_task']


def test_dashboard_shows_steps_even_when_stopped():
    with open(os.path.join(ROOT, 'src', 'components', 'Dashboard.jsx'), encoding='utf-8') as f:
        src = f.read()
    # 중지·오류도 finishOptimization 으로 단계 결과를 보여 주고, 진행 중 단계는 실패로 세지 않는다
    assert "status.error.includes" not in src
    assert '!st.ok && !st.pending' in src


def test_junk_step_that_stopped_or_skipped_is_not_shown_as_success(recorded, monkeypatch):
    def stopped(categories, cancel_event=None):
        optimizer._junk_clean_state.update(status='cancelled', freed_mb=35.2, warnings=[])
    monkeypatch.setattr(optimizer, 'clean_junk_background', stopped)
    optimizer._run_deep_optimization()
    junk = optimizer.get_deep_optimization_status()['steps'][0]
    assert junk['ok'] is False and junk['cancelled'] is True and '중지됨' in junk['detail']

    def skipped(categories, cancel_event=None):
        optimizer._junk_clean_state.update(status='success', freed_mb=12.0,
                                           warnings=['임시 폴더 위치가 안전하지 않아 정리하지 않았습니다: R:\\ (드라이브 루트)'])
    monkeypatch.setattr(optimizer, 'clean_junk_background', skipped)
    optimizer._run_deep_optimization()
    junk = optimizer.get_deep_optimization_status()['steps'][0]
    assert junk['ok'] is False and junk['partial'] is True and '건너뜀' in junk['detail']
