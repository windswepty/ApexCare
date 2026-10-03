"""
APEX CARE — 되돌릴 수 있는 시스템 변경 계층.

이 앱이 OS 설정을 바꾸는 모든 경로는 이 모듈을 거친다.

왜 필요한가:
  기존 코드는 레지스트리와 전원 설정을 직접 덮어쓰기만 하고 원래 값을 기록하지 않았다.
  그래서 게이밍 모드가 켠 NetworkThrottlingIndex 와 HwSchMode 가 표준·에코로 바꿔도
  영원히 남았고, 사용자 PC 에 여러 모드의 설정이 뒤섞인 상태가 만들어졌다.
  "모드가 적용되지 않는다"는 증상의 실체가 이것이다.

이 모듈이 보장하는 것:
  1. 바꾸기 전에 원래 값을 반드시 기록한다. 한 번 기록한 원본은 절대 덮어쓰지 않는다.
     (우리가 바꾼 값을 '원본'으로 다시 기록하면 진짜 원본이 영영 사라진다)
  2. 바꾼 뒤 다시 읽어서 실제로 반영됐는지 확인한다. 반환 코드를 믿지 않는다.
  3. 실패는 실패라고 보고한다. 조용히 성공으로 넘기지 않는다.
  4. 언제든 restore_all() 로 전부 원래대로 되돌릴 수 있다.
  5. 원래 값이 '없었던' 항목은 복구 시 값을 되돌리는 게 아니라 지운다.

저널 위치: PC 전체에 걸친 변경은 HKLM\\SOFTWARE\\APEX CARE 의 'Journal'(machine_store, 관리자만 씀),
          이 계정의 시작 프로그램 표시(HKCU)는 %APPDATA%\\APEX_CARE_DATA\\system_state.json.
"""

import ctypes
import functools
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import uuid
import winreg

from backend import machine_store

log = logging.getLogger('SystemState')

# 이 계정의 저널 파일: 이 계정의 시작 프로그램 표시(HKCU) 기록과, 예전 버전이 남긴 기록
APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
JOURNAL_PATH = os.path.join(APPDATA_DIR, 'system_state.json')
_MACHINE_VALUE = 'Journal'           # PC 쪽 저널(machine_store)의 값 이름

HIVES = {
    'HKLM': winreg.HKEY_LOCAL_MACHINE,
    'HKCU': winreg.HKEY_CURRENT_USER,
}


# ─────────────────────────────────────────────
# 저널 입출력
# ─────────────────────────────────────────────

# 저널의 읽기-고치기-쓰기와, '원래 값 기록 → 쓰기 → 확인' 한 묶음을 한 번에 하나만 한다.
# pywebview 는 JS 호출마다 스레드를 새로 쓰고, 게임 부스터 감시 스레드도 모드를 바꾼다. 예전에는 잠금이 없어
# 한쪽의 되돌리기가 다른 쪽이 막 기록한 원래 값을 지우거나, 두 스레드가 같은 임시 파일에 써서 저널이 깨졌다.
_lock = threading.RLock()

_READ_RETRIES = 3          # 백신 검사 등으로 잠깐 잠긴 저널을 다시 읽어 볼 횟수
_RETRY_WAIT = 0.15


class JournalUnreadable(Exception):
    """저널 파일은 있는데 읽지 못했다(잠김·권한). 깨진 것과 다르다 — 비우면 원래 값 기록을 잃는다."""


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        with _lock:
            return fn(*a, **kw)
    return wrapper


# 저널은 두 곳에 나눠 둔다.
#   PC 전체(전원 플랜·세부값, HKLM, 서비스): machine_store 의 'Journal'. 관리자만 쓸 수 있다.
#   이 계정의 시작 프로그램 표시(HKCU\...\StartupApproved): JOURNAL_PATH. 계정마다 다른 값이라 계정마다 둔다.
# 예전 버전은 모두 JOURNAL_PATH 에 두었다. 그 파일은 같은 계정의 일반 권한 프로그램도 쓸 수 있어서, 거기 써 넣은
# 항목을 관리자 권한의 '되돌리기' 가 어느 HKLM 키에든 썼다. 계정마다 한 번만 PC 쪽으로 옮기고(_import_legacy),
# 그 뒤로 그 파일에서는 시작 프로그램 표시 기록만 읽는다.
_USER_PATH = 'software\\microsoft\\windows\\currentversion\\explorer\\startupapproved\\'
_KINDS = ('registry', 'power_value', 'power_plan', 'service')
# 종류별 '원래 값' 을 담는 칸(예전 기록과 합칠 때 쓴다). group·why·set_to 는 지금 기록의 것을 둔다.
_ORIGINAL_FIELDS = {'registry': ('existed', 'value', 'type', 'created_keys'), 'power_value': ('value',),
                    'power_plan': ('value',), 'service': ('start', 'delayed', 'value')}


def _is_user_entry(e):
    return isinstance(e, dict) and e.get('kind') == 'registry' and e.get('hive') == 'HKCU'


def _user_key(e):
    return f"reg:HKCU\\{e['path']}\\{e['name']}"


def _trusted_user_entry(e, key=None):
    """계정 파일의 기록 중 쓰는 것: 이 계정의 시작 프로그램 표시뿐. HKCU 의 다른 곳(관리자만 쓰는 Software\\Policies 등)을
    관리자 권한의 되돌리기로 쓰게 하지 않는다. key 를 주면 키 이름도 그 기록의 정규 이름과 같아야 한다
    (키가 'svc:sysmain' 인데 내용은 시작 프로그램 표시인 기록이 PC 저널의 같은 키를 가리지 못하게)."""
    ok = (_is_user_entry(e) and isinstance(e.get('path'), str) and isinstance(e.get('name'), str)
          and e['path'].lower().startswith(_USER_PATH))
    return ok and (key is None or key == _user_key(e))


def _account_sid():
    """이 프로세스를 실행한 계정의 SID. 모르면 None."""
    try:
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.LocalFree.argtypes = [ctypes.c_void_p]
        adv.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        adv.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                                            ctypes.POINTER(ctypes.c_uint32)]
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        token = ctypes.c_void_p()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):   # TOKEN_QUERY
            return None
        try:
            size = ctypes.c_uint32()
            adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))                      # TokenUser
            buf = ctypes.create_string_buffer(size.value)
            if not size.value or not adv.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                return None
            psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            out = ctypes.c_void_p()
            if not adv.ConvertSidToStringSidW(psid, ctypes.byref(out)):
                return None
            try:
                return ctypes.wstring_at(out.value)
            finally:
                k32.LocalFree(out)
        finally:
            k32.CloseHandle(token)
    except Exception as e:
        log.warning(f"계정 SID 를 읽지 못했습니다: {e}")
        return None


