"""화면에 보이는 숫자·상태가 실제와 같은지. 2026-09 전체 점검에서 찾은 표기 오류의 회귀 테스트.

하나하나가 '고친 부분을 되돌리면 실패하는지' 를 기준으로 쓴다.
"""

import os
import re
import types

import pytest

from backend import (file_finder, game_booster, optimizer, process_boost, system_monitor, system_repair,
                     uninstaller)
from backend import system_state as ss
from tests import fakewin
from tests.conftest import ROOT
from tests.fakewin import NORMAL_PRIORITY_CLASS, REG_SZ, REGISTRY

MB = 1024 * 1024


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _code(rel):
    """주석을 뺀 소스. 옛 문구를 설명하는 주석에 문구 검사가 걸리지 않게 한다."""
    src = re.sub(r'/\*.*?\*/', '', _read(rel), flags=re.S)
    return re.sub(r'(?m)^\s*//.*$|\s//\s.*$', '', src)


# ── 시스템 정보 ────────────────────────────────────────

def test_gpu_name_prefers_discrete_over_integrated_and_virtual():
    # 예전에는 WMI 가 처음 준 이름을 썼다. 노트북은 내장 그래픽이, 원격 도구를 깐 PC 는 가상 어댑터가 보였다.
    assert system_monitor.pick_gpu_name(
        ['Intel(R) UHD Graphics 630', 'NVIDIA GeForce RTX 4060 Laptop GPU']) == 'NVIDIA GeForce RTX 4060 Laptop GPU'
    assert system_monitor.pick_gpu_name(
        ['Microsoft Basic Display Adapter', 'AMD Radeon(TM) 780M Graphics']) == 'AMD Radeon(TM) 780M Graphics'
    assert system_monitor.pick_gpu_name(
        ['Parsec Virtual Display Adapter', 'AMD Radeon RX 7800 XT', 'AMD Radeon(TM) Graphics']) == 'AMD Radeon RX 7800 XT'
    # Intel Arc A 시리즈는 외장이다
    assert system_monitor.pick_gpu_name(
        ['Intel(R) UHD Graphics 770', 'Intel(R) Arc(TM) A770 Graphics']) == 'Intel(R) Arc(TM) A770 Graphics'
    assert system_monitor.pick_gpu_name(['Intel(R) Iris(R) Xe Graphics']) == 'Intel(R) Iris(R) Xe Graphics'
    assert system_monitor.pick_gpu_name([]) is None


def test_dashboard_free_space_comes_from_backend_not_rounded_subtraction():
    src = _read('src/components/Dashboard.jsx')
    assert 'stats.diskFreeGB' in src
    assert 'parseFloat(stats.diskTotalGB) - parseFloat(stats.diskUsedGB)' not in src
    assert "'diskFreeGB'" in _read('backend/system_monitor.py')
    # 'Storage' 는 시스템 드라이브만 잰 값이었다. 그 드라이브 문자를 백엔드에서 받아 쓴다(C: 가 아닐 수 있다)
    assert '>Storage<' not in src and "{sysInfo.systemDrive || '시스템'} 드라이브" in src
    assert 'C: 드라이브</span>' not in src


def test_process_list_can_return_everything_for_game_tab(monkeypatch):
    fake = [types.SimpleNamespace(info={'pid': p, 'name': f'p{p}.exe', 'memory_info': types.SimpleNamespace(rss=(20 + p) * MB),
                                        'cpu_percent': 0.0, 'nice': NORMAL_PRIORITY_CLASS}) for p in range(1, 13)]
    monkeypatch.setattr(system_monitor.psutil, 'process_iter', lambda attrs=None: iter(fake))
    monkeypatch.setattr(system_monitor.process_guard, 'get_own_pid_family', lambda: set())
    assert len(system_monitor.get_processes()) == 8          # RAM 화면: 상위 8개
    assert len(system_monitor.get_processes(0)) == 12        # 게이밍 탭: 전부
    assert "getProcesses(0)" in _read('src/components/GameBooster.jsx')


# ── 정크 정리 ──────────────────────────────────────────

@pytest.fixture
def junk_root(tmp_path, monkeypatch):
    root = tmp_path / 'usertmp'
    root.mkdir()
    missing = tmp_path / 'missing'
    real = os.path.expandvars

    def fake_expandvars(s):
        if s == '%TEMP%':
            return str(root)
        if s.startswith('%'):
            return str(missing / s.replace('%', '').replace('\\', '_'))
        return real(s)
    monkeypatch.setattr(os.path, 'expandvars', fake_expandvars)
    return root


def _write(path, size):
    with open(path, 'wb') as f:
        f.write(b'x' * size)


