"""
APEX CARE — Windows 서비스 제어 (서비스 제어 관리자 API 직접 호출).

이 모듈은 '어떻게' 바꾸는지만 안다. 원래 값을 기록하고 되돌리는 일은
system_state.set_service_start() 가 한다. 다른 곳에서 이 모듈의 set_start_type 을
직접 부르면 원래 값이 기록되지 않으므로 복구할 수 없다.

왜 sc.exe 를 쓰지 않는가:
  기존 코드는 subprocess.run(f'sc config {svc} start= {arg}', shell=True) 로 바꾸고
  반환 코드조차 확인하지 않았다. API 를 직접 부르면 실제 오류 코드를 받을 수 있고
  셸을 거치지 않는다.

왜 핸들 타입을 명시하는가:
  ctypes 의 기본 반환형은 32비트 int 다. SC_HANDLE 은 포인터라 64비트 프로세스에서
  잘릴 수 있고, 잘린 핸들로 부르면 엉뚱한 실패가 난다.
"""

import ctypes
import ctypes.wintypes as wt
import logging
import re

log = logging.getLogger('ServiceCtl')

SERVICES_KEY = r"SYSTEM\CurrentControlSet\Services"

# 시작 유형 (Start 레지스트리 값과 같다)
START_BOOT, START_SYSTEM, START_AUTO, START_DEMAND, START_DISABLED = 0, 1, 2, 3, 4
START_LABELS = {START_BOOT: '부팅', START_SYSTEM: '시스템', START_AUTO: '자동',
                START_DEMAND: '수동', START_DISABLED: '사용 안 함'}

SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_CONFIG = 0x0001
SERVICE_CHANGE_CONFIG = 0x0002
SERVICE_QUERY_STATUS = 0x0004
SERVICE_START = 0x0010
SERVICE_STOP = 0x0020
SERVICE_NO_CHANGE = 0xFFFFFFFF
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONFIG_DELAYED_AUTO_START_INFO = 3
SERVICE_STOPPED = 0x00000001
SERVICE_RUNNING = 0x00000004

# 서비스 이름은 상수로만 넘어오지만, 혹시 모를 경로 조작을 막는다.
_NAME_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,256}$')


class SERVICE_STATUS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wt.DWORD),
        ("dwCurrentState", wt.DWORD),
        ("dwControlsAccepted", wt.DWORD),
        ("dwWin32ExitCode", wt.DWORD),
        ("dwServiceSpecificExitCode", wt.DWORD),
        ("dwCheckPoint", wt.DWORD),
        ("dwWaitHint", wt.DWORD),
    ]


class SERVICE_DELAYED_AUTO_START_INFO(ctypes.Structure):
    _fields_ = [("fDelayedAutostart", wt.BOOL)]


def valid_name(name):
    return isinstance(name, str) and bool(_NAME_RE.match(name))


def _advapi():
    a = ctypes.WinDLL('advapi32', use_last_error=True)
    a.OpenSCManagerW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
    a.OpenSCManagerW.restype = wt.HANDLE
    a.OpenServiceW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.DWORD]
    a.OpenServiceW.restype = wt.HANDLE
    a.CloseServiceHandle.argtypes = [wt.HANDLE]
    a.CloseServiceHandle.restype = wt.BOOL
    a.ChangeServiceConfigW.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD,
                                       wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p,
                                       wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR]
    a.ChangeServiceConfigW.restype = wt.BOOL
    a.ChangeServiceConfig2W.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p]
    a.ChangeServiceConfig2W.restype = wt.BOOL
    a.QueryServiceStatus.argtypes = [wt.HANDLE, ctypes.POINTER(SERVICE_STATUS)]
    a.QueryServiceStatus.restype = wt.BOOL
    a.ControlService.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(SERVICE_STATUS)]
    a.ControlService.restype = wt.BOOL
    a.StartServiceW.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p]
    a.StartServiceW.restype = wt.BOOL
    return a


class _Service:
    """with 문으로 서비스 핸들을 열고 반드시 닫는다."""

    def __init__(self, name, access):
        self.name, self.access = name, access
        self.a = self.scm = self.h = None

    def __enter__(self):
        self.a = _advapi()
        self.scm = self.a.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not self.scm:
            raise OSError(ctypes.get_last_error(), '서비스 관리자를 열지 못했습니다')
        self.h = self.a.OpenServiceW(self.scm, self.name, self.access)
        if not self.h:
            err = ctypes.get_last_error()
            self.a.CloseServiceHandle(self.scm)
            self.scm = None
            raise OSError(err, f"서비스 '{self.name}' 을 열지 못했습니다")
        return self

    def __exit__(self, *exc):
        if self.h:
            self.a.CloseServiceHandle(self.h)
        if self.scm:
            self.a.CloseServiceHandle(self.scm)
        return False


def _reason(err):
    if err == 5:
        return '권한 부족(관리자 권한 필요)'
    if err == 1060:
        return '이 PC 에 없는 서비스입니다'
    return f'Win32 오류 {err}'


