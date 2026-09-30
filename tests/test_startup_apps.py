"""시작 프로그램: Run 값은 지우지 않고 StartupApproved 표시만 저널을 거쳐 바꾼다(작업 관리자와 같은 방식)."""

import copy
import json

import pytest

from backend import optimizer, perf_modes
from backend import system_state as ss
from tests import fakewin
from tests.fakewin import REGISTRY

RUN_U = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_M = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
RUN_32 = r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'
APP_U = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
APP_M = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
APP_32 = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32'
LEGACY = r'Software\APEXCARE\DisabledStartup'
DISABLED_BY_TASKMGR = b'\x03\x00\x00\x00' + b'\x11' * 8


def _dump():
    out = {}

    def walk(key, path):
        out[path] = {n: (v, t) for n, (_, v, t) in key.values.items()}
        for name, sub in key.subkeys.items():
            walk(sub, f'{path}\\{name}')
    for hive, root in REGISTRY.roots.items():
        walk(root, fakewin._HIVE_NAMES[hive])
    return copy.deepcopy(out)


@pytest.fixture
def pc():
    """Windows 에 원래 있는 키와 시작 프로그램."""
    for hive, path in (('HKCU', APP_U), ('HKLM', APP_M), ('HKLM', APP_32)):
        REGISTRY.seed_key(hive, path)
    REGISTRY.seed('HKCU', RUN_U, 'Discord', r'"C:\apps\discord.exe" --tray', fakewin.REG_SZ)
    REGISTRY.seed('HKCU', RUN_U, 'Helper', r'C:\apps\helper.exe', fakewin.REG_SZ)
    REGISTRY.seed('HKLM', RUN_M, 'Helper', r'C:\apps\helper-all.exe', fakewin.REG_SZ)   # 같은 이름, 다른 위치
    REGISTRY.seed('HKLM', RUN_32, 'Adobe', r'C:\apps\adobe.exe', fakewin.REG_SZ)
    REGISTRY.seed('HKCU', APP_U, 'Helper', DISABLED_BY_TASKMGR, fakewin.REG_BINARY)      # 작업 관리자에서 끔
    return _dump()


def _app(app_id):
    return next(a for a in optimizer.get_startup_apps() if a['id'] == app_id)


def test_list_separates_locations_and_reads_task_manager_state(pc):
    ids = {a['id']: a['enabled'] for a in optimizer.get_startup_apps()}
    assert ids == {'HKCU:Discord': True, 'HKCU:Helper': False, 'HKLM:Helper': True, 'HKLM32:Adobe': True}


def test_disable_keeps_run_value_and_is_journaled(pc):
    r = optimizer.toggle_startup_app('HKCU:Discord', False)

    assert r['success'], r
    assert REGISTRY.value('HKCU', RUN_U, 'Discord') == r'"C:\apps\discord.exe" --tray'   # Run 은 그대로
    flag = REGISTRY.value('HKCU', APP_U, 'Discord')
    assert isinstance(flag, bytes) and flag[0] & 1                   # 작업 관리자가 읽는 '꺼짐'
    assert _app('HKCU:Discord')['enabled'] is False
    entry = ss.pending_changes()['reg:HKCU\\' + APP_U + '\\Discord']
    assert entry['group'] == 'startup:HKCU:Discord' and entry['existed'] is False


def test_enabling_again_restores_original_instead_of_writing_new_value(pc):
    optimizer.toggle_startup_app('HKCU:Discord', False)
    assert optimizer.toggle_startup_app('HKCU:Discord', True)['success']
    assert _dump() == pc and ss.pending_changes() == {}


def test_item_disabled_in_task_manager_goes_back_to_exact_original_bytes(pc):
    assert optimizer.toggle_startup_app('HKCU:Helper', True)['success']
    assert REGISTRY.value('HKCU', APP_U, 'Helper')[0] == 0x02
    # 원래 값(bytes)은 저널 JSON 에 16진수로 남는다
    with open(ss.JOURNAL_PATH, encoding='utf-8') as f:
        stored = json.load(f)['entries']['reg:HKCU\\' + APP_U + '\\Helper']['value']
    assert stored == {'__bytes__': DISABLED_BY_TASKMGR.hex()}

    assert optimizer.toggle_startup_app('HKCU:Helper', False)['success']
    assert REGISTRY.value('HKCU', APP_U, 'Helper') == DISABLED_BY_TASKMGR
    assert ss.pending_changes() == {}


@pytest.mark.usefixtures('as_admin')
def test_revert_everything_turns_startup_apps_back_on(pc):
    optimizer.toggle_startup_app('HKCU:Discord', False)
    optimizer.toggle_startup_app('HKLM32:Adobe', False)
    assert perf_modes.revert_everything()['success']
    assert _dump() == pc


def test_same_name_in_two_places_needs_an_id(pc):
    r = optimizer.toggle_startup_app('Helper', True)             # 이름만: 어느 쪽인지 모른다
    assert r['success'] is False and '여러 위치' in r['message']
    assert REGISTRY.writes == []
    assert optimizer.toggle_startup_app('Discord', False)['success']   # 하나뿐이면 이름으로도 된다


def test_write_failure_is_reported_and_nothing_changes(pc):
    REGISTRY.deny_write_value('HKLM', APP_32)
    r = optimizer.toggle_startup_app('HKLM32:Adobe', False)
    assert r['success'] is False
    assert _app('HKLM32:Adobe')['enabled'] is True and REGISTRY.value('HKLM', RUN_32, 'Adobe')