def test_freed_space_is_what_was_deleted_not_drive_free_space_delta(junk_root, monkeypatch):
    # 예전에는 정리 전후 드라이브 여유 공간 차이를 썼다. 그 사이 다른 프로그램이 쓴 것까지 섞였다.
    import shutil
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: (_ for _ in ()).throw(AssertionError('여유 공간으로 재지 않는다')))
    _write(junk_root / 'a.tmp', 2 * MB)
    _write(junk_root / 'b.log', 1 * MB)
    _write(junk_root / 'locked.tmp', 3 * MB)
    real_remove = os.remove

    def remove(p, *a, **kw):
        if os.path.basename(p) == 'locked.tmp':
            raise PermissionError('다른 프로그램이 사용 중')
        return real_remove(p, *a, **kw)
    monkeypatch.setattr(os, 'remove', remove)

    optimizer.clean_junk_background([1], cancel_event=None)
    st = optimizer.get_junk_clean_status()

    assert st['status'] == 'success', st
    assert st['freed_mb'] == 3.0
    assert st['skipped_mb'] == 3.0 and st['skipped_count'] == 1       # 건너뛴 파일을 파일마다 잰 값
    assert st['warnings'] == []


def test_junk_scan_error_is_not_listed_as_a_cleanable_item(monkeypatch):
    monkeypatch.setattr(optimizer, '_get_dir_size_mb', lambda *a, **k: (_ for _ in ()).throw(OSError('읽기 실패')))
    optimizer.scan_junk_background()
    st = optimizer.get_junk_scan_status()
    assert st['status'] == 'error'
    assert st['data'] == [] and '읽기 실패' in st['error']


def test_windows_update_cache_is_not_selected_by_default(junk_root):
    optimizer.scan_junk_background()
    items = {d['id']: d for d in optimizer.get_junk_scan_status()['data']}
    assert items[1]['selected'] and items[2]['selected']
    assert not items[3]['selected'] and not items[4]['selected'] and not items[5]['selected']
    assert '렌더링' not in items[4]['name']                     # Prefetch 는 렌더링과 관계없다
    assert '이미 설치 완료된' not in items[3]['description']


def test_unreadable_recycle_bin_size_is_unknown_not_zero(junk_root, monkeypatch):
    # 되돌릴 수 없는 항목이다. 읽지 못한 크기를 0.0 MB 로 보이면 비어 있는 줄 알고 고른다.
    monkeypatch.setattr(optimizer, '_recycle_bin_bytes', lambda: None)
    optimizer.scan_junk_background()
    item = {d['id']: d for d in optimizer.get_junk_scan_status()['data']}[5]
    assert item['sizeMB'] is None and '읽지 못했습니다' in item['description']
    ui = _code('src/components/StorageCenter.jsx')
    assert "'크기 모름'" in ui


def test_emptied_recycle_bin_with_unknown_size_says_so(monkeypatch):
    sizes = iter([None, None])
    monkeypatch.setattr(optimizer, '_recycle_bin_bytes', lambda: next(sizes))

    class Shell:
        @staticmethod
        def SHEmptyRecycleBinW(*a):
            return 0
    monkeypatch.setattr(optimizer.ctypes, 'windll', type('W', (), {'shell32': Shell})())
    freed, why = optimizer._empty_recycle_bin()
    assert freed == 0 and why and '측정하지 못해' in why          # 0 MB 를 확보했다고 조용히 말하지 않는다


def _bin(monkeypatch, sizes):
    seq = iter(sizes)
    monkeypatch.setattr(optimizer, '_recycle_bin_bytes', lambda: next(seq))
    emptied = []
    monkeypatch.setattr(optimizer, '_empty_recycle_bin', lambda: emptied.append(1) or (100, None))
    return emptied


def test_recycle_bin_that_grew_after_confirmation_is_not_emptied(monkeypatch):
    # 확인 창에는 0 바이트였는데, 그 뒤 '대용량 · 중복' 에서 20GB 를 휴지통으로 보냈다
    emptied = _bin(monkeypatch, [20 * 1024 ** 3])
    optimizer.clean_junk_background([5], cancel_event=None, recycle_bytes_seen=0)
    st = optimizer.get_junk_clean_status()
    assert emptied == [] and any('내용이 바뀌어' in w for w in st['warnings'])


def test_recycle_bin_that_shrank_and_refilled_after_confirmation_is_not_emptied(monkeypatch):
    # 확인 창에는 3GB. 그 뒤 탐색기에서 비우고, '프로그램 삭제' 가 남은 폴더 800MB 를 휴지통으로 보냈다.
    # 예전에는 '커졌을 때만' 막아서, 확인 창에 없던 800MB 가 영구 삭제됐다
    emptied = _bin(monkeypatch, [800 * 1024 ** 2])
    optimizer.clean_junk_background([5], cancel_event=None, recycle_bytes_seen=3 * 1024 ** 3)
    assert emptied == [] and any('내용이 바뀌어' in w for w in optimizer.get_junk_clean_status()['warnings'])


