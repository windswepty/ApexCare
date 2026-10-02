"""대용량·중복 파일 검사: 파일을 쓰기로 열지 않고, 온라인 전용(OneDrive) 파일은 읽지도 지우지도 않는다.

온라인 전용 파일은 내용을 읽거나 쓰기로 열면 통째로 내려받아진다. 리눅스에는 그 속성이 없으므로
_is_cloud_only 를 바꿔 특정 파일을 온라인 전용으로 흉내 낸다.
"""

import os
import types

import pytest

from backend import file_finder

MB = 1024 * 1024


def _write(path, size, fill=b'a'):
    with open(path, 'wb') as f:
        f.write(fill * size)
    return str(path)


@pytest.fixture
def disk(tmp_path, monkeypatch):
    """검사 범위를 임시 폴더 하나로 줄이고, 파일 열기를 모두 기록한다."""
    monkeypatch.setattr(file_finder, 'get_local_drives', lambda: [str(tmp_path)])
    opened = []
    real_open = open

    def spy_open(path, mode='r', *a, **kw):
        opened.append((os.path.basename(str(path)), mode))
        return real_open(path, mode, *a, **kw)
    monkeypatch.setattr(file_finder, 'open', spy_open, raising=False)   # 모듈 안의 open 만 바꾼다

    cloud = set()
    real_cloud = file_finder._is_cloud_only
    monkeypatch.setattr(file_finder, '_is_cloud_only',
                        lambda p: os.path.basename(str(p)) in cloud or real_cloud(p))
    return types.SimpleNamespace(root=tmp_path, opened=opened, cloud=cloud)


def _names(items):
    return sorted(os.path.basename(i['path']) for i in items)


def test_duplicate_scan_never_opens_files_for_writing(disk):
    for n in ('a.bin', 'b.bin'):
        _write(disk.root / n, 11 * MB)
    _write(disk.root / 'c.bin', 11 * MB, fill=b'c')          # 크기만 같다

    dups = file_finder.scan_duplicates()

    assert _names(dups) == ['a.bin', 'b.bin']
    assert disk.opened and all(mode == 'rb' for _, mode in disk.opened), disk.opened


def test_large_scan_never_opens_files(disk):
    _write(disk.root / 'big.iso', 2 * MB)
    assert _names(file_finder.scan_large_files(min_mb=1)) == ['big.iso']
    # 드라이브 루트의 .GamingRoot(Xbox 게임 폴더 표식)만 읽는다. 검사 대상 파일은 열지 않는다.
    assert [o for o in disk.opened if o[0] != '.GamingRoot'] == []       # 크기·시각은 속성으로 읽는다


def test_cloud_only_files_are_neither_read_nor_listed(disk):
    for n in ('local1.mp4', 'local2.mp4', 'cloud.mp4'):
        _write(disk.root / n, 11 * MB)
    disk.cloud.add('cloud.mp4')

    dups = file_finder.scan_duplicates()
    large = file_finder.scan_large_files(min_mb=1)

    assert _names(dups) == ['local1.mp4', 'local2.mp4']
    assert 'cloud.mp4' not in _names(large)
    assert not [n for n, _ in disk.opened if n == 'cloud.mp4'], '온라인 전용 파일을 열었습니다(내려받음)'


def test_file_that_goes_cloud_only_before_hashing_is_not_read(disk, monkeypatch):
    # 첫 순회 뒤 OneDrive '공간 확보' 가 파일을 온라인 전용으로 바꾼 경우
    for n in ('x.mkv', 'y.mkv'):
        _write(disk.root / n, 11 * MB)
    real_hash = file_finder._hash_file

    def hash_after_dehydrate(path, *a, **kw):
        disk.cloud.add('y.mkv')
        return real_hash(path, *a, **kw)
    monkeypatch.setattr(file_finder, '_hash_file', hash_after_dehydrate)

    assert file_finder.scan_duplicates() == []
    assert not [n for n, _ in disk.opened if n == 'y.mkv']


