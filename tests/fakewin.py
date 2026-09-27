"""
테스트용 가짜 Windows. backend 를 import 하기 '전에' install() 한다(conftest.py 가 한다).

왜 필요한가:
  이 앱은 관리자 권한으로 레지스트리·전원 설정·서비스·프로세스를 바꾼다. 테스트가 진짜
  시스템을 건드리면 개발 PC 가 망가진다(실제로 옛 테스트 스크립트가 성능 모드를 바꾸고
  대기 메모리를 비웠다). 여기서는 그 모든 경로를 메모리 안의 가짜로 바꾸고, 가짜로 바꾸지
  못한 Win32 호출·외부 명령은 부르는 즉시 예외가 나게 막는다.

가짜로 바꾸는 것:
  - winreg          메모리 레지스트리. 대소문자 무시, 읽기·쓰기 권한 거부, '쓰기 무시' 흉내
  - 전원 설정        system_state._powrprof / active_plan_guid / available_plans
  - 서비스 시작 유형  system_state._sc_config_start → 가짜 레지스트리 Start·DelayedAutostart 쓰기
  - APPDATA 등       임시 폴더로 (저널·settings.json 이 거기 생긴다)

막는 것 (부르면 BlockedCall):
  - ctypes.WinDLL / ctypes.windll / ctypes.oledll
  - subprocess.Popen(→ run·call·check_output 포함), os.system, os.startfile
  - psutil.Process 의 우선순위·종료·일시정지 같은 '바꾸는' 메서드
"""

import atexit
import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import uuid

import psutil

INSTALLED = False
REAL = {}            # 막기 전 원래 객체. 자가 테스트(가짜 없이 import 하면 막히는지)에서 쓴다.
SANDBOX = None       # APPDATA 등을 옮겨 둔 임시 폴더


class BlockedCall(RuntimeError):
    """테스트 중에 진짜 Windows API·외부 명령을 부르려 했다."""


def _blocked(what):
    raise BlockedCall(f"fakewin: 테스트 중에는 실제 시스템을 바꿀 수 있는 호출을 막습니다 ({what})")


# ═════════════════════════════════════════════
# winreg
# ═════════════════════════════════════════════

HKEY_CLASSES_ROOT = 0x80000000
HKEY_CURRENT_USER = 0x80000001
HKEY_LOCAL_MACHINE = 0x80000002
HKEY_USERS = 0x80000003
HKEY_CURRENT_CONFIG = 0x80000005
_HIVE_NAMES = {HKEY_CLASSES_ROOT: 'HKCR', HKEY_CURRENT_USER: 'HKCU',
               HKEY_LOCAL_MACHINE: 'HKLM', HKEY_USERS: 'HKU', HKEY_CURRENT_CONFIG: 'HKCC'}
_HIVE_BY_NAME = {v: k for k, v in _HIVE_NAMES.items()}

KEY_QUERY_VALUE = 0x0001
KEY_SET_VALUE = 0x0002
KEY_CREATE_SUB_KEY = 0x0004
KEY_ENUMERATE_SUB_KEYS = 0x0008
KEY_NOTIFY = 0x0010
KEY_CREATE_LINK = 0x0020
KEY_WOW64_64KEY = 0x0100
KEY_WOW64_32KEY = 0x0200
KEY_READ = 0x20019
KEY_EXECUTE = 0x20019
KEY_WRITE = 0x20006
KEY_ALL_ACCESS = 0xF003F

REG_NONE = 0
REG_SZ = 1
REG_EXPAND_SZ = 2
REG_BINARY = 3
REG_DWORD = 4
REG_DWORD_LITTLE_ENDIAN = 4
REG_DWORD_BIG_ENDIAN = 5
REG_LINK = 6
REG_MULTI_SZ = 7
REG_QWORD = 11
REG_QWORD_LITTLE_ENDIAN = 11

_ERROR_FILE_NOT_FOUND = 2
_ERROR_ACCESS_DENIED = 5
_ERROR_NO_MORE_ITEMS = 259