def test_recycle_bin_of_unknown_size_is_not_emptied(monkeypatch):
    emptied = _bin(monkeypatch, [None, None])
    optimizer.clean_junk_background([5], cancel_event=None)
    assert emptied == [] and any('확인하지 못해' in w for w in optimizer.get_junk_clean_status()['warnings'])


def test_recycle_bin_as_confirmed_is_emptied(monkeypatch):
    emptied = _bin(monkeypatch, [4096])
    optimizer.clean_junk_background([5], cancel_event=None, recycle_bytes_seen=4096)
    assert emptied == [1] and optimizer.get_junk_clean_status()['status'] == 'success'


def test_cancel_that_arrives_after_everything_ran_is_not_reported_as_stopped(monkeypatch):
    import threading
    ev = threading.Event()

    def empty():
        ev.set()                          # 비우는 동안 '중단' 을 눌렀다(이 단계는 멈출 수 없다)
        return 100, None
    monkeypatch.setattr(optimizer, '_recycle_bin_bytes', lambda: 4096)
    monkeypatch.setattr(optimizer, '_empty_recycle_bin', empty)
    optimizer.clean_junk_background([5], cancel_event=ev, recycle_bytes_seen=4096)
    st = optimizer.get_junk_clean_status()
    assert st['status'] == 'success'                              # 예전에는 '정리를 중단했습니다'
    assert any('되돌릴 수 없습니다' in w for w in st['warnings'])


def test_browser_cache_covers_edge_whale_and_every_profile(tmp_path, monkeypatch):
    # 예전에는 Chrome 'Default' 프로필의 Cache 만 정리했다
    local = tmp_path / 'Local'
    made = {}
    for rel, profile in ((r'Google\Chrome\User Data', 'Default'), (r'Google\Chrome\User Data', 'Profile 2'),
                         (r'Microsoft\Edge\User Data', 'Default'), (r'Naver\Naver Whale\User Data', 'Default')):
        cache = local.joinpath(*rel.split('\\'), profile, 'Cache')
        cache.mkdir(parents=True)
        (cache / 'data_1').write_bytes(b'c' * 1024)
        made[(rel, profile)] = cache
    # 캐시가 아닌 것: 쿠키 DB·시스템 프로필(System Profile)은 대상이 아니다
    local.joinpath('Google', 'Chrome', 'User Data', 'Default', 'Network').mkdir(parents=True)
    (local / 'Google' / 'Chrome' / 'User Data' / 'Default' / 'Network' / 'Cookies').write_bytes(b'cookie')
    local.joinpath('Google', 'Chrome', 'User Data', 'System Profile', 'Cache').mkdir(parents=True)
    monkeypatch.setenv('LOCALAPPDATA', str(local))

    dirs = optimizer.browser_cache_dirs()
    assert {os.path.normcase(p) for _, p in dirs} == {os.path.normcase(str(p)) for p in made.values()}
    assert optimizer._browser_label(dirs) == 'Chrome, Edge, Whale'

    optimizer.clean_junk_background([2], cancel_event=None)
    assert optimizer.get_junk_clean_status()['status'] == 'success'
    assert all(not (p / 'data_1').exists() for p in made.values())
    assert (local / 'Google' / 'Chrome' / 'User Data' / 'Default' / 'Network' / 'Cookies').exists()


def test_one_click_refuses_to_start_while_storage_clean_runs(monkeypatch):
    started = []
    monkeypatch.setattr(optimizer.threading, 'Thread', lambda *a, **k: started.append(1))
    optimizer._junk_clean_state['status'] = 'running'
    r = optimizer.start_deep_optimization()
    assert r['success'] is False and '정크 정리' in r['message'] and started == []


def test_one_click_reports_long_disk_optimization_as_still_running(monkeypatch):
    def clean(categories, cancel_event=None):
        optimizer._junk_clean_state.update(status='success', freed_mb=0.0)
    monkeypatch.setattr(optimizer, 'clean_junk_background', clean)
    monkeypatch.setattr(optimizer, 'purge_ram', lambda: {'success': True})
    monkeypatch.setattr(system_repair, 'run_network_optimization_sync', lambda: {'success': True})
    monkeypatch.setattr(system_repair, 'run_trim', lambda: {'success': True})
    monkeypatch.setattr(system_repair, 'get_trim_status', lambda: {'status': 'running', 'error': None})
    monkeypatch.setattr(optimizer, 'TRIM_WAIT_SEC', 0)

    optimizer._run_deep_optimization()

    trim = optimizer.get_deep_optimization_status()['steps'][-1]
    assert trim['ok'] is False
    assert '진행 중' in trim['detail'] and trim['detail'] != '완료 확인 실패'


