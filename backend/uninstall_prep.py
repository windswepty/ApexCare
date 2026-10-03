"""
APEX CARE — 제거하기 전에 이 앱이 바꾼 것을 되돌린다.

제거 프로그램(tools/uninstall.py)이 설치 폴더를 지우기 전에 `APEX CARE.exe --revert-for-uninstall` 로 부른다.
창을 띄우지 않고 되돌리기만 한 뒤, 결과를 %APPDATA%\\APEX_CARE_DATA\\uninstall_revert.json 에 남기고
종료 코드(0 = 전부 되돌림, 1 = 실패 있음)로 알린다.

왜 필요한가:
  예전 제거 프로그램은 설치 폴더·바로가기·제거 등록만 지웠다. 성능 모드·디블로터·게임 부스트가 바꾼
  전원 설정과 레지스트리, 이 앱으로 꺼 둔 시작 프로그램이 그대로 남았고, 되돌릴 앱이 사라져 방법도 없었다.

되돌리는 것:
  1. 복구 센터의 '전부 원래대로'(perf_modes.revert_everything): system_state 저널 전부와 구버전 백업.
     이 앱으로 끈 시작 프로그램(StartupApproved 표시)도 저널에 있어 여기서 되켜진다
  2. 예전 버전이 Run 에서 지우고 HKCU\\Software\\APEXCARE 에 숨겨 둔 시작 프로그램을 원래 자리로 되살려 켠다
  3. 게임 부스트의 '게임 전 모드' 기록을 지운다. 남겨 두면 다시 설치했을 때 그 모드가 적용된다
  4. 모두 되돌렸으면 PC 쪽 기록(HKLM\\SOFTWARE\\APEX CARE)을 지운다
실패한 항목은 저널·백업에 그대로 남는다(다시 시도할 수 있게). 제거 여부는 제거 프로그램이 사용자에게 묻는다.
"""

import json
import logging
import os

log = logging.getLogger('UninstallPrep')

RESULT_NAME = 'uninstall_revert.json'
_STARTUP_BACKUP = r"Software\APEXCARE\DisabledStartup"
_STARTUP_ORIGIN = _STARTUP_BACKUP + r"\_origin"
_APEX_KEY = r"Software\APEXCARE"


def result_path():
    from backend import config_manager
    return os.path.join(config_manager.APPDATA_DIR, RESULT_NAME)


def _disabled_startup_names():
    import winreg
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_BACKUP, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    names.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    break
                i += 1
    except FileNotFoundError:
        pass
    return names