def _load_machine():
    """PC 쪽 저널. 없거나 깨졌으면 빈 저널(깨진 값은 machine_store 가 옆에 남긴다). 못 읽으면 JournalUnreadable."""
    try:
        data = machine_store.read(_MACHINE_VALUE)
    except machine_store.Unreadable as e:
        log.error(f"PC 저널을 읽지 못했습니다: {e}")
        raise JournalUnreadable(str(e))
    if data is not None and not (isinstance(data, dict) and isinstance(data.get('entries'), dict)):
        log.error('PC 저널 형식이 아닙니다. 옆에 남기고 새로 시작합니다')
        machine_store.write(f"{_MACHINE_VALUE}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}", data)
        data = None
    if data is None:
        data = {'version': 1, 'entries': {}}
    if not isinstance(data.get('imported'), list):
        data['imported'] = []
    return data


def _import_legacy(machine, user, entries):
    """예전 버전이 이 계정의 파일에 남긴 PC 쪽 기록을 PC 저널로 옮긴다. 계정마다 한 번만.

    한 번 옮긴 뒤 그 파일에 생긴 PC 쪽 기록은 이 앱이 쓴 것이 아니다(새 버전은 거기 쓰지 않는다). 쓰지 않는다.
    예전 기록이 없어도 처음 읽을 때 '옮김' 으로 표시한다. 예전에는 옮길 것이 있을 때만 표시해, 새로 설치한 계정은
    나중에 일반 권한 프로그램이 그 파일에 써 넣은 PC 쪽 기록을 계속 받아들였다.
    PC 저널에 같은 키가 이미 있으면 예전 기록의 원래 값을 넣는다. 예전 기록이 더 먼저(새 버전을 쓰기 전에) 남긴 것이라,
    PC 저널의 값은 예전 버전이 이미 바꿔 둔 값이다.
    """
    sid = _account_sid()
    if not sid or sid in machine['imported']:
        legacy = [k for k, e in user['entries'].items() if isinstance(e, dict) and not _is_user_entry(e)]
        if sid and legacy:
            log.warning(f"계정 저널에 PC 쪽 기록 {len(legacy)}개가 있지만 이미 옮긴 계정이라 쓰지 않습니다")
        return
    legacy = {k: e for k, e in user['entries'].items() if isinstance(e, dict) and not _is_user_entry(e)}
    moved = {}
    for k, e in legacy.items():
        if e.get('kind') not in _KINDS:
            continue
        have = machine['entries'].get(k)
        if have is None:
            moved[k] = e
        elif have.get('kind') == e.get('kind'):
            merged = dict(have)
            for f in _ORIGINAL_FIELDS.get(e['kind'], ()):
                if f in e:
                    merged[f] = e[f]
            moved[k] = merged
    new = dict(machine, entries={**machine['entries'], **moved}, imported=machine['imported'] + [sid])
    if not machine_store.write(_MACHINE_VALUE, new):
        return                                  # 다음에 다시 시도한다
    machine.update(new)
    entries.update(moved)
    if legacy:
        log.info(f"예전 저널의 PC 쪽 기록 {len(moved)}개를 옮겼습니다")
        # 계정 파일에서는 뺀다. 못 빼도 이 계정은 옮긴 것으로 기록됐으므로 다시 쓰이지 않는다.
        _save_user_file({'version': 1, 'entries': {k: e for k, e in user['entries'].items() if k not in legacy}})


def _load():
    """저널을 읽는다(PC 쪽과 이 계정 쪽을 합친 것). 없으면 빈 저널.

    둘 중 하나라도 읽지 못하면 JournalUnreadable — 빈 저널로 보고 쓰면 기존 원래 값 기록을 덮는다.
    """
    with _lock:
        machine = _load_machine()
        user = _load_user_file()
        entries = dict(machine['entries'])
        for k, e in user['entries'].items():
            if _trusted_user_entry(e, k) and k not in entries:
                entries[k] = e
            elif _is_user_entry(e):
                log.warning(f"계정 저널의 이 기록은 쓰지 않습니다(시작 프로그램 표시가 아니거나 PC 저널과 키가 겹침): {k}")
        _import_legacy(machine, user, entries)
        return {'version': 1, 'entries': entries}


def _save(data):
    """PC 쪽과 이 계정 쪽에 나눠 쓴다. 바뀐 쪽만 쓴다. 둘 다 저장됐으면 True."""
    with _lock:
        try:
            machine = _load_machine()
            user = _load_user_file()
        except JournalUnreadable:
            return False
        ok = True
        # 키와 내용이 모두 이 계정의 시작 프로그램 표시인 것만 계정 파일로, 나머지는 PC 저널로
        m_entries = {k: e for k, e in data['entries'].items() if not _trusted_user_entry(e, k)}
        if machine['entries'] != m_entries:
            ok = machine_store.write(_MACHINE_VALUE, dict(machine, entries=m_entries))
        # 이 계정 파일에서 쓰지 않는 기록(아직 옮기지 못한 예전 기록 등)은 그대로 둔다
        u_entries = {k: e for k, e in user['entries'].items() if not _trusted_user_entry(e, k)}
        u_entries.update({k: e for k, e in data['entries'].items() if _trusted_user_entry(e, k)})
        if user['entries'] != u_entries:
            ok = _save_user_file({'version': 1, 'entries': u_entries}) and ok
        return ok


def _load_user_file():
    """이 계정의 저널 파일을 읽는다. 없으면 빈 저널. 내용이 깨졌으면 옆으로 옮기고 빈 저널.

    잠깐 잠겨 읽지 못하면 다시 읽고, 끝내 못 읽으면 JournalUnreadable. 예전에는 이것도 '깨짐' 으로 보고
    옆으로 치운 뒤 빈 저널에 새 기록만 남겨, 그때까지의 원래 값 기록이 되돌리기에서 사라졌다.
    """
    with _lock:
        raw = None
        for attempt in range(_READ_RETRIES):
            try:
                with open(JOURNAL_PATH, 'rb') as f:
                    raw = f.read()
                break
            except FileNotFoundError:
                return {'version': 1, 'entries': {}}
            except OSError as e:
                if attempt == _READ_RETRIES - 1:
                    log.error(f"저널을 읽지 못했습니다(잠김·권한): {e}")
                    raise JournalUnreadable(str(e))
                time.sleep(_RETRY_WAIT)
        try:
            data = json.loads(raw.decode('utf-8-sig'))
            if isinstance(data, dict) and isinstance(data.get('entries'), dict):
                return data
            raise ValueError('저널 형식이 아닙니다')
        except ValueError as e:
            # 저널이 깨졌다고 조용히 새로 만들면 기존 백업이 통째로 날아간다.
            # 깨진 파일을 옆에 남겨두고 사람이 확인할 수 있게 한다(시각을 붙여 앞선 것을 덮지 않는다).
            log.error(f"저널이 깨져 있습니다: {e}")
            dest = f"{JOURNAL_PATH}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                os.replace(JOURNAL_PATH, dest)
                log.error(f"깨진 저널을 {dest} 로 옮겼습니다")
            except Exception:
                pass
            return {'version': 1, 'entries': {}}