def _hive(h):
    """'HKLM' 같은 이름이나 HKEY_* 상수를 상수로."""
    if isinstance(h, str):
        return _HIVE_BY_NAME[h.upper()]
    return h


def _parts(path):
    return [p for p in (path or '').split('\\') if p]


def _not_found():
    return FileNotFoundError(_ERROR_FILE_NOT_FOUND, '지정된 파일을 찾을 수 없습니다 (fakewin)')


def _denied():
    return PermissionError(_ERROR_ACCESS_DENIED, '액세스가 거부되었습니다 (fakewin)')


class _Key:
    __slots__ = ('name', 'subkeys', 'values')

    def __init__(self, name):
        self.name = name
        self.subkeys = {}        # 소문자 이름 -> _Key
        self.values = {}         # 소문자 이름 -> (원래 이름, 값, 타입)


class FakeRegistry:
    """메모리 레지스트리.

    규칙(deny_read / deny_write / ignore_writes)은 (하이브, 경로, 값 이름 또는 None) 으로 건다.
    값 이름이 None 이면 그 키의 모든 값에 적용된다.
      deny_read     그 값을 읽으면 PermissionError
      deny_write    그 키를 쓰기 권한으로 열거나 값을 쓰거나 지우면 PermissionError
      ignore_writes 쓰기·지우기가 '성공한 척' 하고 실제로는 아무것도 바뀌지 않는다
                    (다른 프로그램이 되돌려 놓는 경우를 흉내. 되읽어 확인하는지 본다)
    writes 에는 winreg 를 거쳐 실제로 바뀐 것만 쌓인다. '아무것도 쓰지 않았다' 를 확인할 때 쓴다.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.roots = {h: _Key(n) for h, n in _HIVE_NAMES.items()}
        self.deny_read = set()
        self.deny_write = set()
        self.ignore_writes = set()
        self.writes = []

    # ── 규칙 ───────────────────────────────────
    @staticmethod
    def _rule(hive, path, name=None):
        return (_hive(hive), '\\'.join(_parts(path)).lower(),
                None if name is None else name.lower())

    def _matches(self, rules, hive, parts, name=None):
        path = '\\'.join(parts).lower()
        n = None if name is None else name.lower()
        for rh, rp, rn in rules:
            if rh == hive and rp == path and (rn is None or rn == n):
                return True
        return False

    def deny_read_value(self, hive, path, name=None):
        self.deny_read.add(self._rule(hive, path, name))

    def deny_write_value(self, hive, path, name=None):
        self.deny_write.add(self._rule(hive, path, name))

    def ignore_write_value(self, hive, path, name=None):
        self.ignore_writes.add(self._rule(hive, path, name))

    # ── 테스트가 직접 쓰고 읽는 도우미 (규칙·writes 를 거치지 않는다) ──
    def _find(self, hive, parts, create=False):
        k = self.roots[hive]
        for p in parts:
            nxt = k.subkeys.get(p.lower())
            if nxt is None:
                if not create:
                    return None
                nxt = k.subkeys[p.lower()] = _Key(p)
            k = nxt
        return k

    def seed(self, hive, path, name, value, vtype=REG_DWORD):
        k = self._find(_hive(hive), _parts(path), create=True)
        k.values[(name or '').lower()] = (name or '', value, vtype)

    def seed_key(self, hive, path):
        self._find(_hive(hive), _parts(path), create=True)

    def get(self, hive, path, name):
        """값을 (값, 타입) 으로. 없으면 None."""
        k = self._find(_hive(hive), _parts(path))
        if k is None:
            return None
        v = k.values.get((name or '').lower())
        return None if v is None else (v[1], v[2])

    def value(self, hive, path, name):
        got = self.get(hive, path, name)
        return None if got is None else got[0]

    def has_key(self, hive, path):
        return self._find(_hive(hive), _parts(path)) is not None


REGISTRY = FakeRegistry()


class PyHKEY:
    """winreg 가 돌려주는 키 핸들 흉내. with 문과 CloseKey 를 지원한다."""

    def __init__(self, hive, parts, access):
        self.hive = hive
        self.parts = list(parts)
        self.access = access
        self.closed = False

    def _key(self):
        if self.closed:
            raise OSError(6, '핸들이 닫혔습니다 (fakewin)')
        k = REGISTRY._find(self.hive, self.parts)
        if k is None:                      # 연 뒤에 다른 곳에서 키가 지워졌다
            raise _not_found()
        return k

    def Close(self):
        self.closed = True

    def Detach(self):
        self.closed = True
        return 0

    def __int__(self):
        return id(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.Close()
        return False


def _base(key):
    if isinstance(key, PyHKEY):
        key._key()
        return key.hive, list(key.parts)
    if key in _HIVE_NAMES:
        return key, []
    raise OSError(6, f'알 수 없는 키 핸들 {key!r} (fakewin)')


def _handle(key):
    """하이브 상수를 그대로 넘긴 경우엔 모든 권한을 가진 핸들로 본다."""
    return key if isinstance(key, PyHKEY) else PyHKEY(*_base(key), KEY_ALL_ACCESS)


def OpenKey(key, sub_key, reserved=0, access=KEY_READ):
    hive, parts = _base(key)
    parts += _parts(sub_key)
    if REGISTRY._find(hive, parts) is None:
        raise _not_found()
    if access & (KEY_SET_VALUE | KEY_CREATE_SUB_KEY) and REGISTRY._matches(REGISTRY.deny_write, hive, parts):
        raise _denied()
    return PyHKEY(hive, parts, access)


OpenKeyEx = OpenKey


def CreateKeyEx(key, sub_key, reserved=0, access=KEY_WRITE):
    hive, parts = _base(key)
    parts += _parts(sub_key)
    if REGISTRY._matches(REGISTRY.deny_write, hive, parts):
        raise _denied()
    if REGISTRY._find(hive, parts) is None:
        REGISTRY._find(hive, parts, create=True)
        REGISTRY.writes.append(('create_key', _HIVE_NAMES[hive], '\\'.join(parts), None, None))
    return PyHKEY(hive, parts, access)


def CreateKey(key, sub_key):
    return CreateKeyEx(key, sub_key, 0, KEY_ALL_ACCESS)


def CloseKey(hkey):
    if isinstance(hkey, PyHKEY):
        hkey.Close()


def QueryValueEx(key, value_name):
    key = _handle(key)
    if not key.access & KEY_QUERY_VALUE:
        raise _denied()
    k = key._key()
    if REGISTRY._matches(REGISTRY.deny_read, key.hive, key.parts, value_name or ''):
        raise _denied()
    v = k.values.get((value_name or '').lower())
    if v is None:
        raise _not_found()
    return v[1], v[2]


def _check_value(vtype, value):
    if vtype == REG_DWORD:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f'REG_DWORD 에는 int 만 쓸 수 있습니다 ({value!r})')
        if not 0 <= value <= 0xFFFFFFFF:
            raise OverflowError(f'REG_DWORD 범위를 벗어났습니다 ({value})')
    elif vtype == REG_QWORD:
        if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            raise OverflowError(f'REG_QWORD 범위를 벗어났습니다 ({value!r})')
    elif vtype in (REG_SZ, REG_EXPAND_SZ):
        if not isinstance(value, str):
            raise TypeError(f'REG_SZ 에는 str 만 쓸 수 있습니다 ({value!r})')


def SetValueEx(key, value_name, reserved, vtype, value):
    key = _handle(key)
    if not key.access & KEY_SET_VALUE:
        raise _denied()
    k = key._key()
    if REGISTRY._matches(REGISTRY.deny_write, key.hive, key.parts, value_name or ''):
        raise _denied()
    _check_value(vtype, value)
    if REGISTRY._matches(REGISTRY.ignore_writes, key.hive, key.parts, value_name or ''):
        return
    k.values[(value_name or '').lower()] = (value_name or '', value, vtype)
    REGISTRY.writes.append(('set', _HIVE_NAMES[key.hive], '\\'.join(key.parts), value_name, value))


def DeleteValue(key, value_name):
    key = _handle(key)
    if not key.access & KEY_SET_VALUE:
        raise _denied()
    k = key._key()
    if REGISTRY._matches(REGISTRY.deny_write, key.hive, key.parts, value_name or ''):
        raise _denied()
    if (value_name or '').lower() not in k.values:
        raise _not_found()
    if REGISTRY._matches(REGISTRY.ignore_writes, key.hive, key.parts, value_name or ''):
        return
    del k.values[(value_name or '').lower()]
    REGISTRY.writes.append(('delete', _HIVE_NAMES[key.hive], '\\'.join(key.parts), value_name, None))


def DeleteKey(key, sub_key):
    hive, parts = _base(key)
    parts += _parts(sub_key)
    if not parts:
        raise _denied()
    parent = REGISTRY._find(hive, parts[:-1])
    k = REGISTRY._find(hive, parts)
    if parent is None or k is None:
        raise _not_found()
    if k.subkeys or REGISTRY._matches(REGISTRY.deny_write, hive, parts):
        raise _denied()                    # 진짜 DeleteKey 도 하위 키가 있으면 거부한다
    del parent.subkeys[parts[-1].lower()]
    REGISTRY.writes.append(('delete_key', _HIVE_NAMES[hive], '\\'.join(parts), None, None))


def EnumKey(key, index):
    key = _handle(key)
    if not key.access & KEY_ENUMERATE_SUB_KEYS:
        raise _denied()
    subs = list(key._key().subkeys.values())
    if index >= len(subs):
        raise OSError(_ERROR_NO_MORE_ITEMS, '데이터가 더 이상 없습니다 (fakewin)')
    return subs[index].name


def EnumValue(key, index):
    key = _handle(key)
    if not key.access & KEY_QUERY_VALUE:
        raise _denied()
    vals = list(key._key().values.values())
    if index >= len(vals):
        raise OSError(_ERROR_NO_MORE_ITEMS, '데이터가 더 이상 없습니다 (fakewin)')
    name, value, vtype = vals[index]
    if REGISTRY._matches(REGISTRY.deny_read, key.hive, key.parts, name):
        raise _denied()
    return name, value, vtype


def QueryInfoKey(key):
    k = _handle(key)._key()
    return len(k.subkeys), len(k.values), 0


def ConnectRegistry(computer_name, key):
    if computer_name:
        _blocked('winreg.ConnectRegistry 원격')
    return key


def ExpandEnvironmentStrings(s):
    out = s
    for name, val in os.environ.items():
        out = out.replace(f'%{name}%', val)
    return out


def _make_winreg_module():
    m = types.ModuleType('winreg')
    m.__doc__ = 'fakewin 이 만든 가짜 winreg (메모리 레지스트리)'
    m.__fakewin__ = True
    m.error = OSError
    m.HKEYType = PyHKEY
    g = globals()
    for name in list(g):
        if name.startswith(('HKEY_', 'KEY_', 'REG_')):
            setattr(m, name, g[name])
    for fn in (OpenKey, CreateKey, CreateKeyEx, CloseKey, QueryValueEx,
               SetValueEx, DeleteValue, DeleteKey, EnumKey, EnumValue, QueryInfoKey,
               ConnectRegistry, ExpandEnvironmentStrings):
        setattr(m, fn.__name__, fn)
    m.OpenKeyEx = OpenKeyEx
    return m


winreg = _make_winreg_module()


# ═════════════════════════════════════════════
# 전원 설정
# ═════════════════════════════════════════════

PLAN_BALANCED = '381b4222-f694-41f0-9685-ff5bb260df2e'
PLAN_HIGH_PERF = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
PLAN_POWER_SAVER = 'a1841308-3541-4fab-bc81-f71556f20b4a'
PLAN_ULTIMATE = 'e9a42b02-d5df-448d-aa00-03f14749eb61'


def guid_str(obj):
    """ctypes GUID 구조체(또는 그 byref)를 소문자 GUID 문자열로."""
    g = getattr(obj, '_obj', obj)          # ctypes.byref(x)._obj 가 x 다
    raw = struct.pack('<IHH', g.Data1, g.Data2, g.Data3) + bytes(g.Data4)
    return str(uuid.UUID(bytes_le=raw)).lower()


class FakePower:
    """활성 플랜, 존재하는 플랜, 플랜별 세부값(AC/DC)을 메모리에 둔다.

    fail_read / fail_write 에 (plan, setting, 'ac'|'dc') 를 넣으면 그 값의 읽기·쓰기가 실패한다.
    ignore_writes 에 넣으면 쓰기가 성공을 돌려주지만 값은 그대로다.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.plans = {PLAN_BALANCED: '균형 조정', PLAN_HIGH_PERF: '고성능',
                      PLAN_POWER_SAVER: '절전'}
        self.active = PLAN_BALANCED
        self.values = {}                   # (plan, sub, setting, 'ac'|'dc') -> int
        self.fail_read = set()
        self.fail_write = set()
        self.ignore_writes = set()
        self.fail_set_active = False
        self.activations = []              # PowerSetActiveScheme 로 켠 플랜 순서

    def seed_value(self, plan, sub, setting, value, dc_value=None):
        self.values[(plan, sub, setting, 'ac')] = value
        self.values[(plan, sub, setting, 'dc')] = value if dc_value is None else dc_value

    def get(self, plan, sub, setting, side='ac'):
        return self.values.get((plan, sub, setting, side))

    def _read(self, side, pg, sg, stg, out):
        plan, sub, setting = guid_str(pg), guid_str(sg), guid_str(stg)
        if (plan, setting, side) in self.fail_read:
            return _ERROR_ACCESS_DENIED
        v = self.values.get((plan, sub, setting, side))
        if v is None:
            return _ERROR_FILE_NOT_FOUND
        out._obj.value = v
        return 0

    def _write(self, side, pg, sg, stg, value):
        plan, sub, setting = guid_str(pg), guid_str(sg), guid_str(stg)
        if (plan, setting, side) in self.fail_write:
            return _ERROR_ACCESS_DENIED
        if plan not in self.plans:
            return _ERROR_FILE_NOT_FOUND
        if (plan, setting, side) in self.ignore_writes:
            return 0
        self.values[(plan, sub, setting, side)] = int(getattr(value, 'value', value))
        return 0