def _delete_key_if_empty(path):
    """값도 하위 키도 없을 때만 지운다. 무언가 남아 있으면 그대로 둔다."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as k:
            subkeys, values, _ = winreg.QueryInfoKey(k)
        if subkeys or values:
            return
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def _restore_disabled_startup():
    """예전 버전이 숨겨 둔 시작 프로그램을 원래 자리로 되살린다. 항목별 step 목록.

    켜고 끈 표시는 숨기기 전 상태로 돌린다. 예전 버전이 숨기기 전에 이미 작업 관리자에서 꺼 둔 항목은 꺼진 채
    되살린다. 예전에는 무조건 켜서, '전부 원래대로' 뒤에 새 변경('켜기')이 기록되고 사용자가 끈 항목이 켜졌다.
    """
    from backend import optimizer, system_state
    steps = []
    for name in _disabled_startup_names():
        r = optimizer._migrate_one_legacy(name)          # Run 에 되살리고 '꺼짐' 으로 표시(그때 원래 표시를 기록)
        ok, detail = bool(r.get('ok')), r.get('reason', '')
        if ok and not r.get('reregistered'):
            group = optimizer._startup_group(r['tag'], name)
            if any(e.get('group') == group for e in system_state.pending_changes().values()):
                back = system_state.restore_group(group)       # 숨기기 전 표시로(대개 '켜짐')
                ok = bool(back.get('ok'))
                detail = '' if ok else '; '.join(f.get('reason', '') for f in back.get('failed', []))
            else:
                detail = '숨기기 전에 작업 관리자에서 꺼 둔 항목이라 꺼진 채 되살렸습니다'
        steps.append({'name': f"시작 프로그램 '{name}' 되살리기", 'ok': ok,
                      'detail': detail if ok or detail else '실패'})
    # 이 앱이 만든 키는 비었을 때만 지운다(깊은 것부터)
    for path in (_STARTUP_ORIGIN, _STARTUP_BACKUP, _APEX_KEY):
        _delete_key_if_empty(path)
    return steps


def revert_for_uninstall():
    """제거 전 되돌리기. {'success', 'steps', 'failed', 'remaining'}"""
    from backend import config_manager, perf_modes, system_state

    steps = []
    r = perf_modes.revert_everything()
    if r.get('error') == 'UAC_REQUIRED':
        steps.append({'name': '시스템 설정 되돌리기', 'ok': False,
                      'detail': r.get('message') or '관리자 권한이 필요합니다.'})
    else:
        for p in r.get('parts', []):
            detail = p.get('detail', '')
            reasons = [f.get('reason') for f in p.get('failed') or [] if f.get('reason')]
            if reasons:
                detail = f"{detail} — {'; '.join(reasons[:5])}"
            steps.append({'name': p['name'], 'ok': bool(p['ok']), 'detail': detail})

    # 예전 버전이 숨겨 둔 시작 프로그램은 revert_everything 이 되살린다('구버전 시작 프로그램'). 관리자 권한이 없어
    # 그쪽이 돌지 않았을 때만 여기서 한다(HKCU 만 쓴다).
    if r.get('error') == 'UAC_REQUIRED':
        steps.extend(_restore_disabled_startup())

    # 앱이 비정상 종료돼 남은 프로세스 우선순위·효율 모드(게임 부스트·에코). 앱이 지워지면 되돌릴 주체가 없다.
    try:
        from backend import process_boost
        n, bad = process_boost.recover_after_crash()
        if n or bad:
            steps.append({'name': '낮춰 둔 앱의 우선순위·효율 모드 되돌리기', 'ok': not bad,
                          'detail': (f'{n}개 되돌림' if not bad else '; '.join(bad[:5]))})
    except Exception as e:
        steps.append({'name': '낮춰 둔 앱의 우선순위·효율 모드 되돌리기', 'ok': False, 'detail': str(e)})

    # 복귀할 '게임 전 모드' 는 더 없다. revert_everything 이 모드를 표준으로 기록했다.
    if config_manager.get_boost_restore_mode() is not None:
        saved = config_manager.set_boost_restore_mode(None)
        steps.append({'name': '게임 부스트 복귀 기록 지우기', 'ok': bool(saved),
                      'detail': '' if saved else '설정 파일에 저장하지 못했습니다'})

    # 다른 Windows 계정에서 끈 시작 프로그램은 그 계정의 레지스트리에 있다. 앱이 지워지면 되돌릴 주체가 없으므로
    # 그 계정의 하이브(HKU\<SID>)에서 되돌린다. 되돌리지 못한 것은 숨기지 않고 알린다.
    steps.extend(_revert_other_accounts())

    failed = [s for s in steps if not s['ok']]
    remaining = len(system_state.pending_changes())
    if not failed and remaining == 0:
        # 되돌릴 것이 하나도 없으면 PC 쪽 기록(HKLM\SOFTWARE\APEX CARE)도 지운다. 남은 것이 있으면 다시 설치했을 때
        # 이어서 되돌릴 수 있게 둔다.
        from backend import machine_store
        if not machine_store.remove():
            failed.append({'name': 'APEX CARE 기록 지우기', 'ok': False,
                           'detail': f'HKLM\\{machine_store.KEY} 를 지우지 못했습니다'})
            steps.append(failed[-1])
    return {'success': not failed, 'steps': steps, 'failed': failed, 'remaining': remaining}


def _revert_other_accounts():
    """다른 계정의 저널 파일에 남은 시작 프로그램 표시를 그 계정의 레지스트리에서 되돌린다. 계정마다 step 하나.

    그 계정이 로그인해 있으면 레지스트리가 이미 HKU\\<SID> 에 올라와 있다. 아니면 그 계정의 NTUSER.DAT 를 잠깐
    올렸다가(RegLoadKey) 되돌린 뒤 바로 내린다(RegUnLoadKey). 시작 프로그램 표시(StartupApproved) 기록만 다룬다.
    """
    from backend import system_state
    steps = []
    for sid, home, path, data in _other_account_journals():
        entries = {k: e for k, e in data['entries'].items() if system_state._trusted_user_entry(e)}
        if not entries:
            continue
        account = os.path.basename(home.rstrip('\\/'))
        name = f"다른 계정({account})에서 끈 시작 프로그램 {len(entries)}개 되돌리기"
        try:
            done, failed, why = _revert_in_hive(sid, home, entries)
        except Exception as e:                    # 무엇이 잘못됐든 숨기지 않는다
            done, failed, why = [], [], f'되돌리지 못했습니다: {e}'
        note = ''
        if done:
            rest = {k: e for k, e in data['entries'].items() if k not in done}
            if not _write_json(path, dict(data, entries=rest)):
                # 되돌리기는 끝났다. 기록이 남아도 다시 돌리면 같은 원래 값을 다시 쓸 뿐이다.
                note = ' (그 계정의 변경 기록 파일은 고치지 못했습니다)'
        reasons = [f.get('reason', '') for f in failed] + ([why] if why else [])
        if reasons:
            steps.append({'name': name, 'ok': False,
                          'detail': f"{len(done)}개 되돌림, {len(entries) - len(done)}개 실패 — " + '; '.join(reasons[:3])
                                    + ". 그 계정의 작업 관리자 → 시작 앱에서 다시 켤 수 있습니다" + note})
        else:
            steps.append({'name': name, 'ok': True, 'detail': f'{len(done)}개 되돌림' + note})
    return steps


_LOGGED_OUT_HIVE_PREFIX = 'APEXCARE_'


def _revert_in_hive(sid, home, entries):
    """(되돌린 키, 실패 목록, 하이브 문제 설명|None)"""
    import uuid
    import winreg
    from backend import system_state
    try:
        loaded = winreg.OpenKey(winreg.HKEY_USERS, sid, 0, winreg.KEY_READ | winreg.KEY_WRITE)
    except FileNotFoundError:
        loaded = None
    if loaded is not None:                       # 로그인해 있다(빠른 사용자 전환)
        with loaded:
            done, failed = system_state.restore_user_entries_under(loaded, entries)
        return done, failed, None

    ntuser = os.path.join(home, 'NTUSER.DAT')
    if not os.path.isfile(ntuser):
        return [], [], '그 계정의 레지스트리 파일(NTUSER.DAT)을 찾지 못했습니다'
    if not _enable_privileges('SeBackupPrivilege', 'SeRestorePrivilege'):
        return [], [], '다른 계정의 레지스트리를 열 권한을 얻지 못했습니다'
    temp = _LOGGED_OUT_HIVE_PREFIX + uuid.uuid4().hex[:12]
    try:
        _load_hive(temp, ntuser)
    except OSError as e:
        return [], [], f'그 계정의 레지스트리를 열지 못했습니다({e})'
    done, failed, why = [], [], None
    try:
        with winreg.OpenKey(winreg.HKEY_USERS, temp, 0, winreg.KEY_READ | winreg.KEY_WRITE) as hive:
            done, failed = system_state.restore_user_entries_under(hive, entries)
    except OSError as e:
        why = f'그 계정의 레지스트리를 쓰지 못했습니다({e})'
    finally:
        # 반드시 내린다. 올려 둔 채로 두면 그 계정이 로그인할 때 레지스트리를 쓰지 못해 임시 프로필로 열린다.
        if not _unload_hive(temp):
            why = ('그 계정의 레지스트리를 내리지 못했습니다. 재부팅하면 풀리며, 그 전에 그 계정으로 로그인하면 '
                   '임시 프로필로 열릴 수 있습니다')
    return done, failed, why


def _enable_privileges(*names):
    """이 프로세스(관리자 권한)의 토큰에 있는 권한을 켠다. 모두 켰으면 True."""
    import ctypes
    from ctypes import wintypes
    try:
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)

        class LUID(ctypes.Structure):
            _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]

        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [('Luid', LUID), ('Attributes', wintypes.DWORD)]

        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [('PrivilegeCount', wintypes.DWORD), ('Privileges', LUID_AND_ATTRIBUTES * 1)]

        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
        adv.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES),
                                              wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        token = wintypes.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token)):   # ADJUST | QUERY
            return False
        try:
            for name in names:
                tp = TOKEN_PRIVILEGES(1)
                if not adv.LookupPrivilegeValueW(None, name, ctypes.byref(tp.Privileges[0].Luid)):
                    return False
                tp.Privileges[0].Attributes = 0x2                      # SE_PRIVILEGE_ENABLED
                ctypes.set_last_error(0)
                ok = adv.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
                if not ok or ctypes.get_last_error() == 1300:          # ERROR_NOT_ALL_ASSIGNED
                    return False
            return True
        finally:
            k32.CloseHandle(token)
    except Exception as e:
        log.warning(f'권한을 켜지 못했습니다: {e}')
        return False


def _load_hive(name, ntuser_path):
    """NTUSER.DAT 를 HKU\\<name> 에 올린다. 실패하면 OSError."""
    import winreg
    winreg.LoadKey(winreg.HKEY_USERS, name, ntuser_path)


def _unload_hive(name):
    """HKU\\<name> 을 내린다. 내렸으면(또는 원래 없으면) True. 잠깐 쓰이는 중이면 몇 번 다시 시도한다."""
    import ctypes
    import time
    import winreg
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    adv.RegUnLoadKeyW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    adv.RegUnLoadKeyW.restype = ctypes.c_long
    hku = ctypes.c_int32(winreg.HKEY_USERS).value        # 미리 정의된 핸들은 부호 확장된 값이다
    for _ in range(5):
        adv.RegUnLoadKeyW(hku, name)
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_USERS, name))
        except FileNotFoundError:
            return True
        time.sleep(0.2)
    log.error(f'HKU\\{name} 을 내리지 못했습니다')
    return False


def _write_json(path, data):
    tmp = None
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix='system_state.', suffix='.tmp', dir=os.path.dirname(path))
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        tmp = None
        return True
    except OSError as e:
        log.warning(f'{path} 를 고치지 못했습니다: {e}')
        return False
    finally:
        if tmp:
            try:
                os.remove(tmp)                    # 우리가 만든 임시 파일만 지운다
            except OSError:
                pass


def _other_account_journals():
    """다른 계정의 저널 파일. [(SID, 프로필 폴더, 저널 경로, 저널 dict)]. 읽기만 한다."""
    import winreg
    from backend import system_state
    out = []
    mine = os.path.normcase(os.path.realpath(system_state.JOURNAL_PATH))
    my_sid = system_state._account_sid()
    profiles = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, profiles, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            sids, i = [], 0
            while True:
                try:
                    sids.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
            for sid in sids:
                try:
                    with winreg.OpenKey(k, sid) as pk:
                        home = winreg.ExpandEnvironmentStrings(winreg.QueryValueEx(pk, 'ProfileImagePath')[0])
                except OSError:
                    continue
                path = os.path.join(home, 'AppData', 'Roaming', 'APEX_CARE_DATA', 'system_state.json')
                if sid == my_sid or os.path.normcase(os.path.realpath(path)) == mine:
                    continue
                try:
                    with open(path, 'rb') as f:
                        data = json.loads(f.read().decode('utf-8-sig'))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict) and isinstance(data.get('entries'), dict):
                    out.append((sid, home, path, data))
    except OSError:
        pass
    return out


def _write_result(res):
    path = result_path()
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main_cli():
    """`APEX CARE.exe --revert-for-uninstall` 진입점. 종료 코드: 0 전부 되돌림, 1 실패 있음."""
    try:
        res = revert_for_uninstall()
    except Exception as e:                    # 무엇이 잘못됐는지 제거 프로그램이 보여줄 수 있게 남긴다
        log.exception('제거 전 되돌리기 실패')
        res = {'success': False, 'steps': [],
               'failed': [{'name': '제거 전 되돌리기', 'ok': False, 'detail': str(e) or type(e).__name__}],
               'remaining': None}
    try:
        _write_result(res)
    except Exception as e:
        log.error(f'결과 파일을 쓰지 못했습니다: {e}')
        return 1                              # 결과를 전하지 못하면 성공이라고 할 수 없다
    return 0 if res['success'] else 1
