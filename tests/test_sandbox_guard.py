"""tools/sandbox/real_checks.py 는 시스템을 바꾼다. Windows 샌드박스 밖에서는 절대 돌면 안 된다.

모듈은 가짜 Windows 위에서 불러오기만 하고(점검 함수는 부르지 않는다) 차단이 동작하는지 본다.
"""

import importlib.util
import os

import pytest

from tests.conftest import ROOT

PATH = os.path.join(ROOT, 'tools', 'sandbox', 'real_checks.py')


def _load():
    spec = importlib.util.spec_from_file_location('apex_real_checks', PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize('user, flag', [
    ('developer', '1'),                  # 표시가 있어도 샌드박스 계정이 아니면 거부
    ('WDAGUtilityAccount', None),        # 샌드박스 계정이어도 실행 스크립트 표시가 없으면 거부
    ('', None),
])
def test_refuses_outside_sandbox(monkeypatch, user, flag):
    mod = _load()
    monkeypatch.setenv('USERNAME', user)
    if flag is None:
        monkeypatch.delenv('APEX_SANDBOX', raising=False)
    else:
        monkeypatch.setenv('APEX_SANDBOX', flag)
    with pytest.raises(SystemExit) as e:
        mod.main()
    assert e.value.code == 2
    assert mod.RESULTS == []             # 점검이 하나도 돌지 않았다


def test_guard_runs_before_other_imports():
    with open(PATH, encoding='utf-8') as f:
        src = f.read()
    guard = src.index("if __name__ == '__main__':\n    refuse_outside_sandbox()")
    assert guard < src.index('import ctypes') and guard < src.index('import subprocess')
    main_body = src[src.index('def main():'):]
    assert main_body.split('\n')[1].strip() == 'refuse_outside_sandbox()'


def test_sandbox_launcher_maps_repo_and_python_read_only():
    with open(os.path.join(ROOT, 'tools', 'sandbox', 'start_sandbox_check.ps1'), encoding='utf-8-sig') as f:
        src = f.read()
    assert '<Networking>Disable</Networking>' in src
    # 저장소·파이썬·설치 파일(dist)은 읽기 전용, 결과 폴더만 쓰기 가능
    assert src.count('<ReadOnly>true</ReadOnly>') == 3 and src.count('<ReadOnly>false</ReadOnly>') == 1
    assert '<SandboxFolder>C:\\apex\\out</SandboxFolder><ReadOnly>false' in src
    for folder in ('repo', 'python', 'dist'):
        assert f'<SandboxFolder>C:\\apex\\{folder}</SandboxFolder><ReadOnly>true' in src
    with open(os.path.join(ROOT, 'tools', 'sandbox', 'run_in_sandbox.cmd'), encoding='utf-8') as f:
        cmd = f.read()
    assert 'set APEX_SANDBOX=1' in cmd and 'real_checks.py' in cmd


def test_sandbox_shuts_itself_down_but_never_a_real_pc():
    # 끝난 샌드박스가 열려 있으면 연결된 dist 의 파일을 잡아 다음 build_all.bat 이 실패한다(실제로 났다).
    # 그래서 스스로 닫지만, 이 파일이 실제 PC 에서 실행돼도 그 PC 를 끄면 안 된다.
    with open(os.path.join(ROOT, 'tools', 'sandbox', 'run_in_sandbox.cmd'), encoding='utf-8') as f:
        lines = [l for l in f.read().splitlines() if 'shutdown' in l.lower() and not l.lower().startswith('rem')]
    assert lines
    for line in lines:
        assert line.lower().startswith('if /i "%username%"=="wdagutilityaccount" ')
