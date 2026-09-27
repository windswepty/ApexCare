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

저널 위치: %APPDATA%\\APEX_CARE_DATA\\system_state.json
"""

import ctypes
import json
import logging
import os
import subprocess
import uuid
import winreg

log = logging.getLogger('SystemState')

APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
JOURNAL_PATH = os.path.join(APPDATA_DIR, 'system_state.json')

HIVES = {
    'HKLM': winreg.HKEY_LOCAL_MACHINE,
    'HKCU': winreg.HKEY_CURRENT_USER,
}


# ─────────────────────────────────────────────
# 저널 입출력
# ─────────────────────────────────────────────

def _load():
    try:
        with open(JOURNAL_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('entries'), dict):
                return data
    except FileNotFoundError:
        pass
    except Exception as e:
        # 저널이 깨졌다고 조용히 새로 만들면 기존 백업이 통째로 날아간다.
        # 깨진 파일을 옆에 남겨두고 사람이 확인할 수 있게 한다.
        log.error(f"저널을 읽지 못했습니다: {e}")
        try:
            os.replace(JOURNAL_PATH, JOURNAL_PATH + '.corrupt')
            log.error(f"깨진 저널을 {JOURNAL_PATH}.corrupt 로 옮겼습니다")
        except Exception:
            pass
    return {'version': 1, 'entries': {}}


def _save(data):
    """원자적으로 쓴다. 쓰다가 죽으면 복구 정보가 통째로 사라진다."""
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        tmp = JOURNAL_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, JOURNAL_PATH)
        return True
    except Exception as e:
        log.error(f"저널 저장 실패: {e}")
        return False


def _record(key, entry):
    """원본을 기록한다. 이미 기록돼 있으면 건드리지 않는다 — 이게 핵심이다.

    원본이 디스크에 안전하게 있으면 True, 저장에 실패했으면 False.
    False 면 호출부는 시스템을 바꾸면 안 된다. 기록 없이 바꾸면 되돌릴 방법이 없다.
    """
    data = _load()
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
    data = _load()
    for k in keys:
        data['entries'].pop(k, None)
    _save(data)


def pending_changes():
    """아직 되돌리지 않은 변경 목록. UI 가 '되돌리기' 버튼을 띄울지 판단하는 데 쓴다."""
    return _load()['entries']


def has_pending():
    return bool(_load()['entries'])


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


def set_registry(hive, path, name, value, group, vtype=winreg.REG_DWORD, why=''):
    """레지스트리 값을 바꾸고 결과를 검증한다.

    group 은 '이 변경이 어느 기능에 속하는가' 다(예: 'mode:gaming').
    나중에 그 기능만 골라 되돌릴 때 쓴다.
    """
    try:
        existed, before, before_type = read_registry_strict(hive, path, name)
    except PermissionError:
        return {'ok': False, 'verified': False,
                'reason': '원래 값을 읽을 권한이 없어 바꾸지 않았습니다(관리자 권한 필요)'}
    except OSError as e:
        return {'ok': False, 'verified': False,
                'reason': f'원래 값을 읽지 못해 바꾸지 않았습니다: {e}'}
    entry_key = f"reg:{hive}\\{path}\\{name}"

    if not _record(entry_key, {
        'kind': 'registry', 'group': group, 'hive': hive, 'path': path,
        'name': name, 'existed': existed, 'value': _enc(before),
        'type': before_type if existed else vtype, 'why': why,
    }):
        return dict(_NOT_RECORDED)

    try:
        with winreg.CreateKeyEx(HIVES[hive], path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, name, 0, vtype, value)
    except PermissionError:
        return {'ok': False, 'verified': False, 'reason': '권한 부족(관리자 권한 필요)'}
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
    if not _record(_PLAN_KEY, {
        'kind': 'power_plan', 'group': group, 'value': before, 'why': why,
    }):
        return dict(_NOT_RECORDED)
    data = _load()
    entry = data['entries'].get(_PLAN_KEY)
    if entry is not None and entry.get('group') != group:
        entry['group'] = group
        entry['why'] = why or entry.get('why', '')
        _save(data)
        entry = _load()['entries'].get(_PLAN_KEY)
    if entry is None or entry.get('group') != group:
        return {'ok': False, 'verified': False,
                'reason': '원래 전원 플랜 기록을 저장하지 못해 바꾸지 않았습니다'}

    if guid_str not in available_plans():
        return {'ok': False, 'verified': False,
                'reason': f'이 PC 에 없는 전원 플랜입니다 ({KNOWN_PLANS.get(guid_str, guid_str)})'}
    try:
        g = _guid(guid_str)
        r = _powrprof().PowerSetActiveScheme(None, ctypes.byref(g))
        if r != 0:
            return {'ok': False, 'verified': False, 'reason': f'PowerSetActiveScheme 오류 {r}'}
    except Exception as e:
        return {'ok': False, 'verified': False, 'reason': str(e)}

    after = active_plan_guid()
    if after != guid_str.lower():
        return {'ok': False, 'verified': False,
                'reason': f'전환 후 확인 실패 (기대 {guid_str}, 실제 {after})'}
    return {'ok': True, 'verified': True, 'before': before, 'after': after}


def _read_power_value(plan, sub, setting, ac):
    p = _powrprof()
    val = ctypes.c_ulong()
    pg, sg, stg = _guid(plan), _guid(sub), _guid(setting)
    fn = p.PowerReadACValueIndex if ac else p.PowerReadDCValueIndex
    r = fn(None, ctypes.byref(pg), ctypes.byref(sg), ctypes.byref(stg), ctypes.byref(val))
    return (val.value if r == 0 else None)


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
        before = _read_power_value(plan, sub, setting, ac)
        if before is None:
            # 원래 값을 모르면 되돌릴 수 없다. 모르는 채로 바꾸지 않는다.
            results.append({'ac': ac, 'ok': False,
                            'reason': '원래 값을 읽지 못해 바꾸지 않았습니다'})
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
    return {'ok': ok, 'verified': ok, 'detail': results,
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
    _record(key, {
        'kind': 'service', 'group': group, 'service': service,
        'start': start, 'delayed': delayed, 'why': why,
    })
    # _record 는 저장 실패를 알리지 않는다. 기록이 실제로 남았는지 확인한 뒤에만 바꾼다.
    if key not in _load()['entries']:
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


def _restore(predicate):
    data = _load()
    entries = data['entries']
    done, failed, plans_touched = [], [], set()

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
                if e.get('value'):
                    res = _powrprof().PowerSetActiveScheme(None, ctypes.byref(_guid(e['value'])))
                    if res != 0:
                        failed.append({'key': key, 'reason': f'플랜 복구 실패 {res}'})
                        continue
                    if active_plan_guid() != str(e['value']).lower():
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
            failed.append({'key': key, 'reason': '권한 부족(관리자 권한으로 실행하세요)'})
        except Exception as ex:
            failed.append({'key': key, 'reason': str(ex)})

    # 되돌린 세부값을 실제로 반영시킨다. 원래 플랜을 되돌린 '뒤' 이므로
    # 지금 활성 플랜만 다시 활성화한다.
    _reapply_if_active(plans_touched)

    # 성공한 것만 저널에서 지운다. 실패한 건 남겨야 다음에 다시 시도할 수 있다.
    if done:
        _forget(done)

    return {'ok': not failed, 'restored': len(done), 'failed': failed,
            'remaining': len(pending_changes())}