def _save_user_file(data):
    """이 계정의 저널 파일을 원자적으로 쓴다. 쓰다가 죽으면 복구 정보가 통째로 사라진다."""
    with _lock:
        tmp = None
        try:
            os.makedirs(APPDATA_DIR, exist_ok=True)
            # 쓸 때마다 다른 임시 파일. 같은 이름을 함께 쓰면 서로의 내용을 잘라 먹는다.
            fd, tmp = tempfile.mkstemp(prefix='system_state.', suffix='.tmp', dir=APPDATA_DIR)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(_READ_RETRIES):
                try:
                    os.replace(tmp, JOURNAL_PATH)
                    tmp = None
                    return True
                except PermissionError:
                    if attempt == _READ_RETRIES - 1:
                        raise
                    time.sleep(_RETRY_WAIT)
        except Exception as e:
            log.error(f"저널 저장 실패: {e}")
            return False
        finally:
            if tmp:
                try:
                    os.remove(tmp)            # 우리가 만든 임시 파일만 지운다
                except OSError:
                    pass


def _record(key, entry):
    """원본을 기록한다. 이미 기록돼 있으면 건드리지 않는다 — 이게 핵심이다.

    원본이 디스크에 안전하게 있으면 True, 저장에 실패했으면 False.
    False 면 호출부는 시스템을 바꾸면 안 된다. 기록 없이 바꾸면 되돌릴 방법이 없다.
    """
    with _lock:
        try:
            data = _load()
        except JournalUnreadable:
            return False      # 기존 기록을 읽지 못하면 새로 쓰지 않는다(기존 기록을 덮게 된다)
        if key in data['entries']:
            return True           # 이미 원본이 있다. 덮어쓰면 진짜 원본을 잃는다.
        data['entries'][key] = entry
        return _save(data)


_NOT_RECORDED = {'ok': False, 'verified': False,
                 'reason': '원래 값을 기록하지 못해 바꾸지 않았습니다 (저널 저장 실패)'}


def _enc(value):
    """저널(JSON)에 넣을 수 있게 바꾼다. bytes(REG_BINARY 등)는 {'__bytes__': 16진수}."""
    if isinstance(value, (bytes, bytearray)):
        return {'__bytes__': bytes(value).hex()}
    return value


def _dec(value):
    """_enc 의 반대. 형식이 깨졌으면 None."""
    if isinstance(value, dict) and '__bytes__' in value:
        try:
            return bytes.fromhex(value['__bytes__'])
        except (TypeError, ValueError):
            return None
    return value


def _forget(keys):
    with _lock:
        try:
            data = _load()
        except JournalUnreadable:
            return False      # 못 읽었는데 쓰면 다른 기록까지 지운다. 기록이 남으면 다시 되돌릴 수 있다.
        for k in keys:
            data['entries'].pop(k, None)
        return _save(data)


def _forget_and_hand_over(keys, kept_keys):
    """되돌린 기록을 지우되, 그 기록이 '이 앱이 만든 키' 로 들고 있던 것 중 아직 남은 키(다른 값이 있어 못 지움)는
    그 키 안에 값을 둔 남은 기록에 넘긴다. 예전에는 그 정보가 함께 지워져, 마지막 값을 되돌려도 빈 키가 남았다
    (시작 프로그램을 하나씩 다시 켜면 StartupApproved\\Run 이 원래 없던 PC 에 빈 키로 남음).
    """
    with _lock:
        try:
            data = _load()
        except JournalUnreadable:
            return False
        entries = data['entries']
        for k in keys:
            entries.pop(k, None)
        for hive, path in kept_keys:
            low = path.lower()
            for e in entries.values():
                p = str(e.get('path', '')).lower()
                if e.get('kind') == 'registry' and e.get('hive') == hive and (p == low or p.startswith(low + '\\')):
                    ck = e.setdefault('created_keys', [])
                    if path not in ck:
                        ck.append(path)
                    break
        return _save(data)


def pending_changes():
    """아직 되돌리지 않은 변경 목록. UI 가 '되돌리기' 버튼을 띄울지 판단하는 데 쓴다.

    읽기 전용이다. 저널이 계속 잠겨 읽지 못하면 빈 목록을 돌려준다(쓰는 쪽 _record/_forget/_restore 는
    그때 아무것도 쓰지 않고 실패를 알리므로 기록은 지워지지 않는다).
    """
    try:
        return _load()['entries']
    except JournalUnreadable:
        return {}


def pending_changes_or_none():
    """pending_changes 와 같지만, 저널을 읽지 못하면 None. 화면이 '되돌릴 것 없음' 과 '모름' 을 구분하게 한다."""
    try:
        return _load()['entries']
    except JournalUnreadable:
        return None


def setting_of(key):
    """저널 키가 가리키는 '설정 하나'. 전원 세부값은 전원 연결(ac)·배터리(dc) 값을 따로 기록하지만 화면에는 설정 하나다.
    예전에는 같은 변경을 적용 결과는 10개, 되돌릴 변경·되돌린 수는 17개로 셌다."""
    if key.startswith('power:') and key.endswith((':ac', ':dc')):
        return key[:-3]
    return key


def count_settings(keys):
    return len({setting_of(k) for k in keys})


def has_pending():
    return bool(pending_changes())


# ─────────────────────────────────────────────
# 레지스트리
# ─────────────────────────────────────────────

def read_registry_strict(hive, path, name):
    """(존재여부, 값, 타입). 값이 없으면 (False, None, None).

    '없음' 과 '읽지 못함' 을 구분한다. 읽기 실패(권한 등)는 OSError 로 올린다.
    읽지 못한 것을 '원래 없었음' 으로 기록하면, 복구할 때 멀쩡한 값을 지우게 된다.
    """
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            val, typ = winreg.QueryValueEx(k, name)
            return True, val, typ
    except FileNotFoundError:
        return False, None, None


def read_registry(hive, path, name):
    """(존재여부, 값, 타입) 을 돌려준다. 없거나 읽지 못하면 (False, None, None).

    표시용이다. 변경 전 원래 값을 기록할 때는 read_registry_strict 를 쓴다.
    """
    try:
        return read_registry_strict(hive, path, name)
    except Exception as e:
        log.debug(f"레지스트리 읽기 실패 {hive}\\{path}\\{name}: {e}")
        return False, None, None