# ── SFC·DISM·디스크 최적화 출력 ─────────────────────────

def test_sfc_utf16_output_is_decoded_and_summarized():
    # sfc.exe 는 파이프로 출력하면 UTF-16 으로 쓴다. 코드 페이지로 읽으면 글자마다 NUL 이 끼었다.
    text = ('\r\n시스템 검사를 시작합니다.\r\n확인 45% 완료.\r확인 100% 완료.\r\n\r\n'
            'Windows 리소스 보호에서 무결성 위반을 찾지 못했습니다.\r\n')
    decoded = system_repair.decode_console_output(text.encode('utf-16-le'))
    assert '\x00' not in decoded and '무결성 위반을 찾지 못했습니다' in decoded
    summary = system_repair.summarize_output(decoded)
    assert '%' not in summary
    assert summary.endswith('무결성 위반을 찾지 못했습니다.')


def test_sfc_four_line_result_keeps_its_first_line():
    # '찾았지만 일부를 고치지 못함' 은 결과 한 줄 + CBS.log 안내 3줄이다. 예전에는 마지막 3줄만 남아
    # '복구함' 과 '일부 복구 못 함' 이 똑같이 보였다.
    text = ('확인 100% 완료.\r\n\r\n'
            'Windows 리소스 보호에서 손상된 파일을 찾았지만 그중 일부를 복구할 수 없습니다.\r\n'
            '온라인 복구의 경우 세부 정보는 %WinDir%\\Logs\\CBS\\CBS.log에 있는\r\n'
            'CBS 로그 파일에 포함되어 있습니다. 예를 들면 C:\\Windows\\Logs\\CBS\\CBS.log입니다.\r\n'
            '오프라인 복구의 경우 세부 정보는 /OFFLOGFILE 플래그가 제공하는 로그 파일에 포함되어 있습니다.\r\n')
    summary = system_repair.summarize_output(text)
    assert summary.startswith('Windows 리소스 보호에서 손상된 파일을 찾았지만 그중 일부를 복구할 수 없습니다.')


def test_repair_tools_are_never_killed_and_report_real_elapsed_time(monkeypatch):
    # HDD 조각 모음은 수십 분~몇 시간 걸린다. 예전에는 300초, 그다음 3시간에 강제 종료했고(화면은 '끝날 때까지 진행'),
    # SFC·DISM 도 1·2시간에 죽였다(복구가 반쯤 적용될 수 있음).
    assert system_repair.TRIM_TIMEOUT_SEC is None
    started = []
    monkeypatch.setattr(system_repair.threading, 'Thread',
                        lambda target, args, daemon: started.append(args) or type('T', (), {'start': lambda self: None})())
    clock = [1000.0]
    monkeypatch.setattr(system_repair.time, 'time', lambda: clock[0])
    for run, status in ((system_repair.run_sfc, system_repair.get_sfc_status),
                        (system_repair.run_dism, system_repair.get_dism_status),
                        (system_repair.run_trim, system_repair.get_trim_status)):
        assert run()['success']
        assert started[-1][2] is None                       # 시간 제한(강제 종료) 없음
        clock[0] += 754
        st = status()
        assert st['status'] == 'running' and st['elapsed_sec'] == 754   # 화면을 다시 띄워도 0 부터 세지 않는다
        started[-1][1].update(status='success', finished_at=clock[0])
        clock[0] += 100
        assert status()['elapsed_sec'] == 754               # 끝난 뒤에는 늘지 않는다


def test_command_timeout_is_reported_in_words(monkeypatch):
    import subprocess

    def fake_run(args, **kw):
        raise subprocess.TimeoutExpired(args, kw.get('timeout'))
    monkeypatch.setattr(system_repair.subprocess, 'run', fake_run)
    state = {'status': 'running', 'error': None}
    system_repair._run_hidden_cmd_bg([system_repair.sys_tool('defrag.exe'), '/C', '/O'], state, 120)
    assert state['status'] == 'error' and '2분' in state['error']


# ── 우선순위 복구 개수 ─────────────────────────────────

def test_restore_all_does_not_count_exited_processes_as_restored(procs):
    procs.add(100, 'a.exe')
    procs.add(200, 'b.exe')
    assert process_boost.set_priority(100, 'idle', owner='user')['ok']
    assert process_boost.set_priority(200, 'idle', owner='user')['ok']
    procs.remove(200)                                   # 이미 끝났다
    r = process_boost.restore_all()
    assert r['ok'] and r['restored'] == 1 and r['gone'] == 1


def test_adjusted_count_ignores_exited_processes(procs):
    procs.add(100, 'a.exe')
    assert process_boost.set_priority(100, 'idle', owner='user')['ok']
    assert process_boost.adjusted_count() == 1
    procs.remove(100)
    assert process_boost.adjusted_count() == 0          # 복구 센터에 '조정된 프로세스 1개' 가 남지 않는다


