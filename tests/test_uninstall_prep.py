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
    assert code.index('_app_running()') < code.index('_revert_system_changes(') < code.index('rmdir /s /q')


def test_new_module_is_in_pyinstaller_hiddenimports():
    assert "'backend.uninstall_prep'" in _read('APEX CARE Payload.spec')
