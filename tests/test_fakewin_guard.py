"""가짜 Windows 자체의 안전장치. 이게 깨지면 다른 테스트가 진짜 시스템을 바꿀 수 있다."""

import ctypes
import os
import subprocess
import sys

import psutil
import pytest

from tests import fakewin
from tests.conftest import ROOT


def _run_python(code):
    """막히기 전의 진짜 Popen 으로 별도 파이썬을 띄운다. 그 프로세스엔 fakewin 이 없다."""
    Popen = fakewin.REAL['subprocess.Popen']
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    p = Popen([sys.executable, '-c', code], cwd=ROOT, env=env,
              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate(timeout=120)
    return p.returncode, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')


def test_backend_import_without_fakewin_is_blocked():
    # 문지기만 있고 가짜 Windows 는 없는 상태. backend 코드가 한 줄도 돌기 전에 멈춰야 한다.
    code = (
        "import sys\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "from tests import import_guard\n"
        "import_guard.install()\n"
        "import backend.system_state\n"
        "print('IMPORTED')\n"
    )
    rc, out, err = _run_python(code)
    assert rc != 0
    assert 'IMPORTED' not in out
    assert 'BackendImportBlocked' in err
    for mod in ('perf_modes', 'optimizer', 'game_booster', 'debloater', 'system_repair'):
        rc, out, err = _run_python(code.replace('backend.system_state', f'backend.{mod}'))
        assert rc != 0 and 'BackendImportBlocked' in err, mod


def test_win32_calls_are_blocked():
    with pytest.raises(fakewin.BlockedCall):
        ctypes.WinDLL('powrprof')
    with pytest.raises(fakewin.BlockedCall):
        ctypes.windll.shell32.IsUserAnAdmin()
    with pytest.raises(fakewin.BlockedCall):
        subprocess.run(['powercfg', '/list'])
    with pytest.raises(fakewin.BlockedCall):
        os.system('echo hi')


def test_real_process_changes_are_blocked():
    me = psutil.Process(os.getpid())
    current = me.nice()                     # 읽기는 된다
    with pytest.raises(fakewin.BlockedCall):
        me.nice(current)                    # 같은 값이라도 쓰기는 막는다


def test_backend_holds_fakes_and_sandbox():
    from backend import config_manager, optimizer, system_repair, system_state

    assert system_state.winreg is fakewin.winreg
    assert optimizer.winreg is fakewin.winreg
    assert sys.modules['winreg'] is fakewin.winreg
    sandbox = os.path.realpath(fakewin.SANDBOX)
    assert os.path.realpath(system_state.JOURNAL_PATH).startswith(sandbox)
    assert os.path.realpath(config_manager.CONFIG_FILE).startswith(sandbox)
    # 가짜 레지스트리에 쓴 것은 메모리에만 남는다
    system_repair._restore_dword(r'SOFTWARE\ApexCareTest', 'X', None)
    assert fakewin.REGISTRY.writes == []


def test_not_admin_by_default():
    # 관리자 판정도 Win32 호출이라 막혀 있다. 막히면 '관리자 아님' 으로 떨어져야 한다.
    from backend import perf_modes
    assert perf_modes.is_admin() is False
    assert perf_modes.apply_mode('gaming')['error'] == 'UAC_REQUIRED'
    assert fakewin.POWER.activations == []