def test_delete_refuses_cloud_only_files(disk, monkeypatch):
    local = _write(disk.root / 'local.bin', 1024)
    cloud = _write(disk.root / 'cloud.bin', 1024)
    disk.cloud.add('cloud.bin')
    sent = []
    monkeypatch.setattr(file_finder.safe_delete, 'to_recycle_bin',
                        lambda paths: sent.extend(paths) or {'ok': list(paths), 'failed': [], 'bytes': 1024})

    r = file_finder.delete_files([local, cloud])

    assert sent == [local]
    assert [f['path'] for f in r['failed']] == [cloud]
    assert '클라우드' in r['failed'][0]['reason']


@pytest.mark.parametrize('attrs, expected', [
    (0x20, False),              # 보관(일반 파일)
    (0x400000, True),           # RECALL_ON_DATA_ACCESS — OneDrive 온라인 전용
    (0x40000, True),            # RECALL_ON_OPEN
    (0x1000, True),             # OFFLINE
    (None, False),              # 속성이 없는 OS(리눅스)
])
def test_cloud_only_attribute_check(monkeypatch, attrs, expected):
    st = types.SimpleNamespace() if attrs is None else types.SimpleNamespace(st_file_attributes=attrs)
    monkeypatch.setattr(file_finder.os, 'lstat', lambda p: st)
    assert file_finder._is_cloud_only('x') is expected


def test_unreadable_attributes_count_as_cloud_only(monkeypatch):
    def fail(p):
        raise PermissionError(5, 'denied')
    monkeypatch.setattr(file_finder.os, 'lstat', fail)
    assert file_finder._is_cloud_only('x') is True           # 모르면 읽지 않는다


def _gaming_root_bytes(*names):
    body = b''.join(n.encode('utf-16-le') + b'\x00\x00' for n in names)
    return b'RGBX' + len(names).to_bytes(4, 'little') + body


def test_xbox_game_folder_is_skipped_even_when_renamed(disk):
    # Xbox 앱(게임 패스)은 드라이브 루트의 .GamingRoot 에 설치 폴더를 적는다. 사용자가 이름을 바꿀 수 있다.
    (disk.root / '.GamingRoot').write_bytes(_gaming_root_bytes('MyGames'))
    for rel in (('MyGames', 'Halo', 'Content', 'data.pak'), ('XboxGames', 'Forza', 'Content', 'big.pak'),
                ('Nexon', 'Maple', 'Data.wz'), ('Videos', 'trip.mp4')):
        target = disk.root.joinpath(*rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        _write(target, 2 * MB)

    assert _names(file_finder.scan_large_files(min_mb=1)) == ['trip.mp4']
    r = file_finder.delete_files([str(disk.root / 'MyGames' / 'Halo' / 'Content' / 'data.pak')])
    assert r['deleted'] == 0 and '게임' in r['failed'][0]['reason']


def test_broken_gaming_root_is_ignored(disk):
    (disk.root / '.GamingRoot').write_bytes(b'garbage')
    assert file_finder._read_gaming_root(str(disk.root)) == []


def test_only_fixed_disks_are_scanned(monkeypatch):
    import types
    import psutil
    parts = [types.SimpleNamespace(mountpoint='C:/', fstype='NTFS', opts='rw,fixed'),
             types.SimpleNamespace(mountpoint='E:/', fstype='FAT32', opts='rw,removable'),
             types.SimpleNamespace(mountpoint='Z:/', fstype='NTFS', opts='rw,remote'),
             types.SimpleNamespace(mountpoint='F:/', fstype='', opts='cdrom')]
    monkeypatch.setattr(psutil, 'disk_partitions', lambda all=False: parts)
    # USB 메모리·네트워크 드라이브는 휴지통이 없어 이 화면에서 지울 수 없다. 목록에 올리지 않는다.
    assert file_finder.get_local_drives() == ['C:/']