def _missing_keys(hive, path):
    """path 중 지금 없는 키들(깊은 것부터). 모두 있으면 []. 확인하지 못하면 [](지우지 않는 쪽).

    값을 쓰면서 없던 키를 만들었다면, 되돌린 뒤 그 키가 비어 있을 때 지워야 '원래대로' 다.
    (샌드박스 점검에서 StartupApproved\\Run 이 원래 없던 PC 에 빈 키가 남았다)
    """
    parts = [x for x in path.split('\\') if x]
    missing = []
    for i in range(len(parts), 0, -1):
        sub = '\\'.join(parts[:i])
        try:
            with winreg.OpenKey(HIVES[hive], sub, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
                return missing
        except FileNotFoundError:
            missing.append(sub)
        except OSError:
            return []
    return missing


def _delete_key_if_empty(hive, path):
    """값도 하위 키도 없을 때만 지운다. 다른 무엇이 들어 있으면 그대로 둔다."""
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            subkeys, values, _ = winreg.QueryInfoKey(k)
        if subkeys or values:
            return False
        winreg.DeleteKeyEx(HIVES[hive], path, winreg.KEY_WOW64_64KEY, 0)
        return True
    except OSError:
        return False


@_locked
def set_registry(hive, path, name, value, group, vtype=winreg.REG_DWORD, why=''):
    """레지스트리 값을 바꾸고 결과를 검증한다.

    group 은 '이 변경이 어느 기능에 속하는가' 다(예: 'mode:gaming').
    나중에 그 기능만 골라 되돌릴 때 쓴다.
    """
    try:
        existed, before, before_type = read_registry_strict(hive, path, name)
    except PermissionError:
        return {'ok': False, 'verified': False,
                'reason': '원래 값을 읽기가 거부되어 바꾸지 않았습니다(보안 정책이 이 값을 잠갔을 수 있습니다)'}
    except OSError as e:
        return {'ok': False, 'verified': False,
                'reason': f'원래 값을 읽지 못해 바꾸지 않았습니다: {e}'}
    entry_key = f"reg:{hive}\\{path}\\{name}"

    if not _record(entry_key, {
        'kind': 'registry', 'group': group, 'hive': hive, 'path': path,
        'name': name, 'existed': existed, 'value': _enc(before),
        'type': before_type if existed else vtype, 'why': why,
        'created_keys': [] if existed else _missing_keys(hive, path),
    }):
        return dict(_NOT_RECORDED)

    try:
        with winreg.CreateKeyEx(HIVES[hive], path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, name, 0, vtype, value)
    except PermissionError:
        return {'ok': False, 'verified': False, 'reason': '쓰기가 거부되었습니다(다른 프로그램이나 보안 정책이 이 값을 잠갔을 수 있습니다)'}
    except Exception as e:
        return {'ok': False, 'verified': False, 'reason': str(e)}

    # 반환 코드를 믿지 않는다. 다시 읽어서 확인한다.
    ok2, after, _ = read_registry(hive, path, name)
    verified = ok2 and after == value
    if not verified:
        return {'ok': False, 'verified': False,
                'reason': f'쓴 뒤 다시 읽으니 값이 다름 (기대 {value}, 실제 {after})'}
    return {'ok': True, 'verified': True, 'before': before, 'after': after}


# ─────────────────────────────────────────────
# 전원 설정 (powrprof 직접 호출)
# ─────────────────────────────────────────────
# powercfg.exe 를 subprocess 로 부르는 대신 API 를 직접 쓴다.
# 이유: 실제 오류 코드를 받을 수 있고, 값을 되읽어 검증할 수 있고,
#       셸을 거치지 않아 주입 위험이 없고, 훨씬 빠르다.

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_uint8 * 8)]


def _guid(s):
    u = uuid.UUID(s)
    g = _GUID()
    g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
    g.Data4 = (ctypes.c_uint8 * 8)(*u.bytes[8:])
    return g


def _powrprof():
    return ctypes.WinDLL('powrprof', use_last_error=True)


# 전원 설정 GUID
SUB_PROCESSOR = '54533251-82be-4824-96c1-47b60b740d00'
PROCTHROTTLEMIN = '893dee8e-2bef-41e0-89c6-b55d0929964c'
PROCTHROTTLEMAX = 'bc5038f7-23e0-4960-96da-33abaf5935ec'
CPMINCORES = '0cc5b647-c1df-4637-891a-dec35c318583'
SUB_USB = '2a737441-1930-4402-8d77-b2bebba308a3'
USB_SELECTIVE_SUSPEND = '48e6b7a6-50f5-4782-a5d4-53bb8f07e226'
# 프로세서 성능 부스트 모드: 0 사용 안 함(기본 클럭까지만), 1 사용, 2 공격적, 3 효율적 사용, 4 효율적 공격적
PERFBOOSTMODE = 'be337238-0d82-4146-a960-4f3749d470c7'
# 에너지 성능 기본 설정(EPP, 0~100): 0 이면 성능 우선, 클수록 효율 우선. CPPC 를 쓰는 CPU 에서 클럭 결정에 쓰인다
PERFEPP = '36687f9e-e3a5-4dbf-b1dc-15eb381c6863'
SUB_PCIEXPRESS = '501a4d13-42af-4429-9fd1-a8218c268e20'
# PCIe 링크 상태 전원 관리(ASPM): 0 끔, 1 보통 절전, 2 최대 절전
PCIE_ASPM = 'ee12f906-d277-404b-b6da-e5fa1a576df5'

PLAN_BALANCED = '381b4222-f694-41f0-9685-ff5bb260df2e'
PLAN_HIGH_PERF = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
PLAN_POWER_SAVER = 'a1841308-3541-4fab-bc81-f71556f20b4a'
PLAN_ULTIMATE = 'e9a42b02-d5df-448d-aa00-03f14749eb61'

KNOWN_PLANS = {
    PLAN_BALANCED: '균형 조정',
    PLAN_HIGH_PERF: '고성능',
    PLAN_POWER_SAVER: '절전',
    PLAN_ULTIMATE: '최고의 성능',
}


def active_plan_guid():
    """현재 활성 전원 플랜 GUID 를 소문자 문자열로."""
    try:
        p = _powrprof()
        ptr = ctypes.POINTER(_GUID)()
        if p.PowerGetActiveScheme(None, ctypes.byref(ptr)) != 0 or not ptr:
            return None
        g = ptr.contents
        import struct
        u = uuid.UUID(bytes_le=struct.pack('<IHH', g.Data1, g.Data2, g.Data3) + bytes(g.Data4))
        ctypes.windll.kernel32.LocalFree(ptr)
        return str(u).lower()
    except Exception as e:
        log.warning(f"활성 플랜 조회 실패: {e}")
        return None


ACCESS_SCHEME = 16
ERROR_NO_MORE_ITEMS = 259


