"""
APEX CARE - Optimizer
정크 정리, 원클릭 최적화, 대기 메모리 해제, 하드웨어 맞춤 튜닝, 시작 프로그램.

이 모듈에서 지키는 것:
  - 임시·캐시 파일만 영구 삭제한다(CLAUDE.md 가 허용한 유일한 영구 삭제). 사용자 파일은 여기서 지우지 않는다.
  - 정리 폴더 안의 정션·심볼릭 링크는 따라가지 않는다. 지우기 직전에 실제 경로가 시작 폴더 안인지 확인한다.
  - 시스템 변경(서비스·레지스트리)은 system_state 를 거친다. 원래 값을 기록하지 못하면 바꾸지 않는다.
  - 결과는 항목별 성패로 돌려준다. 하나라도 실패하면 성공이라고 하지 않는다.
"""
import os
import time
import stat
import ctypes
import ctypes.wintypes as wintypes
import logging
import subprocess
import threading
import winreg

import psutil

from backend import safe_delete
from backend import system_repair
from backend import system_state

log = logging.getLogger('Optimizer')

CREATE_NO_WINDOW = 0x08000000

# ─────────────────────────────────────────────
# 보호 상수 (file_finder 가 PROTECTED_ROOTS·DANGER_EXTS 를 가져다 쓴다)
# ─────────────────────────────────────────────

PROTECTED_ROOTS = [
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\system32',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\syswow64',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\winsxs',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\assembly',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\servicing',
    os.environ.get('WINDIR', 'C:\\Windows').lower() + '\\installer',
    os.environ.get('PROGRAMFILES', 'C:\\Program Files').lower(),
    os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)').lower(),
    os.environ.get('APPDATA', '').lower(),
    os.environ.get('LOCALAPPDATA', '').lower() + '\\microsoft',
    # 게임 플랫폼
    'steamlibrary', 'steamapps',
    'origin games', 'riot games', 'epic games',
    'battle.net', 'ubisoft game launcher',
]

# 어떤 경우에도 지우지 않는 확장자
DANGER_EXTS = frozenset({
    '.dll', '.exe', '.sys', '.ini', '.ocx', '.drv', '.cpl',
    '.cat', '.mum', '.manifest', '.msi', '.msp', '.mst',
    '.inf', '.nls', '.tlb', '.ax', '.acm', '.scr', '.com',
})

# 임시·캐시 폴더에서 지워도 되는 확장자
SAFE_JUNK_EXTS = frozenset({
    '.tmp', '.log', '.bak', '.old', '.chk', '.pf',
    '.dmp', '.etl', '.cache',
})


def _is_protected_path(file_path):
    """보조 방어선: 보호 구역 이름이 경로에 들어 있으면 건너뛴다.

    경계 판단은 _clean_root 의 실경로 검사(safe_delete.is_inside)가 한다.
    이 함수는 '더 건너뛰는' 쪽으로만 작동하는 추가 필터다.
    """
    path_lower = file_path.lower()
    return any(pr in path_lower for pr in PROTECTED_ROOTS)


# ─────────────────────────────────────────────
# 안전한 순회와 삭제
# ─────────────────────────────────────────────

FILE_ATTRIBUTE_READONLY = 0x0001
FILE_ATTRIBUTE_SYSTEM = 0x0004
FILE_ATTRIBUTE_DIRECTORY = 0x0010
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400

DAY = 24 * 3600


def _lstat(path):
    try:
        return os.lstat(path)
    except OSError:
        return None


def _is_reparse_stat(st):
    """정션·심볼릭 링크·기타 재분석 지점인가. 확인할 수 없으면 True(따라가지 않는다)."""
    if st is None:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, 'st_file_attributes', 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def _birth_time(st):
    return getattr(st, 'st_birthtime', None) or st.st_ctime


def _env_dir(name):
    v = os.environ.get(name)
    return v if v else None


def _critical_dirs():
    """이 폴더와 같거나 이 폴더를 품은 곳은 정리 시작점이 될 수 없다."""
    out = [_env_dir(n) for n in ('SystemRoot', 'windir', 'ProgramFiles', 'ProgramFiles(x86)',
                                 'ProgramW6432', 'ProgramData', 'APPDATA', 'LOCALAPPDATA',
                                 'USERPROFILE', 'PUBLIC', 'OneDrive', 'OneDriveConsumer',
                                 'OneDriveCommercial')]
    home = _env_dir('USERPROFILE')
    if home:
        out += [os.path.join(home, d) for d in
                ('Documents', 'Desktop', 'Downloads', 'Pictures', 'Videos', 'Music',
                 'OneDrive', 'Favorites', 'Saved Games', 'Contacts', 'Links', 'Searches')]
    return [p for p in out if p]


def _forbidden_parents():
    """이 폴더 안은 정리 시작점이 될 수 없다(%TEMP% 가 잘못 설정된 경우 대비)."""
    win = _env_dir('SystemRoot') or _env_dir('windir')
    out = []
    if win:
        out += [os.path.join(win, d) for d in ('System32', 'SysWOW64', 'WinSxS', 'servicing', 'Installer')]
    out += [_env_dir(n) for n in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432',
                                  'OneDrive', 'OneDriveConsumer', 'OneDriveCommercial')]
    home = _env_dir('USERPROFILE')
    if home:
        out += [os.path.join(home, d) for d in
                ('Documents', 'Desktop', 'Downloads', 'Pictures', 'Videos', 'Music', 'OneDrive')]
    return [p for p in out if p]


def _validate_clean_root(root, kind=None):
    """정리 시작 폴더를 확인한다.

    반환: (실경로, None) — 정리해도 됨
          (None, None)   — 폴더가 없음(할 일 없음)
          (None, 이유)   — 안전하지 않아 거부
    """
    if not root or '%' in root:
        return None, None
    if not os.path.isdir(root):
        return None, None
    real = safe_delete.norm(root)
    if len(real) <= 3 or os.path.dirname(real) == real:
        return None, f'드라이브 루트는 정리하지 않습니다 ({real})'
    for c in _critical_dirs():
        if safe_delete.is_inside(c, real):
            return None, f'중요 폴더를 포함하고 있어 정리하지 않습니다 ({root})'
    for c in _forbidden_parents():
        if safe_delete.is_inside(real, c):
            return None, f'보호 폴더 안이라 정리하지 않습니다 ({root})'
    if kind == 'user_temp':
        base = os.path.basename(real).lower()
        parent = os.path.basename(os.path.dirname(real)).lower()
        # 원격 데스크톱은 Temp\2 같은 세션별 폴더를 쓴다
        if base not in ('temp', 'tmp') and not (base.isdigit() and parent in ('temp', 'tmp')):
            return None, f'TEMP 경로가 임시 폴더로 보이지 않아 정리하지 않습니다 ({root})'
    return real, None


def _safe_walk(root_real, cancel_event=None, min_dir_age=0, now=None):
    """topdown 순회. 재분석 지점과 시작 폴더 밖으로 나가는 폴더는 dirs 에서 잘라낸다.

    bottom-up os.walk 는 정션을 따라 들어가서, 정션 하나로 C:\\ 전체가 정리 대상이 될 수 있었다.
    """
    now = now or time.time()
    for cur, dirs, files in os.walk(root_real, topdown=True, followlinks=False):
        if cancel_event is not None and cancel_event.is_set():
            return
        # 가지치기 뒤에 폴더가 정션으로 바뀌었을 수도 있다. 들어온 곳을 다시 확인한다.
        if not safe_delete.is_inside(cur, root_real):
            dirs[:] = []
            continue
        keep = []
        for d in dirs:
            st = _lstat(os.path.join(cur, d))
            if _is_reparse_stat(st):
                continue
            # 방금 만들어진 폴더는 설치 프로그램이 쓰는 중일 수 있다. 통째로 건너뛴다.
            if min_dir_age and now - _birth_time(st) < min_dir_age:
                continue
            keep.append(d)
        dirs[:] = keep
        yield cur, files


def _file_eligible(path, name, st, policy, now):
    """이 파일이 정책상 지울 수 있는 것인가. (가능 여부, 이유)"""
    if st is None:
        return False, 'stat'
    if _is_reparse_stat(st):
        return False, 'reparse'
    attrs = getattr(st, 'st_file_attributes', 0)
    if attrs & FILE_ATTRIBUTE_DIRECTORY:
        return False, 'dir'
    # 읽기 전용·시스템 파일은 지우지 않는다. 예전에는 chmod 로 풀고 지웠다.
    if attrs & (FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_SYSTEM):
        return False, 'attr'
    ext = os.path.splitext(name)[1].lower()
    if ext in DANGER_EXTS:
        return False, 'ext'
    if ext == '':
        # 확장자 없는 파일은 브라우저 캐시 폴더에서만 지운다
        if not policy.get('allow_no_ext'):
            return False, 'ext'
    elif ext not in SAFE_JUNK_EXTS:
        return False, 'ext'
    min_age = policy.get('min_age', 0)
    if min_age:
        newest = max(st.st_mtime, _birth_time(st))
        if now - newest < min_age:
            return False, 'recent'
    if _is_protected_path(path):
        return False, 'protected'
    return True, ''


# ── 핸들 기준 삭제 ─────────────────────────────
# 경로 문자열로 확인하고 os.remove 하면, 확인과 삭제 사이에 상위 폴더가 정션으로
# 바뀌는 경쟁을 막을 수 없다. 파일을 먼저 열고, 연 대상의 실제 경로·속성을 확인한 뒤
# 그 핸들로 지운다. 공유 모드 0 으로 열기 때문에 다른 프로그램이 쓰고 있는 파일은 열리지 않고 건너뛴다.

DELETE = 0x00010000
FILE_READ_ATTRIBUTES = 0x0080
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_DISPOSITION_INFO_CLASS = 4          # FileDispositionInfo
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _BHFI(ctypes.Structure):
    _fields_ = [('dwFileAttributes', wintypes.DWORD),
                ('ftCreationTime', wintypes.FILETIME),
                ('ftLastAccessTime', wintypes.FILETIME),
                ('ftLastWriteTime', wintypes.FILETIME),
                ('dwVolumeSerialNumber', wintypes.DWORD),
                ('nFileSizeHigh', wintypes.DWORD),
                ('nFileSizeLow', wintypes.DWORD),
                ('nNumberOfLinks', wintypes.DWORD),
                ('nFileIndexHigh', wintypes.DWORD),
                ('nFileIndexLow', wintypes.DWORD)]


