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
  2. 원래 값을 읽지 못했거나 그 기록을 디스크에 남기지 못하면 아무것도 바꾸지 않는다.
  3. 바꾼 뒤 다시 읽어서 실제로 반영됐는지 확인한다. 반환 코드를 믿지 않는다.
  4. 실패는 실패라고 보고한다. 조용히 성공으로 넘기지 않는다.
  5. 언제든 restore_all() 로 전부 원래대로 되돌릴 수 있다.
  6. 원래 값이 '없었던' 항목은 복구 시 값을 되돌리는 게 아니라 지운다.
  7. 되돌리기에 실패한 항목은 저널에 남긴다. 그래야 다시 시도할 수 있다.

여러 기능이 같은 값을 바꿀 때(층):
  게이밍 모드와 네트워크 튜닝이 둘 다 NetworkThrottlingIndex 를 바꾸는 식이다.
  기능(group)마다 '그 기능이 바꾸기 직전 값'을 층으로 쌓는다. 맨 위 층을 되돌리면 그 직전 값을 쓰고,
  중간 층을 되돌리면 값은 그대로 두고 그 층의 원래 값을 바로 위 층에 넘긴다.
  그래서 어떤 순서로 되돌려도 마지막에는 진짜 원본이 남는다.

기록 종류(kind):
  registry            레지스트리 값 (set_registry, delete_registry_value)
  service             서비스 시작 유형 (set_service_start)
  tcp_autotuning      TCP 수신 창 자동 튜닝 수준 (set_tcp_autotuning)
  power_value         전원 플랜 세부값 (set_power_value)
  power_plan          활성 전원 플랜 (set_active_plan)
  power_plan_created  이 앱이 복제해 만든 전원 플랜 (create_plan_copy). 복구 = 원래 플랜을 켠 뒤 삭제

