"""제거 전 되돌리기: APEX CARE 를 지우기 전에 이 앱이 바꾼 것을 전부 원래대로."""

import ast
import copy
import json
import os

import pytest

from backend import config_manager, debloater, optimizer, perf_modes, uninstall_prep
from backend import system_state as ss
from tests import fakewin
from tests.conftest import ROOT
from tests.fakewin import POWER, REGISTRY, SERVICES

RUN_USER = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_MACHINE = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
MM = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'
NAGLE_IF = r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{aaaa}'


def _dump_registry():
    """가짜 레지스트리 전체를 {경로: {값 이름: (값, 타입)}} 으로. 키가 새로 생기거나 남아도 드러난다."""
    out = {}

    def walk(key, path):
        out[path] = {n: (v, t) for n, (_, v, t) in key.values.items()}
        for name, sub in key.subkeys.items():
            walk(sub, f'{path}\\{name}')
    for hive, root in REGISTRY.roots.items():
        walk(root, fakewin._HIVE_NAMES[hive])
    return out


def _state():
    return _dump_registry(), POWER.active, copy.deepcopy(POWER.values)


def _seed_pc():
    """사용자 PC 의 원래 상태."""
    for plan in POWER.plans:
        for sub, setting in ((ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN), (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX),
                             (ss.SUB_PROCESSOR, ss.CPMINCORES), (ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND)):
            POWER.seed_value(plan, sub, setting, 42, dc_value=24)
    REGISTRY.seed('HKLM', MM, 'SystemResponsiveness', 20)
    REGISTRY.seed_key('HKLM', NAGLE_IF)
    # Windows 에 원래 있는 정책 키. 값만 없다(있으면 사용자가 정한 정책이다).
    REGISTRY.seed_key('HKLM', r'SOFTWARE\Policies\Microsoft\Windows\DataCollection')
    REGISTRY.seed_key('HKCU', r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run')
    REGISTRY.seed_key('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run')
    SERVICES.add('DiagTrack', 2)
    SERVICES.add('SysMain', 2)
    REGISTRY.seed('HKCU', RUN_USER, 'UserApp', r'"C:\apps\user.exe" --tray', fakewin.REG_SZ)
    REGISTRY.seed('HKLM', RUN_MACHINE, 'MachineApp', r'C:\apps\machine.exe', fakewin.REG_SZ)


def _use_everything():
    """APEX CARE 를 쓰면서 바뀐 것들."""
    assert perf_modes.apply_mode('gaming')['success']
    assert debloater._apply_telemetry_policy()[0]
    assert optimizer.apply_hardware_tailored_tuning(4, 4, consent=True)['steps'][0]['ok']   # SysMain 끔
    # 게임 도중 앱이 죽어 남은 Nagle 과 '게임 전 모드' 기록
    assert ss.set_registry('HKLM', NAGLE_IF, 'TcpAckFrequency', 1, group='boost')['ok']
    config_manager.set_boost_restore_mode('eco')
    assert optimizer.toggle_startup_app('UserApp', False)['success']
    assert optimizer.toggle_startup_app('MachineApp', False)['success']


@pytest.fixture
def no_ram_purge(monkeypatch):
    monkeypatch.setattr(optimizer, 'purge_ram', lambda: {'success': True})


@pytest.mark.usefixtures('as_admin', 'no_ram_purge')
def test_everything_is_back_to_original_before_uninstall():
    _seed_pc()
    before = _state()
    _use_everything()
    assert _state() != before

    res = uninstall_prep.revert_for_uninstall()

    assert res['success'], res['failed']
    assert _state() == before                       # 이 앱이 만든 키(Software\APEXCARE)까지 남지 않는다
    assert ss.pending_changes() == {}
    assert config_manager.get_boost_restore_mode() is None
    assert res['remaining'] == 0


@pytest.mark.usefixtures('as_admin', 'no_ram_purge')
def test_startup_apps_go_back_to_their_own_hive():
    _seed_pc()
    _use_everything()
    uninstall_prep.revert_for_uninstall()
    assert REGISTRY.value('HKCU', RUN_USER, 'UserApp') == r'"C:\apps\user.exe" --tray'
    assert REGISTRY.value('HKLM', RUN_MACHINE, 'MachineApp') == r'C:\apps\machine.exe'
    assert REGISTRY.get('HKCU', RUN_USER, 'MachineApp') is None      # HKLM 항목이 HKCU 로 옮겨지지 않는다


@pytest.mark.usefixtures('as_admin', 'no_ram_purge')
def test_failures_are_reported_and_kept_for_retry():
    _seed_pc()
    _use_everything()
    REGISTRY.deny_write_value('HKLM', MM)

    res = uninstall_prep.revert_for_uninstall()

    assert res['success'] is False
    assert res['failed'] and res['remaining'] > 0
    assert any(k.startswith(f'reg:HKLM\\{MM}') for k in ss.pending_changes())   # 다시 시도할 수 있게 남는다
    # 실패한 것이 있어도 되돌릴 수 있는 것은 되돌린다
    assert REGISTRY.value('HKCU', RUN_USER, 'UserApp') is not None
    assert SERVICES.start_of('DiagTrack')[0] == 2



@pytest.mark.usefixtures('as_admin', 'no_ram_purge')
def test_legacy_hidden_startup_apps_come_back_before_uninstall():
    # 예전 버전이 Run 에서 지우고 HKCU\Software\APEXCARE 에 숨긴 항목. 앱을 지우면 영영 꺼진 채 남았다.
    _seed_pc()
    REGISTRY.seed('HKCU', r'Software\APEXCARE\DisabledStartup', 'OldTool', r'C:\apps\old.exe', fakewin.REG_SZ)
    REGISTRY.seed('HKCU', r'Software\APEXCARE\DisabledStartup\_origin', 'OldTool', 'HKLM|' + RUN_MACHINE,
                  fakewin.REG_SZ)

    res = uninstall_prep.revert_for_uninstall()

    assert res['success'], res['failed']
    assert REGISTRY.value('HKLM', RUN_MACHINE, 'OldTool') == r'C:\apps\old.exe'
    assert optimizer._approved_state('HKLM', 'OldTool') != 'disabled'
    assert not REGISTRY.has_key('HKCU', r'Software\APEXCARE')
    assert ss.pending_changes() == {}


@pytest.mark.usefixtures('as_admin', 'no_ram_purge')
def test_reregistered_legacy_item_turned_off_by_user_stays_off():
    # 프로그램이 HKLM Run 에 스스로 다시 등록했고, 사용자가 작업 관리자에서 껐다. 원래 위치 기록은 없다(아주 옛 버전).
    _seed_pc()
    REGISTRY.seed('HKCU', r'Software\APEXCARE\DisabledStartup', 'OldTool', r'C:\apps\old.exe', fakewin.REG_SZ)
    REGISTRY.seed('HKLM', RUN_MACHINE, 'OldTool', r'C:\apps\old.exe', fakewin.REG_SZ)
    disabled = b'\x03\x00\x00\x00' + b'\x11' * 8
    REGISTRY.seed('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run', 'OldTool',
                  disabled, fakewin.REG_BINARY)

    res = uninstall_prep.revert_for_uninstall()

    assert res['success'], res['failed']
    assert REGISTRY.get('HKCU', RUN_USER, 'OldTool') is None                  # HKCU 에 중복 등록하지 않는다
    assert REGISTRY.value('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
                          'OldTool') == disabled                              # 사용자가 끈 상태 그대로
    assert ss.pending_changes() == {} and res['remaining'] == 0               # 되돌릴 주체 없는 기록을 남기지 않는다


@pytest.mark.usefixtures('as_admin', 'no_ram_purge')
def test_priorities_left_by_a_crash_are_restored_before_uninstall(procs, monkeypatch):
    from backend import game_booster, process_boost
    monkeypatch.setattr(game_booster, '_set_process_power_throttling', lambda pid, v: True)
    procs.add(900, 'chrome.exe', nice=fakewin.BELOW_NORMAL_PRIORITY_CLASS)
    game_booster._tame_processes([900])
    process_boost._original.clear()                                           # 앱이 비정상 종료됐다

    res = uninstall_prep.revert_for_uninstall()

    assert res['success'], res['failed']
    assert procs.procs[900].nice == fakewin.BELOW_NORMAL_PRIORITY_CLASS
    assert any('우선순위' in s['name'] for s in res['steps'])

def test_without_admin_nothing_is_changed_and_it_fails():
    _seed_pc()
    before = _state()
    res = uninstall_prep.revert_for_uninstall()
    assert res['success'] is False
    assert res['failed'][0]['name'] == '시스템 설정 되돌리기'
    assert _state() == before


@pytest.mark.usefixtures('as_admin')
def test_main_cli_writes_result_file_and_exit_code(monkeypatch):
    assert uninstall_prep.main_cli() == 0
    path = os.path.join(config_manager.APPDATA_DIR, uninstall_prep.RESULT_NAME)
    assert os.path.realpath(path).startswith(os.path.realpath(fakewin.SANDBOX))
    with open(path, encoding='utf-8') as f:
        assert json.load(f)['success'] is True

    monkeypatch.setattr(perf_modes, 'is_admin', lambda: False)
    assert uninstall_prep.main_cli() == 1
    with open(path, encoding='utf-8') as f:
        assert json.load(f)['success'] is False

    def boom():
        raise RuntimeError('터짐')
    monkeypatch.setattr(uninstall_prep, 'revert_for_uninstall', boom)
    assert uninstall_prep.main_cli() == 1
    with open(path, encoding='utf-8') as f:
        assert '터짐' in json.load(f)['failed'][0]['detail']


# ── 앱·제거 프로그램 연결 (정적 검사: 제거 프로그램은 PyQt6·pywin32 가 있어야 import 된다) ──

def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


@pytest.mark.usefixtures('as_admin', 'no_ram_purge')
def test_running_main_py_with_flag_reverts_and_exits_without_window(monkeypatch):
    import runpy
    import sys
    _seed_pc()
    before = _state()
    _use_everything()
    monkeypatch.setattr(sys, 'argv', ['main.py', '--revert-for-uninstall'])
    monkeypatch.setitem(sys.modules, 'webview', None)      # 창을 띄우는 쪽으로 가면 ImportError 로 드러난다

    with pytest.raises(SystemExit) as e:
        runpy.run_path(os.path.join(ROOT, 'main.py'), run_name='__main__')

    assert e.value.code == 0
    assert _state() == before
    with open(uninstall_prep.result_path(), encoding='utf-8') as f:
        assert json.load(f)['success'] is True


def test_main_handles_flag_before_webview_and_without_api():
    tree = ast.parse(_read('main.py'))
    body = tree.body
    flag_at = next(i for i, n in enumerate(body)
                   if isinstance(n, ast.If) and '--revert-for-uninstall' in ast.unparse(n.test))
    webview_at = next(i for i, n in enumerate(body)
                      if isinstance(n, ast.Import) and any(a.name == 'webview' for a in n.names))
    assert flag_at < webview_at
    branch = ast.unparse(body[flag_at])
    assert 'uninstall_prep.main_cli()' in branch and 'sys.exit' in branch
    assert 'Api(' not in branch


def test_uninstaller_reverts_first_and_never_force_kills():
    src = _read('tools/uninstall.py')
    assert '--revert-for-uninstall' in src
    assert uninstall_prep.RESULT_NAME in src                # 결과 파일 이름이 앱과 같다
    assert 'taskkill' not in src.lower()                    # 강제 종료하면 부스트 정리가 돌지 않는다
    tree = ast.parse(src)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    code = ast.unparse(main)
    # 되돌리기 → (실패하면 묻기) → 설치 폴더 삭제 순서
    assert code.index('_app_running()') < code.index('_revert_system_changes(') < code.index('_write_cleanup_bat(')


# ── 설치 폴더 지우기 (샌드박스 점검에서 설치 폴더가 남는 것이 드러났다) ──

def _load_uninstaller(monkeypatch):
    """제거 프로그램을 PyQt6·pywin32 없이 불러온다(창은 띄우지 않는다)."""
    import importlib.util
    import sys
    import types
    qtw = types.ModuleType('PyQt6.QtWidgets')
    class QMessageBox:                                     # 함수 기본값에서 StandardButton.Ok 를 읽는다
        class StandardButton:
            Ok = Yes = No = 0
    qtw.QApplication, qtw.QMessageBox = object, QMessageBox
    qtc = types.ModuleType('PyQt6.QtCore')
    qtc.Qt = object
    win32 = types.ModuleType('win32com.client')

    class Shell:
        def SpecialFolders(self, name):
            return r'C:\Users\u\Desktop'
    win32.Dispatch = lambda name: Shell()
    win32com = types.ModuleType('win32com')
    win32com.client = win32
    for name, mod in (('PyQt6', types.ModuleType('PyQt6')), ('PyQt6.QtWidgets', qtw), ('PyQt6.QtCore', qtc),
                      ('win32com', win32com), ('win32com.client', win32)):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location('apex_uninstaller', os.path.join(ROOT, 'tools', 'uninstall.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


INSTALL = r'C:\Program Files\APEX CARE'
BAT = r'C:\Windows\Temp\apexcare-uninst-ab12\cleanup.bat'


def _shown_text(line):
    """결과 창 줄(PowerShell -EncodedCommand)에서 보여 줄 문구를 꺼낸다."""
    import base64
    b64 = line.rsplit(' ', 1)[-1]
    return base64.b64decode(b64).decode('utf-16-le')


def test_cleanup_runs_outside_install_dir_and_retries(monkeypatch):
    un = _load_uninstaller(monkeypatch)
    lines = un._cleanup_bat_lines(BAT, INSTALL, [r'C:\Users\Public\Desktop\APEX CARE.lnk'])
    body = [l for l in lines if l != '@echo off']
    # 작업 폴더는 System32(관리자만 씀). 설치 폴더·자기 폴더면 지워지지 않고, 사용자가 쓸 수 있는 폴더면
    # cmd 가 거기 심은 ping.exe·reg.exe 를 먼저 찾아 관리자 권한으로 실행한다
    assert body[0] == r'cd /d "%SystemRoot%\System32"'
    tools = [l for l in lines if 'PING.EXE' in l or 'reg.exe' in l]
    assert tools and all(l.startswith('"%SystemRoot%\\System32\\') for l in tools)
    retry = lines.index(':retry')
    rmdir = lines.index(f'if exist "{INSTALL}" rmdir /s /q "{INSTALL}"')
    assert retry < rmdir < lines.index('if %tries% lss 30 goto retry')
    assert not any(l.startswith('timeout') for l in lines)   # 창 없이 돌면 바로 끝나 기다리지 못한다
    # 끝에 자기 자신과 이 제거 프로그램이 만든 폴더만 지운다(/s 없이: 비었을 때만)
    assert lines[-1] == r'(goto) 2>nul & del "%~f0" & rmdir "C:\Windows\Temp\apexcare-uninst-ab12"'


def test_cleanup_reports_success_only_when_folder_is_gone(monkeypatch):
    un = _load_uninstaller(monkeypatch)
    lines = un._cleanup_bat_lines(BAT, INSTALL, [r'C:\Users\Public\Desktop\APEX CARE.lnk'])
    removed, failed = lines.index(':removed'), lines.index(':cleanup')
    reg = next(i for i, l in enumerate(lines) if 'reg.exe" delete' in l)
    shown = [(i, _shown_text(l)) for i, l in enumerate(lines) if '-EncodedCommand' in l]
    ok = next(i for i, t in shown if '제거되었습니다' in t)
    fail = next(i for i, t in shown if '지우지 못했습니다' in t)
    # 폴더를 지웠을 때만 프로그램 목록에서 빼고 '제거되었습니다' 라고 한다. 못 지우면 경로를 알려 준다.
    assert lines.index(f'if not exist "{INSTALL}" goto removed') < removed < reg < ok < failed < fail
    assert INSTALL in _shown_text(lines[fail])
    assert lines[ok + 1] == 'goto end'
    assert 'HKLM' in lines[reg] and '/reg:64' in lines[reg]


def test_result_message_works_on_every_edition_and_only_this_session(monkeypatch):
    # msg.exe 는 Home 에디션에 없고, 'msg *' 는 PC 의 모든 세션에 보낸다
    un = _load_uninstaller(monkeypatch)
    lines = un._cleanup_bat_lines(BAT, INSTALL, [])
    assert not any(l.startswith('msg') for l in lines)
    assert any('powershell.exe' in l and 'MessageBox' in _shown_text(l) for l in lines if '-EncodedCommand' in l)
    assert all(l.isascii() for l in lines)                          # 한국어 문구도 코드 페이지와 상관없이


def test_cleanup_bat_never_writes_a_mangled_path_and_skips_odd_shortcuts(monkeypatch, tmp_path):
    un = _load_uninstaller(monkeypatch)
    monkeypatch.setattr(un, '_bat_encoding', lambda: 'ascii')
    # 경로가 코드 페이지로 나타나지 않으면 '?' 로 바꿔 쓰지 않고 실패한다(깨진 경로로 rmdir 을 부르지 않는다)
    with pytest.raises(UnicodeEncodeError):
        un._write_cleanup_bat(str(tmp_path / 'x.bat'), r'C:\Users\라브\AppData\Local\APEX CARE')
    assert not os.path.exists(tmp_path / 'x.bat') or os.path.getsize(tmp_path / 'x.bat') == 0
    # 선택 항목(바로 가기)은 나타낼 수 없으면 빼고 진행한다. 예전에는 그 하나 때문에 정리 전체가 취소됐다
    desk = tmp_path / '바탕 화면'
    desk.mkdir()
    (desk / 'APEX CARE.lnk').write_bytes(b'')
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    (tmp_path / 'OneDrive').mkdir()
    (tmp_path / 'OneDrive' / '바탕 화면').mkdir()
    (tmp_path / 'OneDrive' / '바탕 화면' / 'APEX CARE.lnk').write_bytes(b'')
    assert un._shortcut_paths() == []


def test_cleanup_bat_is_never_written_over_an_existing_file(monkeypatch, tmp_path):
    # 미리 만들어 둔 파일에 덮어쓰지 않는다('x' 모드)
    un = _load_uninstaller(monkeypatch)
    bat = tmp_path / 'cleanup.bat'
    bat.write_text('echo planted')
    with pytest.raises(FileExistsError):
        un._write_cleanup_bat(str(bat), INSTALL)
    assert bat.read_text() == 'echo planted'


def test_uninstaller_starts_cleanup_with_its_own_working_dir():
    main = next(n for n in ast.parse(_read('tools/uninstall.py')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'main')
    code = ast.unparse(main)
    assert 'os.startfile' not in code                          # 작업 폴더를 물려주는 실행 방식
    popen = next(n for n in ast.walk(main) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'subprocess.Popen')
    kw = {k.arg: ast.unparse(k.value) for k in popen.keywords}
    assert kw.get('cwd') == "_system32('')" and kw.get('shell') == 'False'