_K32 = None


def _k32():
    """전용 kernel32 인스턴스. 전역 ctypes.windll.kernel32 의 argtypes 를 건드리지 않는다."""
    global _K32
    if _K32 is None:
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        k.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BHFI)]
        k.GetFileInformationByHandle.restype = wintypes.BOOL
        k.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        k.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        k.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.SetFileInformationByHandle.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        _K32 = k
    return _K32


def _ft_to_unix(ft):
    v = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return v / 1e7 - 11644473600.0


def _win_path(path):
    p = os.path.abspath(path)
    if len(p) >= 248 and not p.startswith('\\\\?\\'):
        p = '\\\\?\\UNC\\' + p[2:] if p.startswith('\\\\') else '\\\\?\\' + p
    return p


def _final_path(h):
    k = _k32()
    size = 1024
    for _ in range(2):
        buf = ctypes.create_unicode_buffer(size)
        n = k.GetFinalPathNameByHandleW(h, buf, size, 0)
        if n == 0:
            return None
        if n < size:
            p = buf.value
            if p.startswith('\\\\?\\UNC\\'):
                p = '\\\\' + p[8:]
            elif p.startswith('\\\\?\\'):
                p = p[4:]
            return os.path.normcase(p)
        size = n + 1
    return None


def _within(real_path, root_real):
    return real_path == root_real or real_path.startswith(root_real + os.sep)


def _err_reason(err):
    return {2: 'gone', 3: 'gone', 5: 'denied', 32: 'locked', 33: 'locked', 1920: 'denied'}.get(err, f'error {err}')


def _dispose(h):
    """열린 핸들에 삭제 표시를 한다. 핸들을 닫으면 지워진다. (성공 여부, 오류 코드)"""
    flag = ctypes.c_ubyte(1)                 # FILE_DISPOSITION_INFO.DeleteFile = TRUE
    ok = _k32().SetFileInformationByHandle(h, FILE_DISPOSITION_INFO_CLASS, ctypes.byref(flag), 1)
    return bool(ok), (0 if ok else ctypes.get_last_error())


def _open_for_delete(path):
    """(핸들, 오류코드). 공유 모드 0 — 누가 열고 있으면 실패한다."""
    k = _k32()
    h = k.CreateFileW(_win_path(path), DELETE | FILE_READ_ATTRIBUTES, 0, None,
                      OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, None)
    if h is None or h == _INVALID_HANDLE:
        return None, ctypes.get_last_error()
    return h, 0


def _delete_file_checked(path, root_real, min_age=0, now=None):
    """연 파일을 확인하고 지운다. 반환 {'ok', 'size', 'reason'}"""
    now = now or time.time()
    h, err = _open_for_delete(path)
    if h is None:
        return {'ok': False, 'size': 0, 'reason': _err_reason(err)}
    k = _k32()
    try:
        info = _BHFI()
        if not k.GetFileInformationByHandle(h, ctypes.byref(info)):
            return {'ok': False, 'size': 0, 'reason': 'info'}
        size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
        attrs = info.dwFileAttributes
        if attrs & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT):
            return {'ok': False, 'size': size, 'reason': 'reparse'}
        if attrs & (FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_SYSTEM):
            return {'ok': False, 'size': size, 'reason': 'attr'}
        if info.nNumberOfLinks != 1:
            # 하드 링크는 다른 이름이 가리키는 원본일 수 있다
            return {'ok': False, 'size': size, 'reason': 'hardlink'}
        if min_age:
            newest = max(_ft_to_unix(info.ftCreationTime), _ft_to_unix(info.ftLastWriteTime))
            if now - newest < min_age:
                return {'ok': False, 'size': size, 'reason': 'recent'}
        final = _final_path(h)
        if not final or not _within(final, root_real):
            return {'ok': False, 'size': size, 'reason': 'outside'}
        ok, derr = _dispose(h)
        if not ok:
            return {'ok': False, 'size': size, 'reason': _err_reason(derr)}
        return {'ok': True, 'size': size, 'reason': ''}
    finally:
        k.CloseHandle(h)


# ─────────────────────────────────────────────
# 정크 항목 정의
# ─────────────────────────────────────────────

RECYCLE_BIN_ID = 5
ALL_JUNK_IDS = (1, 2, 3, 4, 5)
ONE_CLICK_JUNK_IDS = (1, 2)      # 원클릭은 업데이트 캐시·Prefetch·휴지통을 절대 포함하지 않는다


def _process_running(names):
    """이름이 같은 프로세스가 도는가. 확인할 수 없으면 None."""
    try:
        for p in psutil.process_iter(['name']):
            if (p.info.get('name') or '').lower() in names:
                return True
        return False
    except Exception:
        return None


def _service_status(name):
    """'running'·'stopped' 등. 서비스가 없으면 'missing', 확인할 수 없으면 None."""
    try:
        return psutil.win_service_get(name).status()
    except psutil.NoSuchProcess:
        return 'missing'
    except Exception:
        return None


def _windows_update_busy():
    """업데이트 캐시를 지우면 안 되는 이유. 지워도 되면 None."""
    for path, label in (
        (r'SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired',
         '업데이트 설치를 마치려면 재부팅이 필요한 상태입니다'),
        (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',
         '업데이트가 재부팅을 기다리고 있습니다'),
    ):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                           winreg.KEY_READ | winreg.KEY_WOW64_64KEY))
            return label
        except FileNotFoundError:
            pass
        except OSError:
            return '업데이트 상태를 확인하지 못했습니다'
    for svc, label in (('wuauserv', 'Windows Update 서비스'),
                       ('BITS', '백그라운드 전송(BITS) 서비스'),
                       ('TrustedInstaller', 'Windows 모듈 설치 관리자')):
        s = _service_status(svc)
        if s is None:
            return f'{label} 상태를 확인하지 못했습니다'
        if s not in ('stopped', 'missing'):
            return f'{label}가 실행 중입니다'
    return None


def _chrome_busy():
    r = _process_running({'chrome.exe'})
    if r is None:
        return 'Chrome 실행 여부를 확인하지 못했습니다'
    return 'Chrome 이 실행 중입니다' if r else None


def _junk_specs():
    """정리 항목. roots 는 (경로, 종류). 정책은 항목마다 다르다."""
    sysroot = os.environ.get('SystemRoot') or os.environ.get('windir') or ''
    local = os.environ.get('LOCALAPPDATA') or ''
    temp = os.environ.get('TEMP') or os.environ.get('TMP') or ''
    j = os.path.join
    return {
        1: {'name': '임시 파일 (%TEMP%, Windows\\Temp)',
            'roots': [(temp, 'user_temp'), (j(sysroot, 'Temp') if sysroot else '', None)],
            'policy': {'min_age': DAY, 'allow_no_ext': False},
            'precheck': None},
        2: {'name': 'Chrome 브라우저 캐시',
            'roots': [(j(local, 'Google', 'Chrome', 'User Data', 'Default', 'Cache') if local else '', None)],
            'policy': {'min_age': 0, 'allow_no_ext': True},
            'precheck': _chrome_busy},
        3: {'name': 'Windows Update 다운로드 캐시',
            'roots': [(j(sysroot, 'SoftwareDistribution', 'Download') if sysroot else '', None)],
            'policy': {'min_age': DAY, 'allow_no_ext': False},
            'precheck': _windows_update_busy},
        4: {'name': 'Prefetch 데이터',
            'roots': [(j(sysroot, 'Prefetch') if sysroot else '', None)],
            'policy': {'min_age': DAY, 'allow_no_ext': False},
            'precheck': None},
    }


def _normalize_ids(ids):
    out = []
    try:
        for x in (ids or []):
            try:
                v = int(x)
            except (TypeError, ValueError):
                continue
            if v in ALL_JUNK_IDS and v not in out:
                out.append(v)
    except TypeError:
        return []
    return out


def _measure_root(root, kind, policy, state_obj=None, cancel_event=None):
    """실제로 지울 수 있는 파일만 센다. (바이트, 파일 수, 거부 이유)"""
    real, refused = _validate_clean_root(root, kind)
    if not real:
        return 0, 0, refused
    now = time.time()
    total = count = 0
    for cur, files in _safe_walk(real, cancel_event, policy.get('min_age', 0), now):
        for name in files:
            fp = os.path.join(cur, name)
            ok, _ = _file_eligible(fp, name, _lstat(fp), policy, now)
            if ok:
                try:
                    total += os.lstat(fp).st_size
                    count += 1
                except OSError:
                    pass
        if state_obj is not None and count and count % 200 == 0:
            state_obj['progress'] = min(95, state_obj.get('progress', 0) + 1)
    return total, count, None


def _get_dir_size_mb(dir_path, state_obj=None, max_files=10000, policy=None):
    """(구 이름 유지) 정리 정책으로 지울 수 있는 파일의 크기(MB)."""
    b, _, _ = _measure_root(dir_path, None, policy or {'min_age': DAY, 'allow_no_ext': False}, state_obj)
    return round(b / (1024 * 1024), 2)


# ─────────────────────────────────────────────
# 휴지통
# ─────────────────────────────────────────────

class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_int64),
                ("i64NumItems", ctypes.c_int64)]


_SH32 = None


def _sh32():
    global _SH32
    if _SH32 is None:
        s = ctypes.WinDLL('shell32', use_last_error=True)
        s.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_SHQUERYRBINFO)]
        s.SHQueryRecycleBinW.restype = ctypes.c_long
        s.SHEmptyRecycleBinW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
        s.SHEmptyRecycleBinW.restype = ctypes.c_long
        _SH32 = s
    return _SH32


