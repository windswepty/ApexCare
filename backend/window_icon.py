"""
APEX CARE — 실행 중인 창의 아이콘(작업 표시줄·Alt+Tab)을 화면 설정의 '앱 아이콘 색' 으로 바꾼다.

화면(theme.js)이 칠한 PNG 를 받아 WM_SETICON 으로 이 창에만 건다. 창 아이콘만 바뀐다.
exe 파일·바로 가기의 아이콘은 바꾸지 않는다. 고정된 작업 표시줄 단추는 바로 가기 아이콘을 보여 주므로
그쪽은 shortcut_icon.py 가 맡는다.
처음 바꾸기 전의 창 아이콘을 기억해 두었다가 '기본' 으로 돌리면 그것으로 되돌린다.
"""

import base64
import binascii
import logging

log = logging.getLogger('WindowIcon')

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
MAX_PNG_BYTES = 512 * 1024
_WM_SETICON, _WM_GETICON = 0x0080, 0x007F
_ICON_SMALL, _ICON_BIG = 0, 1

_original = {}      # hwnd -> (큰 아이콘, 작은 아이콘)  처음 바꾸기 전의 것
_made = {}          # hwnd -> [이 모듈이 만든 HICON]  바꾼 뒤 지운다(새는 핸들이 없게)


def decode_png(data):
    """화면이 보낸 base64 PNG 를 검사해 bytes 로. 형식이 틀리거나 너무 크면 None."""
    if not isinstance(data, str) or not data or len(data) > MAX_PNG_BYTES * 4 // 3 + 4:
        return None
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw.startswith(PNG_MAGIC) or len(raw) > MAX_PNG_BYTES:
        return None
    return raw


def _user32():
    import ctypes
    import ctypes.wintypes as wt
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u.SendMessageW.restype = ctypes.c_ssize_t
    u.CreateIconFromResourceEx.argtypes = [ctypes.c_char_p, wt.DWORD, wt.BOOL, wt.DWORD,
                                           ctypes.c_int, ctypes.c_int, wt.UINT]
    u.CreateIconFromResourceEx.restype = wt.HICON
    u.DestroyIcon.argtypes = [wt.HICON]
    return u


def _icon_from_png(u, png, size):
    # Vista 부터 PNG 를 그대로 아이콘 자료로 받는다. 0x00030000 = 아이콘 형식 버전
    return u.CreateIconFromResourceEx(png, len(png), True, 0x00030000, size, size, 0)


def apply(hwnd, png):
    """png(bytes) 로 창 아이콘을 바꾼다. png 가 None 이면 처음 아이콘으로 되돌린다. 성공 여부."""
    if not hwnd:
        return False
    u = _user32()
    if hwnd not in _original:
        _original[hwnd] = (u.SendMessageW(hwnd, _WM_GETICON, _ICON_BIG, 0),
                           u.SendMessageW(hwnd, _WM_GETICON, _ICON_SMALL, 0))
    if png is None:
        big, small = _original[hwnd]
        new = []
    else:
        big, small = _icon_from_png(u, png, 256), _icon_from_png(u, png, 32)
        if not big or not small:
            for h in (big, small):
                if h:
                    u.DestroyIcon(h)
            log.warning('PNG 로 아이콘을 만들지 못했습니다')
            return False
        new = [big, small]
    u.SendMessageW(hwnd, _WM_SETICON, _ICON_BIG, big or 0)
    u.SendMessageW(hwnd, _WM_SETICON, _ICON_SMALL, small or 0)
    for h in _made.pop(hwnd, []):          # 앞서 만든 아이콘은 이제 쓰지 않는다
        u.DestroyIcon(h)
    if new:
        _made[hwnd] = new
    return True
