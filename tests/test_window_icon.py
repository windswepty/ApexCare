"""앱 아이콘 색: 실행 중인 창의 아이콘만 바꾸고, 기본으로 돌리면 처음 아이콘으로 되돌린다."""

import base64

import pytest

from backend import window_icon as wi

PNG = wi.PNG_MAGIC + b'\x00' * 64


class FakeUser32:
    def __init__(self):
        self.icons = {1: 'exe-big', 0: 'exe-small'}      # 창의 처음 아이콘
        self.made, self.destroyed = [], []

    def SendMessageW(self, hwnd, msg, wparam, lparam):
        if msg == wi._WM_GETICON:
            return self.icons[wparam]
        if msg == wi._WM_SETICON:
            self.icons[wparam] = lparam
        return 0

    def CreateIconFromResourceEx(self, data, size, is_icon, ver, cx, cy, flags):
        h = f'h{len(self.made)}'
        self.made.append(h)
        return h

    def DestroyIcon(self, h):
        self.destroyed.append(h)


@pytest.fixture
def user32(monkeypatch):
    u = FakeUser32()
    monkeypatch.setattr(wi, '_user32', lambda: u)
    monkeypatch.setattr(wi, '_original', {})
    monkeypatch.setattr(wi, '_made', {})
    return u


def test_png_from_the_screen_is_checked():
    assert wi.decode_png(base64.b64encode(PNG).decode()) == PNG
    assert wi.decode_png(base64.b64encode(b'GIF89a....').decode()) is None          # PNG 가 아니다
    assert wi.decode_png('***') is None and wi.decode_png('') is None and wi.decode_png(None) is None
    too_big = base64.b64encode(wi.PNG_MAGIC + b'\x00' * (wi.MAX_PNG_BYTES + 1)).decode()
    assert wi.decode_png(too_big) is None


def test_icon_is_changed_then_restored_without_leaking_handles(user32):
    assert wi.apply(77, PNG)
    assert user32.icons == {1: 'h0', 0: 'h1'}
    assert wi.apply(77, PNG)                                     # 색을 또 바꾸면 앞서 만든 아이콘을 지운다
    assert user32.icons == {1: 'h2', 0: 'h3'} and user32.destroyed == ['h0', 'h1']
    assert wi.apply(77, None)                                    # 기본: 처음 아이콘으로
    assert user32.icons == {1: 'exe-big', 0: 'exe-small'} and user32.destroyed == ['h0', 'h1', 'h2', 'h3']
    assert wi.apply(None, PNG) is False                          # 창을 못 찾으면 아무것도 하지 않는다


def test_api_rejects_a_bad_picture_before_touching_the_window(monkeypatch):
    from backend.api import Api
    api = object.__new__(Api)
    api._window = None
    monkeypatch.setattr(wi, 'apply', lambda *a: (_ for _ in ()).throw(AssertionError('창을 건드리면 안 된다')))
    r = api.setWindowIcon('not-a-png')
    assert r['success'] is False and '형식' in r['message']