저널 위치: %APPDATA%\\APEX_CARE_DATA\\system_state.json
"""

import ctypes
import json
import logging
import os
import re
import struct
import subprocess
import threading
import time
import uuid
import winreg

log = logging.getLogger('SystemState')

APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
JOURNAL_PATH = os.path.join(APPDATA_DIR, 'system_state.json')

HIVES = {
    'HKLM': winreg.HKEY_LOCAL_MACHINE,
    'HKCU': winreg.HKEY_CURRENT_USER,
}

_REG_TYPES = {winreg.REG_SZ, winreg.REG_EXPAND_SZ, winreg.REG_BINARY, winreg.REG_DWORD,
              winreg.REG_MULTI_SZ, winreg.REG_QWORD}

CREATE_NO_WINDOW = 0x08000000

# 저널 읽기-수정-쓰기와 시스템 변경을 한 줄로 세운다.
# pywebview 는 API 호출마다 스레드를 따로 쓰고 게임 부스터도 자기 스레드에서 모드를 바꾼다.
# 잠금이 없으면 두 스레드가 각자 읽은 저널을 저장하면서 서로의 원본 기록을 지운다.
_lock = threading.RLock()


def lock():
    """여러 변경을 한 덩어리로 묶을 때 쓴다(예: 이전 모드 복구 → 새 모드 적용).

    RLock 이라 잡은 채로 이 모듈의 함수를 불러도 막히지 않는다.
    """
    return _lock


class JournalError(Exception):
    """저널을 읽거나 쓸 수 없다. 이 상태에서는 시스템을 바꾸지 않는다."""


# ─────────────────────────────────────────────
# 저널 입출력
# ─────────────────────────────────────────────

def _empty():
    return {'version': 2, 'seq': 0, 'entries': {}}


def _quarantine(reason):
    """깨진 저널을 지우지 않고 옆에 보존한다. 이전 보존본은 덮어쓰지 않는다."""
    for n in range(1, 1000):
        dst = f'{JOURNAL_PATH}.corrupt-{n}'
        if os.path.exists(dst):
            continue
        try:
            os.rename(JOURNAL_PATH, dst)
            log.error(f'깨진 저널을 {dst} 로 옮겼습니다 ({reason})')
            return True
        except FileExistsError:
            continue
        except OSError as e:
            log.error(f'깨진 저널을 보존하지 못했습니다: {e}')
            return False
    return False


def _load():
    """저널을 읽는다. 읽을 수 없으면 JournalError.

    파일이 없으면 빈 저널이다. 내용이 깨졌으면 옆에 보존하고 빈 저널로 시작한다.
    그 밖의 읽기 오류(백신이 잠깐 잡고 있는 경우 등)는 손상이 아니다.
    빈 저널로 취급하면 다음 저장이 기존 원본 기록을 통째로 덮어쓰므로 오류로 올린다.
    """
    last = None
    for _ in range(3):
        try:
            with open(JOURNAL_PATH, 'r', encoding='utf-8') as f:
                raw = f.read()
        except FileNotFoundError:
            return _empty()
        except OSError as e:
            last = e
            time.sleep(0.2)
            continue

        try:
            data = json.loads(raw)
            why = '형식이 올바르지 않음'
        except ValueError as e:
            data, why = None, f'JSON 파싱 실패: {e}'

        if isinstance(data, dict) and isinstance(data.get('entries'), dict):
            if not isinstance(data.get('seq'), int):
                data['seq'] = max([_seq(e) for e in data['entries'].values()] + [0])
            return data
        if _quarantine(why):
            return _empty()
        raise JournalError('저널이 손상됐고 보존하지 못했습니다')
    raise JournalError(f'저널을 읽지 못했습니다: {last}')


def _replace(src, dst):
    # 백신·인덱서가 방금 쓴 파일을 잠깐 열고 있으면 교체가 실패한다. 몇 번 다시 시도한다.
    for i in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == 4:
                raise
            time.sleep(0.1 * (i + 1))


def _save(data):
    """원자적으로 쓴다. 쓰다가 죽으면 복구 정보가 통째로 사라진다."""
    tmp = f'{JOURNAL_PATH}.tmp-{os.getpid()}'
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=1)
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, JOURNAL_PATH)
        return True
    except Exception as e:
        log.error(f'저널 저장 실패: {e}')
        try:
            os.remove(tmp)      # 이 모듈이 방금 만든 임시 파일이다
        except OSError:
            pass
        return False


def _seq(e):
    s = e.get('seq', 0) if isinstance(e, dict) else 0
    return s if isinstance(s, int) else 0


def _base_of(key, e):
    """같은 대상(레지스트리 값 하나, 서비스 하나 등)을 가리키는 기록끼리 묶는 이름."""
    b = e.get('base') if isinstance(e, dict) else None
    return b if isinstance(b, str) and b else str(key).lower()


def _reg_base(hive, path, name):
    # 레지스트리는 대소문자를 가리지 않는다. 모듈마다 다르게 적어도 같은 값으로 묶여야 한다.
    return f'reg:{hive}\\{path}\\{name}'.lower()


def _layers(data, base):
    ls = [(k, e) for k, e in data['entries'].items()
          if isinstance(e, dict) and _base_of(k, e) == base]
    ls.sort(key=lambda kv: _seq(kv[1]))
    return ls


def _enc(v):
    if isinstance(v, (bytes, bytearray)):
        return {'__bytes__': bytes(v).hex()}
    return v


def _dec(v):
    if isinstance(v, dict) and isinstance(v.get('__bytes__'), str):
        try:
            return bytes.fromhex(v['__bytes__'])
        except ValueError:
            return None
    return v


def _record(base, group, entry, only_if_layered=False):
    """원본을 기록한다. 이 기능(group)의 기록이 이미 있으면 건드리지 않는다 — 이게 핵심이다.

    only_if_layered: 지금 값이 이미 원하는 값일 때 쓴다. 다른 기능의 층이 없으면 바뀌는 게
      없으므로 기록하지 않는다. 층이 있으면 이 기능의 층을 올려 둔다. 아래 기능을 먼저
      되돌려도 이 기능이 원하는 값이 유지되게 하려는 것이다.

    반환: (ok, reason, recorded). ok 가 False 면 원본이 디스크에 없다는 뜻이다.
    이때 호출부는 시스템을 바꾸면 안 된다.
    """
    with _lock:
        try:
            data = _load()
        except JournalError as e:
            return False, str(e), False
        layers = _layers(data, base)
        if any(e.get('group') == group for _, e in layers):
            return True, '', False          # 이미 원본이 있다. 덮어쓰면 진짜 원본을 잃는다.
        if only_if_layered and not layers:
            return True, '', False
        key = base if not layers and base not in data['entries'] else f'{base}@{group}'
        seq = int(data.get('seq') or 0) + 1
        rec = dict(entry)
        rec.update({'base': base, 'group': group, 'seq': seq, 'ts': int(time.time())})
        data['seq'] = seq
        data['entries'][key] = rec
        if not _save(data):
            return False, '저널 저장 실패', False
        return True, '', True


def _forget(keys):
    with _lock:
        try:
            data = _load()
        except JournalError as e:
            log.error(f'저널에서 항목을 지우지 못했습니다: {e}')
            return False
        for k in keys:
            data['entries'].pop(k, None)
        return _save(data)


def _adopt(base, fields):
    """구버전 백업의 원래 값을 저널 맨 아래 층에 반영한다.

    구버전이 이미 바꿔 둔 값을 새 기능이 '원본'으로 기록했을 때 쓴다.
    반환: 'amended'(저널을 고침) / 'none'(기록 없음) / 'error'
    """
    with _lock:
        try:
            data = _load()
        except JournalError:
            return 'error'
        layers = _layers(data, base)
        if not layers:
            return 'none'
        _, bottom = layers[0]
        bottom.update(fields)
        bottom['legacy_adopted'] = True
        return 'amended' if _save(data) else 'error'


def pending_changes():
    """아직 되돌리지 않은 변경 목록. UI 가 '되돌리기' 버튼을 띄울지 판단하는 데 쓴다."""
    try:
        data = _load()
    except JournalError as e:
        log.error(f'변경 목록을 읽지 못했습니다: {e}')
        return {}
    return {k: e for k, e in data['entries'].items() if isinstance(e, dict)}


def has_pending():
    return bool(pending_changes())


def has_entry(hive, path, name):
    """이 레지스트리 값의 원래 값이 저널에 있는가. 저널을 못 읽으면 True(건드리지 않는 쪽)."""
    try:
        data = _load()
    except JournalError:
        return True
    return bool(_layers(data, _reg_base(hive, path, name)))


def corrupt_journals():
    """보존해 둔 손상 저널 파일 목록. UI 가 '기록 일부를 잃었을 수 있음' 을 알리는 데 쓴다."""
    try:
        prefix = os.path.basename(JOURNAL_PATH) + '.corrupt'
        return sorted(os.path.join(APPDATA_DIR, f) for f in os.listdir(APPDATA_DIR)
                      if f.startswith(prefix))
    except OSError:
        return []


# ─────────────────────────────────────────────
# Windows 기본 도구 실행
# ─────────────────────────────────────────────
# 셸을 거치지 않고, 절대경로로, 인자 리스트로 실행한다.
# 셸을 거치면 설정 파일에서 온 문자열이 명령으로 해석되고, 이름만 쓰면 현재 폴더의
# 같은 이름 파일이 관리자 권한으로 실행될 수 있다.

def _windows_dir():
    try:
        buf = ctypes.create_unicode_buffer(260)
        n = ctypes.windll.kernel32.GetSystemWindowsDirectoryW(buf, 260)
        if 0 < n < 260:
            return buf.value
    except Exception:
        pass
    return os.environ.get('SystemRoot') or r'C:\Windows'


def system32_path(name):
    """System32 안의 절대경로. 환경변수가 아니라 API 로 Windows 폴더를 찾는다."""
    windir = _windows_dir()
    # 32비트 프로세스에서는 System32 가 SysWOW64 로 바뀐다. 64비트 도구는 Sysnative 로 부른다.
    if struct.calcsize('P') == 4 and os.path.isdir(os.path.join(windir, 'Sysnative')):
        return os.path.join(windir, 'Sysnative', name)
    return os.path.join(windir, 'System32', name)


class _Job:
    """자식 프로세스와 그 자식들을 한 번에 끝내기 위한 Job Object."""

    def __init__(self, proc):
        self.handle = None
        try:
            k32 = ctypes.WinDLL('kernel32', use_last_error=True)
            k32.CreateJobObjectW.restype = ctypes.c_void_p
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
            k32.AssignProcessToJobObject.restype = ctypes.c_int
            k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            k32.TerminateJobObject.restype = ctypes.c_int
            k32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            h = k32.CreateJobObjectW(None, None)
            if h and k32.AssignProcessToJobObject(h, int(proc._handle)):
                self.handle, self._k32 = h, k32
            elif h:
                k32.CloseHandle(h)
        except Exception as e:
            log.debug(f'Job Object 준비 실패: {e}')

    def kill(self, proc):
        if self.handle:
            try:
                if self._k32.TerminateJobObject(self.handle, 1):
                    return
            except Exception:
                pass
        # Job 을 못 쓰면 psutil 로 자식까지 찾아 끝낸다
        try:
            import psutil
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass

    def close(self):
        if self.handle:
            try:
                self._k32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


def _decode(b):
    if not b:
        return ''
    # sfc 처럼 파이프로 UTF-16 을 내보내는 도구가 있다
    if b.count(b'\x00') > len(b) // 4:
        return b.decode('utf-16-le', errors='replace')
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return b.decode(f'cp{ctypes.windll.kernel32.GetOEMCP()}', errors='replace')
        except Exception:
            return b.decode('mbcs', errors='replace')


def run_system_tool(args, timeout=60, cancel_event=None):
    """Windows 기본 도구를 셸 없이 실행한다.

    args[0] 은 절대경로여야 한다. timeout=None 이면 끝날 때까지 기다린다.
    시간이 넘거나 cancel_event 가 켜지면 프로세스 트리 전체를 끝낸다.
    반환: {'rc', 'out', 'err', 'timedOut', 'cancelled', 'error'}
    """
    res = {'rc': None, 'out': '', 'err': '', 'timedOut': False, 'cancelled': False, 'error': None}
    if not args or not isinstance(args, (list, tuple)) or not os.path.isabs(str(args[0])):
        res['error'] = '실행 파일은 절대경로여야 합니다'
        return res
    if not all(isinstance(a, str) for a in args):
        res['error'] = '인자는 문자열이어야 합니다'
        return res
    try:
        proc = subprocess.Popen(list(args), shell=False, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=CREATE_NO_WINDOW)
    except OSError as e:
        res['error'] = str(e)
        return res

    job = _Job(proc)
    deadline = None if timeout is None else time.monotonic() + timeout
    out = err = b''
    try:
        while True:
            wait = 0.5 if cancel_event is not None else None
            if deadline is not None:
                left = max(0.0, deadline - time.monotonic())
                wait = left if wait is None else min(wait, left)
            try:
                out, err = proc.communicate(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                stop = None
                if cancel_event is not None and cancel_event.is_set():
                    stop = 'cancelled'
                elif deadline is not None and time.monotonic() >= deadline:
                    stop = 'timedOut'
                if not stop:
                    continue
                res[stop] = True
                job.kill(proc)
                try:
                    out, err = proc.communicate(timeout=15)
                except Exception:
                    pass
                break
    finally:
        job.close()
    res['rc'] = proc.returncode
    res['out'] = _decode(out)
    res['err'] = _decode(err)
    return res


# ─────────────────────────────────────────────
# 레지스트리
# ─────────────────────────────────────────────

def read_registry_ex(hive, path, name):
    """('present', 값, 타입) / ('absent', None, None) / ('error', 사유, None).

    '없음'과 '읽기 실패'를 구분해야 한다. 읽기 실패를 '원래 없었음'으로 기록하면
    복구할 때 원래 있던 값을 지워 버린다.
    """
    if hive not in HIVES:
        return 'error', f'알 수 없는 하이브 {hive}', None
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            val, typ = winreg.QueryValueEx(k, name)
            return 'present', val, typ
    except FileNotFoundError:
        return 'absent', None, None
    except OSError as e:
        return 'error', str(e), None


def read_registry(hive, path, name):
    """(존재여부, 값, 타입) 을 돌려준다. 없으면 (False, None, None)."""
    st, val, typ = read_registry_ex(hive, path, name)
    if st == 'present':
        return True, val, typ
    if st == 'error':
        log.debug(f"레지스트리 읽기 실패 {hive}\\{path}\\{name}: {val}")
    return False, None, None


def _key_exists(hive, path):
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return True         # 있는데 못 여는 경우다. 지우지 않는 쪽으로 본다.


def _delete_key_if_empty(hive, path):
    """이 앱이 만든 키가 비었으면 지운다. 값이나 하위 키가 하나라도 있으면 두고 간다."""
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            subkeys, values, _ = winreg.QueryInfoKey(k)
        if subkeys == 0 and values == 0:
            winreg.DeleteKeyEx(HIVES[hive], path, winreg.KEY_WOW64_64KEY, 0)
    except OSError:
        pass


def _value_fits(vtype, v):
    if vtype == winreg.REG_DWORD:
        return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xFFFFFFFF
    if vtype == winreg.REG_QWORD:
        return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xFFFFFFFFFFFFFFFF
    if vtype in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        return isinstance(v, str)
    if vtype == winreg.REG_MULTI_SZ:
        return isinstance(v, list) and all(isinstance(s, str) for s in v)
    if vtype == winreg.REG_BINARY:
        return v is None or isinstance(v, (bytes, bytearray))
    return False


def _fail(reason):
    return {'ok': False, 'verified': False, 'reason': reason, 'error': reason}


def set_registry(hive, path, name, value, group, vtype=winreg.REG_DWORD, why=''):
    """레지스트리 값을 바꾸고 결과를 검증한다.

    group 은 '이 변경이 어느 기능에 속하는가' 다(예: 'perf_mode').
    나중에 그 기능만 골라 되돌릴 때 쓴다.
    반환 ok 가 False 면 아무것도 바뀌지 않았거나(원본 기록 실패 등) 확인에 실패한 것이다.
    """
    if hive not in HIVES:
        return _fail(f'알 수 없는 하이브입니다: {hive}')
    if vtype not in _REG_TYPES or not _value_fits(vtype, value):
        return _fail('값의 형식이 올바르지 않습니다')
    base = _reg_base(hive, path, name)
    with _lock:
        st, before, before_type = read_registry_ex(hive, path, name)
        if st == 'error':
            return _fail(f'원래 값을 읽지 못해 바꾸지 않았습니다 ({before})')
        existed = st == 'present'
        same = existed and before == value and before_type == vtype

        ok, reason, _ = _record(base, group, {
            'kind': 'registry', 'hive': hive, 'path': path, 'name': name,
            'existed': existed, 'value': _enc(before) if existed else None,
            'type': before_type if existed else vtype,
            'key_existed': existed or _key_exists(hive, path), 'why': why,
        }, only_if_layered=same)
        if not ok:
            return _fail(f'되돌릴 정보를 저장하지 못해 바꾸지 않았습니다 ({reason})')
        if same:
            return {'ok': True, 'verified': True, 'before': before, 'after': before,
                    'changed': False, 'reason': '', 'error': None}

        try:
            with winreg.CreateKeyEx(HIVES[hive], path, 0,
                                    winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.SetValueEx(k, name, 0, vtype, value)
        except PermissionError:
            return _fail('권한 부족(관리자 권한 필요)')
        except OSError as e:
            return _fail(str(e))

        # 반환 코드를 믿지 않는다. 다시 읽어서 확인한다.
        st2, after, _ = read_registry_ex(hive, path, name)
        if st2 != 'present' or after != value:
            return _fail(f'쓴 뒤 다시 읽으니 값이 다름 (기대 {value}, 실제 {after})')
        return {'ok': True, 'verified': True, 'before': before, 'after': after,
                'changed': True, 'reason': '', 'error': None}


def delete_registry_value(hive, path, name, group, why=''):
    """레지스트리 값을 지운다. 원래 값을 먼저 기록하므로 복구하면 되살아난다."""
    if hive not in HIVES:
        return _fail(f'알 수 없는 하이브입니다: {hive}')
    base = _reg_base(hive, path, name)
    with _lock:
        st, before, before_type = read_registry_ex(hive, path, name)
        if st == 'error':
            return _fail(f'원래 값을 읽지 못해 지우지 않았습니다 ({before})')
        if st == 'absent':
            # 이미 없다. 다른 기능의 층이 있으면 이 기능의 층만 올려 둔다.
            ok, reason, _ = _record(base, group, {
                'kind': 'registry', 'hive': hive, 'path': path, 'name': name,
                'existed': False, 'value': None, 'type': winreg.REG_DWORD,
                'key_existed': _key_exists(hive, path), 'why': why,
            }, only_if_layered=True)
            if not ok:
                return _fail(f'되돌릴 정보를 저장하지 못했습니다 ({reason})')
            return {'ok': True, 'verified': True, 'changed': False, 'reason': '', 'error': None}

        ok, reason, _ = _record(base, group, {
            'kind': 'registry', 'hive': hive, 'path': path, 'name': name,
            'existed': True, 'value': _enc(before), 'type': before_type,
            'key_existed': True, 'why': why,
        })
        if not ok:
            return _fail(f'되돌릴 정보를 저장하지 못해 지우지 않았습니다 ({reason})')
        try:
            with winreg.OpenKey(HIVES[hive], path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass
        except PermissionError:
            return _fail('권한 부족(관리자 권한 필요)')
        except OSError as e:
            return _fail(str(e))

        st2, _, _ = read_registry_ex(hive, path, name)
        if st2 != 'absent':
            return _fail('지운 뒤 다시 읽으니 값이 남아 있습니다')
        return {'ok': True, 'verified': True, 'changed': True, 'before': before,
                'reason': '', 'error': None}


def adopt_registry_original(hive, path, name, existed, value, vtype=winreg.REG_DWORD):
    """구버전 백업이 들고 있던 원래 값을 저널에 반영한다('amended' / 'none' / 'error')."""
    if existed and not _value_fits(vtype, value):
        return 'error'
    return _adopt(_reg_base(hive, path, name), {
        'existed': bool(existed), 'value': _enc(value) if existed else None,
        'type': vtype,
    })


def write_registry_original(hive, path, name, existed, value, vtype=winreg.REG_DWORD,
                            create_key=True):
    """기록해 둔 원래 값으로 되돌린다(저널 밖 백업용). {'ok', 'reason', 'skipped'}"""
    status, reason = _restore_registry({
        'hive': hive, 'path': path, 'name': name, 'existed': bool(existed),
        'value': _enc(value), 'type': vtype, 'key_existed': True,
    }, create_key=create_key)
    return {'ok': status != 'failed', 'reason': reason, 'skipped': status == 'skipped'}


# ─────────────────────────────────────────────
# 서비스 시작 유형
# ─────────────────────────────────────────────

_SERVICE_RE = re.compile(r'^[A-Za-z0-9_.-]+$')
_SERVICES_KEY = r'SYSTEM\CurrentControlSet\Services'
START_TYPES = ('auto', 'delayed-auto', 'demand', 'disabled')
_START_VALUE = {'boot': 0, 'system': 1, 'auto': 2, 'delayed-auto': 2, 'demand': 3, 'disabled': 4}


def _read_service_start(service):
    """(ok, Start, DelayedAutostart 또는 None)"""
    path = f'{_SERVICES_KEY}\\{service}'
    st, start, _ = read_registry_ex('HKLM', path, 'Start')
    if st != 'present' or not isinstance(start, int):
        return False, None, None
    st2, delayed, _ = read_registry_ex('HKLM', path, 'DelayedAutostart')
    if st2 == 'error':
        return False, None, None
    return True, start, (delayed if st2 == 'present' else None)


def _start_type_name(start, delayed):
    if start == 2:
        return 'delayed-auto' if delayed else 'auto'
    return {0: 'boot', 1: 'system', 3: 'demand', 4: 'disabled'}.get(start)


def _service_matches(service, start_type):
    ok, start, delayed = _read_service_start(service)
    if not ok or start != _START_VALUE.get(start_type):
        return False
    if start_type == 'delayed-auto':
        return bool(delayed)
    if start_type == 'auto':
        return not delayed
    return True


def _sc_config(service, start_type):
    if not _SERVICE_RE.match(service) or start_type not in _START_VALUE:
        return {'rc': None, 'error': '잘못된 인자'}
    return run_system_tool([system32_path('sc.exe'), 'config', service, 'start=', start_type],
                           timeout=30)


def set_service_start(service, start_type, group, why=''):
    """서비스 시작 유형을 바꾼다. 원래 Start·DelayedAutostart 를 먼저 기록한다.

    반환: {'ok': bool, 'error': str|None, 'changed': bool}
    """
    if not isinstance(service, str) or not _SERVICE_RE.match(service):
        return {'ok': False, 'error': '서비스 이름이 올바르지 않습니다', 'changed': False}
    if start_type not in START_TYPES:
        return {'ok': False, 'error': f'알 수 없는 시작 유형입니다: {start_type}', 'changed': False}
    with _lock:
        ok, start, delayed = _read_service_start(service)
        if not ok:
            return {'ok': False, 'changed': False,
                    'error': '원래 시작 유형을 읽지 못해 바꾸지 않았습니다(서비스가 없을 수 있음)'}
        same = _service_matches(service, start_type)
        rec_ok, reason, _ = _record(f'svc:{service}'.lower(), group, {
            'kind': 'service', 'service': service, 'start': start, 'delayed': delayed, 'why': why,
        }, only_if_layered=same)
        if not rec_ok:
            return {'ok': False, 'changed': False,
                    'error': f'되돌릴 정보를 저장하지 못해 바꾸지 않았습니다 ({reason})'}
        if same:
            return {'ok': True, 'error': None, 'changed': False}

        r = _sc_config(service, start_type)
        if not _service_matches(service, start_type):
            detail = r.get('error') or (r.get('out') or r.get('err') or '').strip()[-200:]
            return {'ok': False, 'changed': False,
                    'error': f'시작 유형을 바꾸지 못했습니다 (코드 {r.get("rc")}) {detail}'.strip()}
        return {'ok': True, 'error': None, 'changed': True,
                'before': _start_type_name(start, delayed)}


# ─────────────────────────────────────────────
# TCP 수신 창 자동 튜닝
# ─────────────────────────────────────────────

AUTOTUNING_LEVELS = ('disabled', 'highlyrestricted', 'restricted', 'normal', 'experimental')


def read_tcp_autotuning():
    """현재 자동 튜닝 수준. 확실히 알 수 없으면 None.

    netsh 출력은 한글판에서 라벨이 번역돼 파싱이 깨지므로 PowerShell 의 열거값을 읽는다.
    """
    ps = system32_path(r'WindowsPowerShell\v1.0\powershell.exe')
    r = run_system_tool([ps, '-NoProfile', '-NonInteractive', '-Command',
                         '(Get-NetTCPSetting -SettingName Internet -ErrorAction Stop)'
                         '.AutoTuningLevelLocal'], timeout=30)
    if r['rc'] != 0:
        return None
    level = (r['out'] or '').strip().lower()
    return level if level in AUTOTUNING_LEVELS else None


def _set_autotuning_raw(level):
    if level not in AUTOTUNING_LEVELS:          # 명령줄에 들어가는 값은 허용 목록만
        return {'rc': None, 'error': '허용되지 않은 값'}
    return run_system_tool([system32_path('netsh.exe'), 'interface', 'tcp', 'set', 'global',
                            f'autotuninglevel={level}'], timeout=60)


def set_tcp_autotuning(level, group, why=''):
    """자동 튜닝 수준을 바꾼다. 원래 값을 확실히 읽었을 때만 바꾼다."""
    if level not in AUTOTUNING_LEVELS:
        return _fail(f'알 수 없는 자동 튜닝 수준입니다: {level}')
    with _lock:
        before = read_tcp_autotuning()
        if before is None:
            return _fail('현재 TCP 자동 튜닝 수준을 확인하지 못해 바꾸지 않았습니다')
        same = before == level
        ok, reason, _ = _record('tcp:autotuning', group, {
            'kind': 'tcp_autotuning', 'value': before, 'why': why,
        }, only_if_layered=same)
        if not ok:
            return _fail(f'되돌릴 정보를 저장하지 못해 바꾸지 않았습니다 ({reason})')
        if same:
            return {'ok': True, 'verified': True, 'before': before, 'after': before,
                    'changed': False, 'reason': '', 'error': None}
        r = _set_autotuning_raw(level)
        after = read_tcp_autotuning()
        if after != level:
            return _fail(f'적용 후 확인 실패 (명령 코드 {r.get("rc")}, 기대 {level}, '
                         f'실제 {after or "확인 불가"})')
        return {'ok': True, 'verified': True, 'before': before, 'after': after,
                'changed': True, 'reason': '', 'error': None}


def adopt_tcp_autotuning_original(level):
    if level not in AUTOTUNING_LEVELS:
        return 'error'
    return _adopt('tcp:autotuning', {'value': level})


def write_tcp_autotuning_original(level):
    status, reason = _restore_tcp({'value': level})
    return {'ok': status != 'failed', 'reason': reason, 'skipped': status == 'skipped'}


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


def _guid_str(g):
    return str(uuid.UUID(bytes_le=struct.pack('<IHH', g.Data1, g.Data2, g.Data3)
                         + bytes(g.Data4))).lower()


_GUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _is_guid(s):
    return isinstance(s, str) and bool(_GUID_RE.match(s.lower()))


def _powrprof():
    return ctypes.WinDLL('powrprof', use_last_error=True)


# 전원 설정 GUID
SUB_PROCESSOR = '54533251-82be-4824-96c1-47b60b740d00'
PROCTHROTTLEMIN = '893dee8e-2bef-41e0-89c6-b55d0929964c'
PROCTHROTTLEMAX = 'bc5038f7-23e0-4960-96da-33abaf5935ec'
CPMINCORES = '0cc5b647-c1df-4637-891a-dec35c318583'
SUB_USB = '2a737441-1930-4402-8d77-b2bebba308a3'
USB_SELECTIVE_SUSPEND = '48e6b7a6-50f5-4782-a5d4-53bb8f07e226'

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
        s = _guid_str(ptr.contents)
        ctypes.windll.kernel32.LocalFree(ptr)
        return s
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


def plan_name(guid_str):
    if not guid_str:
        return '알 수 없음'
    g = str(guid_str).lower()
    return available_plans().get(g) or KNOWN_PLANS.get(g) or g


def _activate(guid_str):
    """플랜을 켜고 다시 읽어 확인한다. (ok, reason)"""
    try:
        r = _powrprof().PowerSetActiveScheme(None, ctypes.byref(_guid(guid_str)))
    except Exception as e:
        return False, str(e)
    if r != 0:
        return False, f'PowerSetActiveScheme 오류 {r}'
    after = active_plan_guid()
    if after != guid_str:
        return False, f'전환 후 확인 실패 (기대 {guid_str}, 실제 {after})'
    return True, ''


def set_active_plan(guid_str, group, why=''):
    """전원 플랜을 바꾼다. 원래 플랜을 기록해 두고, 바꾼 뒤 확인한다."""
    target = str(guid_str or '').lower()
    with _lock:
        if target not in available_plans():
            return _fail(f'이 PC 에 없는 전원 플랜입니다 ({KNOWN_PLANS.get(target, target)})')
        before = active_plan_guid()
        if not before:
            return _fail('현재 전원 플랜을 읽지 못해 바꾸지 않았습니다')
        same = before == target
        ok, reason, _ = _record('power:active_plan', group, {
            'kind': 'power_plan', 'value': before, 'why': why,
        }, only_if_layered=same)
        if not ok:
            return _fail(f'되돌릴 정보를 저장하지 못해 바꾸지 않았습니다 ({reason})')
        if same:
            return {'ok': True, 'verified': True, 'before': before, 'after': before,
                    'changed': False, 'reason': '', 'error': None}
        ok, reason = _activate(target)
        if not ok:
            return _fail(reason)
        return {'ok': True, 'verified': True, 'before': before, 'after': target,
                'changed': True, 'reason': '', 'error': None}


def create_plan_copy(source_guid, name, group, why=''):
    """source 플랜을 복제해 이 앱 전용 플랜을 만든다. 원래 플랜은 건드리지 않는다.

    새 GUID 를 먼저 저널에 기록한 뒤 만든다. 그래야 기록 없이 남는 플랜이 생기지 않는다.
    반환: {'ok', 'plan', 'reason', 'error'}
    """
    src = str(source_guid or '').lower()
    with _lock:
        if src not in available_plans():
            r = _fail('복제할 전원 플랜을 찾지 못했습니다')
            r['plan'] = None
            return r
        new = str(uuid.uuid4())
        key = f'plan_created:{new}'
        ok, reason, _ = _record(key, group, {
            'kind': 'power_plan_created', 'plan': new, 'source': src, 'name': name,
            'why': why or f"전용 전원 플랜 '{name}'",
        })
        if not ok:
            r = _fail(f'되돌릴 정보를 저장하지 못해 만들지 않았습니다 ({reason})')
            r['plan'] = None
            return r

        p = _powrprof()
        sg, dg = _guid(src), _guid(new)
        pdg = ctypes.pointer(dg)
        own_addr = ctypes.addressof(dg)
        try:
            rc = p.PowerDuplicateScheme(None, ctypes.byref(sg), ctypes.byref(pdg))
        except Exception as e:
            rc = str(e)
        actual = new
        if rc == 0:
            actual = _guid_str(pdg.contents)
            if ctypes.cast(pdg, ctypes.c_void_p).value != own_addr:
                # 준 GUID 를 쓰지 않고 새로 할당했다. 저널을 실제 GUID 로 고친다.
                try:
                    ctypes.windll.kernel32.LocalFree(pdg)
                except Exception:
                    pass
        if rc != 0 or actual not in available_plans():
            _forget([key])          # 만들어지지 않았으니 기록도 거둔다
            r = _fail(f'전원 플랜을 복제하지 못했습니다 (오류 {rc})')
            r['plan'] = None
            return r
        if actual != new:
            fixed = _adopt(key, {'plan': actual})
            if fixed != 'amended':
                _delete_plan(actual, src)
                _forget([key])
                r = _fail('만든 전원 플랜을 기록하지 못해 지웠습니다')
                r['plan'] = None
                return r

        try:
            nbuf = ctypes.create_unicode_buffer(name)
            p.PowerWriteFriendlyName(None, ctypes.byref(_guid(actual)), None, None,
                                     nbuf, ctypes.c_ulong(ctypes.sizeof(nbuf)))
        except Exception as e:
            log.debug(f'플랜 이름 쓰기 실패: {e}')
        return {'ok': True, 'verified': True, 'plan': actual, 'reason': '', 'error': None}


def _delete_plan(plan, source=None):
    """이 앱이 만든 플랜을 지운다. 켜져 있으면 다른 플랜을 먼저 켠다. (status, reason)"""
    plans = available_plans()
    if plan not in plans:
        return 'done', ''
    if active_plan_guid() == plan:
        fallback = next((g for g in (str(source or '').lower(), PLAN_BALANCED)
                         if g and g != plan and g in plans), None)
        if not fallback:
            return 'failed', '켤 수 있는 다른 전원 플랜이 없어 전용 플랜을 지우지 못했습니다'
        ok, reason = _activate(fallback)
        if not ok:
            return 'failed', f'다른 플랜으로 바꾸지 못해 전용 플랜을 지우지 못했습니다 ({reason})'
    try:
        rc = _powrprof().PowerDeleteScheme(None, ctypes.byref(_guid(plan)))
    except Exception as e:
        rc = str(e)
    if plan in available_plans():
        return 'failed', f'전용 전원 플랜을 지우지 못했습니다 (오류 {rc})'
    return 'done', ''


def _read_power_value(plan, sub, setting, ac):
    p = _powrprof()
    val = ctypes.c_ulong()
    pg, sg, stg = _guid(plan), _guid(sub), _guid(setting)
    fn = p.PowerReadACValueIndex if ac else p.PowerReadDCValueIndex
    r = fn(None, ctypes.byref(pg), ctypes.byref(sg), ctypes.byref(stg), ctypes.byref(val))
    return (val.value if r == 0 else None)


def _write_power_value(plan, sub, setting, ac, value):
    p = _powrprof()
    pg, sg, stg = _guid(plan), _guid(sub), _guid(setting)
    fn = p.PowerWriteACValueIndex if ac else p.PowerWriteDCValueIndex
    return fn(None, ctypes.byref(pg), ctypes.byref(sg), ctypes.byref(stg), ctypes.c_ulong(value))


def set_power_value(sub, setting, value, group, plan=None, label='', both_ac_dc=True):
    """전원 플랜의 세부 설정을 바꾼다.

    plan 을 지정하지 않으면 현재 활성 플랜에 적용한다.
    both_ac_dc: False 면 전원 연결(AC) 값만 바꾸고 배터리(DC) 값은 그대로 둔다.
    """
    with _lock:
        plan = str(plan or active_plan_guid() or '').lower()
        if not plan:
            return _fail('활성 전원 플랜을 읽지 못했습니다')

        results = []
        for ac in ([True, False] if both_ac_dc else [True]):
            tag = '전원 연결' if ac else '배터리'
            before = _read_power_value(plan, sub, setting, ac)
            if before is None:
                results.append({'ac': ac, 'ok': False,
                                'reason': f'{tag} 원래 값을 읽지 못해 바꾸지 않았습니다'})
                continue
            base = f"power:{plan}:{sub}:{setting}:{'ac' if ac else 'dc'}".lower()
            same = before == value
            ok, reason, _ = _record(base, group, {
                'kind': 'power_value', 'plan': plan, 'sub': sub, 'setting': setting,
                'ac': ac, 'value': before, 'why': label,
            }, only_if_layered=same)
            if not ok:
                results.append({'ac': ac, 'ok': False,
                                'reason': f'{tag}: 되돌릴 정보를 저장하지 못해 바꾸지 않았습니다'})
                continue
            if same:
                results.append({'ac': ac, 'ok': True, 'before': before, 'after': before,
                                'changed': False, 'reason': ''})
                continue
            try:
                r = _write_power_value(plan, sub, setting, ac, value)
                if r != 0:
                    results.append({'ac': ac, 'ok': False, 'reason': f'{tag} 쓰기 오류 {r}'})
                    continue
            except Exception as e:
                results.append({'ac': ac, 'ok': False, 'reason': str(e)})
                continue
            after = _read_power_value(plan, sub, setting, ac)
            results.append({'ac': ac, 'ok': after == value, 'before': before, 'after': after,
                            'changed': True,
                            'reason': '' if after == value else f'{tag} 기대 {value}, 실제 {after}'})

        # 쓴 값은 플랜을 다시 적용해야 반영된다. 단, 지금 켜진 플랜일 때만.
        # 꺼진 플랜을 여기서 켜 버리면 사용자가 쓰던 플랜이 바뀐다.
        if any(r.get('changed') for r in results) and plan == active_plan_guid():
            try:
                _powrprof().PowerSetActiveScheme(None, ctypes.byref(_guid(plan)))
            except Exception:
                pass

        ok = bool(results) and all(r['ok'] for r in results)
        return {'ok': ok, 'verified': ok, 'detail': results,
                'reason': '' if ok else '; '.join(r['reason'] for r in results if not r['ok']),
                'error': None if ok else '; '.join(r['reason'] for r in results if not r['ok'])}


# ─────────────────────────────────────────────
# 복구
# ─────────────────────────────────────────────

# 층을 넘길 때 옮겨야 하는 '원래 상태' 필드
_STATE_FIELDS = {
    'registry': ('existed', 'value', 'type', 'key_existed'),
    'service': ('start', 'delayed', 'value'),
    'tcp_autotuning': ('value',),
    'power_value': ('value',),
    'power_plan': ('value',),
}

# 되돌리는 순서. 전원 플랜 전환은 세부값 뒤에, 전용 플랜 삭제는 원래 플랜을 켠 뒤에 한다.
_ORDER = {'registry': 0, 'service': 1, 'tcp_autotuning': 2, 'power_value': 3,
          'power_plan': 4, 'power_plan_created': 5}


def restore_group(group):
    """특정 그룹의 변경만 되돌린다(예: 이전 성능 모드)."""
    return _restore(group)


def restore_all():
    """이 앱이 바꾼 모든 시스템 설정을 원래대로 되돌린다."""
    return _restore(None)


def _restore_registry(e, create_key=True):
    hive, path, name = e.get('hive'), e.get('path'), e.get('name')
    if hive not in HIVES or not isinstance(path, str) or not path or not isinstance(name, str):
        return 'failed', '기록 형식이 올바르지 않아 건드리지 않았습니다'
    try:
        if e.get('existed'):
            vtype = e.get('type') if e.get('type') in _REG_TYPES else None
            value = _dec(e.get('value'))
            if vtype is None or not _value_fits(vtype, value):
                return 'failed', '기록 형식이 올바르지 않아 건드리지 않았습니다'
            if not create_key and not _key_exists(hive, path):
                return 'skipped', '대상 키가 더 이상 없습니다'
            with winreg.CreateKeyEx(HIVES[hive], path, 0,
                                    winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.SetValueEx(k, name, 0, vtype, value)
            st, after, _ = read_registry_ex(hive, path, name)
            if st != 'present' or after != value:
                return 'failed', f'되돌린 뒤 다시 읽으니 값이 다름 (기대 {value}, 실제 {after})'
            return 'done', ''

        # 원래 없던 값이다. 되돌린다는 건 '지운다'는 뜻이다.
        try:
            with winreg.OpenKey(HIVES[hive], path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass
        st, _, _ = read_registry_ex(hive, path, name)
        if st == 'present':
            return 'failed', '원래 없던 값을 지우지 못했습니다'
        if st == 'error':
            return 'failed', '지운 뒤 확인하지 못했습니다'
        if e.get('key_existed') is False:
            _delete_key_if_empty(hive, path)
        return 'done', ''
    except PermissionError:
        return 'failed', '권한 부족(관리자 권한으로 실행하세요)'
    except OSError as ex:
        return 'failed', str(ex)


def _restore_service(e):
    svc = e.get('service')
    if not isinstance(svc, str) or not _SERVICE_RE.match(svc):
        return 'failed', '기록 형식이 올바르지 않아 건드리지 않았습니다'
    start = e.get('start')
    if isinstance(start, int) and not isinstance(start, bool):
        target = _start_type_name(start, e.get('delayed'))
    else:
        old = e.get('value')                      # 옛 형식: 시작 유형 이름
        target = old if old in _START_VALUE else None
    if not target:
        return 'failed', '원래 시작 유형 기록이 올바르지 않습니다'
    if _service_matches(svc, target):
        return 'done', ''
    r = _sc_config(svc, target)
    if not _service_matches(svc, target):
        return 'failed', f'{svc} 시작 유형을 되돌리지 못했습니다 (코드 {r.get("rc")})'
    return 'done', ''


def _restore_tcp(e):
    level = e.get('value')
    if level not in AUTOTUNING_LEVELS:
        return 'failed', '기록된 값이 허용 목록에 없어 건드리지 않았습니다'
    if read_tcp_autotuning() == level:
        return 'done', ''
    r = _set_autotuning_raw(level)
    after = read_tcp_autotuning()
    if after == level:
        return 'done', ''
    if after is None and r.get('rc') == 0:
        return 'done', '명령은 성공했지만 결과를 다시 읽지 못했습니다'
    return 'failed', f'TCP 자동 튜닝을 되돌리지 못했습니다 (코드 {r.get("rc")}, 현재 {after})'


def _restore_power_value(e):
    plan = str(e.get('plan') or '').lower()
    sub, setting = e.get('sub'), e.get('setting')
    if not (_is_guid(plan) and _is_guid(sub) and _is_guid(setting)):
        return 'failed', '기록 형식이 올바르지 않아 건드리지 않았습니다'
    value = e.get('value')
    if value is None:
        return 'skipped', '원래 값을 읽지 못했던 항목이라 건드리지 않았습니다'
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        return 'failed', '기록 형식이 올바르지 않아 건드리지 않았습니다'
    if plan not in available_plans():
        return 'skipped', '전원 플랜이 더 이상 없습니다'
    ac = bool(e.get('ac'))
    if _read_power_value(plan, sub, setting, ac) == value:
        return 'done', ''
    r = _write_power_value(plan, sub, setting, ac, value)
    if r != 0:
        return 'failed', f'쓰기 오류 {r}'
    after = _read_power_value(plan, sub, setting, ac)
    if after != value:
        return 'failed', f'되돌린 뒤 다시 읽으니 값이 다름 (기대 {value}, 실제 {after})'
    return 'done', ''


def _restore_power_plan(e):
    target = e.get('value')
    if not target:
        return 'skipped', '원래 전원 플랜 기록이 없습니다'
    target = str(target).lower()
    if not _is_guid(target):
        return 'failed', '기록 형식이 올바르지 않아 건드리지 않았습니다'
    if target not in available_plans():
        return 'skipped', f'원래 전원 플랜({KNOWN_PLANS.get(target, target)})이 더 이상 없습니다'
    if active_plan_guid() == target:
        return 'done', ''
    ok, reason = _activate(target)
    return ('done', '') if ok else ('failed', f'원래 전원 플랜으로 돌아가지 못했습니다 ({reason})')


def _restore_one(e):
    kind = e.get('kind')
    if kind == 'registry':
        return _restore_registry(e)
    if kind == 'service':
        return _restore_service(e)
    if kind == 'tcp_autotuning':
        return _restore_tcp(e)
    if kind == 'power_value':
        return _restore_power_value(e)
    if kind == 'power_plan':
        return _restore_power_plan(e)
    if kind == 'power_plan_created':
        plan = str(e.get('plan') or '').lower()
        if not _is_guid(plan):
            return 'failed', '기록 형식이 올바르지 않아 건드리지 않았습니다'
        return _delete_plan(plan, e.get('source'))
    return 'failed', f'알 수 없는 종류: {kind}'


def _restore(group):
    with _lock:
        try:
            data = _load()
        except JournalError as ex:
            return {'ok': False, 'restored': 0, 'skipped': [], 'remaining': None,
                    'failed': [{'key': 'journal', 'what': '변경 기록', 'reason': str(ex)}]}
        entries = data['entries']

        by_base = {}
        for key, e in entries.items():
            if isinstance(e, dict):
                by_base.setdefault(_base_of(key, e), []).append(key)

        actions = []            # (key, entry, 성공하면 저널에서 지울 키들)
        released = 0            # 값은 두고 원래 값을 위 층에 넘긴 수
        for keys in by_base.values():
            layers = sorted(keys, key=lambda k: _seq(entries[k]))
            if group is None:
                # 전부 되돌릴 때는 맨 아래 층(진짜 원본)으로 바로 간다
                actions.append((layers[0], entries[layers[0]], layers))
                continue
            idx = next((i for i, k in enumerate(layers) if entries[k].get('group') == group), None)
            if idx is None:
                continue
            k = layers[idx]
            if idx == len(layers) - 1:
                actions.append((k, entries[k], [k]))
            else:
                # 위에 다른 기능의 층이 있다. 지금 값은 그 기능이 쓴 값이므로 건드리지 않는다.
                # 대신 이 층의 원래 값을 위 층에 넘겨, 그 기능을 되돌릴 때 진짜 원본으로 가게 한다.
                upper = entries[layers[idx + 1]]
                for f in _STATE_FIELDS.get(entries[k].get('kind'), ()):
                    if f in entries[k]:
                        upper[f] = entries[k][f]
                    else:
                        upper.pop(f, None)
                del entries[k]
                released += 1

        actions.sort(key=lambda a: _ORDER.get(a[1].get('kind'), 99))
        created = {str(a[1].get('plan') or '').lower() for a in actions
                   if a[1].get('kind') == 'power_plan_created'}

        done_keys, failed, skipped, deferred = [], [], [], []
        restored = released
        touched, deleted_plans = set(), set()
        for key, e, fkeys in actions:
            kind = e.get('kind')
            what = e.get('why') or key
            if kind == 'power_value' and str(e.get('plan') or '').lower() in created:
                deferred.append((fkeys, str(e.get('plan')).lower()))   # 플랜째 지워진다
                continue
            try:
                status, reason = _restore_one(e)
            except PermissionError:
                status, reason = 'failed', '권한 부족(관리자 권한으로 실행하세요)'
            except Exception as ex:
                status, reason = 'failed', str(ex)
            if status == 'failed':
                failed.append({'key': key, 'what': what, 'reason': reason})
                continue
            if status == 'skipped':
                skipped.append({'key': key, 'what': what, 'reason': reason})
            else:
                restored += 1
            done_keys.extend(fkeys)
            if kind == 'power_value':
                touched.add(str(e.get('plan') or '').lower())
            if kind == 'power_plan_created':
                deleted_plans.add(str(e.get('plan') or '').lower())

        for fkeys, plan in deferred:
            # 전용 플랜을 지우지 못했으면 기록을 남긴다(플랜 삭제 실패는 이미 보고됐다)
            if plan in deleted_plans:
                done_keys.extend(fkeys)

        # 되돌린 세부값은 그 플랜이 '지금 켜져 있을 때만' 다시 적용한다.
        # 예전에는 여기서 세부값을 되돌린 플랜을 무조건 다시 켰다. 원래 플랜으로 돌아간 직후
        # 게이밍·절전 플랜이 다시 켜져서, 되돌리기의 결과가 벗어나려던 플랜이 됐다.
        active = active_plan_guid()
        if active and active in touched:
            try:
                _powrprof().PowerSetActiveScheme(None, ctypes.byref(_guid(active)))
            except Exception:
                pass

        # 성공한 것만 저널에서 지운다. 실패한 건 남겨야 다음에 다시 시도할 수 있다.
        for k in done_keys:
            entries.pop(k, None)
        if done_keys or released:
            if not _save(data):
                failed.append({'key': 'journal', 'what': '변경 기록',
                               'reason': '되돌린 결과를 기록하지 못했습니다. 다시 시도하면 같은 값으로 다시 되돌립니다.'})

        return {'ok': not failed, 'restored': restored, 'failed': failed, 'skipped': skipped,
                'remaining': len(pending_changes())}
