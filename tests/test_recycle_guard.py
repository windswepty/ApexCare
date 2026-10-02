"""휴지통에 들어가지 않는 대상은 지우지 않는다.

SHFileOperationW 의 FOF_ALLOWUNDO 는 '가능하면' 휴지통이다. FOF_NOCONFIRMATION 과 함께 쓰면 이동식 드라이브,
휴지통 최대 크기보다 큰 대상, '휴지통 사용 안 함' 드라이브에서는 묻지 않고 영구 삭제된다.
"""

import pytest

from backend import safe_delete
from tests.fakewin import REG_DWORD, REGISTRY

GUID = '{11111111-2222-3333-4444-555555555555}'
BB = r'Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume' + '\\' + GUID
POLICY = r'Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'
GB = 1024 ** 3


@pytest.fixture
def volume(monkeypatch):
    info = {'dtype': safe_delete.DRIVE_FIXED, 'guid': GUID, 'total': 500 * GB}
    monkeypatch.setattr(safe_delete, '_volume_info', lambda p: (info['dtype'], info['guid'], info['total']))
    return info


@pytest.fixture
def target(tmp_path):
    f = tmp_path / 'movie.mp4'
    f.write_bytes(b'x' * 1000)
    return f


def test_removable_drive_is_refused(volume, target):
    volume['dtype'] = 2                                  # DRIVE_REMOVABLE (USB 메모리)
    r = safe_delete.to_recycle_bin([str(target)])
    assert r['ok'] == [] and r['bytes'] == 0 and target.exists()
    assert '휴지통이 없는 드라이브' in r['failed'][0]['reason']


def test_nuke_on_delete_drive_is_refused(volume, target):
    REGISTRY.seed('HKCU', BB, 'NukeOnDelete', 1, REG_DWORD)
    r = safe_delete.to_recycle_bin([str(target)])
    assert r['ok'] == [] and target.exists() and '바로 제거' in r['failed'][0]['reason']


def test_bigger_than_recycle_bin_is_refused(volume):
    REGISTRY.seed('HKCU', BB, 'MaxCapacity', 1024, REG_DWORD)          # 1 GB
    why = safe_delete.recycle_block_reason('X:\\big.vhdx', 2 * GB)
    assert why and '최대 크기' in why
    assert safe_delete.recycle_block_reason('X:\\small.bin', 512 * 1024 ** 2) is None


def test_default_capacity_is_5_percent_when_volume_has_no_setting(volume):
    # 볼륨별 설정이 없으면 Windows 기본(볼륨의 5%)으로 본다. 500 GB → 25 GB
    assert safe_delete.recycle_block_reason('X:\\a', 24 * GB) is None
    assert safe_delete.recycle_block_reason('X:\\a', 26 * GB) is not None


def test_policy_without_recycle_bin_is_refused(volume):
    REGISTRY.seed('HKCU', POLICY, 'NoRecycleFiles', 1, REG_DWORD)
    assert '정책' in safe_delete.recycle_block_reason('X:\\a', 10)


def test_unknown_volume_is_refused(monkeypatch, target):
    def boom(p):
        raise OSError('읽기 실패')
    monkeypatch.setattr(safe_delete, '_volume_info', boom)
    r = safe_delete.to_recycle_bin([str(target)])
    assert r['ok'] == [] and target.exists() and '확인하지 못해' in r['failed'][0]['reason']


def test_nuke_warning_flag_is_set_as_last_resort():
    import inspect
    assert 'FOF_WANTNUKEWARNING' in inspect.getsource(safe_delete.to_recycle_bin)
