"""성능 모드 비교용 CPU 측정: 계산만 하고 시스템은 바꾸지 않으며, 결과를 모드별로 남긴다."""

import pytest

from backend import config_manager, perf_bench, perf_modes
from tests.fakewin import POWER, REGISTRY, SERVICES


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(perf_bench, 'BENCH_SECONDS', 0.05)
    real = perf_bench._measure
    monkeypatch.setattr(perf_bench, '_measure', lambda s: real(min(s, 0.05)))


def _mode_is(monkeypatch, mode, **extra):
    """perf_modes.get_mode 가 돌려줄 '지금 걸린 모드'. 실제로 모드를 적용하지 않고 측정만 시험한다."""
    info = {'mode': mode, 'inSync': True, 'boostOverride': False}
    info.update(extra)
    monkeypatch.setattr(perf_modes, 'get_mode', lambda: dict(info))


def test_bench_records_score_per_mode_and_changes_nothing(quick, monkeypatch):
    config_manager.set_optimization_mode('eco', user_set=True)
    _mode_is(monkeypatch, 'eco')
    power_before = (POWER.active, dict(POWER.values))

    r = perf_bench.run(0.05)

    assert r['success'] and r['mode'] == 'eco' and r['result']['score'] > 0
    assert perf_bench.get_results()['eco']['score'] == r['result']['score']
    # 계산만 한다: 전원·레지스트리·서비스는 그대로
    assert (POWER.active, dict(POWER.values)) == power_before
    assert REGISTRY.writes == [] and SERVICES.calls == []

    config_manager.set_optimization_mode('gaming', user_set=True)
    _mode_is(monkeypatch, 'gaming')
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


def test_result_goes_to_the_mode_that_is_really_applied(quick, monkeypatch):
    # 저장된 모드는 에코인데 게임 부스트가 게임 동안 게이밍을 쓰는 중이면, 그 측정은 게이밍 결과다
    _mode_is(monkeypatch, 'eco', boostOverride=True)
    assert perf_bench.run(0.05)['mode'] == 'gaming'
    assert 'eco' not in perf_bench.get_results()


def test_no_result_is_recorded_when_the_real_mode_is_unknown(quick, monkeypatch):
    # 앱 밖에서 전원 플랜이 바뀌었으면 어느 모드의 결과인지 모른다. 틀린 칸에 남기지 않는다.
    _mode_is(monkeypatch, 'gaming', inSync=False)
    r = perf_bench.run(0.05)
    assert r['success'] is False and '모드' in r['message']
    assert perf_bench.get_results() == {}