POWER = FakePower()


class FakePowrprof:
    """system_state._powrprof() 가 돌려주는 객체. 쓰는 함수만 흉내 낸다."""

    def PowerSetActiveScheme(self, root, scheme):
        if POWER.fail_set_active:
            return _ERROR_ACCESS_DENIED
        g = guid_str(scheme)
        if g not in POWER.plans:
            return _ERROR_FILE_NOT_FOUND
        POWER.active = g
        POWER.activations.append(g)
        return 0

    def PowerReadACValueIndex(self, root, pg, sg, stg, out):
        return POWER._read('ac', pg, sg, stg, out)

    def PowerReadDCValueIndex(self, root, pg, sg, stg, out):
        return POWER._read('dc', pg, sg, stg, out)

    def PowerWriteACValueIndex(self, root, pg, sg, stg, value):
        return POWER._write('ac', pg, sg, stg, value)

    def PowerWriteDCValueIndex(self, root, pg, sg, stg, value):
        return POWER._write('dc', pg, sg, stg, value)

    def __getattr__(self, name):
        _blocked(f'powrprof.{name} (fakewin 에 흉내가 없음)')


POWRPROF = FakePowrprof()


def fake_active_plan_guid():
    return POWER.active


def fake_available_plans():
    return dict(POWER.plans)