def available_plans():
    """이 PC 에 실제로 존재하는 전원 플랜만 돌려준다.

    최신 노트북(Modern Standby)에서는 고성능·절전 플랜이 아예 없는 경우가 있다.
    없는 플랜으로 전환을 시도하면 조용히 실패하므로 미리 확인해야 한다.

    주의: PowerReadFriendlyName 으로 확인하면 안 된다. Windows 는 '최고의 성능'처럼
    이 PC 에 등록되지 않은 플랜의 이름도 알고 있어서, 이름이 읽힌다는 것이
    플랜이 존재한다는 뜻이 되지 않는다. PowerEnumerate 가 유일하게 정확한 방법이다.
    """
    out = {}
    p = _powrprof()
    index = 0
    while index < 64:                      # 폭주 방지
        try:
            buf = (ctypes.c_ubyte * 16)()  # GUID 하나
            size = ctypes.c_ulong(16)
            r = p.PowerEnumerate(None, None, None, ctypes.c_ulong(ACCESS_SCHEME),
                                 ctypes.c_ulong(index), ctypes.byref(buf),
                                 ctypes.byref(size))
            if r == ERROR_NO_MORE_ITEMS:
                break
            if r != 0:
                log.debug(f"PowerEnumerate 오류 {r} (index={index})")
                break
            g = uuid.UUID(bytes_le=bytes(buf))
            guid_str = str(g).lower()

            name = KNOWN_PLANS.get(guid_str, '')
            try:
                nbuf = ctypes.create_unicode_buffer(256)
                nsize = ctypes.c_ulong(ctypes.sizeof(nbuf))
                gg = _guid(guid_str)
                if p.PowerReadFriendlyName(None, ctypes.byref(gg), None, None,
                                           ctypes.byref(nbuf), ctypes.byref(nsize)) == 0:
                    name = nbuf.value or name
            except Exception:
                pass
            out[guid_str] = name or guid_str
            index += 1
        except Exception as e:
            log.debug(f"플랜 열거 실패: {e}")
            break
    return out


_PLAN_KEY = 'power:active_plan'


@_locked
def set_active_plan(guid_str, group, why=''):
    """전원 플랜을 바꾼다. 원래 플랜을 기록해 두고, 바꾼 뒤 확인한다.

    활성 플랜은 하나라서 원래 값 기록도 하나다. 그 기록은 마지막으로 플랜을 바꾼 group 이
    가진다. 다른 group 이 남긴 기록이 있으면 원래 값은 그대로 두고 소유만 넘겨받는다.
    넘겨받지 않으면 이 group 을 되돌려도 플랜이 돌아오지 않는다(예: 구버전 맞춤 튜닝이
    'hw_tuning' 으로 남긴 기록 때문에 성능 모드 전환이 플랜을 되돌리지 못했다).
    원래 값 기록을 남기지 못하면 바꾸지 않는다.
    """
    before = active_plan_guid()
    if not before:
        return {'ok': False, 'verified': False,
                'reason': '현재 전원 플랜을 읽지 못해 바꾸지 않았습니다'}
    if guid_str not in available_plans():
        return {'ok': False, 'verified': False,
                'reason': f'이 PC 에 없는 전원 플랜입니다 ({KNOWN_PLANS.get(guid_str, guid_str)})'}
    try:
        had_record = _PLAN_KEY in _load()['entries']
    except JournalUnreadable:
        return dict(_NOT_RECORDED)
    if not _record(_PLAN_KEY, {
        'kind': 'power_plan', 'group': group, 'value': before, 'why': why,
    }):
        return dict(_NOT_RECORDED)
    try:
        data = _load()
    except JournalUnreadable:
        return dict(_NOT_RECORDED)
    entry = data['entries'].get(_PLAN_KEY)
    if entry is not None and entry.get('group') != group:
        entry['group'] = group
        entry['why'] = why or entry.get('why', '')
        _save(data)
        entry = _load()['entries'].get(_PLAN_KEY)
    if entry is None or entry.get('group') != group:
        return {'ok': False, 'verified': False,
                'reason': '원래 전원 플랜 기록을 저장하지 못해 바꾸지 않았습니다'}

    def failed(reason):
        # 이번 호출이 만든 기록인데 플랜이 그대로면 바뀐 것이 없다. 남기면 '되돌리지 못한 설정 1개' 가 계속 보이고,
        # 플랜 전환을 막는 PC 에서는 그 기록을 되돌리는 것도 계속 실패했다.
        if not had_record and active_plan_guid() == before:
            _forget([_PLAN_KEY])
        return {'ok': False, 'verified': False, 'reason': reason}

    try:
        g = _guid(guid_str)
        r = _powrprof().PowerSetActiveScheme(None, ctypes.byref(g))
        if r != 0:
            return failed(f'PowerSetActiveScheme 오류 {r}')
    except Exception as e:
        return failed(str(e))

    after = active_plan_guid()
    if after != guid_str.lower():
        return failed(f'전환 후 확인 실패 (기대 {guid_str}, 실제 {after})')
    # 이 앱이 바꿔 둔 플랜. 원래 플랜이 지워진 뒤 사용자가 다른 플랜을 골랐는지 알아보는 데 쓴다(_restore).
    try:
        data = _load()
        if _PLAN_KEY in data['entries'] and data['entries'][_PLAN_KEY].get('set_to') != after:
            data['entries'][_PLAN_KEY]['set_to'] = after
            _save(data)
    except JournalUnreadable:
        pass
    return {'ok': True, 'verified': True, 'before': before, 'after': after}


_ERROR_FILE_NOT_FOUND = 2


def _read_power_raw(plan, sub, setting, ac):
    """(Win32 반환 코드, 값). 코드 2(ERROR_FILE_NOT_FOUND)는 이 PC 의 전원 설정에 그 항목이 없다는 뜻이다."""
    p = _powrprof()
    val = ctypes.c_ulong()
    pg, sg, stg = _guid(plan), _guid(sub), _guid(setting)
    fn = p.PowerReadACValueIndex if ac else p.PowerReadDCValueIndex
    r = fn(None, ctypes.byref(pg), ctypes.byref(sg), ctypes.byref(stg), ctypes.byref(val))
    return r, (val.value if r == 0 else None)


def _read_power_value(plan, sub, setting, ac):
    return _read_power_raw(plan, sub, setting, ac)[1]


def power_value(sub, setting, ac=True, plan=None):
    """활성(또는 지정) 플랜의 세부값을 읽는다. 없거나 읽지 못하면 None. 읽기만 한다."""
    plan = plan or active_plan_guid()
    return _read_power_value(plan, sub, setting, ac) if plan else None


