"""system_repair: 구버전 네트워크 튜닝 되돌리기와 명령 실행 방식."""

import os
import subprocess

import pytest

from backend import config_manager, system_repair
from tests.conftest import ROOT
from tests.fakewin import REGISTRY

THROTTLE = system_repair._THROTTLE_KEY
NAGLE = system_repair._NAGLE_BASE
IFACE = '{11111111-2222-3333-4444-555555555555}'


@pytest.fixture
def cmds(monkeypatch):
    """netsh 같은 명령을 실제로 돌리지 않고 기록만 한다."""
    calls = []

    def fake(args, timeout=120):
        calls.append(list(args))
        return {'success': True, 'message': 'ok', 'output': ''}
    monkeypatch.setattr(system_repair, '_run_hidden_cmd', fake)
    return calls


def _backup(b):
    cfg = config_manager.load_config()
    cfg['network_tweak_backup'] = b
    config_manager.save_config(cfg)


def test_no_backup_writes_nothing(cmds):
    REGISTRY.seed('HKLM', THROTTLE, 'NetworkThrottlingIndex', 0xFFFFFFFF)
    REGISTRY.seed('HKLM', f'{NAGLE}\\{IFACE}', 'TcpAckFrequency', 1)

    r = system_repair.restore_network_tweaks()

    assert r['success'] and r['restored'] == []
    assert cmds == [] and REGISTRY.writes == []
    assert REGISTRY.value('HKLM', f'{NAGLE}\\{IFACE}', 'TcpAckFrequency') == 1


def test_restores_backup_and_clears_it(cmds):
    REGISTRY.seed('HKLM', THROTTLE, 'NetworkThrottlingIndex', 0xFFFFFFFF)
    REGISTRY.seed('HKLM', f'{NAGLE}\\{IFACE}', 'TcpAckFrequency', 1)
    REGISTRY.seed('HKLM', f'{NAGLE}\\{IFACE}', 'TCPNoDelay', 1)
    _backup({'autotuning': 'Normal', 'throttling_index': 10,
             'interfaces': {IFACE: {'TcpAckFrequency': None, 'TCPNoDelay': 0}}})

    r = system_repair.restore_network_tweaks()

    assert r['success'], r
    assert cmds == [[system_repair.sys_tool('netsh.exe'), 'int', 'tcp', 'set', 'global', 'autotuninglevel=normal']]
    assert REGISTRY.value('HKLM', THROTTLE, 'NetworkThrottlingIndex') == 10
    assert REGISTRY.get('HKLM', f'{NAGLE}\\{IFACE}', 'TcpAckFrequency') is None
    assert REGISTRY.value('HKLM', f'{NAGLE}\\{IFACE}', 'TCPNoDelay') == 0
    assert 'network_tweak_backup' not in config_manager.load_config()


def test_failed_items_stay_in_backup(cmds):
    REGISTRY.seed('HKLM', THROTTLE, 'NetworkThrottlingIndex', 0xFFFFFFFF)
    REGISTRY.seed('HKLM', f'{NAGLE}\\{IFACE}', 'TcpAckFrequency', 1)
    REGISTRY.deny_write_value('HKLM', f'{NAGLE}\\{IFACE}')
    iface_backup = {IFACE: {'TcpAckFrequency': None, 'TCPNoDelay': None}}
    _backup({'autotuning': 'normal', 'throttling_index': None, 'interfaces': iface_backup})

    r = system_repair.restore_network_tweaks()

    assert r['success'] is False
    assert any(IFACE in f['item'] for f in r['failed'])
    assert REGISTRY.get('HKLM', THROTTLE, 'NetworkThrottlingIndex') is None   # 원래 없던 값
    # 성공한 항목만 빠지고 실패한 어댑터는 남아 다시 시도할 수 있다
    assert config_manager.load_config()['network_tweak_backup'] == {'interfaces': iface_backup}


def test_unknown_autotuning_value_is_not_run(cmds):
    _backup({'autotuning': 'normal & calc.exe'})
    r = system_repair.restore_network_tweaks()
    assert cmds == []
    assert r['failed'] and r['failed'][0]['item'] == 'TCP 자동 튜닝'


def test_run_hidden_cmd_rejects_string_commands(monkeypatch):
    runs = []

    def fake_run(args, **kw):
        runs.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
    monkeypatch.setattr(system_repair.subprocess, 'run', fake_run)

    r = system_repair._run_hidden_cmd('ipconfig /flushdns & del C:\\x')
    assert r['success'] is False and runs == []
    assert system_repair._run_hidden_cmd([])['success'] is False and runs == []

    # 이름만 넘기면 실행하지 않는다. 관리자 권한에서 '현재 폴더' 의 같은 이름 exe 가 먼저 실행될 수 있다
    assert system_repair._run_hidden_cmd(['ipconfig', '/flushdns'])['success'] is False and runs == []

    tool = system_repair.sys_tool('ipconfig.exe')
    assert os.path.isabs(tool) and tool.lower().endswith(os.path.join('system32', 'ipconfig.exe').lower()) \
        or 'sysnative' in tool.lower()
    assert system_repair._run_hidden_cmd([tool, '/flushdns'])['success']
    args, kw = runs[0]
    assert args == [tool, '/flushdns'] and kw.get('shell') is False


def test_every_tool_is_launched_by_absolute_path():
    import re
    for rel in ('backend/system_repair.py', 'backend/system_monitor.py', 'backend/storage.py', 'backend/uninstaller.py'):
        with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
            src = f.read()
        # 실행 목록의 첫 인자로 이름만 쓴 곳이 없어야 한다(sys_tool(...)·_powershell_exe() 로 절대 경로)
        assert not re.search(r"\[\s*[\"'](sfc|dism|defrag|netsh|ipconfig|taskkill|powershell|cmd|reg|ping)(\.exe)?[\"']", src, re.I), rel
