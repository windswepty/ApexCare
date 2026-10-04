"""고정한 작업 표시줄 단추의 아이콘: 이 앱의 바로 가기만, 원래 값을 먼저 기록하고, 기본으로 돌리면 그대로 되돌린다."""

import contextlib
import os
import struct

import pytest

from backend import config_manager
from backend import shortcut_icon as si
from tests.conftest import ROOT


def png(size):
    return si.PNG_MAGIC + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', size, size) + b'\x08\x06\x00\x00\x00' + b'x' * 20


PNGS = [png(s) for s in (256, 48, 32, 16)]
EXE = r'C:\Program Files\APEX CARE\APEX CARE.exe'


@pytest.fixture
def links(monkeypatch):
    """가짜 바로 가기: {경로: [대상, (아이콘 경로, 번호)]}. 파일도 만들어 둔다(목록·존재 확인용)."""
    store = {}
    os.makedirs(si.pinned_dir(), exist_ok=True)

    def add(name, target, icon=('', 0)):
        path = os.path.join(si.pinned_dir(), name)
        open(path, 'wb').close()
        store[path] = [target, icon]
        return path

    def read(path):
        if path not in store:
            return None
        return store[path][0], store[path][1]

    writes = []

    def write(path, icon):
        writes.append((path, icon))
        if store.get('_fail') == path:
            return False
        store[path][1] = (icon[0], int(icon[1]))
        return True

    monkeypatch.setattr(si, 'read_link', read)
    monkeypatch.setattr(si, 'write_icon', write)
    monkeypatch.setattr(si, 'notify', lambda paths: None)
    monkeypatch.setattr(si, '_Com', contextlib.nullcontext)
    monkeypatch.setattr(si, '_own_exe', lambda: EXE)
    monkeypatch.setattr(si, '_same_file', lambda a, b: os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b)))
    store_api = type('Links', (), {})()
    store_api.add, store_api.store, store_api.writes = add, store, writes
    return store_api


def test_ico_holds_each_png_once_and_rejects_bad_input():
    data = si.build_ico(PNGS)
    count = struct.unpack_from('<HHH', data, 0)
    assert count == (0, 1, 4)
    first = struct.unpack_from('<BBBBHHII', data, 6)
    assert first[0] == 16 and first[7] == 6 + 16 * 4                         # 작은 것부터, 자료는 머리 뒤에
    last = struct.unpack_from('<BBBBHHII', data, 6 + 16 * 3)
    assert last[0] == 0 and data[last[7]:last[7] + 8] == si.PNG_MAGIC        # 256 은 0 으로 적는다
    assert si.build_ico([]) is None and si.build_ico([b'GIF89a' + b'0' * 30]) is None
    assert si.build_ico([png(256), png(256)]) is None                        # 같은 크기 두 번
    assert si.build_ico([png(100)]) is None                                  # 아이콘 크기가 아니다


def test_only_this_apps_pins_change_and_the_original_is_recorded_first(links):
    mine = links.add('APEX CARE.lnk', EXE)
    other = links.add('Chrome.lnk', r'C:\Program Files\Google\Chrome\chrome.exe', ('chrome.exe', 0))
    r = si.apply_pngs(PNGS)
    assert r['success'] and r['changed'] == 1
    assert [p for p, _ in links.writes] == [mine]                            # 다른 프로그램의 단추는 건드리지 않는다
    assert links.store[other][1] == ('chrome.exe', 0)
    new_icon = links.store[mine][1][0]
    assert os.path.exists(new_icon) and os.path.basename(new_icon).startswith(si._PREFIX)
    assert config_manager.load_config()[si.CONFIG_KEY] == {mine: ['', 0]}  # 바꾸기 전 값

    # 색을 또 바꿔도 처음 기록은 그대로, 예전 아이콘 파일은 지운다(쌓이지 않게)
    r = si.apply_pngs([png(256), png(32)])
    assert r['changed'] == 1 and config_manager.load_config()[si.CONFIG_KEY] == {mine: ['', 0]}
    assert not os.path.exists(new_icon) and os.path.exists(links.store[mine][1][0])

    # 기본으로: 원래 값으로 되돌리고 기록·아이콘 파일을 지운다
    now_icon = links.store[mine][1][0]
    r = si.restore()
    assert r['success'] and r['restored'] == 1 and links.store[mine][1] == ('', 0)
    assert si.CONFIG_KEY not in config_manager.load_config() and not os.path.exists(now_icon)