def _query_recycle_bin():
    """(바이트, 항목 수). 읽지 못하면 None."""
    try:
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        if _sh32().SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return int(info.i64Size), int(info.i64NumItems)
    except Exception as e:
        log.debug(f"휴지통 조회 실패: {e}")
    return None


def _empty_recycle_bin():
    """휴지통을 비우고 결과를 되읽어 확인한다. 사용자가 직접 고르고 확인했을 때만 불린다."""
    before = _query_recycle_bin()
    if before is not None and before[1] == 0:
        return {'ok': True, 'freed_bytes': 0, 'message': '휴지통이 이미 비어 있습니다.'}
    try:
        # 1 NOCONFIRMATION | 2 NOPROGRESSUI | 4 NOSOUND — 확인은 UI 에서 이미 받았다
        hr = _sh32().SHEmptyRecycleBinW(None, None, 7) & 0xFFFFFFFF
    except Exception as e:
        return {'ok': False, 'freed_bytes': 0, 'message': f'휴지통 비우기 실패: {e}'}
    after = _query_recycle_bin()
    if after is not None:
        ok = after[1] == 0
    else:
        ok = hr == 0
    freed = max(0, before[0] - after[0]) if (before and after) else 0
    if ok:
        return {'ok': True, 'freed_bytes': freed, 'message': '휴지통을 비웠습니다.'}
    left = f' (남은 항목 {after[1]}개)' if after else ''
    return {'ok': False, 'freed_bytes': freed,
            'message': f'휴지통을 다 비우지 못했습니다{left}. 오류 0x{hr:08X}'}


# ─────────────────────────────────────────────
# 정크 스캔
# ─────────────────────────────────────────────

_scan_lock = threading.Lock()
_junk_scan_state = {"status": "idle", "data": [], "progress": 0, "eta_seconds": 0}
_junk_scan_thread = None


def get_junk_scan_status():
    return _junk_scan_state


def scan_junk_background():
    """정리 대상 크기를 잰다. 읽기만 한다. 크기는 실제로 지울 수 있는 파일만 센다."""
    st = _junk_scan_state
    st.update({"status": "running", "progress": 0, "eta_seconds": 0})
    try:
        specs = _junk_specs()
        sizes, notes = {}, {}
        for i, (cid, spec) in enumerate(specs.items()):
            total, refused = 0, []
            for root, kind in spec['roots']:
                b, _, why = _measure_root(root, kind, spec['policy'], st)
                total += b
                if why:
                    refused.append(why)
            sizes[cid] = round(total / (1024 * 1024), 2)
            reason = spec['precheck']() if spec['precheck'] else None
            notes[cid] = reason or ('; '.join(refused) if refused else None)
            st['progress'] = int((i + 1) * 90 / len(specs))

        rb = _query_recycle_bin()
        recycle_mb = round(rb[0] / (1024 * 1024), 2) if rb else 0.0

        def item(cid, selected, desc, **extra):
            d = {"id": cid, "name": specs[cid]['name'], "sizeMB": sizes[cid], "category": "System",
                 "selected": selected, "description": desc, "blocked": notes.get(cid)}
            d.update(extra)
            return d

        st["data"] = [
            item(1, True, "24시간 넘게 지난 .tmp·.log 같은 임시 파일만 지웁니다. 사용 중인 파일은 건너뜁니다."),
            item(2, True, "Chrome 이 저장한 이미지·스크립트 캐시입니다. Chrome 이 실행 중이면 건너뜁니다.",
                 category="Browser"),
            # 기본 해제. 설치를 기다리는 업데이트 파일이 섞여 있을 수 있다.
            item(3, False, "업데이트 대기 중이거나 Windows Update 가 동작 중이면 건너뜁니다."),
            item(4, False, "프로그램 실행 기록 캐시입니다. 지우면 Windows 가 다시 만듭니다."),
            # 기본 해제. 이 목록에서 유일하게 되돌릴 수 없는 항목이다.
            {"id": RECYCLE_BIN_ID, "name": "휴지통 비우기", "sizeMB": recycle_mb, "category": "System",
             "selected": False, "irreversible": True, "blocked": None,
             "description": "휴지통 안의 파일을 완전히 삭제합니다. 되돌릴 수 없습니다."},
        ]
        st.update({"progress": 100, "eta_seconds": 0, "status": "success"})
    except Exception as e:
        log.exception("정크 스캔 실패")
        st["data"] = [{"id": 999, "name": f"검사 오류: {e}", "sizeMB": 0, "category": "Error",
                       "selected": False, "description": ""}]
        st["status"] = "error"


def scan_junk():
    global _junk_scan_thread
    with _scan_lock:
        if _junk_scan_state["status"] == "running":
            return {"success": False, "message": "이미 검사 중입니다."}
        _junk_scan_state["status"] = "running"
    _junk_scan_thread = threading.Thread(target=scan_junk_background, daemon=True)
    _junk_scan_thread.start()
    return {"success": True}


# ─────────────────────────────────────────────
# 정크 정리
# ─────────────────────────────────────────────

# 정리 실행 전체를 감싸는 잠금. 저장공간 탭 정리와 원클릭이 같은 폴더를 동시에 지우지 않게 한다.
_junk_run_lock = threading.Lock()
_junk_cancel_event = threading.Event()
_active_junk_cancel = None

_junk_clean_state = {"status": "idle", "freed_mb": 0.0, "skipped_mb": 0.0, "error": None,
                     "progress": 0, "eta_seconds": 0, "details": {}, "categories": [],
                     "deleted_count": 0, "skipped_count": 0, "skipped_log": None,
                     "recycle_bin": None, "message": ""}
_junk_clean_thread = None

SKIP_LOG_MAX_BYTES = 512 * 1024
SKIP_LOG_MAX_LINES = 300


def get_junk_clean_status():
    return _junk_clean_state


def _skip_log_dir():
    base = os.environ.get('APPDATA')
    return os.path.join(base, 'APEX_CARE_DATA', 'logs') if base else None


