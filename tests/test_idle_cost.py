"""가만히 있을 때 앱이 쓰는 CPU·메모리: 보지 않는 화면과 쉬는 창이 백엔드를 계속 깨우지 않는다.

예전에는 모든 탭이 처음부터 떠서 숨긴 탭까지 2~5초마다 프로세스 목록 등을 불렀고, 부드러운 스크롤이
requestAnimationFrame 을 초당 60번 영원히 돌렸으며, CPU·GPU 수집 스레드가 1초마다 강제 가비지 컬렉션을 했다.
"""

import os
import re
import threading
import time as real_time

from backend import system_monitor
from tests.conftest import ROOT


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


# ── 백엔드 ─────────────────────────────────────

def test_cpu_collector_rests_until_the_screen_asks(monkeypatch):
    me = threading.get_ident()
    calls = []

    class Clock:
        time = staticmethod(real_time.time)

        @staticmethod
        def sleep(s):
            if threading.get_ident() != me:        # 뒤에서 도는 수집 스레드는 그대로 잔다
                real_time.sleep(s)

    def cpu_percent(interval=None):
        if threading.get_ident() == me:
            calls.append(interval)
        return 7.0

    monkeypatch.setattr(system_monitor, 'time', Clock)
    monkeypatch.setattr(system_monitor.psutil, 'cpu_percent', cpu_percent)
    monkeypatch.setattr(system_monitor, '_last_demand', 0.0)

    assert system_monitor._cpu_tick() is False and calls == []

    system_monitor.get_system_stats()                    # 화면이 값을 요청했다
    assert system_monitor._wanted()
    assert system_monitor._cpu_tick() is True and calls == [1]

    monkeypatch.setattr(system_monitor, '_last_demand', real_time.time() - system_monitor._DEMAND_WINDOW_SEC - 1)
    assert system_monitor._cpu_tick() is False and calls == [1]


def test_gpu_collector_checks_demand_before_reading_counters():
    src = _read('backend/system_monitor.py')
    loop = src[src.index('def _gpu_poller'):src.index('# Start GPU poller')]
    assert loop.index('if not _wanted():') < loop.index('CollectQueryData(hq)', loop.index('while True'))


def test_no_forced_garbage_collection_in_loops():
    for f in os.listdir(os.path.join(ROOT, 'backend')):
        if f.endswith('.py'):
            assert 'gc.collect()' not in _read(os.path.join('backend', f)).replace('(gc.collect)', ''), f


# ── 화면 ───────────────────────────────────────

POLLING_TABS = {'Dashboard': 'dashboard', 'RestoreCenter': 'restore', 'RamBooster': 'ram', 'GameBooster': 'gamebooster'}


def test_hidden_tabs_do_not_poll():
    app = _read('src/App.jsx')
    for comp, tab in POLLING_TABS.items():
        assert re.search(rf"<{comp} active={{activeTab === '{tab}'}}", app), comp
        src = _read(f'src/components/{comp}.jsx')
        assert 'usePolling(' in src and re.search(r'usePolling\([^)]*\bactive\b', src), comp
    for comp in ('RamBooster', 'GameBooster', 'RestoreCenter'):
        assert 'setInterval' not in _read(f'src/components/{comp}.jsx'), comp


def test_tabs_mount_on_first_visit():
    # 열지 않은 탭이 앱 시작 때 프로그램 목록·드라이브 조회(PowerShell) 등을 부르지 않게 한다
    app = _read('src/App.jsx')
    tabs = re.findall(r"display: activeTab === '([a-z]+)' \? 'block' : 'none'", app)
    assert len(tabs) >= 10
    for tab in tabs:
        assert f"{{isMounted('{tab}') && <" in app, tab
    assert "new Set(['dashboard'])" in app


def test_polling_pauses_while_window_is_hidden():
    src = _read('src/usePolling.js')
    assert 'document.hidden' in src and 'visibilitychange' in src
    assert 'if (!enabled) return' in src
    header = _read('src/components/Header.jsx')
    assert '!document.hidden' in header


def test_smooth_scroll_runs_frames_only_while_scrolling():
    for rel in ('src/App.jsx', 'src/components/Sidebar.jsx'):
        src = _read(rel)
        assert 'requestAnimationFrame' not in src and 'new Lenis' not in src, rel
        assert 'attachSmoothScroll(' in src, rel
    src = _read('src/smoothScroll.js')
    # 애니메이션이 끝나면 다음 프레임을 예약하지 않는다
    assert 'lenis.animate.isRunning ? requestAnimationFrame(loop) : null' in src
    assert "lenis.on('virtual-scroll', start)" in src
    assert 'autoRaf' not in src


# ── CPU 실제 속도 ───────────────────────────────

def test_clock_is_base_times_processor_performance():
    assert system_monitor.clock_from(3800, 120.0) == 4560          # 부스트 중
    assert system_monitor.clock_from(3800, 70.0) == 2660           # 에코(상한 70%)
    for base, pct in ((None, 100), (0, 100), (3800, None), (3800, 0)):
        assert system_monitor.clock_from(base, pct) is None         # 모르면 지어내지 않는다


def test_clock_is_measured_only_when_the_screen_asks(monkeypatch):
    me = threading.get_ident()
    sampled = []

    class Clock:
        time = staticmethod(real_time.time)

        @staticmethod
        def sleep(s):
            if threading.get_ident() != me:
                real_time.sleep(s)

    monkeypatch.setattr(system_monitor, 'time', Clock)
    monkeypatch.setattr(system_monitor.psutil, 'cpu_percent', lambda interval=None: 3.0)
    monkeypatch.setattr(system_monitor, '_sample_clock',
                        lambda: sampled.append(threading.get_ident()) or 4321)
    monkeypatch.setattr(system_monitor, '_last_demand', 0.0)

    system_monitor._cpu_tick()
    assert me not in sampled
    system_monitor.note_demand()
    system_monitor._cpu_tick()
    assert me in sampled and system_monitor._cpu_clock_mhz == 4321
    assert system_monitor.get_system_stats() is None or 'cpuClockMHz' in system_monitor.get_system_stats()


def test_stats_report_clock_fields():
    src = _read('backend/system_monitor.py')
    assert "'cpuClockMHz': _cpu_clock_mhz" in src and "'cpuBaseMHz': cpu_base_mhz()" in src
    assert 'cpuClockMHz' in _read('src/components/Header.jsx')
    assert 'cpuClockMHz' in _read('src/components/PerformanceModes.jsx')