def test_nothing_changes_when_the_original_cannot_be_recorded(links, monkeypatch):
    mine = links.add('APEX CARE.lnk', EXE, ('old.ico', 3))
    monkeypatch.setattr(config_manager, 'update_config', lambda change: False)
    r = si.apply_pngs(PNGS)
    assert r['success'] is False and '기록하지 못해' in r['message'] and links.writes == []
    assert links.store[mine][1] == ('old.ico', 3)


def test_failed_restore_keeps_the_record_for_another_try(links):
    mine = links.add('APEX CARE.lnk', EXE, ('orig.ico', 2))
    assert si.apply_pngs(PNGS)['changed'] == 1
    ours = links.store[mine][1][0]
    links.store['_fail'] = mine
    r = si.restore()
    assert r['success'] is False and r['failed'] == ['APEX CARE.lnk']
    assert config_manager.load_config()[si.CONFIG_KEY] == {mine: ['orig.ico', 2]} and os.path.exists(ours)
    del links.store['_fail']
    assert si.restore()['success'] and links.store[mine][1] == ('orig.ico', 2)


def test_restore_leaves_shortcuts_that_no_longer_carry_our_icon(links):
    mine = links.add('APEX CARE.lnk', EXE, ('orig.ico', 0))
    gone = links.add('Old.lnk', EXE)
    assert si.apply_pngs(PNGS)['changed'] == 2
    links.store[mine][1] = (r'D:\my\custom.ico', 0)        # 사용자가 속성 창에서 직접 바꿨다
    os.remove(gone)                                         # 고정을 풀었다
    links.writes.clear()
    r = si.restore()
    assert r['success'] and links.writes == [] and links.store[mine][1] == (r'D:\my\custom.ico', 0)
    assert r['restored'] == 0                               # 되돌려 쓴 것이 없으면 '되돌림' 으로 세지 않는다
    assert si.CONFIG_KEY not in config_manager.load_config()


def test_dev_run_and_missing_pins_change_nothing(links, monkeypatch):
    assert si.apply_pngs(PNGS)['changed'] == 0                              # 고정한 단추 없음
    links.add('APEX CARE.lnk', EXE)
    monkeypatch.setattr(si, '_own_exe', lambda: None)                       # python main.py
    r = si.apply_pngs(PNGS)
    assert r['success'] and r['changed'] == 0 and links.writes == []
    assert si.restore() == {'success': True, 'restored': 0, 'failed': [], 'message': ''}


def test_api_validates_pngs_and_wiring_is_in_place(links):
    from backend.api import Api
    import base64
    api = object.__new__(Api)
    assert api.setPinnedIcon(['not-base64!'])['success'] is False
    assert api.setPinnedIcon(['x'] * 20)['success'] is False
    links.add('APEX CARE.lnk', EXE)
    assert api.setPinnedIcon([base64.b64encode(p).decode() for p in PNGS])['changed'] == 1
    assert api.setPinnedIcon('')['restored'] == 1

    spec = open(os.path.join(ROOT, 'APEX CARE Payload.spec'), encoding='utf-8').read()
    assert "'backend.shortcut_icon'" in spec and "'win32com.shell.shell'" in spec
    theme = open(os.path.join(ROOT, 'src', 'theme.js'), encoding='utf-8').read()
    assert 'api.setPinnedIcon(' in theme
    prep = open(os.path.join(ROOT, 'backend', 'uninstall_prep.py'), encoding='utf-8').read()
    assert 'shortcut_icon.restore()' in prep