# ── 게임 부스터 ────────────────────────────────────────

class _Proc:
    def __init__(self, cmd):
        self._cmd = cmd

    def cmdline(self):
        if isinstance(self._cmd, Exception):
            raise self._cmd
        return self._cmd


def test_java_apps_are_not_mistaken_for_minecraft():
    assert not game_booster._is_game_process(_Proc(['javaw.exe', '-jar', 'idea.jar']), 'javaw.exe')
    assert not game_booster._is_game_process(_Proc(PermissionError()), 'javaw.exe')
    assert game_booster._is_game_process(
        _Proc(['javaw.exe', '-cp', 'x', 'net.minecraft.client.main.Main']), 'javaw.exe')
    assert game_booster._is_game_process(_Proc([]), 'cs2.exe')
    assert not game_booster._is_game_process(_Proc([]), 'notepad.exe')
    assert game_booster.game_label('tslgame.exe') == 'PUBG: BATTLEGROUNDS (tslgame.exe)'


def test_timer_resolution_is_not_requested_where_it_has_no_effect(monkeypatch):
    calls = []
    monkeypatch.setattr(game_booster, '_set_timer_resolution', lambda on: calls.append(on) or True)
    monkeypatch.setattr(game_booster, 'timer_request_effective', lambda: False)
    from backend import config_manager
    c = config_manager.load_config()
    c.update(boost_timer_resolution=True, boost_tame_background=False,
             boost_disable_nagle=False, boost_auto_power_mode=False)
    assert config_manager.save_config(c)

    game_booster._enter_boost_mode()

    assert calls == [] and 'timer' not in game_booster._applied
    assert not any('타이머' in x for x in game_booster.get_booster_status()['appliedBoosts'])
    assert game_booster.get_booster_status()['timer_effective'] is False


def test_turning_booster_off_reverts_right_away():
    from backend import config_manager
    nagle = game_booster._NAGLE_BASE
    iface = '{aaaaaaaa-0000-0000-0000-000000000001}'
    REGISTRY.seed('HKLM', f'{nagle}\\{iface}', 'TcpAckFrequency', 2)
    c = config_manager.load_config()
    c.update(boost_timer_resolution=False, boost_tame_background=False,
             boost_disable_nagle=True, boost_auto_power_mode=False)
    assert config_manager.save_config(c)
    game_booster._booster_state.update(enabled=True, active=True)
    game_booster._enter_boost_mode()
    assert REGISTRY.value('HKLM', f'{nagle}\\{iface}', 'TcpAckFrequency') == 1

    r = game_booster.toggle_booster(False)

    # 예전에는 '되돌렸습니다' 라고 한 뒤 되돌리기를 루프(최대 2초 뒤)에 맡겼다
    assert r['reverted'] is True and '되돌렸습니다' in r['message']
    assert REGISTRY.value('HKLM', f'{nagle}\\{iface}', 'TcpAckFrequency') == 2
    assert ss.pending_changes() == {}
    assert game_booster._booster_state['active'] is False


# ── 프로그램 삭제 ──────────────────────────────────────

_UNINST = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'


def _register_app(key, name, uninstall, location=''):
    REGISTRY.seed('HKLM', f'{_UNINST}\\{key}', 'DisplayName', name, REG_SZ)
    REGISTRY.seed('HKLM', f'{_UNINST}\\{key}', 'UninstallString', uninstall, REG_SZ)
    if location:
        REGISTRY.seed('HKLM', f'{_UNINST}\\{key}', 'InstallLocation', location, REG_SZ)
    REGISTRY.seed('HKLM', f'{_UNINST}\\{key}', 'InstallDate', '20240115', REG_SZ)


def _unregister_app(key):
    parent = REGISTRY._find(fakewin._hive('HKLM'), [p for p in _UNINST.split('\\')])
    del parent.subkeys[key.lower()]


@pytest.fixture
def program_files(tmp_path, monkeypatch):
    pf = tmp_path / 'Program Files'
    pf.mkdir()
    monkeypatch.setenv('ProgramFiles', str(pf))
    uninstaller._known_locations.clear()
    uninstaller._known_publishers.clear()
    return pf


def test_uninstall_runs_the_registered_command_not_a_ui_string(monkeypatch, program_files):
    _register_app('FooApp', 'Foo App', r'"C:\Program Files\Foo\uninst.exe" /S')
    ran = []
    monkeypatch.setattr(uninstaller, 'run_uninstall', lambda s: ran.append(s) or {'success': True})

    assert uninstaller.uninstall_by_name('Foo App')['success']
    assert ran == [r'"C:\Program Files\Foo\uninst.exe" /S']

    r = uninstaller.uninstall_by_name(r'cmd.exe /c del C:\x')          # 목록에 없는 이름(= 명령줄)은 실행하지 않는다
    assert r['success'] is False and ran == [r'"C:\Program Files\Foo\uninst.exe" /S']
    assert uninstaller.get_installed_apps()[0]['installDate'] == '2024-01-15'