@_locked
def set_power_value(sub, setting, value, group, plan=None, label='', both_ac_dc=True):
    """전원 플랜의 세부 설정을 바꾼다.

    plan 을 지정하지 않으면 현재 활성 플랜에 적용한다.
    both_ac_dc: 노트북 배터리 구동 시에도 같은 값을 적용할지.
      기존 코드는 코어 파킹과 USB 를 AC 에만 적용해서, 배터리로 쓰면
      게이밍 모드가 절반만 걸리는 문제가 있었다.
    """
    plan = plan or active_plan_guid()
    if not plan:
        return {'ok': False, 'verified': False, 'reason': '활성 전원 플랜을 읽지 못했습니다'}

    results = []
    for ac in ([True, False] if both_ac_dc else [True]):
        code, before = _read_power_raw(plan, sub, setting, ac)
        if before is None:
            # 원래 값을 모르면 되돌릴 수 없다. 모르는 채로 바꾸지 않는다.
            # 항목 자체가 없는 PC(예: PCIe 절전이 없는 가상 머신)는 실패가 아니라 '지원하지 않음' 이다.
            results.append({'ac': ac, 'ok': False, 'unsupported': code == _ERROR_FILE_NOT_FOUND,
                            'reason': ('이 PC 의 전원 설정에 없는 항목입니다' if code == _ERROR_FILE_NOT_FOUND
                                       else '원래 값을 읽지 못해 바꾸지 않았습니다')})
            continue
        key = f"power:{plan}:{sub}:{setting}:{'ac' if ac else 'dc'}"
        if not _record(key, {
            'kind': 'power_value', 'group': group, 'plan': plan, 'sub': sub,
            'setting': setting, 'ac': ac, 'value': before, 'why': label,
        }):
            results.append({'ac': ac, 'ok': False, 'reason': _NOT_RECORDED['reason']})
            continue
        try:
            p = _powrprof()
            pg, sg, stg = _guid(plan), _guid(sub), _guid(setting)
            fn = p.PowerWriteACValueIndex if ac else p.PowerWriteDCValueIndex
            r = fn(None, ctypes.byref(pg), ctypes.byref(sg), ctypes.byref(stg),
                   ctypes.c_ulong(value))
            if r != 0:
                results.append({'ac': ac, 'ok': False, 'reason': f'쓰기 오류 {r}'})
                continue
        except Exception as e:
            results.append({'ac': ac, 'ok': False, 'reason': str(e)})
            continue

        after = _read_power_value(plan, sub, setting, ac)
        results.append({'ac': ac, 'ok': after == value, 'before': before, 'after': after,
                        'reason': '' if after == value else f'기대 {value}, 실제 {after}'})

    # 쓴 값은 플랜을 다시 활성화해야 실제로 적용된다.
    # 단, 지금 활성 플랜일 때만. 비활성 플랜을 켜면 기록 없이 플랜을 바꾸는 셈이 된다.
    _reapply_if_active({plan})

    ok = all(r['ok'] for r in results)
    unsupported = bool(results) and all(r.get('unsupported') for r in results)
    return {'ok': ok, 'verified': ok, 'detail': results, 'unsupported': unsupported,
            'before': next((r.get('before') for r in results if r.get('ac')), None),
            'reason': '' if ok else '; '.join(r['reason'] for r in results if not r['ok'])}


def _reapply_if_active(plans):
    """세부값을 쓴 플랜이 지금 활성 플랜이면 다시 활성화해 반영시킨다.

    비활성 플랜은 건드리지 않는다. 예전 복구 경로는 원래 플랜을 되돌린 '뒤에'
    세부값을 고친 플랜(예: 고성능)을 다시 활성화해서, '전부 원래대로' 를 눌러도
    고성능 플랜이 켜진 채로 끝났다.
    """
    active = active_plan_guid()
    if active and active in plans:
        try:
            _powrprof().PowerSetActiveScheme(None, ctypes.byref(_guid(active)))
        except Exception:
            pass


# ─────────────────────────────────────────────
# 서비스 시작 유형
# ─────────────────────────────────────────────
# 레지스트리 Start 값을 직접 쓰지 않고 sc.exe 를 쓴다. SCM 이 설정을 캐시하고 있어서
# 레지스트리만 바꾸면 재부팅 전까지 SCM 과 어긋난다. 확인은 레지스트리를 다시 읽어서 한다.

_SERVICES_KEY = r'SYSTEM\CurrentControlSet\Services'
START_TYPES = ('auto', 'delayed-auto', 'demand', 'disabled')
_START_VALUE = {'auto': 2, 'delayed-auto': 2, 'demand': 3, 'disabled': 4}
CREATE_NO_WINDOW = 0x08000000


def _valid_service_name(service):
    # 명령줄에 들어가는 값이다. 문자·숫자·_ . - 만 허용한다.
    return (isinstance(service, str) and 0 < len(service) <= 256
            and all(c.isascii() and (c.isalnum() or c in '_.-') for c in service))


def read_service_start(service):
    """(ok, Start, DelayedAutostart) 를 돌려준다. 서비스가 없거나 읽지 못하면 ok=False."""
    if not _valid_service_name(service):
        return False, None, None
    path = f'{_SERVICES_KEY}\\{service}'
    ok, start, _ = read_registry('HKLM', path, 'Start')
    if not ok or not isinstance(start, int):
        return False, None, None
    has_delayed, delayed, _ = read_registry('HKLM', path, 'DelayedAutostart')
    return True, start, (delayed if has_delayed else None)


def service_start_type(service):
    """'auto'·'delayed-auto'·'demand'·'disabled'·'boot'·'system' 또는 None(읽지 못함)."""
    ok, start, delayed = read_service_start(service)
    if not ok:
        return None
    if start == 2:
        return 'delayed-auto' if delayed else 'auto'
    return {0: 'boot', 1: 'system', 3: 'demand', 4: 'disabled'}.get(start)


def _sc_config_start(service, start_type):
    """sc.exe config <서비스> start= <유형>. shell=False, 절대 경로, 인자는 검증한 값만."""
    if not _valid_service_name(service) or start_type not in _START_VALUE:
        return {'rc': None, 'error': '허용되지 않은 인자'}
    sysroot = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or r'C:\Windows'
    sc = os.path.join(sysroot, 'System32', 'sc.exe')
    try:
        r = subprocess.run([sc, 'config', service, 'start=', start_type], shell=False,
                           capture_output=True, text=True, errors='replace',
                           creationflags=CREATE_NO_WINDOW, timeout=30)
    except Exception as e:
        return {'rc': None, 'error': str(e) or type(e).__name__}
    err = '' if r.returncode == 0 else (r.stderr or r.stdout or '').strip()[-200:]
    return {'rc': r.returncode, 'error': err}


def _write_service_start(service, start_type):
    """쓰고 다시 읽어 확인한다. (ok, reason)"""
    if service_start_type(service) == start_type:
        return True, ''
    r = _sc_config_start(service, start_type)
    now = service_start_type(service)
    if now != start_type:
        detail = r.get('error') or ''
        return False, (f'{service} 시작 유형을 {start_type} 로 바꾸지 못했습니다 '
                       f'(sc 코드 {r.get("rc")}, 현재 {now}) {detail}').strip()
    return True, ''