def read_config(name):
    """서비스의 현재 시작 유형을 읽는다. 읽기만 한다.

    {'exists', 'start', 'delayed', 'running'} 를 돌려준다.
    start 가 None 이면 '읽지 못함' 이다. '없음' 과 구분해야 한다 — 읽지 못한 값을
    원래 값으로 기록하면 복구할 때 엉뚱한 값을 쓰게 된다.
    """
    from backend import system_state as ss
    if not valid_name(name):
        return {'exists': False, 'start': None, 'delayed': False, 'running': None,
                'reason': '올바르지 않은 서비스 이름'}
    path = f"{SERVICES_KEY}\\{name}"
    try:
        existed, start, _ = ss.read_registry_strict('HKLM', path, 'Start')
    except OSError as e:
        return {'exists': True, 'start': None, 'delayed': False, 'running': None,
                'reason': f'시작 유형을 읽지 못했습니다: {e}'}
    if not existed:
        return {'exists': False, 'start': None, 'delayed': False, 'running': None,
                'reason': '이 PC 에 없는 서비스입니다'}
    try:
        d_existed, delayed, _ = ss.read_registry_strict('HKLM', path, 'DelayedAutostart')
    except OSError as e:
        return {'exists': True, 'start': None, 'delayed': False, 'running': None,
                'reason': f'지연 시작 여부를 읽지 못했습니다: {e}'}
    return {'exists': True, 'start': int(start), 'delayed': bool(d_existed and int(delayed) == 1),
            'running': is_running(name), 'reason': ''}


def is_running(name):
    """실행 중이면 True, 멈춰 있으면 False, 알 수 없으면 None."""
    if not valid_name(name):
        return None
    try:
        with _Service(name, SERVICE_QUERY_STATUS) as s:
            st = SERVICE_STATUS()
            if not s.a.QueryServiceStatus(s.h, ctypes.byref(st)):
                return None
            return st.dwCurrentState == SERVICE_RUNNING
    except Exception:
        return None


def set_start_type(name, value):
    """시작 유형을 바꾸고 되읽어 확인한다. value = {'start': int, 'delayed': bool}.

    이 함수는 원래 값을 기록하지 않는다. 기록이 필요한 변경은
    system_state.set_service_start() 로 해야 한다. 여기를 직접 부르는 곳은
    system_state 의 복구 경로뿐이다.
    """
    if not valid_name(name):
        return {'ok': False, 'reason': '올바르지 않은 서비스 이름'}
    try:
        start = int(value['start'])
        delayed = bool(value.get('delayed', False))
    except (TypeError, KeyError, ValueError):
        return {'ok': False, 'reason': f'알 수 없는 시작 유형 값: {value!r}'}
    if start not in START_LABELS:
        return {'ok': False, 'reason': f'알 수 없는 시작 유형: {start}'}
    # 지연 시작은 '자동' 에만 의미가 있다. 다른 유형에 켜라고 하면 API 가 거부한다.
    if start != START_AUTO:
        delayed = False

    try:
        with _Service(name, SERVICE_CHANGE_CONFIG | SERVICE_QUERY_CONFIG) as s:
            if not s.a.ChangeServiceConfigW(s.h, SERVICE_NO_CHANGE, start, SERVICE_NO_CHANGE,
                                            None, None, None, None, None, None, None):
                return {'ok': False, 'reason': _reason(ctypes.get_last_error())}
            if start == START_AUTO:
                info = SERVICE_DELAYED_AUTO_START_INFO(1 if delayed else 0)
                if not s.a.ChangeServiceConfig2W(s.h, SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
                                                 ctypes.byref(info)):
                    return {'ok': False,
                            'reason': '지연 시작 설정 실패: ' + _reason(ctypes.get_last_error())}
    except OSError as e:
        return {'ok': False, 'reason': _reason(e.errno) if e.errno else str(e)}
    except Exception as e:
        return {'ok': False, 'reason': str(e)}

    # 반환 코드를 믿지 않는다. 다시 읽어서 확인한다.
    now = read_config(name)
    if now.get('start') != start or (start == START_AUTO and now.get('delayed') != delayed):
        return {'ok': False,
                'reason': f"바꾼 뒤 다시 읽으니 값이 다릅니다 "
                          f"(기대 {START_LABELS[start]}{'(지연)' if delayed else ''}, "
                          f"실제 {START_LABELS.get(now.get('start'), now.get('start'))}"
                          f"{'(지연)' if now.get('delayed') else ''})"}
    return {'ok': True, 'start': start, 'delayed': delayed}


def stop(name):
    """서비스를 멈춘다. 이미 멈춰 있으면 성공으로 본다."""
    if not valid_name(name):
        return {'ok': False, 'reason': '올바르지 않은 서비스 이름'}
    if is_running(name) is False:
        return {'ok': True, 'reason': '이미 중지됨'}
    try:
        with _Service(name, SERVICE_STOP | SERVICE_QUERY_STATUS) as s:
            st = SERVICE_STATUS()
            if not s.a.ControlService(s.h, SERVICE_CONTROL_STOP, ctypes.byref(st)):
                return {'ok': False, 'reason': _reason(ctypes.get_last_error())}
            return {'ok': True, 'reason': ''}
    except OSError as e:
        return {'ok': False, 'reason': _reason(e.errno) if e.errno else str(e)}
    except Exception as e:
        return {'ok': False, 'reason': str(e)}


def start(name):
    """서비스를 시작한다. 이미 실행 중이면 성공으로 본다."""
    if not valid_name(name):
        return {'ok': False, 'reason': '올바르지 않은 서비스 이름'}
    if is_running(name):
        return {'ok': True, 'reason': '이미 실행 중'}
    try:
        with _Service(name, SERVICE_START | SERVICE_QUERY_STATUS) as s:
            if not s.a.StartServiceW(s.h, 0, None):
                err = ctypes.get_last_error()
                if err == 1056:          # ERROR_SERVICE_ALREADY_RUNNING
                    return {'ok': True, 'reason': '이미 실행 중'}
                return {'ok': False, 'reason': _reason(err)}
            return {'ok': True, 'reason': ''}
    except OSError as e:
        return {'ok': False, 'reason': _reason(e.errno) if e.errno else str(e)}
    except Exception as e:
        return {'ok': False, 'reason': str(e)}
