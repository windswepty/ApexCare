"""APEX CARE 제거 프로그램.

관리자 권한으로 돈다(Uninstaller.spec uac_admin=True). 그래서 다음을 지킨다.
- 명령 파일(.bat)을 만들지 않는다. 삭제와 레지스트리 정리는 이 프로세스 안에서 하고,
  실행 중인 제거 프로그램 자신만 MoveFileExW(MOVEFILE_DELAY_UNTIL_REBOOT)로 재시작 때 지운다.
- 앱을 강제 종료하지 않는다. 창에 닫기를 요청하고, 안 닫히면 사용자에게 닫아 달라고 한다.
  강제로 죽이면 앱이 종료하면서 되돌리는 우선순위·게임 부스트가 그대로 남는다.
- 제거 전에 '설정을 원래대로 되돌리고 제거할까요?' 를 묻고, 앱을 --revert-all 로 실행해 되돌린다.
- 되돌리지 않은 변경 기록이 남아 있으면 %APPDATA%\\APEX_CARE_DATA 를 지우지 않는다.
  다시 설치하면 복구 센터에서 되돌릴 수 있어야 한다.
- 우리가 설치한 파일과 우리 바로 가기만 지운다. 폴더에 다른 파일이 있으면 폴더는 남긴다.
- 결과는 실제 성패대로 보여 준다.
"""

import ctypes
import json
import os
import secrets
import subprocess
import sys
import time
import winreg
from ctypes import wintypes

from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PyQt6.QtCore import Qt

APP_NAME = 'APEX CARE'
APP_EXE = 'APEX CARE.exe'
UNINSTALLER_EXE = 'APEX CARE Uninstaller.exe'
SHORTCUT_NAME = 'APEX CARE.lnk'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\APEX CARE'
STARTUP_BACKUP_KEY = r'Software\APEXCARE\DisabledStartup'
STARTUP_ORIGIN_KEY = r'Software\APEXCARE\DisabledStartup\_origin'
APEX_ROOT_KEY = r'Software\APEXCARE'
RESULT_PREFIX = '.revert-result-'

DATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
JOURNAL_PATH = os.path.join(DATA_DIR, 'system_state.json')
SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')
KNOWN_DATA_JSON = {'settings.json', 'system_state.json'}
LEGACY_BACKUP_KEYS = {
    'network_tweak_backup': '이전 버전의 네트워크 설정 백업',
    'service_start_backup': '이전 버전의 서비스 시작 유형 백업',
}

CLOSE_WAIT_SEC = 20
REVERT_WAIT_SEC = 600

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_user32 = ctypes.WinDLL('user32', use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
WM_CLOSE = 0x0010
GW_OWNER = 4

_kernel32.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD)]
_kernel32.K32EnumProcesses.restype = wintypes.BOOL
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
_kernel32.MoveFileExW.restype = wintypes.BOOL

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL


# ─────────────────────────────────────────────
# 경로
# ─────────────────────────────────────────────

def _norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _is_inside(path, root):
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip('\\') + '\\')


def program_files_dir():
    # 32비트 프로세스에서도 64비트 Program Files 를 가리킨다
    return os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles') or r'C:\Program Files'


def expected_install_dir():
    return os.path.join(program_files_dir(), APP_NAME)


# ─────────────────────────────────────────────
# 실행 중인 앱 찾기·닫기 요청
# ─────────────────────────────────────────────

def _image_path(pid):
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        _kernel32.CloseHandle(h)


