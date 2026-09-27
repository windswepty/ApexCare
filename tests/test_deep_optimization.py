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
    body = src[src.index('const runMasterOptimization'):]
    body = body[:body.index('\n  };\n')]
    assert 'getDeepOptimizationPlan' in body
    confirm_at = body.index('window.confirm(')
    assert confirm_at < body.index('startDeepOptimization()')
    # 확인을 거절하면 시작하지 않는다
    assert re.search(r'if \(!window\.confirm\([^;]*\)\) return;', body, re.S)
