"""
APEX CARE — 테두리 없는 창의 '최대화 ↔ 이전 크기'.

창이 frameless 라 Windows 의 기본 최대화(pywebview window.maximize)를 쓰면 작업 표시줄까지 덮는다.
(실측: 1920×1080 화면에서 최대화하면 창이 1920×1080, 작업 영역은 1920×1032.)
그래서 창이 있는 모니터의 '작업 영역'(작업 표시줄을 뺀 곳)으로 창을 옮기고, 다시 누르면 전의 위치·크기로 돌린다.
창 위치만 바꾼다. 시스템 설정은 건드리지 않는다.
"""

import ctypes
import ctypes.wintypes as wt

_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_MONITOR_DEFAULTTONEAREST = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT), ('rcWork', wt.RECT), ('dwFlags', wt.DWORD)]


def _user32():
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    u.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    u.MonitorFromWindow.restype = wt.HMONITOR
    u.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
    return u


def find_own_window(title):
    """이 프로세스가 연, 제목이 title 인 최상위 창. 없으면 None.

    pywebview 의 .NET 창 객체를 다른 스레드에서 만지지 않으려고 Win32 로 찾는다.
    같은 제목의 다른 프로그램 창을 잡지 않게 프로세스 ID 로 거른다.
    """
    import os
    u = _user32()
    me, found = os.getpid(), []
    proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def each(hwnd, _):
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me:
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(hwnd)
                return False
        return True
    u.EnumWindows(proc(each), 0)
    return found[0] if found else None


def window_rect(hwnd):
    """(x, y, 너비, 높이). 읽지 못하면 None."""
    u = _user32()
    r = wt.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def work_area_of(hwnd):
    """창이 있는(가장 가까운) 모니터의 작업 영역 (x, y, 너비, 높이). 읽지 못하면 None."""
    u = _user32()
    mon = u.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if not mon:
        return None
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not u.GetMonitorInfoW(mon, ctypes.byref(info)):
        return None
    w = info.rcWork
    return (w.left, w.top, w.right - w.left, w.bottom - w.top)


def move_to(hwnd, rect):
    x, y, w, h = rect
    return bool(_user32().SetWindowPos(hwnd, None, x, y, w, h, _SWP_NOZORDER | _SWP_NOACTIVATE))


def toggle(hwnd, saved, get_rect=window_rect, get_work=work_area_of, move=move_to):
    """최대화 ↔ 이전 크기. saved 는 최대화 전 위치(없으면 None). 새 saved 를 돌려준다.

    이미 최대화돼 있으면(saved 가 있으면) 전 위치로 돌린다. 아니면 지금 위치를 기억하고 작업 영역으로 옮긴다.
    옮기지 못했으면 saved 를 바꾸지 않는다(다음 클릭이 엉뚱한 쪽으로 가지 않게).
    """
    if saved:
        return None if move(hwnd, saved) else saved
    now, work = get_rect(hwnd), get_work(hwnd)
    if not now or not work:
        return None
    return now if move(hwnd, work) else None
