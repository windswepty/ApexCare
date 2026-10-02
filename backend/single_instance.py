"""
APEX CARE — 한 번에 하나만 실행.

두 번째 창이 뜨면 두 앱이 같은 저널·설정·우선순위를 따로 다룬다. 두 번째 앱은 첫 앱이 IDLE 로 낮춰 둔 우선순위를
'원래 값' 으로 기록하고, 첫 앱이 게임 중에 남긴 기록을 '지난번 비정상 종료의 잔여물' 로 보고 되돌렸다.
이름 있는 뮤텍스로 막고, 이미 떠 있는 창을 앞으로 가져온다.

PC 전체 상태(저널·성능 모드)는 HKLM 에 하나라서 다른 Windows 계정(빠른 사용자 전환)의 실행도 막는다.
같은 로그인 세션이면 Local 뮤텍스가, 다른 세션이면 Global 뮤텍스만 겹친다. 그것으로 어느 쪽인지 알린다.
"""

import ctypes
import logging

log = logging.getLogger('SingleInstance')

MUTEX_NAME = 'Local\\APEXCARE_SingleInstance_8F2C1A'
GLOBAL_MUTEX_NAME = 'Global\\APEXCARE_SingleInstance_8F2C1A'
_ERROR_ACCESS_DENIED = 5
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9

_handles = []           # 프로세스가 끝날 때까지 쥐고 있는다(닫으면 다른 인스턴스가 뜰 수 있다)


def acquire(name=MUTEX_NAME):
    """이 프로세스가 첫 인스턴스면 True. 이미 다른 인스턴스가 있으면 False.

    뮤텍스를 만들지 못한 경우(드묾)는 True — 확인하지 못했다고 앱을 못 켜게 하지 않는다.
    다른 계정이 만든 Global 뮤텍스는 열 권한이 없어 ERROR_ACCESS_DENIED 로 실패한다. 그것도 '이미 있음' 이다.
    """
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, False, name)
        err = ctypes.get_last_error()
    except Exception as e:
        log.warning(f"중복 실행 확인 실패: {e}")
        return True
    if not h:
        if err == _ERROR_ACCESS_DENIED:
            return False
        log.warning(f"중복 실행 확인용 뮤텍스를 만들지 못했습니다 (오류 {err})")
        return True
    if err == _ERROR_ALREADY_EXISTS:
        try:
            k32.CloseHandle(ctypes.c_void_p(h))
        except Exception:
            pass
        return False
    _handles.append(h)
    return True


def acquire_both():
    """None 이면 첫 인스턴스. 'same' 이면 이 로그인 세션에 이미 떠 있다. 'other' 면 다른 계정·세션에서 떠 있다."""
    if not acquire(MUTEX_NAME):
        return 'same'
    if not acquire(GLOBAL_MUTEX_NAME):
        return 'other'
    return None


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


OTHER_SESSION_MESSAGE = ('다른 Windows 사용자 계정에서 APEX CARE 가 실행 중입니다.\n\n'
                         '성능 모드와 변경 기록은 PC 전체에 하나라서 한 번에 한 계정에서만 쓸 수 있습니다. '
                         '그 계정에서 APEX CARE 를 닫은 뒤 다시 실행해 주세요.')


def tell_other_session(title='APEX CARE'):
    """다른 계정에서 실행 중이라 끝낸다는 것을 알린다."""
    try:
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.MessageBoxW(None, OTHER_SESSION_MESSAGE, title, 0x40 | 0x10000)   # MB_ICONINFORMATION | MB_SETFOREGROUND
    except Exception as e:
        log.warning(f"안내 창을 띄우지 못했습니다: {e}")