def _write_skip_log(skipped):
    """건너뛴 파일 목록을 앱 데이터 폴더에 남긴다. 기록한 경로를 돌려준다(실패하면 None)."""
    d = _skip_log_dir()
    if not d or not skipped:
        return None
    try:
        from datetime import datetime
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, 'junk_skipped.log')
        mode = 'a'
        try:
            if os.path.getsize(path) > SKIP_LOG_MAX_BYTES:
                mode = 'w'                    # 크기 제한: 넘으면 새로 쓴다
        except OSError:
            pass
        rows = sorted(skipped, key=lambda x: x[1], reverse=True)
        with open(path, mode, encoding='utf-8') as f:
            f.write(f"\n=== 건너뛴 파일 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"{len(rows)}개 ===\n")
            for p, size, why in rows[:SKIP_LOG_MAX_LINES]:
                f.write(f"[{size / (1024 * 1024):.2f} MB] ({why}) {p}\n")
            if len(rows) > SKIP_LOG_MAX_LINES:
                f.write(f"... 외 {len(rows) - SKIP_LOG_MAX_LINES}개\n")
        return path
    except Exception as e:
        log.debug(f"건너뛴 파일 로그 기록 실패: {e}")
        return None


_SKIP_LABEL = {'locked': '사용 중', 'denied': '권한 없음', 'outside': '정리 폴더 밖',
               'hardlink': '하드 링크', 'reparse': '링크', 'attr': '읽기 전용',
               'recent': '최근 파일', 'info': '정보 읽기 실패'}


class _Tally:
    def __init__(self):
        self.freed = 0
        self.deleted = 0
        self.attempted = 0
        self.skipped_bytes = 0
        self.skipped = []           # (경로, 크기, 이유)
        self.by_drive = {}

    def ok(self, path, size):
        self.freed += size
        self.deleted += 1
        drv = os.path.splitdrive(path)[0].upper() or '?'
        self.by_drive[drv] = self.by_drive.get(drv, 0) + size

    def skip(self, path, size, reason):
        self.skipped_bytes += size
        self.skipped.append((path, size, _SKIP_LABEL.get(reason, reason)))


def _clean_root(root, kind, policy, cancel_event, tally, on_file=None):
    """한 폴더를 정리한다. 반환 {'refused': 이유|None, 'deleted', 'freed', 'attempted'}"""
    real, refused = _validate_clean_root(root, kind)
    if not real:
        if refused:
            log.warning(f"정리 거부: {refused}")
        return {'refused': refused, 'deleted': 0, 'freed': 0, 'attempted': 0}
    now = time.time()
    d0, f0, a0 = tally.deleted, tally.freed, tally.attempted
    min_age = policy.get('min_age', 0)
    for cur, files in _safe_walk(real, cancel_event, min_age, now):
        for name in files:
            if cancel_event is not None and cancel_event.is_set():
                break
            fp = os.path.join(cur, name)
            st = _lstat(fp)
            ok, _ = _file_eligible(fp, name, st, policy, now)
            if not ok:
                continue
            tally.attempted += 1
            # 삭제 직전: 실경로가 시작 폴더 안인가
            if not safe_delete.is_inside(fp, real):
                tally.skip(fp, st.st_size, 'outside')
                continue
            r = _delete_file_checked(fp, real, min_age, now)
            if r['ok']:
                tally.ok(fp, r['size'])
            elif r['reason'] == 'gone':
                tally.attempted -= 1
            else:
                tally.skip(fp, r['size'] or st.st_size, r['reason'])
            if on_file:
                on_file()
    return {'refused': None, 'deleted': tally.deleted - d0, 'freed': tally.freed - f0,
            'attempted': tally.attempted - a0}


def _mb(b):
    return round(b / (1024 * 1024), 2)


def _clean_worker(ids, cancel_event):
    """정리 본체. 잠금은 호출부가 잡는다. 결과 dict 를 돌려준다."""
    global _active_junk_cancel
    _active_junk_cancel = cancel_event
    st = _junk_clean_state
    st.update({"status": "running", "freed_mb": 0.0, "skipped_mb": 0.0, "error": None,
               "progress": 0, "eta_seconds": 0, "details": {}, "categories": [],
               "deleted_count": 0, "skipped_count": 0, "skipped_log": None,
               "recycle_bin": None, "message": ""})
    tally = _Tally()
    cats = []
    recycle = None

    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    try:
        specs = _junk_specs()
        n = max(1, len(ids))
        for i, cid in enumerate(ids):
            base_prog = int(i * 95 / n)
            st['progress'] = base_prog
            if cancelled():
                cats.append({'id': cid, 'name': specs.get(cid, {}).get('name', '휴지통 비우기'),
                             'state': 'cancelled', 'reason': '중단됨'})
                continue

            if cid == RECYCLE_BIN_ID:
                recycle = _empty_recycle_bin()
                tally.freed += recycle['freed_bytes']
                cats.append({'id': cid, 'name': '휴지통 비우기',
                             'state': 'done' if recycle['ok'] else 'failed',
                             'freed_mb': _mb(recycle['freed_bytes']), 'reason': recycle['message']})
                continue

            spec = specs[cid]
            blocked = spec['precheck']() if spec['precheck'] else None
            if blocked:
                cats.append({'id': cid, 'name': spec['name'], 'state': 'skipped', 'reason': blocked})
                continue

            counter = {'n': 0}

            def tick(_c=counter, _b=base_prog):
                _c['n'] += 1
                if _c['n'] % 50 == 0:
                    st['progress'] = min(_b + int(95 / n) - 1, _b + _c['n'] // 50)

            res = {'deleted': 0, 'freed': 0, 'attempted': 0}
            refused = []
            for root, kind in spec['roots']:
                if cancelled():
                    break
                r = _clean_root(root, kind, spec['policy'], cancel_event, tally, tick)
                if r['refused']:
                    refused.append(r['refused'])
                for k in res:
                    res[k] += r[k]
            if refused:
                state, reason = 'failed', '; '.join(refused)
            elif cancelled():
                state, reason = 'cancelled', '중단됨'
            elif res['attempted'] and not res['deleted']:
                state, reason = 'failed', '지울 수 있는 파일을 하나도 지우지 못했습니다(사용 중이거나 권한 없음)'
            else:
                state, reason = 'done', ''
            cats.append({'id': cid, 'name': spec['name'], 'state': state, 'reason': reason,
                         'freed_mb': _mb(res['freed']), 'deleted': res['deleted'],
                         'skipped': res['attempted'] - res['deleted']})

        log_path = _write_skip_log(tally.skipped)
        if cancelled():
            status = 'cancelled'
        elif any(c['state'] in ('failed', 'skipped') for c in cats):
            status = 'partial'
        else:
            status = 'success'

        parts = [f"{_mb(tally.freed)}MB 정리"]
        if tally.skipped:
            parts.append(f"{len(tally.skipped)}개 파일 건너뜀")
        for c in cats:
            if c['state'] in ('failed', 'skipped'):
                parts.append(f"{c['name']}: {c['reason']}")
        if status == 'cancelled':
            parts.insert(0, '중단됨 — 이미 지운 파일은 되돌릴 수 없습니다')

        st.update({
            "status": status,
            "freed_mb": _mb(tally.freed),
            "skipped_mb": _mb(tally.skipped_bytes),
            "details": {k: _mb(v) for k, v in tally.by_drive.items() if v},
            "categories": cats,
            "deleted_count": tally.deleted,
            "attempted_count": tally.attempted,
            "skipped_count": len(tally.skipped),
            "skipped_log": log_path,
            "recycle_bin": recycle,
            "message": ' · '.join(parts),
            "progress": 100 if status != 'cancelled' else st.get('progress', 0),
            "eta_seconds": 0,
        })
        log.info(f"[JunkPurger] {st['message']}")
    except Exception as e:
        log.exception("정크 정리 실패")
        st.update({"status": "error", "error": str(e), "categories": cats,
                   "freed_mb": _mb(tally.freed), "deleted_count": tally.deleted,
                   "message": f"정리 중 오류: {e}"})
    finally:
        _active_junk_cancel = None
    return dict(st)


def clean_junk_sync(ids, cancel_event=None):
    """정리 잠금을 지키는 동기 실행(C14). 이미 정리 중이면 status 'busy'."""
    ids = _normalize_ids(ids)
    if not ids:
        return {"status": "success", "success": True, "freed_mb": 0.0, "categories": [],
                "message": "선택한 항목이 없습니다."}
    if not _junk_run_lock.acquire(blocking=False):
        return {"status": "busy", "success": False, "freed_mb": 0.0, "categories": [],
                "message": "다른 정리 작업이 진행 중입니다."}
    try:
        res = _clean_worker(ids, cancel_event)
    finally:
        _junk_run_lock.release()
    res['success'] = res.get('status') == 'success'
    return res


def clean_junk_background(category_ids, cancel_event=None):
    """구 진입점. 이제 잠금을 지키는 동기 실행이다(clean_junk_sync 와 같다)."""
    return clean_junk_sync(category_ids, cancel_event=cancel_event)


def clean_junk(category_ids, cancel_event=None):
    """저장공간 탭의 비동기 정리. 진행 상태는 get_junk_clean_status 로 본다."""
    global _junk_clean_thread
    ids = _normalize_ids(category_ids)
    if not ids:
        return {"success": True, "message": "선택한 항목이 없습니다."}
    if not _junk_run_lock.acquire(blocking=False):
        return {"success": False, "message": "이미 정리 중입니다."}
    try:
        _junk_cancel_event.clear()
        _junk_clean_state["status"] = "running"

        def runner():
            try:
                _clean_worker(ids, _junk_cancel_event)
            finally:
                _junk_run_lock.release()

        _junk_clean_thread = threading.Thread(target=runner, daemon=True)
        _junk_clean_thread.start()
    except Exception as e:
        _junk_run_lock.release()
        _junk_clean_state["status"] = "error"
        return {"success": False, "message": f"정리를 시작하지 못했습니다: {e}"}
    return {"success": True}


def cancel_junk_clean():
    """진행 중인 정리를 멈춘다. 이미 지운 파일은 되돌아오지 않는다."""
    ev = _active_junk_cancel
    if _junk_clean_state.get("status") == "running" and ev is not None:
        ev.set()
        return {"success": True, "message": "정리를 중단합니다. 이미 지운 파일은 되돌릴 수 없습니다."}
    return {"success": False, "message": "실행 중인 정리 작업이 없습니다."}


# ─────────────────────────────────────────────
# 원클릭 최적화
# ─────────────────────────────────────────────

_deep_lock = threading.Lock()
_cancel_event = threading.Event()

_optimization_state = {
    "running": False, "progress_pct": 0, "eta_seconds": 0, "current_task": "",
    "freed_mb": 0, "error": None, "cancel_requested": False, "cancelled": False,
    "steps": [], "failedCount": 0, "notes": [],
}


def get_deep_optimization_plan():
    """원클릭이 실제로 할 일. 대시보드가 실행 전에 이 목록을 보여 주고 확인을 받는다."""
    return {
        "steps": [
            {"id": "junk", "name": "임시 파일·브라우저 캐시 정리",
             "detail": "%TEMP%·Windows\\Temp 의 24시간 넘은 임시 파일과 Chrome 캐시를 지웁니다. "
                       "휴지통을 거치지 않아 되돌릴 수 없습니다. 사용 중인 파일과 실행 중인 Chrome 의 캐시는 건너뜁니다."},
            {"id": "ram", "name": "대기 메모리 해제",
             "detail": "Windows 가 캐시로 잡아 둔 대기 메모리를 비웁니다. 실행 중인 프로그램은 건드리지 않습니다."},
            {"id": "dns", "name": "DNS 캐시 초기화",
             "detail": "저장된 DNS 조회 결과를 비웁니다."},
            {"id": "trim", "name": "SSD TRIM",
             "detail": "SSD 에만 TRIM 을 실행합니다. HDD 조각 모음은 하지 않습니다. 시작되면 끝날 때까지 진행됩니다."},
        ],
        "excluded": ["Windows Update 캐시", "Prefetch", "휴지통"],
    }


def get_deep_optimization_status():
    st = dict(_optimization_state)
    st["steps"] = [dict(s) for s in _optimization_state.get("steps", [])]
    return st


def _trim_supports_ssd_only():
    try:
        import inspect
        return 'ssd_only' in inspect.signature(system_repair.run_trim).parameters
    except Exception:
        return False


def _trim_detail(ts):
    msg = ts.get('message') or ts.get('error') or ''
    bad = [v for v in (ts.get('volumes') or []) if not v.get('ok')]
    if bad:
        msg = (msg + ' ' if msg else '') + ', '.join(
            f"{v.get('drive', '?')} {v.get('detail', '')}".strip() for v in bad)
    return msg.strip()


def _run_deep_optimization():
    st = _optimization_state
    plan = get_deep_optimization_plan()["steps"]
    steps = [{"id": p["id"], "name": p["name"], "ok": False, "state": "pending", "detail": ""} for p in plan]
    st.update({"running": True, "progress_pct": 0, "eta_seconds": 0,
               "current_task": "준비 중...", "freed_mb": 0, "error": None,
               "cancel_requested": False, "cancelled": False, "steps": steps,
               "failedCount": 0, "notes": []})
    notes = st["notes"]

    def cancelled():
        return _cancel_event.is_set()

    def begin(i, task):
        steps[i]["state"] = "running"
        st["current_task"] = task
        st["progress_pct"] = int(i * 100 / len(steps))

    def finish(i, state, detail=""):
        steps[i]["state"] = state
        steps[i]["ok"] = state == "ok"
        steps[i]["detail"] = detail

    try:
        # 1) 임시 파일·브라우저 캐시
        begin(0, "임시 파일과 브라우저 캐시를 정리하는 중...")
        res = clean_junk_sync(list(ONE_CLICK_JUNK_IDS), cancel_event=_cancel_event)
        st["freed_mb"] = res.get("freed_mb", 0) or 0
        status = res.get("status")
        skipped = [c for c in res.get("categories", []) if c.get("state") == "skipped"]
        failed_cats = [c for c in res.get("categories", []) if c.get("state") == "failed"]
        extra = ''.join(f" · {c['name']} 건너뜀({c['reason']})" for c in skipped)
        if res.get("skipped_count"):
            extra += f" · 사용 중 등으로 {res['skipped_count']}개 건너뜀"
        if status == "busy":
            finish(0, "failed", res.get("message", "다른 정리 작업이 진행 중입니다."))
        elif status == "error":
            finish(0, "failed", res.get("error") or res.get("message", "오류"))
        elif status == "cancelled":
            finish(0, "cancelled", f"중단됨 — 그 전까지 {st['freed_mb']}MB 를 지웠고, 되돌릴 수 없습니다.")
        elif failed_cats:
            finish(0, "failed", '; '.join(f"{c['name']}: {c['reason']}" for c in failed_cats) + extra)
        else:
            finish(0, "ok", f"{st['freed_mb']}MB 정리" + extra)

        # 2) 대기 메모리
        if not cancelled():
            begin(1, "대기 메모리를 해제하는 중...")
            ram = purge_ram()
            if ram.get("success"):
                finish(1, "ok", "")
            else:
                err = ram.get("error") or "실패"
                finish(1, "failed", "관리자 권한이 필요합니다" if err == "UAC_REQUIRED" else err)

        # 3) DNS 캐시
        if not cancelled():
            begin(2, "DNS 캐시를 초기화하는 중...")
            dns = system_repair.run_network_optimization_sync()
            finish(2, "ok" if dns.get("success") else "failed",
                   "" if dns.get("success") else dns.get("message", "실패"))

        # 4) SSD TRIM (SSD 전용 실행을 지원하지 않는 버전이면 HDD 까지 건드릴 수 있어 실행하지 않는다)
        if not cancelled():
            begin(3, "SSD TRIM 을 실행하는 중...")
            if not _trim_supports_ssd_only():
                finish(3, "skipped", "SSD 전용 TRIM 을 지원하지 않는 버전이라 건너뛰었습니다.")
            else:
                tr = system_repair.run_trim(ssd_only=True)
                if tr.get("skipped") or tr.get("nothingToDo"):
                    finish(3, "skipped", tr.get("message", "TRIM 할 SSD 가 없습니다."))
                elif not tr.get("success"):
                    finish(3, "failed", tr.get("message", "TRIM 을 시작하지 못했습니다."))
                else:
                    deadline = time.time() + 600
                    ts = system_repair.get_trim_status()
                    while ts.get("status") == "running" and time.time() < deadline:
                        if cancelled():
                            break
                        time.sleep(1)
                        ts = system_repair.get_trim_status()
                    s = ts.get("status")
                    if s == "running":
                        why = ("중단 요청을 받았지만 TRIM 은 끝날 때까지 백그라운드에서 진행됩니다."
                               if cancelled() else "아직 진행 중입니다. 저장공간 탭에서 결과를 확인하세요.")
                        finish(3, "running", why)
                    elif s == "success":
                        finish(3, "ok", _trim_detail(ts))
                    elif s == "cancelled":
                        finish(3, "cancelled", _trim_detail(ts) or "중단됨")
                    else:
                        finish(3, "failed", _trim_detail(ts) or "TRIM 이 실패했습니다.")

        if cancelled():
            for s in steps:
                if s["state"] == "pending":
                    s["state"] = "cancelled"
                    s["detail"] = "실행하지 않음"
            notes.append("중단했습니다. 이미 지운 임시 파일은 되돌릴 수 없습니다.")
    except Exception as e:
        log.exception("원클릭 최적화 오류")
        st["error"] = str(e)
        for s in steps:
            if s["state"] in ("pending", "running"):
                s["state"] = "failed" if s["state"] == "running" else "cancelled"
                s["detail"] = s["detail"] or ("오류" if s["state"] == "failed" else "실행하지 않음")
    finally:
        failed = [s for s in steps if s["state"] == "failed"]
        okc = sum(1 for s in steps if s["state"] == "ok")
        st["failedCount"] = len(failed)
        st["cancelled"] = _cancel_event.is_set()
        st["progress_pct"] = 100
        head = "중단됨" if st["cancelled"] else ("오류" if st["error"] else "완료")
        st["current_task"] = f"{head} — {okc}개 성공" + (f", {len(failed)}개 실패" if failed else "")
        st["running"] = False


def start_deep_optimization():
    with _deep_lock:
        if _optimization_state["running"]:
            return {"success": False, "message": "이미 최적화가 실행 중입니다."}
        if _junk_run_lock.locked():
            return {"success": False, "message": "정크 파일 정리가 진행 중입니다. 끝난 뒤 다시 시도하세요."}
        try:
            if system_repair.get_trim_status().get("status") == "running":
                return {"success": False, "message": "디스크 최적화가 진행 중입니다. 끝난 뒤 다시 시도하세요."}
        except Exception:
            pass
        _cancel_event.clear()
        _optimization_state["running"] = True
        t = threading.Thread(target=_run_deep_optimization, daemon=True)
        t.start()
    return {"success": True}


def cancel_deep_optimization():
    if _optimization_state["running"]:
        _optimization_state["cancel_requested"] = True
        _cancel_event.set()
        return {"success": True,
                "message": "중단을 요청했습니다. 진행 중인 단계가 끝나면 멈춥니다. 이미 지운 파일은 되돌릴 수 없습니다."}
    return {"success": False, "message": "실행 중인 최적화가 없습니다."}


# ─────────────────────────────────────────────
# 대기 메모리 해제
# ─────────────────────────────────────────────

def _enable_privilege(priv_name):
    """현재 프로세스 토큰에서 권한 하나를 켠다. 성공 여부를 돌려준다."""
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p,
                                                   wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

        h_token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(h_token)):
            return False
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, priv_name, ctypes.byref(luid)):
            kernel32.CloseHandle(h_token)
            return False
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 0x00000002      # SE_PRIVILEGE_ENABLED
        ok = advapi32.AdjustTokenPrivileges(h_token, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
        err = ctypes.get_last_error()
        kernel32.CloseHandle(h_token)
        return bool(ok) and err == 0                   # ERROR_NOT_ALL_ASSIGNED(1300) 이면 실패
    except Exception:
        return False


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _nt_purge_standby():
    """NtSetSystemInformation(SystemMemoryListInformation, MemoryPurgeStandbyList). NTSTATUS 를 돌려준다."""
    ntdll = ctypes.WinDLL('ntdll')
    ntdll.NtSetSystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    ntdll.NtSetSystemInformation.restype = ctypes.c_long
    command = ctypes.c_int(4)
    return ntdll.NtSetSystemInformation(80, ctypes.byref(command), ctypes.sizeof(command)) & 0xFFFFFFFF


def purge_ram():
    """대기 메모리(스탠바이 캐시)를 비운다. 실행 중인 프로세스의 작업 집합은 건드리지 않는다.

    success 는 대기 메모리 해제가 실제로 성공했을 때만 True 다(C13).
    예전에는 NTSTATUS 와 관계없이 True 를 돌려줘 실패해도 '최적화 완료'가 떴다.
    """
    if not _is_admin():
        return {"success": False, "standbyPurged": False, "error": "UAC_REQUIRED",
                "purgedProcesses": 0, "freed_mb": None}
    try:
        if not _enable_privilege("SeProfileSingleProcessPrivilege"):
            return {"success": False, "standbyPurged": False, "purgedProcesses": 0, "freed_mb": None,
                    "error": "대기 메모리를 비우는 데 필요한 권한(SeProfileSingleProcessPrivilege)을 얻지 못했습니다."}
        status = _nt_purge_standby()
        if status != 0:
            why = "권한 부족" if status == 0xC0000061 else "시스템 호출 실패"
            return {"success": False, "standbyPurged": False, "purgedProcesses": 0, "freed_mb": None,
                    "error": f"{why} (NTSTATUS 0x{status:08X})"}
        # Windows 의 '사용 가능' 메모리에는 대기 메모리가 이미 들어 있어 확보량을 정확히 잴 수 없다.
        # 추정치를 지어내지 않고 None 으로 둔다.
        return {"success": True, "standbyPurged": True, "error": None,
                "purgedProcesses": 0, "freed_mb": None}
    except Exception as e:
        return {"success": False, "standbyPurged": False, "error": str(e),
                "purgedProcesses": 0, "freed_mb": None}


# ─────────────────────────────────────────────
# 성능 모드 (실제 구현은 backend/perf_modes.py)
# ─────────────────────────────────────────────

def _guid_from_string(guid_str):
    """GUID 문자열을 ctypes GUID 구조체로."""
    import uuid
    u = uuid.UUID(guid_str)

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_uint8 * 8)]

    g = GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    g.Data4 = (ctypes.c_uint8 * 8)(*u.bytes[8:])
    return g


