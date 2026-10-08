"""
pytest 가 가장 먼저 읽는 파일. 순서가 곧 안전장치다.

  1. import_guard.install()  fakewin 없이 backend 를 import 하면 ImportError 가 나게 막는다
  2. fakewin.install()       가짜 Windows 를 끼우고 backend 를 import 한다
  3. fake_windows 픽스처      테스트마다 가짜가 제자리에 있는지 확인하고 상태를 비운다

1 이 2 보다 먼저라서, 2 가 빠지거나 실패하면 backend 를 쓰는 테스트는 수집 단계에서 전부 실패한다.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests import import_guard  # noqa: E402

import_guard.install()

from tests import fakewin  # noqa: E402

fakewin.install()


def _reset_backend_state():
    from backend import game_booster, optimizer, process_boost, process_guard

    process_boost._original.clear()
    process_guard._family_cache.update(pids=None, ts=0.0)

    game_booster._applied.clear()
    game_booster._tamed_pids = set()
    game_booster._stop_event.clear()
    game_booster._booster_state.update(
        enabled=False, active=False, detected_game=None, boosted_pids=[],
        timer_resolution_set=False, nagle_disabled=False, appliedBoosts=[])

    optimizer._junk_scan_state.update(status='idle', data=[], progress=0, eta_seconds=0)
    optimizer._junk_clean_state.clear()
    optimizer._junk_clean_state.update(status='idle', freed_mb=0.0, error=None,
                                       progress=0, eta_seconds=0)


@pytest.fixture(autouse=True)
def fake_windows():
    fakewin.check()
    fakewin.reset()
    _reset_backend_state()
    yield fakewin
    # 테스트가 가짜를 빼 버렸으면 다음 테스트가 진짜 시스템을 쓸 수 있다. 여기서 끊는다.
    fakewin.check()


@pytest.fixture
def as_admin(monkeypatch):
    """perf_modes 는 관리자가 아니면 아무것도 하지 않는다. 가짜 환경에서는 관리자인 척한다."""
    from backend import perf_modes
    monkeypatch.setattr(perf_modes, 'is_admin', lambda: True)


@pytest.fixture
def procs(monkeypatch):
    """psutil.Process / process_iter 를 가짜 프로세스 표로 바꾼다."""
    return fakewin.FakeProcessTable().install(monkeypatch)
