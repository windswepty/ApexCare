"""링크·정션은 지우지 않는다. 경로를 실제 위치로 풀면 링크가 아니라 링크가 가리키는 원래 폴더가 지워진다."""

import os

import pytest

from backend import safe_delete, uninstaller
from tests import fakewin
from tests.fakewin import REG_SZ, REGISTRY
from tests.test_junk_clean import make_dir_link

_UNINST = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'


def _write(path, size=4096):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x' * size)


@pytest.fixture
def linked(tmp_path, monkeypatch):
    """Program Files 안에 다른 프로그램의 데이터 폴더를 가리키는 링크 하나."""
    pf = tmp_path / 'Program Files'
    real = pf / 'Other Vendor' / 'Data'            # 다른 프로그램(또는 사용자)의 진짜 데이터
    _write(str(real / 'save.dat'))
    link = pf / 'Foo App'
    make_dir_link(real, link)
    monkeypatch.setenv('ProgramFiles', str(pf))
    uninstaller._known_locations.clear()
    return {'pf': pf, 'real': real, 'link': link}


def test_recycle_refuses_a_link_and_leaves_the_target(linked):
    r = safe_delete.to_recycle_bin([str(linked['link'])])

    assert r['ok'] == [] and r['bytes'] == 0
    assert '링크' in r['failed'][0]['reason']
    assert (linked['real'] / 'save.dat').exists() and os.path.lexists(linked['link'])


def test_permanent_delete_refuses_a_link(linked):
    r = safe_delete.permanent_delete([str(linked['link'])], reason='테스트')
    assert r['ok'] == [] and r['failed'] and (linked['real'] / 'save.dat').exists()


def test_link_named_like_the_app_is_not_offered_as_leftover(linked):
    REGISTRY.seed('HKLM', f'{_UNINST}\\Foo', 'DisplayName', 'Foo App', REG_SZ)
    REGISTRY.seed('HKLM', f'{_UNINST}\\Foo', 'UninstallString', 'uninst.exe', REG_SZ)
    REGISTRY.seed('HKLM', f'{_UNINST}\\Foo', 'InstallLocation', str(linked['link']), REG_SZ)
    uninstaller.get_installed_apps()
    del REGISTRY._find(fakewin._hive('HKLM'), _UNINST.split('\\')).subkeys['foo']   # 제거가 끝났다

    assert uninstaller.scan_leftovers('Foo App')['items'] == []
    c = uninstaller.clean_leftovers([str(linked['link'])])          # 화면을 거치지 않고 와도 막는다
    assert c['deleted'] == 0 and c['success'] is False
    assert (linked['real'] / 'save.dat').exists()


def test_sizes_do_not_count_what_is_behind_a_link(tmp_path):
    folder = tmp_path / 'Leftover'
    _write(str(folder / 'own.bin'), 1000)
    outside = tmp_path / 'Elsewhere'
    _write(str(outside / 'big.bin'), 50_000)
    make_dir_link(outside, folder / 'shortcut')

    # 휴지통으로 보내도 링크 너머 파일은 그대로다. 확보 용량에 넣으면 거짓이다.
    assert safe_delete.walk_size(str(folder)) == 1000
    assert safe_delete._size_of(str(folder)) == 1000
    assert uninstaller._folder_size(str(folder)) == (1000, False)