POWER_PLAN_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
POWER_PLAN_HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
POWER_PLAN_POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"


def get_optimization_mode():
    """현재 성능 모드. 실제 구현은 perf_modes.get_mode()."""
    from backend import perf_modes
    info = perf_modes.get_mode()
    # 기존 프론트엔드가 쓰던 키 이름을 유지한다
    info['activePlanGuid'] = info.get('activePlan')
    info['verified'] = info.get('inSync', False)
    return info


def set_optimization_mode(mode, user_set=True):
    """성능 모드 적용. 실제 구현은 perf_modes.apply_mode()."""
    from backend import perf_modes
    return perf_modes.apply_mode(mode, user_set=user_set)


def init_optimization_mode():
    """앱 시작 시 호출된다. 아무것도 쓰지 않는다.

    예전에는 저장된 모드를 시작할 때마다 다시 적용했다. 사용자가 Windows 에서 전원 플랜을
    바꿔 두었어도 앱을 켜는 순간 덮어썼다. 앱을 실행한 것만으로 OS 설정이 바뀌면 안 된다.
    """
    return {"success": True, "applied": False,
            "message": "시작할 때는 성능 모드를 다시 적용하지 않습니다."}


# ─────────────────────────────────────────────
# 서비스 (읽기·시작) 와 하드웨어 맞춤 튜닝
# ─────────────────────────────────────────────

SC_MANAGER_CONNECT = 0x0001
SERVICE_START = 0x0010

