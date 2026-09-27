"""debloater: 정책 항목은 저널(group 'debloat')로 되돌릴 수 있고, PowerShell 은 셸 없이 부른다."""

import subprocess

import pytest

from backend import debloater
from backend import system_state as ss
from tests.fakewin import REGISTRY, SERVICES

DATA = r'SOFTWARE\Policies\Microsoft\Windows\DataCollection'
SEARCH = r'SOFTWARE\Policies\Microsoft\Windows\Windows Search'


def test_telemetry_policy_and_diagtrack_restored_via_journal():
    SERVICES.add('DiagTrack', 2)
    REGISTRY.seed('HKLM', DATA, 'MaxTelemetryAllowed', 3)     # 정책 키에 다른 값이 있어도 건드리지 않는다

    ok, reason = debloater._apply_telemetry_policy()

    assert ok, reason
    assert REGISTRY.value('HKLM', DATA, 'AllowTelemetry') == 0
    assert SERVICES.start_of('DiagTrack')[0] == 4
    entries = ss.pending_changes()
    assert {e['group'] for e in entries.values()} == {debloater.DEBLOAT_GROUP}
    assert set(entries) == {f'reg:HKLM\\{DATA}\\AllowTelemetry', 'svc:diagtrack'}

    res = ss.restore_group(debloater.DEBLOAT_GROUP)

    assert res['ok'], res
    assert REGISTRY.get('HKLM', DATA, 'AllowTelemetry') is None
    assert REGISTRY.value('HKLM', DATA, 'MaxTelemetryAllowed') == 3
    assert ss.service_start_type('DiagTrack') == 'auto'
    assert ss.pending_changes() == {}


def test_cortana_policy_restores_previous_value():
    REGISTRY.seed('HKLM', SEARCH, 'AllowCortana', 1)
    ok, _ = debloater._apply_cortana_policy()
    assert ok and REGISTRY.value('HKLM', SEARCH, 'AllowCortana') == 0
    assert ss.restore_group(debloater.DEBLOAT_GROUP)['ok']
    assert REGISTRY.value('HKLM', SEARCH, 'AllowCortana') == 1


def test_missing_diagtrack_is_skipped():
    ok, reason = debloater._apply_telemetry_policy()
    assert ok, reason
    assert SERVICES.calls == []


@pytest.fixture
def ps_runs(monkeypatch):
    runs = []

    def fake_run(args, **kw):
        runs.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout='0\n', stderr='')
    monkeypatch.setattr(debloater.subprocess, 'run', fake_run)
    return runs


def test_powershell_is_called_without_shell(ps_runs):
    assert debloater._remove_appx('*bing*') is True
    assert len(ps_runs) == 2                       # 제거 + 남은 개수 확인
    for args, kw in ps_runs:
        assert isinstance(args, list) and args[0] == 'powershell.exe'
        assert kw.get('shell') is False
        assert args[-2] == '-Command'


def test_suspicious_pattern_is_rejected(ps_runs):
    assert debloater._remove_appx("*bing*'; Remove-Item C:\\ -Recurse; '") is False
    assert ps_runs == []


def test_debloater_run_reports_each_item(ps_runs, monkeypatch):
    SERVICES.add('DiagTrack', 2)
    SERVICES.fail.add('DiagTrack')
    debloater._run_debloater(['telemetry', 'bing'])
    st = debloater.get_debloat_status()
    assert st['running'] is False
    assert any('Bing' in s for s in st['succeeded'])
    assert any('원격 분석' in f and 'DiagTrack' in f for f in st['failed'])