def test_leftovers_are_not_searched_while_the_program_is_still_installed(program_files):
    folder = program_files / 'Foo App'
    folder.mkdir()
    _register_app('FooApp', 'Foo App', 'uninst.exe', str(folder))

    r = uninstaller.scan_leftovers('Foo App')

    # 제거 창을 닫거나 취소해도 '삭제 완료' 를 누를 수 있었다. 그러면 쓰는 중인 설치 폴더가 잔여물로 잡혔다.
    assert r['success'] is False and r['stillInstalled'] is True and r['items'] == []


def test_leftovers_use_the_install_location_read_before_uninstall(program_files):
    folder = program_files / 'Vendor' / 'FooSuite'
    folder.mkdir(parents=True)
    _register_app('FooApp', 'Foo App', 'uninst.exe', str(folder))
    uninstaller.get_installed_apps()                    # 목록을 보여 줄 때 설치 경로를 기억한다
    _unregister_app('FooApp')                           # 제거가 끝나 등록 정보가 사라졌다

    r = uninstaller.scan_leftovers('Foo App')

    assert r['success'] is True
    assert [(os.path.normcase(i['path']), i['confidence']) for i in r['items']] == \
        [(os.path.normcase(str(folder)), 'certain')]


def test_huge_leftover_size_is_a_lower_bound_not_exact(program_files, monkeypatch):
    folder = program_files / 'Vendor' / 'FooSuite'
    (folder / 'a').mkdir(parents=True)
    (folder / 'b').mkdir()
    (folder / 'a' / 'big.bin').write_bytes(b'x' * 3000)
    (folder / 'b' / 'more.bin').write_bytes(b'x' * 3000)
    _register_app('FooApp', 'Foo App', 'uninst.exe', str(folder))
    uninstaller.get_installed_apps()
    _unregister_app('FooApp')
    monkeypatch.setattr(uninstaller._folder_size, '__defaults__', (1000,))

    item = uninstaller.scan_leftovers('Foo App')['items'][0]

    # 세기를 멈춘 값은 '이 이상' 이다. 예전에는 멈춘 값을 정확한 크기처럼 보여 줬다.
    assert item['sizeCapped'] is True
    assert uninstaller._folder_size(str(folder), cap_bytes=10 ** 9) == (6000, False)
    ui = _code('src/components/Uninstaller.jsx')
    assert 'sizeCapped' in ui and "' 이상'" in ui

def test_leftover_folder_holding_another_installed_program_is_not_offered(program_files):
    shared = program_files / 'Foo App'
    other = shared / 'Other Tool'
    other.mkdir(parents=True)
    _register_app('FooApp', 'Foo App', 'uninst.exe', str(shared))
    _register_app('Other', 'Other Tool', 'other_uninst.exe', str(other))
    uninstaller.get_installed_apps()
    _unregister_app('FooApp')

    r = uninstaller.scan_leftovers('Foo App')
    assert r['success'] and r['items'] == []

    # 화면을 거치지 않고 넘어와도 정리 단계가 다시 막는다
    c = uninstaller.clean_leftovers([str(shared)])
    assert c['deleted'] == 0 and c['success'] is False
    assert c['failed'][0]['reason'] == '설치된 프로그램이 쓰는 폴더'


def test_leftover_outside_cleanable_roots_is_not_listed(program_files, tmp_path):
    outside = tmp_path / 'Games' / 'FooGame'
    outside.mkdir(parents=True)
    _register_app('FooGame', 'Foo Game', 'uninst.exe', str(outside))
    uninstaller.get_installed_apps()
    _unregister_app('FooGame')
    # 목록에 보여 놓고 정리에서 '허용된 폴더 범위 밖' 으로 거부하면 사용자는 지웠다고 믿는다
    assert uninstaller.scan_leftovers('Foo Game')['items'] == []


