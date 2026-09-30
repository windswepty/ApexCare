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
        if threading.get_ident() == me and interval is not None:   # 1초 측정만 센다(오래된 값 대체용 즉시 호출은 제외)
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


def test_stale_cpu_usage_is_not_shown_as_a_measurement(monkeypatch):
    # 수집기가 쉬는 동안 남은 옛 값을 대시보드가 막 열렸을 때 보여 주지 않는다.
    # 예전에는 이때 psutil.cpu_percent(interval=None) 을 불렀는데, psutil 7 은 기준점을 스레드마다 두고
    # pywebview 는 요청마다 새 스레드를 쓰므로 늘 0% 가 나왔다. 이제 '측정 중'(None)이다.
    calls = []
    monkeypatch.setattr(system_monitor, '_cpu_usage', 88)
    monkeypatch.setattr(system_monitor, '_cpu_sample', [real_time.time() - 60])
    monkeypatch.setattr(system_monitor.psutil, 'cpu_percent', lambda interval=None: calls.append(interval) or 0.0)
    assert system_monitor._fresh_cpu_usage() is None and calls == []
    monkeypatch.setattr(system_monitor, '_cpu_sample', [real_time.time()])
    assert system_monitor._fresh_cpu_usage() == 88


def test_psutil_cpu_percent_baseline_is_per_thread():
    # 위 테스트가 왜 필요한지의 근거: 다른 스레드에서 처음 부르면 기준점이 없어 의미 없는 값이 나온다.
    import psutil
    src = __import__('inspect').getsource(psutil.cpu_percent)
    assert '_last_cpu_times.get(tid)' in src


def test_gpu_usage_is_the_busiest_adapter_not_the_sum_of_all():
    s = {
        'pid_100_luid_0x00000000_0x0000A1_phys_0_eng_0_engtype_3D': 30.0,
        'pid_200_luid_0x00000000_0x0000A1_phys_0_eng_0_engtype_3D': 20.0,     # 외장: 50
        'pid_300_luid_0x00000000_0x0000B2_phys_0_eng_0_engtype_3D': 40.0,     # 내장: 40
        'pid_300_luid_0x00000000_0x0000B2_phys_0_eng_3_engtype_VideoDecode': 90.0,
    }
    assert system_monitor.gpu_3d_usage(s) == 50           # 예전 방식(전부 합)은 90
    assert system_monitor.gpu_3d_usage({}) == 0
    assert system_monitor.gpu_3d_usage({'pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D': 170.0}) == 100


def test_gpu_usage_is_none_until_measured_and_when_unavailable(monkeypatch):
    monkeypatch.setattr(system_monitor, '_gpu_usage', 42)
    monkeypatch.setattr(system_monitor, '_gpu_state', 'ok')
    monkeypatch.setattr(system_monitor, '_gpu_sample', [real_time.time() - 60])
    assert system_monitor._fresh_gpu_usage() is None          # 오래된 값
    monkeypatch.setattr(system_monitor, '_gpu_sample', [real_time.time()])
    assert system_monitor._fresh_gpu_usage() == 42
    monkeypatch.setattr(system_monitor, '_gpu_state', 'unavailable')
    assert system_monitor._fresh_gpu_usage() is None          # 이 PC 에서는 읽을 수 없음(0% 로 꾸미지 않음)


def test_failed_stats_are_not_filled_with_zeros(monkeypatch):
    from backend.api import Api
    monkeypatch.setattr(system_monitor, 'get_system_stats', lambda: None)
    r = Api.getSystemStats(None)
    assert r.get('error') and 'cpuUsage' not in r and 'ramTotalGB' not in r
    dash = _read('src/components/Dashboard.jsx')
    assert 'useState(0)' not in dash.split('const [totalFreed')[0] + dash.split('const [totalFreed')[1].split('\n', 1)[1]
    assert 'fill(0)' not in dash and 'stats.cpuUsage || 0' not in dash


def test_numbers_shown_match_their_meaning():
    # GPU 사용률은 엔진·프로세스별 값의 합이라 100 을 넘을 수 있다
    assert '_gpu_usage = min(100, round(usage))' in _read('backend/system_monitor.py')
    # 정크 정리 진행률은 끝낸 대상 수로만 오른다(임의의 최대 파일 수로 나누지 않는다)
    opt = _read('backend/optimizer.py')
    assert '/ max_files' not in opt and "int((i + 1) * 100 / max(steps_total, 1))" in opt
    # 설치 메모리(16GB)와 Windows 가 쓸 수 있는 메모리(15.4GB)를 구분해 보여 준다
    assert "'ramInstalledGB': installed_ram_gb()" in _read('backend/system_monitor.py')
    assert 'ramInstalledGB' in _read('src/components/Dashboard.jsx')