_SERVICE_START_LABEL = {'auto': '자동', 'delayed-auto': '자동(지연된 시작)',
                        'demand': '수동', 'disabled': '사용 안 함'}
_START_VALUE = {'auto': 2, 'delayed-auto': 2, 'demand': 3, 'disabled': 4}


def _get_service_start_type(service_name):
    """레지스트리의 서비스 시작 유형. 2=자동, 3=수동, 4=사용 안 함. 없으면 None."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\%s" % service_name,
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, "Start")
            return int(value)
    except Exception as e:
        log.debug(f"{service_name} 시작 유형 읽기 실패: {e}")
        return None


def _get_service_delayed_auto(service_name):
    """'자동(지연된 시작)' 인가."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\%s" % service_name,
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, "DelayedAutostart")
            return int(value) == 1
    except Exception:
        return False


def _service_start_kind(service_name):
    """'auto'·'delayed-auto'·'demand'·'disabled'. 서비스가 없으면 None, 그 밖은 'other:<값>'."""
    start = _get_service_start_type(service_name)
    if start is None:
        return None
    if start == 2:
        return 'delayed-auto' if _get_service_delayed_auto(service_name) else 'auto'
    return {3: 'demand', 4: 'disabled'}.get(start, f'other:{start}')


def _start_service(service_name):
    """서비스를 시작한다(advapi32). 성공 여부."""
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        scm = advapi32.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not scm:
            return False
        svc = advapi32.OpenServiceW(scm, service_name, SERVICE_START)
        if not svc:
            advapi32.CloseServiceHandle(scm)
            return False
        ok = advapi32.StartServiceW(svc, 0, None)
        err = ctypes.get_last_error()
        advapi32.CloseServiceHandle(svc)
        advapi32.CloseServiceHandle(scm)
        return bool(ok) or err == 1056            # ERROR_SERVICE_ALREADY_RUNNING
    except Exception:
        return False


# 맞춤 튜닝이 다루는 서비스는 SysMain 하나다.
# Windows Search(WSearch)를 끄면 시작 메뉴·탐색기·Outlook 검색이 망가지므로 대상에서 뺐다.
# 전원 플랜은 성능 모드가 소유한다. 맞춤 튜닝은 플랜을 바꾸지 않는다.
HW_TUNING_GROUP = 'hw_tuning'


def _hw_tuning_plan(is_low_end):
    target = 'disabled' if is_low_end else 'auto'
    cur = _service_start_kind('SysMain')
    if cur is None:
        return [], "SysMain 서비스를 찾지 못해 바꿀 항목이 없습니다."
    if cur.startswith('other:'):
        return [], "SysMain 의 시작 유형이 일반적이지 않아 건드리지 않습니다."
    if cur == target or (target == 'auto' and cur == 'delayed-auto'):
        return [], f"SysMain 이 이미 '{_SERVICE_START_LABEL[cur]}' 상태라 바꿀 항목이 없습니다."
    return [{
        'service': 'SysMain', 'from': cur, 'to': target,
        'text': (f"SysMain(수퍼패치) 서비스 시작 유형을 '{_SERVICE_START_LABEL[cur]}'에서 "
                 f"'{_SERVICE_START_LABEL[target]}'(으)로 바꿉니다 — 다음 부팅부터 적용되며, "
                 "복구 센터에서 되돌릴 수 있습니다."),
    }], ''


def apply_hardware_tailored_tuning(cpu_cores, ram_gb, consent=False):
    """사양에 맞춰 SysMain 시작 유형을 조정한다.

    consent 가 True 가 아니면 '미리보기'다. 아무것도 바꾸지 않고 바뀔 항목만 돌려준다.
    적용은 system_state.set_service_start(group 'hw_tuning') 를 거친다. 원래 값을 기록하지
    못하면 바꾸지 않는다. 항목별 applied/failed 를 그대로 돌려준다.
    """
    try:
        try:
            cpu_cores = int(cpu_cores)
            ram_gb = float(ram_gb)
        except (TypeError, ValueError):
            return {"success": False, "applied": False, "changes": [], "applied_items": [], "failed_items": [],
                    "message": "하드웨어 정보를 읽지 못해 맞춤 튜닝을 적용할 수 없습니다."}

        is_low_end = (cpu_cores <= 4 or ram_gb < 8)
        tier = "LowEnd" if is_low_end else "HighEnd"
        plan, why_none = _hw_tuning_plan(is_low_end)
        changes = [p['text'] for p in plan]

        if consent is not True:
            return {"success": True, "applied": False, "tier": tier, "changes": changes,
                    "message": ("아래 항목이 바뀝니다. 전원 플랜·Windows 검색·Windows Update 는 바꾸지 않습니다."
                                if plan else why_none)}

        if not plan:
            return {"success": True, "applied": False, "tier": tier, "changes": [],
                    "applied_items": [], "failed_items": [], "steps": [], "message": why_none}

        if not hasattr(system_state, 'set_service_start'):
            return {"success": False, "applied": False, "tier": tier, "changes": changes,
                    "applied_items": [], "failed_items": [
                        {"service": p['service'], "to": p['to'], "error": "원래 값을 기록할 수 없음"} for p in plan],
                    "steps": [],
                    "message": "서비스 변경을 기록하는 기능이 없어 아무것도 바꾸지 않았습니다."}

        applied, failed, steps = [], [], []
        for p in plan:
            svc, to = p['service'], p['to']
            why = (f"하드웨어 맞춤 튜닝: {svc} 시작 유형 "
                   f"{_SERVICE_START_LABEL[p['from']]} → {_SERVICE_START_LABEL[to]}")
            try:
                r = system_state.set_service_start(svc, to, HW_TUNING_GROUP, why=why) or {}
            except Exception as e:
                r = {'ok': False, 'error': str(e)}
            now_kind = _service_start_kind(svc)
            if r.get('ok') and now_kind == to:
                applied.append({"service": svc, "from": p['from'], "to": to})
                steps.append({"name": f"{svc} → {_SERVICE_START_LABEL[to]}", "ok": True, "detail": ""})
            else:
                err = r.get('error') or r.get('reason') or f"확인 결과 현재 값 {now_kind}"
                failed.append({"service": svc, "to": to, "error": err})
                steps.append({"name": f"{svc} → {_SERVICE_START_LABEL[to]}", "ok": False, "detail": err})
                break                             # 하나라도 실패하면 더 바꾸지 않는다

        ok = not failed
        if ok:
            msg = "맞춤 튜닝을 적용했습니다. 다음 부팅부터 반영되며, 복구 센터에서 되돌릴 수 있습니다."
        else:
            msg = f"맞춤 튜닝을 적용하지 못했습니다: {failed[0]['error']}"
        return {"success": ok, "applied": bool(applied), "tier": tier, "changes": changes,
                "applied_items": applied, "failed_items": failed, "steps": steps,
                "failedCount": len(failed), "message": msg}
    except Exception as e:
        return {"success": False, "applied": False, "changes": [], "applied_items": [], "failed_items": [],
                "message": "맞춤 튜닝 적용에 실패했습니다.", "error": str(e)}


# ── 구버전 서비스 백업(settings.json 의 service_start_backup) ──

_LEGACY_SERVICES = ('SysMain', 'WSearch')
_LEGACY_START_ARG = {2: 'auto', 3: 'demand', 4: 'disabled'}


def _legacy_service_backup():
    try:
        from backend import config_manager
        b = config_manager.load_config().get("service_start_backup")
        return b if isinstance(b, dict) and b else {}
    except Exception:
        return {}


def has_legacy_service_backup():
    """구버전 맞춤 튜닝이 남긴 서비스 백업이 있는가(C10)."""
    return bool(_legacy_service_backup())


def _drop_legacy_service_keys(keys):
    if not keys:
        return True

    def mutate(cfg):
        b = cfg.get("service_start_backup")
        if isinstance(b, dict):
            for k in keys:
                b.pop(k, None)
            if not b:
                cfg.pop("service_start_backup", None)
        return cfg

    try:
        from backend import config_manager
        if hasattr(config_manager, 'update_config'):
            return bool(config_manager.update_config(mutate))
        cfg = config_manager.load_config()
        mutate(cfg)
        return config_manager.save_config(cfg) is not False
    except Exception as e:
        log.warning(f"서비스 백업 정리 저장 실패: {e}")
        return False


def _sc_set_start(service, start_kind):
    """구버전 백업을 되돌릴 때만 쓴다. shell=False, 절대 경로, 이름·값은 고정 목록에서만 온다."""
    if service not in _LEGACY_SERVICES or start_kind not in _START_VALUE:
        return False, '허용되지 않은 값'
    sysroot = os.environ.get('SystemRoot') or os.environ.get('windir') or r'C:\Windows'
    sc = os.path.join(sysroot, 'System32', 'sc.exe')
    try:
        r = subprocess.run([sc, 'config', service, 'start=', start_kind], shell=False,
                           capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=30)
    except Exception as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or f'sc 오류 {r.returncode}').strip()[:200]
    return True, ''