def test_vendor_folder_registered_by_several_apps_is_not_a_leftover(program_files):
    # Adobe Premiere·After Effects·Media Encoder 는 InstallLocation 에 'C:\\Program Files\\Adobe' 를 적는다(실제 PC 확인)
    vendor = program_files / 'Adobe'
    (vendor / 'Adobe Creative Cloud').mkdir(parents=True)       # 등록 정보에 경로가 없는 다른 제품
    (vendor / 'Adobe Premiere Pro 2025').mkdir()
    _register_app('Prem', 'Adobe Premiere Pro 2025', 'u.exe', str(vendor))
    _register_app('AE', 'Adobe After Effects 2025', 'u.exe', str(vendor))
    uninstaller.get_installed_apps()
    _unregister_app('Prem')
    _unregister_app('AE')                                        # 둘 다 지워져 '설치된 다른 프로그램' 가드에 안 걸린다

    paths = [os.path.normcase(i['path']) for i in uninstaller.scan_leftovers('Adobe Premiere Pro 2025')['items']]

    assert os.path.normcase(str(vendor)) not in paths            # 공용 폴더를 통째로 올리지 않는다
    assert paths == [os.path.normcase(str(vendor / 'Adobe Premiere Pro 2025'))]   # 이름이 같은 하위 폴더만


def test_publisher_named_folder_is_not_taken_whole(program_files):
    vendor = program_files / 'XPPen'
    (vendor / 'Driver').mkdir(parents=True)
    _register_app('Pen', 'Pentablet', 'u.exe', str(vendor))
    REGISTRY.seed('HKLM', f'{_UNINST}\\Pen', 'Publisher', 'XPPen Technology', REG_SZ)
    uninstaller.get_installed_apps()
    _unregister_app('Pen')
    assert uninstaller.scan_leftovers('Pentablet')['items'] == []


def test_product_named_like_its_company_is_still_found(program_files):
    own = program_files / 'Rainmeter'
    own.mkdir()
    _register_app('Rm', 'Rainmeter', 'u.exe', str(own))
    REGISTRY.seed('HKLM', f'{_UNINST}\\Rm', 'Publisher', 'Rainmeter', REG_SZ)
    uninstaller.get_installed_apps()
    _unregister_app('Rm')
    items = uninstaller.scan_leftovers('Rainmeter')['items']
    assert [(os.path.normcase(i['path']), i['confidence']) for i in items] == [(os.path.normcase(str(own)), 'certain')]


def test_other_version_still_installed_keeps_shared_data_folder(program_files, monkeypatch, tmp_path):
    appdata = tmp_path / 'Roaming'
    (appdata / 'Python').mkdir(parents=True)                     # 3.12·3.13 이 함께 쓰는 사용자 패키지
    monkeypatch.setenv('APPDATA', str(appdata))
    _register_app('Py312', 'Python 3.12.1 (64-bit)', 'u.exe')
    _register_app('Py313', 'Python 3.13.7 (64-bit)', 'u.exe')
    uninstaller.get_installed_apps()
    _unregister_app('Py312')
    assert uninstaller.scan_leftovers('Python 3.12.1 (64-bit)')['items'] == []


def test_expand_sz_uninstall_string_is_expanded(monkeypatch):
    monkeypatch.setenv('windir', r'C:\Windows')
    REGISTRY.seed('HKLM', f'{_UNINST}\\Sdb', 'DisplayName', 'Compat Fix', REG_SZ)
    REGISTRY.seed('HKLM', f'{_UNINST}\\Sdb', 'UninstallString', r'%windir%\system32\sdbinst.exe -u x.sdb',
                  fakewin.REG_EXPAND_SZ)
    app = next(a for a in uninstaller.get_installed_apps() if a['name'] == 'Compat Fix')
    assert app['uninstallString'].lower().startswith(r'c:\windows\system32\sdbinst.exe')


def test_file_delete_with_everything_rejected_is_not_a_success(tmp_path):
    r = file_finder.delete_files([str(tmp_path / 'nope.bin')])
    assert r['success'] is False and r['deleted'] == 0 and r['failed']


# ── 복구 센터 ──────────────────────────────────────────

def test_startup_changes_are_grouped_under_one_readable_heading():
    from backend.api import Api
    path = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
    for name in ('Discord', 'Steam'):
        assert ss.set_registry('HKCU', path, name, b'\x03' + b'\x00' * 11, f'startup:HKCU:{name}',
                               vtype=fakewin.REG_BINARY, why=f"시작 프로그램 '{name}' 끄기")['ok']
    groups = Api.getPendingSystemChanges(None)['groups']
    assert set(groups) == {'startup'} and len(groups['startup']) == 2
    assert 'startup:' in _read('backend/api.py')
    assert re.search(r"\bstartup: \{ label:", _read('src/components/RestoreCenter.jsx'))


# ── 화면 문구 ──────────────────────────────────────────

