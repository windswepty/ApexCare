"""성능 모드 비교용 CPU 측정: 계산만 하고 시스템은 바꾸지 않으며, 결과를 모드별로 남긴다."""

import pytest

from backend import config_manager, perf_bench, perf_modes
from tests.fakewin import POWER, REGISTRY, SERVICES


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(perf_bench, 'BENCH_SECONDS', 0.05)
    real = perf_bench._measure
    monkeypatch.setattr(perf_bench, '_measure', lambda s: real(min(s, 0.05)))


def test_bench_records_score_per_mode_and_changes_nothing(quick):
    config_manager.set_optimization_mode('eco', user_set=True)
    power_before = (POWER.active, dict(POWER.values))

    r = perf_bench.run(0.05)

    assert r['success'] and r['mode'] == 'eco' and r['result']['score'] > 0
    assert perf_bench.get_results()['eco']['score'] == r['result']['score']
    # 계산만 한다: 전원·레지스트리·서비스는 그대로
    assert (POWER.active, dict(POWER.values)) == power_before
    assert REGISTRY.writes == [] and SERVICES.calls == []

    config_manager.set_optimization_mode('gaming', user_set=True)
    perf_bench.run(0.05)
    assert set(perf_bench.get_results()) == {'eco', 'gaming'}
    assert config_manager.get_optimization_mode() == 'gaming'      # 측정이 저장된 모드를 덮지 않는다


def test_second_run_while_measuring_is_refused(quick):
    assert perf_bench._lock.acquire(blocking=False)
    try:
        r = perf_bench.run(0.05)
        assert r['success'] is False and r['busy'] is True
    finally:
        perf_bench._lock.release()


def test_mode_comes_from_backend_not_screen(quick, monkeypatch):
    monkeypatch.setattr(perf_modes, 'get_mode', lambda: {'mode': 'standard'})
    assert perf_bench.run(0.05)['mode'] == 'standard'