def restore_tailored_service_config():
    """맞춤 튜닝이 바꾼 서비스 시작 유형을 원래대로(C10).

    1) system_state 저널의 'hw_tuning' 그룹을 되돌린다.
    2) 구버전이 settings.json 에 남긴 service_start_backup 이 '있을 때만' 그 값으로 되돌린다.
    둘 다 없으면 아무것도 쓰지 않는다. 예전에는 백업이 없으면 추측한 Windows 기본값으로
    SysMain·WSearch 를 켜서, 앱이 건드린 적 없는 서비스까지 바꿨다.
    """
    restored, failed, notes = [], [], []
    touched = False
    try:
        pending = {}
        try:
            pending = {k: e for k, e in system_state.pending_changes().items()
                       if e.get('group') == HW_TUNING_GROUP}
        except Exception as e:
            failed.append({"name": "변경 기록", "reason": f"저널을 읽지 못했습니다: {e}"})

        if pending:
            touched = True
            r = system_state.restore_group(HW_TUNING_GROUP) or {}
            reasons = {f.get('key'): f.get('reason') for f in (r.get('failed') or []) if isinstance(f, dict)}
            left = system_state.pending_changes()
            for k, e in pending.items():
                label = e.get('service') or e.get('name') or k
                if k in left:
                    failed.append({"name": label, "reason": reasons.get(k) or "복구 실패"})
                else:
                    restored.append(label)

        backup = _legacy_service_backup()
        if backup:
            touched = True
            done_keys = []
            for svc, saved in backup.items():
                if svc not in _LEGACY_SERVICES or not isinstance(saved, dict):
                    failed.append({"name": str(svc), "reason": "알 수 없는 백업 항목"})
                    continue
                cur = _service_start_kind(svc)
                if cur is None:
                    done_keys.append(svc)
                    notes.append(f"{svc} 서비스가 없어 건너뜀")
                    continue
                start = saved.get("start")
                if start not in _LEGACY_START_ARG:
                    failed.append({"name": svc, "reason": "원래 값이 기록되지 않았습니다. 서비스 설정에서 직접 확인하세요."})
                    continue
                target = _LEGACY_START_ARG[start]
                if target == 'auto' and saved.get("delayed"):
                    target = 'delayed-auto'
                if cur != target:
                    ok, err = _sc_set_start(svc, target)
                    now = _service_start_kind(svc)
                    if not ok or now != target:
                        failed.append({"name": svc, "reason": err or f"확인 결과 현재 값 {now}"})
                        continue
                    if target in ('auto', 'delayed-auto') and not _start_service(svc):
                        notes.append(f"{svc} 는 다음 부팅부터 시작됩니다")
                restored.append(svc)
                done_keys.append(svc)
            # 성공한 항목만 백업에서 뺀다. 실패한 건 남겨야 다시 시도할 수 있다.
            if done_keys and not _drop_legacy_service_keys(done_keys):
                notes.append("백업 정리를 저장하지 못했습니다(다시 눌러도 같은 값으로 복구됩니다)")

        if not touched:
            return {"success": True, "nothingToRestore": True, "restored": [], "failed": failed,
                    "message": "되돌릴 서비스 변경이 없습니다."}

        ok = not failed
        msg = (f"서비스 설정을 원래대로 되돌렸습니다: {', '.join(restored)}" if ok and restored
               else "서비스 설정을 원래대로 되돌렸습니다." if ok
               else f"{len(restored)}개 복구, {len(failed)}개 실패: "
                    + ', '.join(f"{f['name']}({f['reason']})" for f in failed))
        if notes:
            msg += " · " + " · ".join(notes)
        return {"success": ok, "nothingToRestore": False, "restored": restored,
                "failed": failed, "message": msg}
    except Exception as e:
        return {"success": False, "nothingToRestore": False, "restored": restored,
                "failed": failed + [{"name": "서비스", "reason": str(e)}],
                "message": "서비스 설정 복구에 실패했습니다.", "error": str(e)}


# ─────────────────────────────────────────────
# 시작 프로그램
# ─────────────────────────────────────────────
# 작업 관리자와 같은 방식으로 켜고 끈다. Run 값은 지우지 않고
# Explorer\StartupApproved\Run(/Run32) 의 플래그만 바꾼다. 그래서 끈 항목도 작업 관리자·설정에
# 그대로 보이고 거기서 다시 켤 수 있다. 예전에는 Run 값을 지우고 HKCU 의 자체 키에만 숨겨 둬서
# 앱을 지우면 되살릴 방법이 없었다.

_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"

