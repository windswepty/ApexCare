"""debloater: 정책은 저널(group 'debloat')로 되돌리고, 앱은 이 계정에서만 기록 후 제거하며 기록으로 되살린다."""

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


# ── 앱 제거 · 되살리기 ─────────────────────────────────────
# PowerShell(Get-AppxPackage·Remove-AppxPackage·Add-AppxPackage -Register)을 FakeAppx 로 흉내 낸다.

import json  # noqa: E402
import os  # noqa: E402

ITEM = {x['id']: x for x in debloater.DEBLOAT_SAFE_LIST}


class FakeAppx:
    """현재 계정의 Appx 설치 상태. debloater._run_ps_json 자리에 끼운다."""

    def __init__(self, root):
        self.root = str(root)                 # WindowsApps 흉내
        self.catalog = {}                     # 이름 -> 패키지 정보 (설치 파일이 있는 한 다시 등록할 수 있다)
        self.installed = set()
        self.remove_ignored = set()           # Remove 가 성공을 돌려주지만 그대로 남는 것
        self.register_ignored = set()         # Register 가 성공을 돌려주지만 설치되지 않는 것
        self.calls = []

    def add(self, name, files=True):
        full = f'{name}_1.0.0.0_x64__8wekyb3d8bbwe'
        loc = os.path.join(self.root, full)
        if files:
            os.makedirs(loc, exist_ok=True)
            with open(os.path.join(loc, 'AppxManifest.xml'), 'w') as f:
                f.write('<Package/>')
        self.catalog[name] = {'name': name, 'fullName': full, 'familyName': f'{name}_8wekyb3d8bbwe',
                              'installLocation': loc, 'nonRemovable': False, 'isFramework': False}
        self.installed.add(name)

    def by_full(self, full):
        return next(n for n, p in self.catalog.items() if p['fullName'] == full)

    def __call__(self, body, arg, timeout):
        if body is debloater._PS_QUERY:
            self.calls.append(('query', list(arg['names'])))
            return True, [dict(self.catalog[n], query=n) for n in arg['names'] if n in self.installed], None
        if body is debloater._PS_REMOVE:
            self.calls.append(('remove', list(arg['fullNames'])))
            for f in arg['fullNames']:
                n = self.by_full(f)
                if n not in self.remove_ignored:
                    self.installed.discard(n)
            return True, [{'fullName': f, 'ok': True, 'error': ''} for f in arg['fullNames']], None
        if body is debloater._PS_REGISTER:
            self.calls.append(('register', list(arg['manifests'])))
            for m in arg['manifests']:
                folder = os.path.normcase(os.path.realpath(os.path.dirname(m)))
                for n, p in self.catalog.items():
                    if os.path.normcase(os.path.realpath(p['installLocation'])) == folder \
                            and n not in self.register_ignored:
                        self.installed.add(n)
            return True, [{'manifest': m, 'ok': True, 'error': ''} for m in arg['manifests']], None
        raise AssertionError('알 수 없는 스크립트')

    def ran(self, kind):
        return [c for c in self.calls if c[0] == kind]


@pytest.fixture
def appx(tmp_path, monkeypatch):
    fake = FakeAppx(tmp_path / 'WindowsApps')
    monkeypatch.setattr(debloater, '_run_ps_json', fake)
    monkeypatch.setattr(debloater, '_windowsapps_roots', lambda: [fake.root])
    monkeypatch.setattr(debloater, '_current_account', lambda: 'kim')
    monkeypatch.setattr(debloater, '_desktop_accounts', lambda: {'kim'})
    return fake


def test_list_uses_exact_names_and_spares_media_player():
    for item in debloater.DEBLOAT_SAFE_LIST:
        for pkg in item.get('packages', []):
            assert debloater._PKG_RE.match(pkg), pkg            # 와일드카드 없음
    all_pkgs = {p for x in debloater.DEBLOAT_SAFE_LIST for p in x.get('packages', [])}
    for keep in ('Microsoft.ZuneMusic', 'Microsoft.XboxGamingOverlay', 'Microsoft.GamingApp',
                 'Microsoft.XboxIdentityProvider'):
        assert keep not in all_pkgs