def test_ui_wording_matches_what_the_features_do():
    sidebar = _code('src/components/Sidebar.jsx')
    labels = re.findall(r"label: '([^']*)'", sidebar)
    assert labels and not any('하드코어' in x or '적출' in x or '완전 삭제' in x for x in labels), labels
    assert '적출' not in _code('src/components/Debloater.jsx')
    assert '찌꺼기 완전 삭제' not in _code('src/components/Uninstaller.jsx')
    # 버전은 package.json 한 곳에서
    assert not re.search(r"v\d+\.\d+\.\d+", sidebar) and 'package.json' in sidebar
    # 제거 명령은 백엔드가 찾는다. 화면이 명령줄을 넘기지 않는다
    assert 'uninstallApp(app.name)' in _code('src/components/Uninstaller.jsx')
    assert 'uninstallString' not in _code('src/components/Uninstaller.jsx')
    # '전부 SSD' 는 모든 드라이브가 SSD 일 때만
    assert "drives.every((d) => d.mediaType === 'ssd')" in _code('src/components/StorageCenter.jsx')
    # SFC 가 끝났다고 '복구 완료' 라고 단정하지 않는다. 설치된 앱에 없는 개발자 도구를 안내하지 않는다
    assert '무결성 복구 완료' not in _code('src/components/DriverUpdater.jsx')
    assert 'F12' not in _code('src/components/ErrorBoundary.jsx')
    # 설치 RAM 으로 사양을 판정한다(8GB PC 가 7.8GB 로 읽혀 저사양이 되지 않게)
    assert 'ramInstalledGB' in _code('src/components/InitialSetupWizard.jsx')


# ── 읽기 전 가짜 기본값 ──────────────────────────────────

def test_screens_do_not_claim_states_before_reading_them():
    # 받기 전에 '0개'·'자동 감지 꺼짐'·'되돌릴 변경이 없습니다' 를 보여 주지 않는다
    game = _code('src/components/GameBooster.jsx')
    assert 'useState(null)' in game and "!status ? '확인 중…'" in game
    restore = _code('src/components/RestoreCenter.jsx')
    assert "loadState === 'ok' && pending.count === 0" in restore
    startup = _code('src/components/StartupManager.jsx')
    assert "loadState === 'loading' ? '…'" in startup
    assert "useState('확인 중…')" in _code('src/components/Header.jsx')


def test_failed_system_stats_are_not_shown_as_zero():
    for rel in ('src/App.jsx', 'src/components/RamBooster.jsx', 'src/components/Dashboard.jsx'):
        src = _code(rel)
        assert "cpuModel !== 'Error'" not in src, rel
        assert '!stats.error' in src, rel


# ── 설치 마법사 ────────────────────────────────────────

def test_installer_progress_is_real_and_failures_are_reported():
    src = _read('tools/setup_wizard.py')
    # 예전: 'Simulate some progress for realism' 로 잠깐씩 멈추며 막대를 채웠다
    assert 'time.sleep' not in src and 'Simulate' not in src
    assert 'def copy_with_progress' in src and 'on_bytes(done, total)' in src
    # 제거 프로그램이 없으면 설치하지 않고, 등록 실패를 삼키지 않는다
    assert 'if missing:' in src
    run = src[src.index('class InstallWorker'):src.index('class LicensePage')]
    assert 'register_uninstall(target_dir' in run
    reg = src[src.index('def register_uninstall'):src.index('def _shortcut_target')]
    assert 'except' not in reg                      # 실패는 부르는 쪽으로 올린다
    # 관리자 권한으로 도는 exe 는 관리자만 쓸 수 있는 Program Files 에, 모든 사용자용(HKLM)으로 등록한다
    assert 'HKEY_LOCAL_MACHINE' in reg and 'HKEY_CURRENT_USER' not in reg
    assert '"ProgramFiles"' in src and "install_dir = os.path.join(os.environ.get(\"LOCALAPPDATA\"" not in src
    # 복사하는 동안에는 취소·Esc·닫기를 받지 않는다(반쪽 설치가 남았다)
    assert 'def reject(self)' in src and 'def closeEvent(self, event)' in src
    assert 'WizardButton.CancelButton]' not in src[src.index('class ProgressPage'):src.index('class FinishPage')]
    # 사용자에게 보이는 화면 이름이 앱과 같다
    un = _read('tools/uninstall.py')
    assert "'Windows 기본 앱 정리'" in un and '디블로터 화면' not in un


def test_stats_use_the_windows_drive_and_survive_a_missing_c_drive(monkeypatch):
    from backend import system_monitor
    seen = []

    def disk_usage(path):
        seen.append(path)
        raise FileNotFoundError(path)                  # 이 PC 에는 그 드라이브가 없다
    monkeypatch.setenv('SystemDrive', 'D:')
    monkeypatch.setattr(system_monitor.psutil, 'disk_usage', disk_usage)
    monkeypatch.setattr(system_monitor, 'memory_lists', lambda: None)

    st = system_monitor.get_system_stats()

    assert seen == ['D:\\']
    # 예전에는 C: 를 못 읽으면 통계 전체가 None 이라 앱이 로딩 화면에서 멈췄다
    assert st is not None and st['systemDrive'] == 'D:' and st['diskPct'] is None and st['ramTotalGB']