# tag: (system_state 하이브 이름, winreg 하이브, Run 경로, StartupApproved 경로, 표시 이름)
RUN_LOCATIONS = {
    'HKCU': ('HKCU', winreg.HKEY_CURRENT_USER, _RUN, _APPROVED + r"\Run", '현재 사용자'),
    'HKLM': ('HKLM', winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run", '모든 사용자'),
    'HKLM32': ('HKLM', winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
               r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32", '모든 사용자 (32비트)'),
}

_LEGACY_BACKUP = r"Software\APEXCARE\DisabledStartup"
_LEGACY_ORIGIN = r"Software\APEXCARE\DisabledStartup\_origin"

_APPROVED_ENABLED = b'\x02' + b'\x00' * 11

# 일괄 끄기에서 빼는 프로그램. 이름·명령줄에 이 문자열이 있으면 '필수'로 본다.
# 틀려도 '더 조심하는' 쪽으로만 틀리게 구체적인 이름을 쓴다.
_ESSENTIAL_RULES = (
    ('보안 프로그램', (
        'securityhealth', 'windows defender', 'msascuil', 'ahnlab', 'alyac', 'naver vaccine',
        'nprotect', 'incainternet', 'veraport', 'wizvera', 'anysign', 'crossex', 'touchen',
        'raonsecure', 'delfino', 'ipinside', 'interezen', 'magicline', 'dreamsecurity', 'ksign',
        'safe transaction', 'norton', 'symantec', 'mcafee', 'kaspersky', '\\eset\\', 'avast',
        '\\avg\\', 'bitdefender', 'malwarebytes', 'sophos', 'trend micro', 'trendmicro', 'webroot',
        'f-secure', 'avira', 'comodo', 'zonealarm', 'hauri', 'virobot',
    )),
    ('게임 보안(안티치트)', (
        'vanguard', 'vgtray', 'easyanticheat', 'battleye', 'xigncode', 'gameguard',
    )),
    ('드라이버·장치 유틸리티', (
        '\\realtek\\', 'rtkaud', 'rthdvcpl', 'ravcpl', 'synaptics', 'syntp', 'elantech', 'etdctrl',
        '\\alps\\', 'wacom', 'xppen', 'pentablet', 'huion', '\\intel\\', 'igfx', '\\nvidia', 'nvcontainer',
        '\\amd\\', 'radeon', 'logitech', 'lghub', 'razer', 'corsair', 'icue', 'steelseries',
        'bluetooth', 'thunderbolt', 'hotkey', 'armoury', 'asus', 'lenovo', '\\dell\\', '\\hp\\',
        'gaming headset', 'audio center', 'xearaudio', 'nahimic', 'dolby', 'maxxaudio',
    )),
    ('동기화·백업', (
        'onedrive', 'dropbox', 'googledrive', 'google drive', '\\google\\drive', 'icloud', 'box drive',
        'nextcloud', 'owncloud', 'pcloud', 'megasync', 'synology', 'mybox', 'tresorit', 'backblaze',
        'carbonite', 'acronis', 'macrium',
    )),
)


def _clean(s):
    return s.replace('\x00', '').strip() if isinstance(s, str) else s


def _reg_read(hive, path, name):
    """(있음, 값, 타입). 64비트 보기로 읽는다."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            v, t = winreg.QueryValueEx(k, name)
            return True, v, t
    except FileNotFoundError:
        return False, None, None
    except OSError:
        return False, None, None


def _reg_values(hive, path):
    out = []
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumValue(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def _approved_state(tag, name):
    """'enabled'·'disabled'·'none'(값 없음 = 켜짐). 첫 바이트가 홀수면 꺼짐(작업 관리자와 같은 판정)."""
    loc = RUN_LOCATIONS[tag]
    exists, val, _ = _reg_read(loc[1], loc[3], name)
    if not exists:
        return 'none'
    if isinstance(val, (bytes, bytearray)) and len(val) >= 1:
        return 'disabled' if (val[0] & 1) else 'enabled'
    return 'enabled'


def _approved_disabled_bytes():
    ft = int((time.time() + 11644473600) * 10 ** 7)
    return b'\x03\x00\x00\x00' + ft.to_bytes(8, 'little')


def _classify_essential(name, command):
    text = f"{name} {os.path.expandvars(command or '')}".lower()
    win = (os.environ.get('SystemRoot') or os.environ.get('windir') or '').lower()
    cmd = os.path.expandvars(command or '').lower().lstrip('"').lstrip()
    if win and cmd.startswith(win + '\\'):
        return True, 'Windows 구성 요소'
    for label, tokens in _ESSENTIAL_RULES:
        if any(t in text for t in tokens):
            return True, label
    return False, ''


def _make_id(tag, name):
    return f"{tag}:{name}"


def _parse_id(app_id):
    if not isinstance(app_id, str) or ':' not in app_id:
        return None, None
    tag, name = app_id.split(':', 1)
    if tag not in RUN_LOCATIONS and tag != 'LEGACY':
        return None, None
    return tag, name


def _legacy_entries():
    """구버전이 Run 에서 지우고 숨겨 둔 항목: [(이름, 값, 타입, 출처문자열|None)]"""
    origins = {n: v for n, v, _ in _reg_values(winreg.HKEY_CURRENT_USER, _LEGACY_ORIGIN)}
    return [(n, v, t, origins.get(n)) for n, v, t in _reg_values(winreg.HKEY_CURRENT_USER, _LEGACY_BACKUP)]


def _legacy_target(origin):
    """구버전 출처 기록을 RUN_LOCATIONS 화이트리스트로 검증한다. (tag, 출처를 아는가) 또는 (None, 이유)."""
    if origin is None:
        return 'HKCU', False                        # 기록이 없으면 현재 사용자로 되살린다(원래 위치 불명)
    if not isinstance(origin, str) or '|' not in origin:
        return None, '원래 위치 기록 형식이 올바르지 않습니다'
    tag, path = origin.split('|', 1)
    loc = RUN_LOCATIONS.get(tag)
    if not loc or path.strip().lower() != loc[2].lower():
        return None, '원래 위치 기록이 허용된 시작 프로그램 위치가 아닙니다'
    return tag, True


def get_startup_apps():
    """Run 키 3곳의 시작 프로그램과 켜짐/꺼짐 상태. 같은 이름도 위치가 다르면 따로 보여 준다."""
    apps = []
    for tag, loc in RUN_LOCATIONS.items():
        for raw_name, value, vtype in _reg_values(loc[1], loc[2]):
            command = _clean(value) if isinstance(value, str) else str(value)
            state = _approved_state(tag, raw_name)
            essential, reason = _classify_essential(raw_name, command)
            apps.append({
                "id": _make_id(tag, raw_name), "name": _clean(raw_name), "command": command,
                "publisher": command,                 # (구 키 유지)
                "location": tag, "locationLabel": loc[4],
                "enabled": state != 'disabled', "approvedState": state,
                "essential": essential, "essentialReason": reason,
                "impact": "Protected" if essential else "High",
                "legacy": False, "originKnown": True,
            })

    for raw_name, value, vtype, origin in _legacy_entries():
        tag, known = _legacy_target(origin)
        command = _clean(value) if isinstance(value, str) else str(value)
        if tag and _reg_read(RUN_LOCATIONS[tag][1], RUN_LOCATIONS[tag][2], raw_name)[0]:
            continue                                  # 이미 Run 에 다시 등록돼 있다
        essential, reason = _classify_essential(raw_name, command)
        apps.append({
            "id": _make_id('LEGACY', raw_name), "name": _clean(raw_name), "command": command,
            "publisher": command, "location": 'LEGACY',
            "locationLabel": '구버전에서 끈 항목' + ('' if known else ' (원래 위치 불명)'),
            "enabled": False, "approvedState": 'legacy',
            "essential": essential, "essentialReason": reason,
            "impact": "Protected" if essential else "High",
            "legacy": True, "originKnown": bool(known),
        })

    apps.sort(key=lambda a: (a["name"].lower(), a["location"]))
    return apps


def _startup_group(tag, name):
    return f"startup:{tag}:{name}"


def _journal_entry(group):
    try:
        for e in system_state.pending_changes().values():
            if e.get('group') == group and e.get('kind') == 'registry':
                return e
    except Exception:
        pass
    return None


def _entry_original_enabled(e):
    """저널에 기록된 원래 StartupApproved 값이 '켜짐' 이었는가. 알 수 없으면 None."""
    if not e.get('existed'):
        return True
    v = e.get('value')
    b = None
    if isinstance(v, (bytes, bytearray)):
        b = bytes(v)
    elif isinstance(v, list) and v and all(isinstance(x, int) for x in v):
        b = bytes(v[:1])
    elif isinstance(v, str):
        try:
            b = bytes.fromhex(v)
        except ValueError:
            b = None
    elif isinstance(v, dict):
        h = v.get('__bytes__') or v.get('hex')
        try:
            b = bytes.fromhex(h) if isinstance(h, str) else None
        except ValueError:
            b = None
    if not b:
        return None
    return not (b[0] & 1)


def _set_approved(tag, name, enabled):
    """StartupApproved 플래그를 system_state 로 바꾼다. 원래 상태로 돌아가는 거면 기록을 되돌린다."""
    loc = RUN_LOCATIONS[tag]
    group = _startup_group(tag, name)
    entry = _journal_entry(group)
    if entry is not None and _entry_original_enabled(entry) == enabled:
        r = system_state.restore_group(group) or {}
        fails = r.get('failed') or []
        reason = '; '.join(f.get('reason', '') for f in fails if isinstance(f, dict)) or '원래 값 복구 실패'
        return bool(r.get('ok')), ('' if r.get('ok') else reason)
    data = _APPROVED_ENABLED if enabled else _approved_disabled_bytes()
    r = system_state.set_registry(loc[0], loc[3], name, data, group, vtype=winreg.REG_BINARY,
                                  why=f"시작 프로그램 '{_clean(name)}' ({loc[4]}) 켜짐/꺼짐") or {}
    return bool(r.get('ok')), (r.get('error') or r.get('reason') or '')


def _migrate_one_legacy(raw_name):
    """구버전이 숨긴 항목 하나를 원래 Run 위치에 되살리고 '꺼짐'으로 표시한다."""
    match = [e for e in _legacy_entries() if e[0] == raw_name]
    if not match:
        return {'ok': False, 'name': _clean(raw_name), 'reason': '구버전 기록을 찾지 못했습니다'}
    _, value, vtype, origin = match[0]
    tag, known = _legacy_target(origin)
    if tag is None:
        return {'ok': False, 'name': _clean(raw_name), 'reason': known}
    if vtype not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str) or not value.strip():
        return {'ok': False, 'name': _clean(raw_name), 'reason': '저장된 명령줄 형식이 올바르지 않습니다'}
    loc = RUN_LOCATIONS[tag]
    note = '' if known else '원래 위치 기록이 없어 현재 사용자(HKCU)로 되살렸습니다'

    if _reg_read(loc[1], loc[2], raw_name)[0]:
        # 프로그램이 스스로 다시 등록했다. 지금 상태를 존중하고 구버전 기록만 정리한다.
        _drop_legacy_value(raw_name)
        return {'ok': True, 'name': _clean(raw_name), 'tag': tag, 'originKnown': known,
                'note': '이미 시작 프로그램에 다시 등록돼 있어 구버전 기록만 정리했습니다'}

    # 1) 먼저 '꺼짐' 표시. 이게 안 되면 Run 을 되살리지 않는다(되살리는 순간 켜져 버린다).
    if _approved_state(tag, raw_name) != 'disabled':
        ok, why = _set_approved(tag, raw_name, False)
        if not ok or _approved_state(tag, raw_name) != 'disabled':
            return {'ok': False, 'name': _clean(raw_name), 'reason': f"'꺼짐' 표시를 쓰지 못했습니다: {why}"}

    # 2) Run 값을 되살린다. 이것은 '새 변경'이 아니라 구버전이 지운 사용자 값의 복원이라
    #    저널에 넣지 않는다(넣으면 '전부 원래대로'가 이 값을 다시 지운다).
    try:
        with winreg.CreateKeyEx(loc[1], loc[2], 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, raw_name, 0, vtype, value)
    except PermissionError:
        return {'ok': False, 'name': _clean(raw_name), 'reason': f'{loc[4]} 위치에 쓰려면 관리자 권한이 필요합니다'}
    except OSError as e:
        return {'ok': False, 'name': _clean(raw_name), 'reason': str(e)}
    exists, back, _ = _reg_read(loc[1], loc[2], raw_name)
    if not exists or back != value:
        return {'ok': False, 'name': _clean(raw_name), 'reason': '되살린 값을 다시 읽으니 다릅니다'}

    _drop_legacy_value(raw_name)
    return {'ok': True, 'name': _clean(raw_name), 'tag': tag, 'originKnown': known, 'note': note}


def _drop_legacy_value(raw_name):
    """앱 자체 키(HKCU\\Software\\APEXCARE)의 구버전 기록을 지운다."""
    for path in (_LEGACY_BACKUP, _LEGACY_ORIGIN):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, raw_name)
        except OSError:
            pass


def migrate_legacy_disabled_startup():
    """구버전이 숨긴 시작 프로그램을 원래 Run 위치로 되살린다(C11). 여전히 꺼져 있고 작업 관리자에서 보인다. 멱등."""
    migrated, failed = [], []
    for raw_name, _, _, _ in _legacy_entries():
        try:
            r = _migrate_one_legacy(raw_name)
        except Exception as e:
            r = {'ok': False, 'name': _clean(raw_name), 'reason': str(e)}
        (migrated if r.get('ok') else failed).append(r)
    return {'ok': not failed, 'migrated': migrated, 'failed': failed}


def toggle_startup_app(app_id, enabled):
    """시작 프로그램을 켜고 끈다(C12). app_id 는 get_startup_apps 의 id.

    Run 값은 지우지 않는다. 같은 이름이 여러 위치에 있어도 id 로 정확히 하나만 바꾼다.
    바꾼 뒤 다시 읽어 확인하고, 확인되지 않으면 실패로 돌려준다.
    """
    enabled = bool(enabled)
    tag, name = _parse_id(app_id)
    if tag is None:
        # 구 호출(이름만): 같은 이름이 하나뿐일 때만 받는다
        if not isinstance(app_id, str) or not app_id.strip():
            return {"success": False, "message": "프로그램 id 가 올바르지 않습니다."}
        same = [a for a in get_startup_apps() if a["name"] == _clean(app_id)]
        if len(same) != 1:
            return {"success": False,
                    "message": ("같은 이름이 여러 위치에 있어 어느 항목인지 알 수 없습니다."
                                if same else f"'{app_id}' 을 시작 프로그램 목록에서 찾지 못했습니다.")}
        tag, name = _parse_id(same[0]["id"])

    shown = _clean(name)
    try:
        if tag == 'LEGACY':
            if not enabled:
                return {"success": True, "enabled": False, "message": f"'{shown}' 은 이미 꺼져 있습니다."}
            m = _migrate_one_legacy(name)
            if not m.get('ok'):
                return {"success": False, "message": f"'{shown}' 을 되살리지 못했습니다: {m.get('reason')}"}
            tag = m['tag']

        loc = RUN_LOCATIONS[tag]
        if not _reg_read(loc[1], loc[2], name)[0]:
            return {"success": False,
                    "message": f"'{shown}' 을 {loc[4]} 시작 프로그램에서 찾지 못했습니다. 이미 제거되었을 수 있습니다."}

        cur = _approved_state(tag, name) != 'disabled'
        if cur == enabled:
            return {"success": True, "enabled": enabled, "id": _make_id(tag, name),
                    "message": f"'{shown}' 은 이미 {'켜져' if enabled else '꺼져'} 있습니다."}

        ok, why = _set_approved(tag, name, enabled)
        after = _approved_state(tag, name) != 'disabled'
        if not ok or after != enabled:
            return {"success": False, "enabled": after, "id": _make_id(tag, name),
                    "message": f"'{shown}' 설정을 바꾸지 못했습니다" + (f": {why}" if why else ".")}
        log.info(f"시작 프로그램 {'켜기' if enabled else '끄기'}: {shown} ({tag})")
        return {"success": True, "enabled": enabled, "id": _make_id(tag, name),
                "message": f"'{shown}' 을 {'켰' if enabled else '껐'}습니다. 다음 로그인부터 적용됩니다."}
    except Exception as e:
        log.error(f"시작 프로그램 전환 실패 {shown}: {e}")
        return {"success": False, "message": f"시작 프로그램 설정 변경에 실패했습니다: {e}"}