def test_only_exact_packages_in_this_account_are_removed_and_recorded(appx):
    appx.add('Microsoft.ZuneVideo')
    appx.add('Microsoft.ZuneMusic')                       # 미디어 플레이어

    status, detail = debloater._apply_appx_item(ITEM['zune'], 'kim')

    assert status == 'removed', detail
    assert appx.installed == {'Microsoft.ZuneMusic'}
    assert appx.ran('remove') == [('remove', ['Microsoft.ZuneVideo_1.0.0.0_x64__8wekyb3d8bbwe'])]
    rec = debloater.get_removed_apps()
    assert [r['name'] for r in rec] == ['Microsoft.ZuneVideo']
    assert rec[0]['account'] == 'kim' and rec[0]['manifestFound'] is True


def test_removed_apps_of_one_item_are_told_apart(appx):
    # 실제 PC 에서 'MSN 뉴스·날씨' 하나를 지우자 같은 이름이 두 줄 보였다. 패키지마다 앱 이름을 붙인다.
    appx.add('Microsoft.BingNews')
    appx.add('Microsoft.BingWeather')
    status, detail = debloater._apply_appx_item(ITEM['bing'], 'kim')
    assert status == 'removed', detail
    names = {r['name']: r['appName'] for r in debloater.get_removed_apps()}
    assert names == {'Microsoft.BingNews': '뉴스', 'Microsoft.BingWeather': '날씨'}
    for item in debloater.DEBLOAT_SAFE_LIST:
        if len(item.get('packages', [])) > 1:
            assert all(debloater.PACKAGE_APP_NAMES.get(p) for p in item['packages']), item['id']


def test_wildcards_are_never_sent_to_powershell(appx):
    debloater._query_packages(['*zune*', 'Microsoft.BingNews', "x'; Remove-Item C:\\ -Recurse"])
    assert appx.ran('query') == [('query', ['Microsoft.BingNews'])]


def test_install_state_is_read_only_and_exact(appx):
    appx.add('Microsoft.BingWeather')                     # 'MSN 뉴스·날씨' 중 하나만 있어도 설치됨
    appx.add('Microsoft.SkypeApp')
    r = debloater.get_install_state()
    assert r['ok'] and r['items']['bing'] == 'installed' and r['items']['skype'] == 'installed'
    assert r['items']['solitaire'] == 'not_installed'
    assert 'telemetry' not in r['items']                   # 정책 항목은 설치 여부가 없다
    assert appx.ran('remove') == [] and appx.ran('register') == []     # 읽기만 한다


def test_install_state_unknown_is_not_reported_as_missing(appx, monkeypatch):
    monkeypatch.setattr(debloater, '_run_ps_json', lambda *a: (False, [], 'PowerShell 시간 초과'))
    r = debloater.get_install_state()
    assert r['ok'] is False and set(r['items'].values()) == {'unknown'}


def test_not_installed_is_not_reported_as_removed(appx):
    debloater._run_debloater(['solitaire'])
    st = debloater.get_debloat_status()
    assert st['succeeded'] == [] and st['failed'] == []
    assert len(st['skipped']) == 1
    assert appx.ran('remove') == []


def test_nothing_is_removed_when_record_cannot_be_saved(appx, monkeypatch):
    appx.add('Microsoft.SkypeApp')
    monkeypatch.setattr(debloater, '_save_removed', lambda data: False)
    status, _ = debloater._apply_appx_item(ITEM['skype'], 'kim')
    assert status == 'failed'
    assert 'Microsoft.SkypeApp' in appx.installed and appx.ran('remove') == []


def test_removal_that_does_not_stick_is_failure_and_not_recorded(appx):
    appx.add('Microsoft.WindowsMaps')
    appx.remove_ignored.add('Microsoft.WindowsMaps')
    status, detail = debloater._apply_appx_item(ITEM['maps'], 'kim')
    assert status == 'failed' and '제거되지 않았습니다' in detail
    assert debloater.get_removed_apps() == []


def test_removed_apps_are_restored_and_record_cleared(appx):
    appx.add('Microsoft.BingNews')
    appx.add('Microsoft.BingWeather')
    assert debloater._apply_appx_item(ITEM['bing'], 'kim')[0] == 'removed'
    assert appx.installed == set()

    res = debloater.restore_removed_apps()

    assert res['success'], res
    assert appx.installed == {'Microsoft.BingNews', 'Microsoft.BingWeather'}
    assert debloater.get_removed_apps() == []


