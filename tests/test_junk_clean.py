"""정크 정리: 링크·정션 너머의 파일은 절대 지우지 않는다.

임시 폴더 안에만 가짜 트리를 만든다. 정리 대상 경로(%TEMP% 등)는 os.path.expandvars 를
바꿔서 이 트리로 돌린다. 진짜 %TEMP% 는 건드리지 않는다.
"""

import os
import sys

import pytest

from backend import config_manager, optimizer
from tests import fakewin


def make_dir_link(target, link):
    """디렉터리 링크를 만든다. 윈도우는 정션, 그 밖은 심볼릭 링크.

    윈도우에서 심볼릭 링크를 쓰지 않는 이유: os.walk 는 심볼릭 링크는 따라가지 않고 정션만
    따라간다. 문서 폴더가 지워진 사고가 정션으로 났으므로 정션으로 시험해야 뜻이 있다.
    만들지 못하면 건너뛰지 않고 실패한다. 건너뛰면 이 파일의 테스트가 링크 없이 '통과' 해서
    아무것도 확인하지 않은 채 CI 가 초록색이 된다.
    """
    if sys.platform == 'win32':
        import _winapi
        try:
            _winapi.CreateJunction(str(target), str(link))
        except OSError as e:
            pytest.fail(f'정션을 만들지 못했습니다: {e}')
        assert os.path.isjunction(link), '정션이 아닌 것이 만들어졌습니다'
        return 'junction'
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.fail(f'심볼릭 링크를 만들지 못했습니다: {e}')
    return 'symlink'


def _write(path, data=b'x' * 64):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / 'usertmp'              # 정리 대상 루트(%TEMP% 대신)
    docs = tmp_path / 'Documents'            # 링크가 가리키는 사용자 폴더
    t = {
        'root': root, 'docs': docs,
        'junk': [root / 'a.tmp', root / 'cachefile', root / 'sub' / 'b.log'],
        'keep_in_root': [root / 'keep.dll', root / 'keep.txt'],
        'user_files': [docs / 'important.log', docs / 'notes', docs / 'photo.bak',
                       docs / 'inner' / 'deep.tmp'],
    }
    for p in t['junk'] + t['keep_in_root'] + t['user_files']:
        _write(str(p))
    (root / 'emptydir').mkdir()
    t['link'] = root / 'docs_link'
    t['link_kind'] = make_dir_link(str(docs), str(t['link']))

    missing = tmp_path / 'missing'
    real_expandvars = os.path.expandvars

    def fake_expandvars(s):
        if s == '%TEMP%':
            return str(root)
        if s.startswith('%'):                # %SystemRoot%\Temp, Chrome 캐시 등은 없는 폴더로
            return str(missing / s.replace('%', '').replace('\\', '_'))
        return real_expandvars(s)
    monkeypatch.setattr(os.path, 'expandvars', fake_expandvars)
    return t


def _clean():
    optimizer.clean_junk_background([1], cancel_event=None)
    st = optimizer.get_junk_clean_status()
    assert st['status'] == 'success', st
    return st


def _assert_user_files_intact(t):
    for p in t['user_files']:
        assert p.exists(), f'링크 너머 사용자 파일이 지워졌습니다: {p}'
    assert (t['docs'] / 'inner').is_dir()


def _spy_candidates(monkeypatch):
    """정리가 삭제 후보로 검사한 파일 경로를 모은다."""
    seen = []
    real_candidate = optimizer._junk_candidate

    def spy(path, root_real):
        seen.append(path)
        return real_candidate(path, root_real)
    monkeypatch.setattr(optimizer, '_junk_candidate', spy)
    return seen


def _assert_never_entered_link(t, seen):
    # 링크 폴더 안으로는 아예 들어가지 않아야 한다(실경로 검사는 두 번째 방어선)
    link = os.path.normcase(str(t['link']))
    assert seen and not [p for p in seen if os.path.normcase(p).startswith(link)]