# ═════════════════════════════════════════════
# 서비스
# ═════════════════════════════════════════════

SERVICES_KEY = r'SYSTEM\CurrentControlSet\Services'
_START_VALUE = {'auto': 2, 'delayed-auto': 2, 'demand': 3, 'disabled': 4}


class FakeServices:
    """sc.exe config 흉내. fail 에 서비스 이름을 넣으면 sc 가 실패한다(값은 그대로)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.fail = set()
        self.calls = []

    def add(self, name, start, delayed=None):
        REGISTRY.seed('HKLM', f'{SERVICES_KEY}\\{name}', 'Start', start)
        if delayed is not None:
            REGISTRY.seed('HKLM', f'{SERVICES_KEY}\\{name}', 'DelayedAutostart', delayed)

    def start_of(self, name):
        """(Start, DelayedAutostart). 없는 값은 None."""
        return (REGISTRY.value('HKLM', f'{SERVICES_KEY}\\{name}', 'Start'),
                REGISTRY.value('HKLM', f'{SERVICES_KEY}\\{name}', 'DelayedAutostart'))

    def sc_config_start(self, service, start_type):
        self.calls.append((service, start_type))
        if start_type not in _START_VALUE:
            return {'rc': None, 'error': '허용되지 않은 인자'}
        if service.lower() in {s.lower() for s in self.fail}:
            return {'rc': 5, 'error': '[SC] OpenService 실패 5: 액세스가 거부되었습니다 (fakewin)'}
        path = f'{SERVICES_KEY}\\{service}'
        if not REGISTRY.has_key('HKLM', path):
            return {'rc': 1060, 'error': '[SC] 지정된 서비스가 없습니다 (fakewin)'}
        REGISTRY.seed('HKLM', path, 'Start', _START_VALUE[start_type])
        if start_type == 'delayed-auto':
            REGISTRY.seed('HKLM', path, 'DelayedAutostart', 1)
        elif start_type == 'auto' and REGISTRY.get('HKLM', path, 'DelayedAutostart') is not None:
            # 원래 없던 값은 만들지 않는다. 없음과 0 은 같은 뜻(지연 시작 아님)이다.
            REGISTRY.seed('HKLM', path, 'DelayedAutostart', 0)
        return {'rc': 0, 'error': ''}


SERVICES = FakeServices()


# ═════════════════════════════════════════════
# 프로세스 (psutil 을 대신할 가짜 프로세스 표)
# ═════════════════════════════════════════════

IDLE_PRIORITY_CLASS = 0x40
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
NORMAL_PRIORITY_CLASS = 0x20
ABOVE_NORMAL_PRIORITY_CLASS = 0x8000
HIGH_PRIORITY_CLASS = 0x80
REALTIME_PRIORITY_CLASS = 0x100


class FakeProc:
    def __init__(self, pid, name, nice=NORMAL_PRIORITY_CLASS, created=1000.0,
                 username='user', cpu=0.0):
        self.pid = pid
        self.name = name
        self.nice = nice
        self.created = created
        self.username = username
        self.cpu = cpu
        self.deny = False                  # True 면 우선순위 변경이 AccessDenied


class FakeProcessTable:
    """psutil.Process / psutil.process_iter 대신 쓰는 프로세스 표.

    install(monkeypatch) 로 psutil 에 끼운다. process_boost·process_guard·game_booster 가
    모두 psutil 모듈 속성을 통해 부르므로 한 번에 바뀐다.
    """

    def __init__(self):
        self.procs = {}
        self.nice_calls = []               # (pid, 설정한 값)

    def add(self, pid, name, **kw):
        self.procs[pid] = FakeProc(pid, name, **kw)
        return self.procs[pid]

    def remove(self, pid):
        self.procs.pop(pid, None)

    def install(self, monkeypatch):
        table = self

        class Process:
            def __init__(self, pid=None):
                if pid is None:
                    pid = os.getpid()
                if pid not in table.procs:
                    raise psutil.NoSuchProcess(pid)
                self.pid = pid
                self._p = table.procs[pid]

            def _live(self):
                p = table.procs.get(self.pid)
                if p is not self._p:        # 끝났거나 PID 를 다른 프로세스가 물려받았다
                    raise psutil.NoSuchProcess(self.pid)
                return p

            def name(self):
                return self._live().name

            def create_time(self):
                return self._live().created

            def username(self):
                return self._live().username

            def nice(self, value=None):
                p = self._live()
                if value is None:
                    return p.nice
                if p.deny:
                    raise psutil.AccessDenied(self.pid)
                table.nice_calls.append((self.pid, value))
                p.nice = value
                return None

            def cpu_percent(self, interval=None):
                return self._live().cpu

            def parent(self):
                return None

            def children(self, recursive=False):
                return []

            def exe(self):
                return ''

            def is_running(self):
                return table.procs.get(self.pid) is self._p

            def __getattr__(self, name):
                _blocked(f'가짜 psutil.Process.{name}')

        def process_iter(attrs=None, ad_value=None):
            for pid in list(table.procs):
                try:
                    p = Process(pid)
                except psutil.NoSuchProcess:
                    continue
                info = {}
                for a in (attrs or ()):
                    info[a] = pid if a == 'pid' else getattr(p, a)()
                p.info = info
                yield p

        monkeypatch.setattr(psutil, 'Process', Process)
        monkeypatch.setattr(psutil, 'process_iter', process_iter)
        return self


def _guard_psutil():
    """진짜 psutil.Process 의 '바꾸는' 메서드를 막는다. 읽기는 그대로 둔다."""
    P = psutil.Process
    REAL['psutil.Process'] = {n: getattr(P, n) for n in
                              ('nice', 'ionice', 'cpu_affinity', 'kill', 'terminate',
                               'suspend', 'resume', 'send_signal') if hasattr(P, n)}

    def _getter_only(name):
        orig = REAL['psutil.Process'][name]

        def method(self, *args, **kwargs):
            if any(a is not None for a in args) or any(v is not None for v in kwargs.values()):
                _blocked(f'psutil.Process.{name}{args} {kwargs}')
            return orig(self)
        method.__name__ = name
        return method

    def _never(name):
        def method(self, *args, **kwargs):
            _blocked(f'psutil.Process.{name}')
        method.__name__ = name
        return method

    for name in ('nice', 'ionice', 'cpu_affinity'):
        if name in REAL['psutil.Process']:
            setattr(P, name, _getter_only(name))
    for name in ('kill', 'terminate', 'suspend', 'resume', 'send_signal'):
        if name in REAL['psutil.Process']:
            setattr(P, name, _never(name))

    # 리눅스 psutil 에는 Windows 우선순위 상수가 없다. 값은 Win32 의 것과 같다.
    for name, val in (('IDLE_PRIORITY_CLASS', IDLE_PRIORITY_CLASS),
                      ('BELOW_NORMAL_PRIORITY_CLASS', BELOW_NORMAL_PRIORITY_CLASS),
                      ('NORMAL_PRIORITY_CLASS', NORMAL_PRIORITY_CLASS),
                      ('ABOVE_NORMAL_PRIORITY_CLASS', ABOVE_NORMAL_PRIORITY_CLASS),
                      ('HIGH_PRIORITY_CLASS', HIGH_PRIORITY_CLASS),
                      ('REALTIME_PRIORITY_CLASS', REALTIME_PRIORITY_CLASS)):
        if not hasattr(psutil, name):
            setattr(psutil, name, val)


# ═════════════════════════════════════════════
# ctypes · subprocess 차단
# ═════════════════════════════════════════════

class _BlockedLoader:
    def __init__(self, label):
        self._label = label

    def __getattr__(self, name):
        _blocked(f'ctypes.{self._label}.{name}')


def _blocked_windll(name, *args, **kwargs):
    _blocked(f'ctypes.WinDLL({name!r})')


class _BlockedPopen(subprocess.Popen):
    def __init__(self, args, *a, **kw):
        _blocked(f'subprocess {args!r}')


def _guard_ctypes_and_processes():
    REAL['ctypes.WinDLL'] = getattr(ctypes, 'WinDLL', None)
    REAL['ctypes.windll'] = getattr(ctypes, 'windll', None)
    REAL['ctypes.oledll'] = getattr(ctypes, 'oledll', None)
    ctypes.WinDLL = _blocked_windll
    ctypes.OleDLL = _blocked_windll
    ctypes.windll = _BlockedLoader('windll')
    ctypes.oledll = _BlockedLoader('oledll')

    REAL['subprocess.Popen'] = subprocess.Popen
    subprocess.Popen = _BlockedPopen
    REAL['os.system'] = os.system
    os.system = lambda cmd: _blocked(f'os.system({cmd!r})')
    if hasattr(os, 'startfile'):
        REAL['os.startfile'] = os.startfile
        os.startfile = lambda *a, **k: _blocked(f'os.startfile{a!r}')


# ═════════════════════════════════════════════
# 설치
# ═════════════════════════════════════════════

def _sandbox_env():
    global SANDBOX
    SANDBOX = tempfile.mkdtemp(prefix='apexcare-fakewin-')
    atexit.register(shutil.rmtree, SANDBOX, ignore_errors=True)   # 우리가 만든 임시 폴더만 지운다
    dirs = {
        'APPDATA': os.path.join(SANDBOX, 'AppData', 'Roaming'),
        'LOCALAPPDATA': os.path.join(SANDBOX, 'AppData', 'Local'),
        'USERPROFILE': os.path.join(SANDBOX, 'home'),
        'HOME': os.path.join(SANDBOX, 'home'),
    }
    for k, v in dirs.items():
        os.makedirs(v, exist_ok=True)
        os.environ[k] = v


def patch_system_state(ss):
    """system_state 의 전원·서비스 경로를 가짜로 바꾼다. 테스트마다 다시 불러도 된다."""
    ss._powrprof = lambda: POWRPROF
    ss.active_plan_guid = fake_active_plan_guid
    ss.available_plans = fake_available_plans
    ss._sc_config_start = SERVICES.sc_config_start


def install():
    """가짜를 끼운다. backend 를 import 하기 전에 불러야 한다. 두 번 불러도 한 번만 한다."""
    global INSTALLED
    if INSTALLED:
        return
    loaded = [m for m in sys.modules if m == 'backend' or m.startswith('backend.')]
    if loaded:
        raise RuntimeError(f'fakewin.install() 전에 backend 가 이미 import 됐습니다: {loaded}')

    _sandbox_env()
    REAL['winreg'] = sys.modules.get('winreg')
    sys.modules['winreg'] = winreg
    _guard_ctypes_and_processes()
    _guard_psutil()
    INSTALLED = True

    from backend import system_state
    patch_system_state(system_state)
    check()


def check():
    """가짜가 제자리에 있는지 확인한다. 하나라도 빠졌으면 AssertionError."""
    assert INSTALLED, 'fakewin 이 설치되지 않았습니다'
    assert sys.modules.get('winreg') is winreg, 'winreg 가 가짜가 아닙니다'
    assert ctypes.WinDLL is _blocked_windll, 'ctypes.WinDLL 이 막혀 있지 않습니다'
    assert isinstance(ctypes.windll, _BlockedLoader), 'ctypes.windll 이 막혀 있지 않습니다'
    assert subprocess.Popen is _BlockedPopen, 'subprocess.Popen 이 막혀 있지 않습니다'
    from backend import system_state as ss
    assert ss.winreg is winreg, 'system_state 가 진짜 winreg 를 쥐고 있습니다'
    assert ss._powrprof() is POWRPROF, '전원 API 가 가짜가 아닙니다'
    assert ss._sc_config_start == SERVICES.sc_config_start, 'sc.exe 호출이 가짜가 아닙니다'
    appdata = os.environ.get('APPDATA', '')
    assert SANDBOX and os.path.realpath(appdata).startswith(os.path.realpath(SANDBOX)), \
        f'APPDATA 가 임시 폴더가 아닙니다: {appdata}'
    assert ss.JOURNAL_PATH.startswith(appdata), f'저널이 임시 폴더 밖입니다: {ss.JOURNAL_PATH}'


def reset():
    """테스트 사이에 가짜 상태와 저널·설정 파일을 비운다."""
    REGISTRY.reset()
    POWER.reset()
    SERVICES.reset()
    from backend import config_manager, system_state
    patch_system_state(system_state)
    for path in (system_state.JOURNAL_PATH, config_manager.CONFIG_FILE):
        for p in (path, path + '.tmp', path + '.corrupt'):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