def test_restore_one_app_by_full_name(appx):
    appx.add('Microsoft.BingNews')
    appx.add('Microsoft.BingWeather')
    debloater._apply_appx_item(ITEM['bing'], 'kim')
    res = debloater.restore_removed_apps([appx.catalog['Microsoft.BingNews']['fullName']])
    assert res['success'] and appx.installed == {'Microsoft.BingNews'}
    assert [r['name'] for r in debloater.get_removed_apps()] == ['Microsoft.BingWeather']


def test_restore_without_install_files_points_to_store_and_keeps_record(appx):
    appx.add('Microsoft.3DBuilder')
    debloater._apply_appx_item(ITEM['3dbuilder'], 'kim')
    os.remove(os.path.join(appx.catalog['Microsoft.3DBuilder']['installLocation'], 'AppxManifest.xml'))

    res = debloater.restore_removed_apps()

    assert res['success'] is False
    assert 'Microsoft Store' in res['failed'][0]['reason']
    assert appx.ran('register') == []
    assert debloater.get_removed_apps()[0]['manifestFound'] is False


def test_restore_refuses_manifest_outside_windowsapps(appx, tmp_path):
    appx.add('Microsoft.YourPhone')
    debloater._apply_appx_item(ITEM['yourphone'], 'kim')
    # 사용자 폴더의 기록을 누가 고쳐서 다른 곳의 매니페스트를 가리키게 했다
    evil = tmp_path / 'evil'
    evil.mkdir()
    (evil / 'AppxManifest.xml').write_text('<Package/>')
    path = debloater._removed_path()
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data['apps'][0]['installLocation'] = str(evil)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)

    res = debloater.restore_removed_apps()

    assert res['success'] is False and appx.ran('register') == []


def test_restore_refuses_apps_removed_by_another_account(appx, monkeypatch):
    appx.add('Microsoft.WindowsFeedbackHub')
    debloater._apply_appx_item(ITEM['feedback'], 'kim')
    monkeypatch.setattr(debloater, '_current_account', lambda: 'admin')
    res = debloater.restore_removed_apps()
    assert res['success'] is False and '다른 계정' in res['failed'][0]['reason']
    assert appx.ran('register') == []


def test_register_reported_ok_but_not_installed_is_failure(appx):
    appx.add('Microsoft.XboxApp')
    debloater._apply_appx_item(ITEM['xbox'], 'kim')
    appx.register_ignored.add('Microsoft.XboxApp')
    res = debloater.restore_removed_apps()
    assert res['success'] is False and '설치돼 있지 않습니다' in res['failed'][0]['reason']
    assert len(debloater.get_removed_apps()) == 1            # 다시 시도할 수 있게 남긴다


def test_removal_refused_when_running_as_another_account(appx, monkeypatch):
    appx.add('Microsoft.BingNews')
    monkeypatch.setattr(debloater, '_current_account', lambda: 'admin')    # 다른 관리자 계정으로 승격
    debloater._run_debloater(['bing'])
    st = debloater.get_debloat_status()
    assert st['succeeded'] == [] and '다른 계정' in st['failed'][0]
    assert appx.ran('remove') == [] and 'Microsoft.BingNews' in appx.installed


def test_debloater_run_reports_each_item(appx):
    appx.add('Microsoft.BingNews')
    SERVICES.add('DiagTrack', 2)
    SERVICES.fail.add('DiagTrack')
    debloater._run_debloater(['telemetry', 'bing'])
    st = debloater.get_debloat_status()
    assert st['running'] is False
    assert any('Bing' in s for s in st['succeeded'])
    assert any('원격 분석' in f and 'DiagTrack' in f for f in st['failed'])


def test_powershell_runs_without_shell_and_names_never_in_command_line(monkeypatch):
    runs = []

    def fake_run(args, **kw):
        runs.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout=b'{"ok":true,"rows":[{"name":"x"}]}\r\n', stderr=b'')
    monkeypatch.setattr(debloater.subprocess, 'run', fake_run)

    ok, rows, err = debloater._run_ps_json(debloater._PS_QUERY, {'names': ['Microsoft.BingNews']}, 5)

    assert ok and rows == [{'name': 'x'}]
    args, kw = runs[0]
    assert isinstance(args, list) and args[0].lower().endswith('powershell.exe')
    assert kw.get('shell') is False and '-EncodedCommand' in args
    assert not any('Microsoft.BingNews' in a for a in args)          # 인자는 환경 변수로만
    assert 'Microsoft.BingNews' in kw['env'][debloater._ARG_ENV]