@_locked
def set_service_start(service, start_type, group, why=''):
    """서비스 시작 유형을 바꾼다. 원래 Start·DelayedAutostart 를 먼저 기록한다.

    원래 값을 읽지 못하거나 저널에 남기지 못하면 바꾸지 않는다.
    반환: {'ok', 'changed', 'before', 'reason'}
    """
    if not _valid_service_name(service):
        return {'ok': False, 'changed': False, 'reason': '서비스 이름이 올바르지 않습니다'}
    if start_type not in START_TYPES:
        return {'ok': False, 'changed': False, 'reason': f'알 수 없는 시작 유형입니다: {start_type}'}

    ok, start, delayed = read_service_start(service)
    if not ok:
        return {'ok': False, 'changed': False,
                'reason': '원래 시작 유형을 읽지 못해 바꾸지 않았습니다(서비스가 없을 수 있음)'}
    before = service_start_type(service)
    if before == start_type:
        return {'ok': True, 'changed': False, 'before': before, 'reason': ''}
    if before not in START_TYPES:
        return {'ok': False, 'changed': False, 'before': before,
                'reason': f'시작 유형이 일반적이지 않아({start}) 건드리지 않았습니다'}

    key = f'svc:{service.lower()}'
    recorded = _record(key, {
        'kind': 'service', 'group': group, 'service': service,
        'start': start, 'delayed': delayed, 'why': why,
    })
    # 기록이 실제로 남았는지 확인한 뒤에만 바꾼다.
    if not recorded or key not in pending_changes():
        return {'ok': False, 'changed': False, 'before': before,
                'reason': '되돌릴 정보를 저장하지 못해 바꾸지 않았습니다'}

    w_ok, reason = _write_service_start(service, start_type)
    return {'ok': w_ok, 'changed': w_ok, 'before': before, 'reason': reason}


def _restore_service(e):
    """기록한 원래 Start·DelayedAutostart 로 되돌린다. (ok, reason)"""
    svc = e.get('service')
    start = e.get('start')
    if start is None and isinstance(e.get('value'), dict):
        # 병합 전 브랜치가 남긴 형식 {'value': {'start', 'delayed'}} 도 읽는다
        start = e['value'].get('start')
        e = dict(e, delayed=e['value'].get('delayed'))
    if not _valid_service_name(svc) or not isinstance(start, int) or isinstance(start, bool):
        return False, '기록 형식이 올바르지 않아 건드리지 않았습니다'
    if start == 2:
        target = 'delayed-auto' if e.get('delayed') else 'auto'
    else:
        target = {3: 'demand', 4: 'disabled'}.get(start)
    if not target:
        return False, f'원래 시작 유형({start})은 이 앱이 되돌리지 않습니다'
    return _write_service_start(svc, target)


@_locked
def restore_service_start(service, start, delayed):
    """저널 밖에 남은 기록(구버전 settings.json 백업)으로 되돌릴 때 쓴다. (ok, reason)"""
    return _restore_service({'service': service, 'start': start, 'delayed': delayed})


# ─────────────────────────────────────────────
# 복구
# ─────────────────────────────────────────────

def restore_group(group):
    """특정 그룹의 변경만 되돌린다(예: 이전 성능 모드)."""
    return _restore(lambda e: e.get('group') == group)


def restore_all():
    """이 앱이 바꾼 모든 시스템 설정을 원래대로 되돌린다."""
    return _restore(lambda e: True)