def test_link_is_the_kind_that_caused_the_bug(tree):
    # 윈도우에서는 막지 않으면 os.walk 가 링크 안으로 들어가야 한다. 그래야 아래 테스트가
    # 가지치기(_walk_junk_tree)를 실제로 시험한다. 리눅스는 followlinks=True 흉내로 시험한다.
    entered = any(os.path.normcase(d).startswith(os.path.normcase(str(tree['link'])))
                  for d, _, _ in os.walk(str(tree['root'])))
    if sys.platform == 'win32':
        assert tree['link_kind'] == 'junction' and entered
    else:
        assert tree['link_kind'] == 'symlink' and not entered


def test_junk_is_cleaned_but_link_target_is_not(tree, monkeypatch):
    # 윈도우에서는 진짜 정션 위에서, 평소 os.walk 그대로 시험한다
    seen = _spy_candidates(monkeypatch)
    _clean()
    _assert_never_entered_link(tree, seen)
    for p in tree['junk']:
        assert not p.exists(), p
    for p in tree['keep_in_root']:
        assert p.exists(), p
    assert not (tree['root'] / 'sub').exists()          # 빈 폴더는 정리된다
    assert not (tree['root'] / 'emptydir').exists()
    assert tree['root'].is_dir()                        # 루트 자체는 남는다
    _assert_user_files_intact(tree)


def test_walk_that_follows_links_still_spares_target(tree, monkeypatch):
    # 윈도우의 os.walk 는 정션을 따라 들어간다. 리눅스에서도 그렇게 돌도록 흉내 낸다.
    real_walk = os.walk

    def walk_following_links(top, topdown=True, onerror=None, followlinks=False):
        return real_walk(top, topdown=topdown, onerror=onerror, followlinks=True)
    monkeypatch.setattr(os, 'walk', walk_following_links)
    seen = _spy_candidates(monkeypatch)

    _clean()
    _assert_user_files_intact(tree)
    for p in tree['junk']:
        assert not p.exists(), p
    _assert_never_entered_link(tree, seen)


def test_realpath_check_protects_even_if_link_detection_fails(tree, monkeypatch):
    # 링크 판정이 정션을 놓친 경우. 삭제 직전의 실경로 검사(safe_delete.is_inside)가 막아야 한다.
    real_walk = os.walk

    def walk_following_links(top, topdown=True, onerror=None, followlinks=False):
        return real_walk(top, topdown=topdown, onerror=onerror, followlinks=True)
    monkeypatch.setattr(os, 'walk', walk_following_links)
    monkeypatch.setattr(optimizer, '_is_link_like', lambda path: False)

    _clean()
    _assert_user_files_intact(tree)
    assert os.path.lexists(tree['link'])


def test_scan_size_counts_only_deletable_files(tree):
    size = optimizer._get_dir_size_mb(str(tree['root']))
    assert size == round(64 * len(tree['junk']) / (1024 * 1024), 2)


def test_skipped_files_log_goes_to_appdata_not_desktop(tree, monkeypatch):
    locked = tree['root'] / 'locked.tmp'
    _write(str(locked))
    real_remove = os.remove

    def remove(path, *a, **kw):
        if os.path.basename(str(path)) == 'locked.tmp':
            raise PermissionError(32, '다른 프로세스가 사용 중입니다 (테스트)')
        return real_remove(path, *a, **kw)
    monkeypatch.setattr(os, 'remove', remove)

    st = _clean()

    expected = os.path.join(config_manager.APPDATA_DIR, 'skipped_files.log')
    assert st['skipped_log'] == expected
    assert os.path.realpath(expected).startswith(os.path.realpath(fakewin.SANDBOX))
    with open(expected, encoding='utf-8') as f:
        assert 'locked.tmp' in f.read()
    home = os.path.expanduser('~')
    assert not os.path.exists(os.path.join(home, 'Desktop')), '바탕화면에 파일을 만들었습니다'
    assert locked.exists()
