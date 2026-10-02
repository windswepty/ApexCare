"""
APEX CARE — 한 번에 하나만 실행.

두 번째 창이 뜨면 두 앱이 같은 저널·설정·우선순위를 따로 다룬다. 두 번째 앱은 첫 앱이 IDLE 로 낮춰 둔 우선순위를
'원래 값' 으로 기록하고, 첫 앱이 게임 중에 남긴 기록을 '지난번 비정상 종료의 잔여물' 로 보고 되돌렸다.
이름 있는 뮤텍스로 막고, 이미 떠 있는 창을 앞으로 가져온다.
"""

import ctypes
import logging

log = logging.getLogger('SingleInstance')

MUTEX_NAME = 'Local\\APEXCARE_SingleInstance_8F2C1A'
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9

_handle = None          # 프로세스가 끝날 때까지 쥐고 있는다(닫으면 다른 인스턴스가 뜰 수 있다)


def acquire(name=MUTEX_NAME):
    """이 프로세스가 첫 인스턴스면 True. 이미 다른 인스턴스가 있으면 False.

    뮤텍스를 만들지 못한 경우(드묾)는 True — 확인하지 못했다고 앱을 못 켜게 하지 않는다.
    """
    global _handle
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, False, name)
        err = ctypes.get_last_error()
    except Exception as e:
        log.warning(f"중복 실행 확인 실패: {e}")
        return True
    if not h:
        log.warning(f"중복 실행 확인용 뮤텍스를 만들지 못했습니다 (오류 {err})")
        return True
    if err == _ERROR_ALREADY_EXISTS:
        try:
            k32.CloseHandle(ctypes.c_void_p(h))
        except Exception:
            pass
        return False
    _handle = h
    return True


def focus_existing(title):
    """이미 떠 있는 같은 제목의 창을 앞으로 가져온다. 찾지 못하면 False."""
    try:
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.FindWindowW.restype = ctypes.c_void_p
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            return False
        u32.ShowWindow(ctypes.c_void_p(hwnd), _SW_RESTORE)
        u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        return True
    except Exception as e:
        log.debug(f"기존 창을 앞으로 가져오지 못했습니다: {e}")
        return False