def test_legacy_entry_is_restored_to_its_own_hive_when_enabled(pc):
    # 예전 버전: Run 에서 지우고 HKCU\Software\APEXCARE 에 숨겼다
    REGISTRY.seed('HKCU', LEGACY, 'OldTool', r'C:\apps\old.exe /min', fakewin.REG_SZ)
    REGISTRY.seed('HKCU', LEGACY + r'\_origin', 'OldTool', 'HKLM|' + RUN_M, fakewin.REG_SZ)
    legacy = _app('LEGACY:OldTool')
    assert legacy['enabled'] is False and legacy['legacy'] is True

    r = optimizer.toggle_startup_app('LEGACY:OldTool', True)

    assert r['success'], r
    assert REGISTRY.value('HKLM', RUN_M, 'OldTool') == r'C:\apps\old.exe /min'
    assert REGISTRY.get('HKCU', RUN_U, 'OldTool') is None
    assert _app('HKLM:OldTool')['enabled'] is True
    assert REGISTRY.get('HKCU', LEGACY, 'OldTool') is None
    assert ss.pending_changes() == {}           # 되살린 Run 값은 사용자 값의 복원이라 저널에 없다


def test_tampered_legacy_origin_is_refused(pc):
    REGISTRY.seed('HKCU', LEGACY, 'Evil', r'C:\evil.exe', fakewin.REG_SZ)
    REGISTRY.seed('HKCU', LEGACY + r'\_origin', 'Evil', r'HKLM|SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce',
                  fakewin.REG_SZ)
    r = optimizer.toggle_startup_app('LEGACY:Evil', True)
    assert r['success'] is False
    assert not [w for w in REGISTRY.writes if w[0] == 'set']


# ── 시작프로그램 폴더 ─────────────────────────────────────
APP_FOLDER_U = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'
APP_FOLDER_M = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'


@pytest.fixture
def folders(pc, tmp_path, monkeypatch):
    """시작프로그램 폴더 두 곳(임시 폴더). 바로 가기 파일은 이 테스트가 만든 빈 파일이다."""
    user, common = tmp_path / 'Startup', tmp_path / 'CommonStartup'
    user.mkdir()
    common.mkdir()
    (user / 'Notes.lnk').write_bytes(b'lnk')
    (user / 'desktop.ini').write_bytes(b'[.ShellClassInfo]')          # 목록에 나오면 안 된다
    (common / 'Vendor Agent.lnk').write_bytes(b'lnk')
    monkeypatch.setattr(optimizer, '_startup_folder',
                        lambda tag: str(user) if tag == 'FOLDER' else str(common))
    return {'user': user, 'common': common, 'dump': _dump()}


def test_startup_folder_items_are_listed_like_task_manager(folders):
    apps = {a['id']: a for a in optimizer.get_startup_apps()}
    assert 'FOLDER:Notes.lnk' in apps and 'FOLDER_ALL:Vendor Agent.lnk' in apps
    assert not any('desktop.ini' in i for i in apps)
    assert apps['FOLDER:Notes.lnk']['enabled'] is True
    assert apps['FOLDER:Notes.lnk']['command'].endswith('Notes.lnk')
    assert apps['FOLDER:Notes.lnk']['name'] == 'Notes'                 # 작업 관리자처럼 .lnk 없이


def test_disabling_a_folder_item_keeps_the_file_and_marks_startupapproved(folders):
    r = optimizer.toggle_startup_app('FOLDER:Notes.lnk', False)

    assert r['success'], r
    assert (folders['user'] / 'Notes.lnk').exists()                    # 파일은 그대로(작업 관리자와 같은 방식)
    flag = REGISTRY.value('HKCU', APP_FOLDER_U, 'Notes.lnk')
    assert isinstance(flag, bytes) and flag[0] & 1
    assert _app('FOLDER:Notes.lnk')['enabled'] is False

    assert optimizer.toggle_startup_app('FOLDER:Notes.lnk', True)['success']
    assert _dump() == folders['dump'] and ss.pending_changes() == {}   # 원래 없던 값·키는 지워진다


@pytest.mark.usefixtures('as_admin')
def test_revert_everything_turns_folder_items_back_on(folders):
    assert optimizer.toggle_startup_app('FOLDER_ALL:Vendor Agent.lnk', False)['success']
    assert REGISTRY.value('HKLM', APP_FOLDER_M, 'Vendor Agent.lnk')[0] & 1
    assert perf_modes.revert_everything()['success']
    assert _dump() == folders['dump']


def test_removed_folder_item_is_reported_not_toggled(folders):
    (folders['user'] / 'Notes.lnk').unlink()
    r = optimizer.toggle_startup_app('FOLDER:Notes.lnk', False)
    assert r['success'] is False and '찾지 못했습니다' in r['message']
    assert REGISTRY.writes == []


def test_folder_location_cannot_be_used_as_legacy_origin(pc):
    # 예전 버전 기록은 Run 경로만 받는다. 폴더 위치 이름으로 위조한 기록은 거부한다.
    REGISTRY.seed('HKCU', LEGACY, 'X', r'C:\x.exe', fakewin.REG_SZ)
    REGISTRY.seed('HKCU', LEGACY + r'\_origin', 'X', 'FOLDER|anything', fakewin.REG_SZ)
    assert optimizer.toggle_startup_app('LEGACY:X', True)['success'] is False