def _restore_registry(e):
    """레지스트리 항목 하나를 되돌리고 되읽어 확인한다. 실패 사유 또는 None."""
    hive, path, name = HIVES[e['hive']], e['path'], e['name']
    original = _dec(e.get('value'))
    if e.get('existed'):
        if original is None:
            return '기록된 원래 값의 형식이 올바르지 않아 건드리지 않았습니다'
        with winreg.CreateKeyEx(hive, path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, name, 0, e.get('type') or winreg.REG_DWORD, original)
    else:
        # 원래 없던 값이다. 되돌린다는 건 '지운다'는 뜻이다.
        try:
            with winreg.OpenKey(hive, path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass
    existed, now, _ = read_registry_strict(e['hive'], path, name)
    if e.get('existed'):
        if not existed or now != original:
            return f"되돌린 뒤 다시 읽으니 값이 다릅니다 (기대 {original}, 실제 {now})"
    elif existed:
        return '원래 없던 값을 지웠지만 아직 남아 있습니다'
    return None


def restore_user_entries_under(base, entries):
    """다른 계정의 하이브(HKU\\<SID> 또는 잠깐 올린 NTUSER.DAT) 아래에서 그 계정의 시작 프로그램 표시 기록을 되돌린다.

    제거할 때만 쓴다. 이 계정의 저널(HKCU)과 같은 규칙이다: 원래 값이 있었으면 그 값으로, 없었으면 지우고,
    되읽어 확인하고, 이 앱이 만든 키는 비었을 때만 지운다. 시작 프로그램 표시가 아닌 기록은 건드리지 않는다.
    반환: (되돌린 키 목록, [{'key', 'reason'}])
    """
    done, failed, created = [], [], set()
    for key, e in entries.items():
        if not _trusted_user_entry(e):
            failed.append({'key': key, 'reason': '시작 프로그램 표시 기록이 아니라 건드리지 않았습니다'})
            continue
        path, name = e['path'], e['name']
        original = _dec(e.get('value'))
        try:
            if e.get('existed'):
                if original is None:
                    failed.append({'key': key, 'reason': '기록된 원래 값의 형식이 올바르지 않아 건드리지 않았습니다'})
                    continue
                with winreg.CreateKeyEx(base, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                    winreg.SetValueEx(k, name, 0, e.get('type') or winreg.REG_BINARY, original)
            else:
                try:
                    with winreg.OpenKey(base, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                        winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
            try:
                with winreg.OpenKey(base, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                    now, _ = winreg.QueryValueEx(k, name)
                exists = True
            except FileNotFoundError:
                exists, now = False, None
        except OSError as ex:
            failed.append({'key': key, 'reason': f'되돌리지 못했습니다: {ex}'})
            continue
        if e.get('existed') and (not exists or now != original):
            failed.append({'key': key, 'reason': f'되돌린 뒤 다시 읽으니 값이 다릅니다 (기대 {original}, 실제 {now})'})
            continue
        if not e.get('existed') and exists:
            failed.append({'key': key, 'reason': '원래 없던 값을 지웠지만 아직 남아 있습니다'})
            continue
        created.update(k for k in e.get('created_keys') or [] if isinstance(k, str))
        done.append(key)
    for path in sorted(created, key=lambda p: p.count('\\'), reverse=True):
        try:
            with winreg.OpenKey(base, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                subkeys, values, _ = winreg.QueryInfoKey(k)
            if not subkeys and not values:
                winreg.DeleteKeyEx(base, path, winreg.KEY_WOW64_64KEY, 0)
        except OSError:
            pass
    return done, failed


@_locked
def _restore(predicate):
    try:
        data = _load()
    except JournalUnreadable as e:
        # 무엇을 되돌려야 하는지 모른다. 아무것도 쓰지 않고 실패로 알린다(기록은 그대로 남는다).
        return {'ok': False, 'restored': 0, 'remaining': None,
                'failed': [{'key': 'journal', 'reason': f'변경 기록 파일을 읽지 못해 되돌리지 못했습니다 ({e})'}]}
    entries = data['entries']
    done, failed, plans_touched = [], [], set()
    fill_set_to = {}
    created_keys = set()        # 되돌린 값을 쓰면서 이 앱이 만들었던 키. 끝에 비어 있으면 지운다.

    # 전원 플랜 전환은 마지막에 해야 한다. 먼저 하면 세부값을 엉뚱한 플랜에 쓴다.
    ordered = sorted(entries.items(), key=lambda kv: kv[1].get('kind') == 'power_plan')

    for key, e in ordered:
        if not predicate(e):
            continue
        try:
            kind = e.get('kind')
            if kind == 'registry':
                reason = _restore_registry(e)
                if reason:
                    failed.append({'key': key, 'reason': reason})
                    continue
                created_keys.update((e['hive'], k) for k in e.get('created_keys') or [])
                done.append(key)

            elif kind == 'power_value':
                if e.get('value') is None:
                    done.append(key)          # 원래 읽을 수 없던 값이면 건드리지 않는다
                    continue
                p = _powrprof()
                pg, sg, stg = _guid(e['plan']), _guid(e['sub']), _guid(e['setting'])
                fn = p.PowerWriteACValueIndex if e['ac'] else p.PowerWriteDCValueIndex
                r = fn(None, ctypes.byref(pg), ctypes.byref(sg), ctypes.byref(stg),
                       ctypes.c_ulong(e['value']))
                if r == _ERROR_FILE_NOT_FOUND and str(e['plan']).lower() not in available_plans():
                    # 값을 바꿨던 플랜이 지워졌다. 그 값도 함께 사라졌으므로 되돌릴 것이 없다. 남기면 이후 모든
                    # 모드 전환·'전부 원래대로'·제거 전 되돌리기가 영원히 실패한다.
                    done.append(key)
                    continue
                if r != 0:
                    failed.append({'key': key, 'reason': f'쓰기 오류 {r}'})
                    continue
                now = _read_power_value(e['plan'], e['sub'], e['setting'], e['ac'])
                if now != e['value']:
                    failed.append({'key': key,
                                   'reason': f"되돌린 뒤 다시 읽으니 값이 다릅니다 (기대 {e['value']}, 실제 {now})"})
                    continue
                plans_touched.add(e['plan'])
                done.append(key)

            elif kind == 'power_plan':
                original = str(e.get('value') or '').lower()
                active = active_plan_guid()
                if original and active != original:
                    if original not in available_plans():
                        # 원래 플랜이 지워졌다. 이 앱이 바꿔 둔 플랜이 아직 켜져 있으면 사용자가 골라야 한다(한 번 안내).
                        # 사용자가 이미 다른 플랜을 골랐으면 돌아갈 곳이 없으니 기록을 정리한다. 예전에는 기록이 영원히
                        # 남아 이후 모든 모드 전환과 제거 전 되돌리기가 실패했다.
                        # 바꿔 둔 플랜을 모르는 예전 기록은 지금 켜진 플랜이 그것이라고 보고 한 번 안내한다
                        set_to = e.get('set_to') if 'set_to' in e else active
                        if 'set_to' not in e and active:
                            fill_set_to[key] = active      # 다음에는 사용자가 다른 플랜을 골랐는지 알 수 있다
                        if active and active == str(set_to or '').lower():
                            name = KNOWN_PLANS.get(original, original)
                            failed.append({'key': key, 'reason': (
                                f"원래 전원 플랜({name})이 이 PC 에서 삭제되어 되돌릴 수 없습니다. "
                                "Windows 설정 → 전원에서 쓸 플랜을 고르면 이 기록은 정리됩니다")})
                            continue
                        done.append(key)
                        continue
                    res = _powrprof().PowerSetActiveScheme(None, ctypes.byref(_guid(original)))
                    if res != 0:
                        failed.append({'key': key, 'reason': f'플랜 복구 실패 {res}'})
                        continue
                    if active_plan_guid() != original:
                        failed.append({'key': key, 'reason': '플랜을 되돌린 뒤 확인에 실패했습니다'})
                        continue
                done.append(key)

            elif kind == 'service':
                ok, reason = _restore_service(e)
                if not ok:
                    failed.append({'key': key, 'reason': reason or '서비스 복구 실패'})
                    continue
                done.append(key)
            else:
                failed.append({'key': key, 'reason': f'알 수 없는 종류: {kind}'})
        except PermissionError:
            failed.append({'key': key, 'reason': '쓰기가 거부되었습니다(다른 프로그램이나 보안 정책이 이 값을 잠갔을 수 있습니다)'})
        except Exception as ex:
            failed.append({'key': key, 'reason': str(ex)})

    # 되돌린 세부값을 실제로 반영시킨다. 원래 플랜을 되돌린 '뒤' 이므로
    # 지금 활성 플랜만 다시 활성화한다.
    _reapply_if_active(plans_touched)

    # 이 앱이 만든 키는 깊은 것부터, 비어 있을 때만 지운다. 같은 키의 다른 값이 아직 남아 있으면 그대로 둔다.
    kept = []
    for hive, path in sorted(created_keys, key=lambda hp: hp[1].count('\\'), reverse=True):
        if not _delete_key_if_empty(hive, path) and not _missing_keys(hive, path):
            kept.append((hive, path))           # 아직 있다(다른 값이 남음)

    # 성공한 것만 저널에서 지운다. 실패한 건 남겨야 다음에 다시 시도할 수 있다.
    if done:
        _forget_and_hand_over(done, kept)
    if fill_set_to:
        try:
            data = _load()
            for key, plan in fill_set_to.items():
                if key in data['entries']:
                    data['entries'][key]['set_to'] = plan
            _save(data)
        except JournalUnreadable:
            pass

    # 개수는 설정 단위로(전원 연결·배터리 값을 하나로). 한쪽만 실패한 설정은 되돌린 것으로 세지 않는다.
    bad = {setting_of(f['key']) for f in failed if isinstance(f.get('key'), str)}
    for f in failed:
        e = entries.get(f.get('key'))
        if isinstance(e, dict) and e.get('why'):
            f.setdefault('what', e['why'])            # 화면이 어느 설정인지 보여 줄 수 있게
    return {'ok': not failed, 'restored': len(done),
            'restored_settings': len({setting_of(k) for k in done} - bad), 'failed_settings': len(bad),
            'failed': failed, 'remaining': len(pending_changes())}