def find_processes(exe_paths):
    """이미지 경로가 exe_paths 중 하나인 프로세스의 PID 목록. 이름이 아니라 전체 경로로 판정한다."""
    targets = {_norm(p) for p in exe_paths}
    names = {os.path.basename(p).lower() for p in exe_paths}
    count = 4096
    while True:
        arr = (wintypes.DWORD * count)()
        needed = wintypes.DWORD(0)
        if not _kernel32.K32EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
            return []
        if needed.value < ctypes.sizeof(arr):
            break
        count *= 2
    pids = []
    own = os.getpid()
    for i in range(needed.value // ctypes.sizeof(wintypes.DWORD)):
        pid = arr[i]
        if pid in (0, 4, own):
            continue
        img = _image_path(pid)
        if not img or os.path.basename(img).lower() not in names:
            continue
        try:
            if _norm(img) in targets:
                pids.append(pid)
        except Exception:
            continue
    return pids


def request_close(pids):
    """PID 들의 최상위 창에 WM_CLOSE 를 보낸다. 앱은 닫히면서 스스로 정리한다. 보낸 창 수를 돌려준다."""
    wanted = set(pids)
    hwnds = []

    def _cb(hwnd, _lparam):
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in wanted and _user32.IsWindowVisible(hwnd) and not _user32.GetWindow(hwnd, GW_OWNER):
            hwnds.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    for hwnd in hwnds:
        _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return len(hwnds)


def _busy_dialog(text):
    dlg = QProgressDialog(text, '', 0, 0)
    dlg.setWindowTitle(f'{APP_NAME} 제거')
    dlg.setCancelButton(None)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.show()
    return dlg


def close_running_app(app, exe_paths):
    """실행 중인 APEX CARE 를 정상 종료시킨다. 닫혔으면 True, 사용자가 취소하면 False."""
    while True:
        pids = find_processes(exe_paths)
        if not pids:
            return True
        request_close(pids)
        dlg = _busy_dialog('실행 중인 APEX CARE 를 닫는 중입니다…')
        deadline = time.monotonic() + CLOSE_WAIT_SEC
        try:
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.1)
                if not find_processes(exe_paths):
                    return True
        finally:
            dlg.close()
        box = QMessageBox(QMessageBox.Icon.Warning, f'{APP_NAME} 제거',
                          'APEX CARE 가 아직 실행 중입니다.\n\n'
                          '진행 중인 작업이 있으면 끝날 때까지 기다린 뒤 APEX CARE 창을 닫고 '
                          '[다시 시도]를 눌러 주세요.\n'
                          '다른 사용자 계정에서 실행 중이면 그 계정에서 닫아야 합니다.')
        retry = box.addButton('다시 시도', QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton('제거 취소', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(retry)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not retry:
            return False


# ─────────────────────────────────────────────
# 되돌리지 않은 변경 확인 (읽기만 한다)
# ─────────────────────────────────────────────

def _registry_value_count(hive, path):
    """키의 값 개수. 키가 없으면 0, 읽지 못하면 None."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as k:
            return winreg.QueryInfoKey(k)[1]
    except FileNotFoundError:
        return 0
    except OSError:
        return None


def read_pending_state():
    st = {
        'journal': 0, 'journal_error': None,
        'settings_error': None, 'legacy_backups': [],
        'hidden_startup': _registry_value_count(winreg.HKEY_CURRENT_USER, STARTUP_BACKUP_KEY),
        'corrupt_files': [], 'unknown_records': [],
    }
    if os.path.exists(JOURNAL_PATH):
        try:
            with open(JOURNAL_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            entries = data.get('entries') if isinstance(data, dict) else None
            if not isinstance(entries, dict):
                raise ValueError('형식이 다릅니다')
            st['journal'] = len(entries)
        except Exception as e:
            st['journal'] = None
            st['journal_error'] = str(e)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError('형식이 다릅니다')
            st['legacy_backups'] = [label for key, label in LEGACY_BACKUP_KEYS.items() if cfg.get(key)]
        except Exception as e:
            st['settings_error'] = str(e)
    try:
        for name in os.listdir(DATA_DIR):
            low = name.lower()
            if '.corrupt' in low:
                st['corrupt_files'].append(name)
            elif low.endswith('.json') and low not in KNOWN_DATA_JSON:
                st['unknown_records'].append(name)
    except OSError:
        pass
    return st


def pending_summary(st):
    lines = []
    if st['journal'] is None:
        lines.append('- 변경 기록 파일을 읽지 못했습니다.')
    elif st['journal']:
        lines.append(f"- 되돌리지 않은 설정 변경: {st['journal']}개")
    for label in st['legacy_backups']:
        lines.append(f'- {label}')
    if st['hidden_startup'] is None:
        lines.append('- 이전 버전이 꺼 둔 시작 프로그램 기록을 읽지 못했습니다.')
    elif st['hidden_startup']:
        lines.append(f"- 이전 버전이 꺼 두고 목록에서 숨긴 시작 프로그램: {st['hidden_startup']}개")
    if not lines:
        lines.append('- 기록된 설정 변경이 없습니다.')
    return '\n'.join(lines)


def data_dir_keep_reason(st):
    """설정 폴더를 남겨야 하면 그 이유, 지워도 되면 None."""
    if st['journal'] is None:
        return '변경 기록 파일을 읽지 못해'
    if st['journal']:
        return f"되돌리지 않은 설정 변경 기록 {st['journal']}개가 있어"
    if st['settings_error']:
        return '설정 파일을 읽지 못해'
    if st['legacy_backups']:
        return '이전 버전의 설정 백업이 남아 있어'
    if st['corrupt_files']:
        return '손상된 기록 파일의 사본이 있어'
    if st['unknown_records']:
        return f"다른 기록 파일({', '.join(st['unknown_records'][:3])})이 있어"
    return None


# ─────────────────────────────────────────────
# 설정 되돌리기 (앱을 --revert-all 로 실행)
# ─────────────────────────────────────────────

def run_revert(app, app_exe, install_dir):
    """앱을 창 없이 실행해 되돌린다. 결과 파일은 관리자만 쓸 수 있는 설치 폴더에 둔다."""
    result_path = os.path.join(install_dir, f'{RESULT_PREFIX}{secrets.token_hex(8)}.json')
    try:
        proc = subprocess.Popen([app_exe, '--revert-all', '--result', result_path],
                                cwd=install_dir, shell=False, close_fds=True)
    except OSError as e:
        return {'exitCode': None, 'report': None, 'launchError': str(e)}

    dlg = _busy_dialog('APEX CARE 가 바꾼 설정을 원래대로 되돌리는 중입니다…')
    deadline = time.monotonic() + REVERT_WAIT_SEC
    try:
        while proc.poll() is None:
            app.processEvents()
            time.sleep(0.05)
            if time.monotonic() > deadline:
                dlg.hide()
                answer = QMessageBox.question(
                    None, f'{APP_NAME} 제거',
                    '설정 되돌리기가 10분 넘게 끝나지 않았습니다.\n\n'
                    '계속 기다릴까요? [아니요]를 누르면 제거를 중단합니다. '
                    '되돌리기는 뒤에서 계속 진행됩니다.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
                if answer != QMessageBox.StandardButton.Yes:
                    return {'aborted': True}
                deadline = time.monotonic() + REVERT_WAIT_SEC
                dlg.show()
    finally:
        dlg.close()

    report = None
    try:
        if os.path.getsize(result_path) <= 1024 * 1024:
            with open(result_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
    except Exception:
        report = None
    try:
        os.remove(result_path)
    except OSError:
        pass
    return {'exitCode': proc.returncode, 'report': report if isinstance(report, dict) else None}


def describe_revert(res):
    """(모두 성공했는가, 사용자에게 보일 설명)."""
    if res.get('launchError'):
        return False, f"APEX CARE 를 실행하지 못해 설정을 되돌리지 못했습니다.\n({res['launchError']})"
    rep = res.get('report')
    if rep is None:
        return False, ('설정 되돌리기 결과를 읽지 못했습니다'
                       f" (종료 코드 {res.get('exitCode')}). 되돌렸는지 확인할 수 없습니다.")

    # 앱이 끝날 때 난 오류로 종료 코드가 바뀔 수 있어, 앱이 직접 적은 코드를 먼저 본다
    code = rep.get('exitCode', res.get('exitCode'))
    lines = []
    rev = rep.get('revert') or {}
    head = rev.get('message') or rep.get('message') or ''
    if head:
        lines.append(head)
    for part in rev.get('parts') or []:
        mark = '완료' if part.get('ok') else '실패'
        line = f"  {mark} · {part.get('name', '')}"
        if not part.get('ok') and part.get('detail'):
            line += f" — {part['detail']}"
        lines.append(line)

    mig = rep.get('startupMigration') or {}
    migrated = mig.get('migrated') or []
    mig_failed = mig.get('failed') or []
    if migrated:
        lines.append(f'이전 버전이 숨겨 둔 시작 프로그램 {len(migrated)}개를 작업 관리자에 다시 보이게 했습니다'
                     '(꺼진 상태는 그대로입니다).')
    if mig_failed:
        lines.append(f'시작 프로그램 {len(mig_failed)}개는 되살리지 못했습니다.')
    if not mig.get('ok') and not mig_failed and mig.get('message'):
        lines.append(mig['message'])
    if rep.get('error') == 'ALREADY_RUNNING' and rep.get('message') and rep['message'] not in lines:
        lines.append(rep['message'])

    return code == 0, '\n'.join(lines) or '설정 되돌리기 결과가 비어 있습니다.'


# ─────────────────────────────────────────────
# 제거
# ─────────────────────────────────────────────

def schedule_delete_on_reboot(path):
    return bool(_kernel32.MoveFileExW(path, None, MOVEFILE_DELAY_UNTIL_REBOOT))


def remove_file(path):
    """'removed' | 'scheduled' | 'missing' | 오류 문자열."""
    if not os.path.lexists(path):
        return 'missing'
    try:
        os.remove(path)
        return 'removed'
    except OSError as e:
        if schedule_delete_on_reboot(path):
            return 'scheduled'
        return str(e)


def shortcut_dirs():
    dirs = []
    try:
        import win32com.client
        shell = win32com.client.Dispatch('WScript.Shell')
        for name in ('AllUsersDesktop', 'AllUsersPrograms', 'Desktop', 'Programs'):
            try:
                d = shell.SpecialFolders(name)
                if d and d not in dirs:
                    dirs.append(d)
            except Exception:
                pass
        return shell, dirs
    except Exception:
        return None, dirs


def remove_shortcuts(install_dir):
    """대상이 설치 폴더 안인 'APEX CARE.lnk' 만 지운다. (지운 경로, 실패)"""
    removed, failed = [], []
    shell, dirs = shortcut_dirs()
    if shell is None:
        return removed, ['바로 가기 위치를 확인하지 못했습니다.']
    for d in dirs:
        path = os.path.join(d, SHORTCUT_NAME)
        if not os.path.isfile(path):
            continue
        try:
            target = shell.CreateShortCut(path).TargetPath
        except Exception:
            continue
        if not target or not _is_inside(target, install_dir):
            continue          # 우리 설치본을 가리키지 않는 바로 가기는 건드리지 않는다
        try:
            os.remove(path)
            removed.append(path)
        except OSError as e:
            failed.append(f'{path}: {e}')
    return removed, failed


def remove_uninstall_entries(install_dir):
    """InstallLocation 이 이 설치 폴더인 제거 정보만 지운다. (지운 수, 실패)"""
    removed, failed = 0, []
    views = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, 'HKLM'),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, 'HKLM(32비트)'),
        (winreg.HKEY_CURRENT_USER, 0, 'HKCU'),
    ]
    for hive, view, label in views:
        try:
            with winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view) as k:
                location, _ = winreg.QueryValueEx(k, 'InstallLocation')
        except FileNotFoundError:
            continue
        except OSError as e:
            failed.append(f'{label}: {e}')
            continue
        try:
            if not location or _norm(location) != _norm(install_dir):
                continue
        except Exception:
            continue
        try:
            if view:
                winreg.DeleteKeyEx(hive, UNINSTALL_KEY, view, 0)
            else:
                winreg.DeleteKey(hive, UNINSTALL_KEY)
            try:
                winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view).Close()
                failed.append(f'{label}: 지운 뒤에도 남아 있습니다.')
            except FileNotFoundError:
                removed += 1
        except OSError as e:
            failed.append(f'{label}: {e}')
    return removed, failed


def _delete_empty_key(hive, path):
    """값도 하위 키도 없을 때만 지운다."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as k:
            subkeys, values, _ = winreg.QueryInfoKey(k)
        if subkeys or values:
            return False
        winreg.DeleteKey(hive, path)
        return True
    except OSError:
        return False


def cleanup_startup_backup_key(st):
    """HKCU\\Software\\APEXCARE 는 숨긴 시작 프로그램 기록이 하나도 없을 때만 지운다."""
    if st['hidden_startup'] != 0:
        return False
    if _registry_value_count(winreg.HKEY_CURRENT_USER, STARTUP_ORIGIN_KEY):
        return False
    _delete_empty_key(winreg.HKEY_CURRENT_USER, STARTUP_ORIGIN_KEY)
    _delete_empty_key(winreg.HKEY_CURRENT_USER, STARTUP_BACKUP_KEY)
    return _delete_empty_key(winreg.HKEY_CURRENT_USER, APEX_ROOT_KEY)


class _SHFILEOPSTRUCTW(ctypes.Structure):
    # shellapi.h: 32비트에서만 1바이트 정렬
    _pack_ = 1 if ctypes.sizeof(ctypes.c_void_p) == 4 else 8
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('wFunc', wintypes.UINT),
        ('pFrom', ctypes.c_void_p),
        ('pTo', wintypes.LPCWSTR),
        ('fFlags', ctypes.c_ushort),
        ('fAnyOperationsAborted', wintypes.BOOL),
        ('hNameMappings', ctypes.c_void_p),
        ('lpszProgressTitle', wintypes.LPCWSTR),
    ]


def recycle_folder(path):
    """휴지통으로 옮긴다. 휴지통에 못 넣는 경우 Windows 가 영구 삭제 여부를 묻는다(FOF_WANTNUKEWARNING)."""
    FO_DELETE = 3
    flags = 0x0040 | 0x0010 | 0x0004 | 0x0400 | 0x4000   # ALLOWUNDO|NOCONFIRMATION|SILENT|NOERRORUI|WANTNUKEWARNING
    src = ctypes.create_unicode_buffer(path + '\0\0')    # 이중 널 종료 목록
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.addressof(src)
    op.pTo = None
    op.fFlags = flags
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc == 0 and not op.fAnyOperationsAborted and not os.path.exists(path):
        return None
    if op.fAnyOperationsAborted:
        return '영구 삭제를 취소해 남겨 두었습니다.'
    return f'일부를 옮기지 못했습니다(코드 {rc}).'


def uninstall_files(install_dir, app_exe):
    """(성공 문장들, 실패 문장들, 중단 여부)."""
    done, failed = [], []

    status = remove_file(app_exe)
    if status == 'removed':
        done.append('프로그램 파일을 지웠습니다.')
    elif status == 'scheduled':
        done.append('프로그램 파일은 사용 중이라 PC 를 다시 시작할 때 지워집니다.')
    elif status != 'missing':
        failed.append(f'프로그램 파일을 지우지 못했습니다: {status}')
        return done, failed, True

    # 되돌리기 결과 파일이 남아 있으면 정리한다(설치 폴더 안의 우리 파일)
    try:
        for name in os.listdir(install_dir):
            if name.startswith(RESULT_PREFIX) and name.endswith('.json'):
                try:
                    os.remove(os.path.join(install_dir, name))
                except OSError:
                    pass
    except OSError:
        pass

    removed, sc_failed = remove_shortcuts(install_dir)
    if removed:
        done.append(f'바로 가기 {len(removed)}개를 지웠습니다.')
    failed.extend(f'바로 가기: {x}' for x in sc_failed)

    n, reg_failed = remove_uninstall_entries(install_dir)
    if n:
        done.append("'앱 및 기능' 목록에서 지웠습니다.")
    failed.extend(f"'앱 및 기능' 항목을 지우지 못했습니다 — {x}" for x in reg_failed)

    # 실행 중인 제거 프로그램 자신은 지금 지울 수 없다. 재시작 때 지운다.
    self_path = os.path.abspath(sys.executable)
    if getattr(sys, 'frozen', False) and _is_inside(self_path, install_dir):
        if schedule_delete_on_reboot(self_path):
            done.append('제거 프로그램 파일은 PC 를 다시 시작하면 지워집니다.')
            try:
                rest = [x for x in os.listdir(install_dir)
                        if _norm(os.path.join(install_dir, x)) != _norm(self_path)]
            except OSError:
                rest = None
            if rest == []:
                schedule_delete_on_reboot(install_dir)   # 비어 있을 때만 지워진다
            elif rest:
                done.append(f"설치 폴더에 다른 파일이 있어 폴더는 남겨 두었습니다: {install_dir}")
        else:
            failed.append(f'제거 프로그램 파일을 지우도록 예약하지 못했습니다: {self_path}')
    else:
        try:
            os.rmdir(install_dir)                          # 비어 있을 때만 지워진다
        except OSError:
            pass
    return done, failed, False


# ─────────────────────────────────────────────
# 화면 흐름
# ─────────────────────────────────────────────

def _info(title, text, warn=False):
    box = QMessageBox(QMessageBox.Icon.Warning if warn else QMessageBox.Icon.Information, title, text)
    box.exec()


def ask_mode(st, can_revert):
    """'revert' | 'keep' | None(취소)."""
    title = f'{APP_NAME} 제거'
    if can_revert:
        text = ('APEX CARE 를 제거합니다.\n\n'
                '제거하기 전에 APEX CARE 가 바꾼 설정(전원 옵션·레지스트리·서비스·시작 프로그램)을 '
                '원래대로 되돌릴까요?\n\n' + pending_summary(st))
    else:
        text = ('APEX CARE 를 제거합니다.\n\n'
                '프로그램 파일(APEX CARE.exe)이 없어 설정을 되돌릴 수 없습니다.\n\n' + pending_summary(st))
    box = QMessageBox(QMessageBox.Icon.Question, title, text)
    b_revert = box.addButton('되돌리고 제거', QMessageBox.ButtonRole.AcceptRole) if can_revert else None
    b_keep = box.addButton('되돌리지 않고 제거', QMessageBox.ButtonRole.DestructiveRole)
    b_cancel = box.addButton('취소', QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(b_revert or b_cancel)
    box.setEscapeButton(b_cancel)
    box.exec()
    clicked = box.clickedButton()
    if b_revert is not None and clicked is b_revert:
        return 'revert'
    if clicked is b_keep:
        return 'keep'
    return None


def main():
    app = QApplication(sys.argv)
    title = f'{APP_NAME} 제거'

    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    expected = expected_install_dir()
    if not getattr(sys, 'frozen', False) or _norm(install_dir) != _norm(expected):
        _info('제거 오류',
              '설치된 위치에서 실행한 제거 프로그램이 아닙니다.\n'
              f'설치 위치: {expected}\n현재 위치: {install_dir}\n\n'
              "'설정 > 앱'에서 APEX CARE 를 제거해 주세요.", warn=True)
        return 1

    app_exe = os.path.join(install_dir, APP_EXE)
    st = read_pending_state()
    mode = ask_mode(st, os.path.isfile(app_exe))
    if mode is None:
        return 0

    if not close_running_app(app, [app_exe]):
        _info(title, '제거를 취소했습니다. 바뀐 것은 없습니다.')
        return 0

    report_lines = []
    if mode == 'revert':
        res = run_revert(app, app_exe, install_dir)
        if res.get('aborted'):
            _info(title, '제거를 중단했습니다. APEX CARE 는 그대로 설치되어 있습니다.')
            return 0
        ok, text = describe_revert(res)
        if not ok:
            box = QMessageBox(QMessageBox.Icon.Warning, title,
                              '설정을 모두 되돌리지는 못했습니다.\n\n' + text + '\n\n'
                              '제거를 중단하면 APEX CARE 의 복구 센터에서 다시 시도할 수 있습니다.')
            b_stop = box.addButton('제거 중단', QMessageBox.ButtonRole.RejectRole)
            b_go = box.addButton('그래도 제거', QMessageBox.ButtonRole.DestructiveRole)
            box.setDefaultButton(b_stop)
            box.setEscapeButton(b_stop)
            box.exec()
            if box.clickedButton() is not b_go:
                _info(title, '제거를 중단했습니다. APEX CARE 는 그대로 설치되어 있습니다.')
                return 0
        report_lines.append('[설정 되돌리기]\n' + text)

    done, failed, aborted = uninstall_files(install_dir, app_exe)

    # 설정 폴더와 이전 버전 기록 — 되돌리기 뒤의 실제 상태로 다시 판단한다
    st_after = read_pending_state()
    if not aborted:
        if os.path.isdir(DATA_DIR):
            reason = data_dir_keep_reason(st_after)
            if reason:
                done.append(f'{reason} 설정 폴더를 남겨 두었습니다: {DATA_DIR}\n'
                            '  APEX CARE 를 다시 설치하면 복구 센터에서 되돌릴 수 있습니다.')
            else:
                err = recycle_folder(DATA_DIR)
                if err:
                    failed.append(f'설정 폴더: {err} ({DATA_DIR})')
                else:
                    done.append('설정 폴더를 휴지통으로 옮겼습니다.')
        if st_after['hidden_startup']:
            done.append(f"이전 버전이 꺼 둔 시작 프로그램 기록 {st_after['hidden_startup']}개가 "
                        '레지스트리 HKCU\\Software\\APEXCARE 에 남아 있습니다.')
        else:
            cleanup_startup_backup_key(st_after)

    if aborted:
        head = '제거를 끝내지 못했습니다. APEX CARE 는 설치된 상태로 남아 있습니다.'
    elif failed:
        head = 'APEX CARE 를 제거했지만 일부 단계가 실패했습니다.'
    else:
        head = 'APEX CARE 를 제거했습니다.'
    body = [head]
    if report_lines:
        body.append('\n'.join(report_lines))
    if done:
        body.append('\n'.join(f'- {x}' for x in done))
    if failed:
        body.append('[실패]\n' + '\n'.join(f'- {x}' for x in failed))
    _info(title, '\n\n'.join(body), warn=bool(failed or aborted))
    return 1 if (failed or aborted) else 0


if __name__ == "__main__":
    sys.exit(main())
