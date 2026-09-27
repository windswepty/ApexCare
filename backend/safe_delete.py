"""
APEX CARE — 되돌릴 수 있는 삭제 계층.

이 앱의 모든 삭제는 이 모듈을 거친다. 이유는 하나다.
상업용 최적화 도구에서 사용자 파일을 휴지통도 거치지 않고 지우는 것은 허용되지 않는다.
복구 수단이 없는 삭제는 버그 하나가 곧바로 사용자 데이터 소실로 이어진다.

제공하는 것:
  - to_recycle_bin()   : 휴지통으로 보낸다(복구 가능). 기본 경로.
                         휴지통에 들어간다고 확인된 항목만 셸에 넘기고, 나머지는 건드리지 않고
                         not_recyclable 로 돌려준다.
  - permanent_delete() : 휴지통을 못 쓰는 경우에만 쓰는 최후 수단. 호출부가 명시적으로 선택해야 한다.
  - is_protected()     : 통째로 지우면 안 되는 경로인지(보호 폴더 자신과 그 상위) 판정한다.
  - is_system_area()   : Windows 폴더처럼 '안쪽' 어디도 지우면 안 되는 영역인지 판정한다.
  - drive_type() / recycle_bin_limit() : 드라이브 종류와 휴지통이 받아 주는 최대 크기.

SHFileOperationW 의 FOF_ALLOWUNDO 가 휴지통 경유를 요청하지만 '보장' 하지는 않는다.
휴지통보다 큰 파일, 이동식 드라이브, 휴지통을 끈 드라이브의 파일은 FOF_NOCONFIRMATION 과
함께 쓰면 묻지 않고 영구 삭제된다. 그래서 셸에 넘기기 전에 직접 확인하고,
FOF_WANTNUKEWARNING 을 백스톱으로 둔다(사전 검사가 틀려도 영구 삭제 전에 셸이 묻는다).
"""

import ctypes
import ctypes.wintypes
import logging
import os
import shutil
import threading
import uuid

log = logging.getLogger('SafeDelete')

# ── SHFileOperationW 상수 ─────────────────────────────────────
FO_DELETE = 0x0003
FOF_SILENT = 0x0004          # 진행 대화상자 숨김
FOF_NOCONFIRMATION = 0x0010  # "정말 지울까요" 묻지 않음 (우리가 이미 물어봤다)
FOF_ALLOWUNDO = 0x0040       # ★ 휴지통 경유 — 이게 없으면 영구 삭제다
FOF_NOCONFIRMMKDIR = 0x0200
FOF_NOERRORUI = 0x0400       # 오류 대화상자 숨김 (반환값으로 처리)
FOF_WANTNUKEWARNING = 0x4000  # ★ 휴지통에 못 넣어 영구 삭제하게 되면 셸이 묻는다 (백스톱)

_RECYCLE_FLAGS = (FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI
                  | FOF_SILENT | FOF_WANTNUKEWARNING)

# ── 파일 속성 ─────────────────────────────────────────────────
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
# 내용이 PC 에 없는 클라우드 자리표시자. 읽으면 내려받고, 지우면 PC 휴지통을 거치지 않는다.
CLOUD_PLACEHOLDER_ATTRS = (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN
                           | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
_NAME_SURROGATE_BIT = 0x20000000   # 정션·심볼릭 링크·마운트 지점처럼 '다른 경로를 가리키는' 재분석 지점

_DRIVE_TYPE_NAMES = {2: 'removable', 3: 'fixed', 4: 'network', 5: 'cdrom', 6: 'ramdisk'}
_DRIVE_TYPE_REASON = {
    'removable': '이동식 드라이브에는 휴지통이 없습니다',
    'network': '네트워크 드라이브에는 휴지통이 없습니다',
    'cdrom': 'CD/DVD 드라이브입니다',
    'ramdisk': '램디스크에는 휴지통이 없습니다',
    'unknown': '드라이브 종류를 확인할 수 없습니다',
}

# 휴지통 최대 크기를 모를 때 쓰는 값. Windows 기본값(첫 40GB 의 10% + 나머지의 5%)보다 항상 작다.
_DEFAULT_BIN_PERCENT = 5
# 휴지통 계산 단위(클러스터·$I 파일)만큼의 오차를 흡수하는 여유
_BIN_SAFETY = 0.95


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("wFunc", ctypes.wintypes.UINT),
        ("pFrom", ctypes.wintypes.LPCWSTR),
        ("pTo", ctypes.wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", ctypes.wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.wintypes.LPCWSTR),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


# ── Win32 함수 ────────────────────────────────────────────────
# 전역 ctypes.windll 의 함수 원형을 바꾸면 다른 모듈에도 번진다. 전용 인스턴스를 쓴다.
_api = {}
_api_lock = threading.Lock()


def _kernel32():
    with _api_lock:
        k = _api.get('kernel32')
        if k is None:
            W = ctypes.wintypes
            k = ctypes.WinDLL('kernel32', use_last_error=True)
            k.GetDriveTypeW.argtypes = [W.LPCWSTR]
            k.GetDriveTypeW.restype = W.UINT
            k.GetVolumePathNameW.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD]
            k.GetVolumePathNameW.restype = W.BOOL
            k.GetVolumeNameForVolumeMountPointW.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD]
            k.GetVolumeNameForVolumeMountPointW.restype = W.BOOL
            k.QueryDosDeviceW.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD]
            k.QueryDosDeviceW.restype = W.DWORD
            k.GetLogicalDrives.argtypes = []
            k.GetLogicalDrives.restype = W.DWORD
            _api['kernel32'] = k
        return k


def _shell32():
    with _api_lock:
        s = _api.get('shell32')
        if s is None:
            s = ctypes.WinDLL('shell32', use_last_error=True)
            s.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
            s.SHFileOperationW.restype = ctypes.c_int
            s.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_GUID), ctypes.wintypes.DWORD,
                                               ctypes.wintypes.HANDLE,
                                               ctypes.POINTER(ctypes.c_wchar_p)]
            s.SHGetKnownFolderPath.restype = ctypes.c_long
            _api['shell32'] = s
        return s


def _known_folder(guid_str):
    """SHGetKnownFolderPath. OneDrive 로 옮겨진 바탕 화면처럼 '실제' 위치를 준다."""
    try:
        ole32 = ctypes.WinDLL('ole32')
        g = _GUID.from_buffer_copy(uuid.UUID(guid_str).bytes_le)
        out = ctypes.c_wchar_p()
        KF_FLAG_DONT_VERIFY = 0x4000   # 폴더를 만들거나 검사하지 않는다(읽기만)
        hr = _shell32().SHGetKnownFolderPath(ctypes.byref(g), KF_FLAG_DONT_VERIFY, None,
                                             ctypes.byref(out))
        try:
            return out.value if hr == 0 else None
        finally:
            if out:
                ole32.CoTaskMemFree(out)
    except Exception:
        return None


# 통째로 지워지면 안 되는 '알려진 폴더'. 이름이 아니라 Windows 가 아는 실제 위치를 쓴다.
_KNOWN_FOLDERS = (
    '{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}',  # Desktop
    '{FDD39AD0-238F-46AF-ADB4-6C85480369C7}',  # Documents
    '{374DE290-123F-4565-9164-39C4925E467B}',  # Downloads
    '{33E28130-4E1E-4676-835A-98395C3BC3BB}',  # Pictures
    '{18989B1D-99B5-455B-841C-AB7C74E4DDFC}',  # Videos
    '{4BD8D571-6D19-48D3-BE97-422220080E43}',  # Music
    '{1777F761-68AD-4D8A-87BD-30B759FA33DD}',  # Favorites
    '{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}',  # Saved Games
    '{56784854-C6CB-462B-8169-88E350ACB882}',  # Contacts
    '{BFB9D5E0-C6A9-404C-B2B2-AE6DB6AF4968}',  # Links
    '{7D1D3A04-DEBB-4115-95CF-2F29DA2920DA}',  # Searches
    '{A52BBA46-E9E1-435F-B3D9-28DAA648C0F6}',  # OneDrive
    '{5E6C858F-0E22-4760-9AFE-EA3317B67173}',  # 사용자 프로필
    '{0762D272-C50A-4BB0-A382-697DCD729B80}',  # 사용자 프로필들의 상위(C:\Users)
    '{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}',  # AppData\Roaming
    '{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}',  # AppData\Local
    '{A520A1A4-1780-4FF6-BD18-167343C5AF16}',  # AppData\LocalLow
    '{5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}',  # AppData\Local\Programs (사용자별 설치 앱)
    '{62AB5D82-FDC1-4DC3-A9DD-070D1D495D97}',  # ProgramData
    '{905E63B6-C1BF-494E-B29C-65B732D3D21A}',  # Program Files
    '{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}',  # Program Files (x86)
    '{F7F1ED05-9F6D-47A2-AAAE-29D317C6F066}',  # Common Files
    '{DE974D24-D9C6-4D3E-BF91-F4455120B917}',  # Common Files (x86)
    '{F38BF404-1D43-42F2-9305-67DE0B28FC23}',  # Windows
    '{DFDF76A2-C82A-4D63-906A-5644AC457385}',  # Public
    '{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}',  # Public Desktop
    '{ED4824AF-DCE4-45A8-81E2-FC7965083634}',  # Public Documents
    '{625B53C3-AB48-4EC1-BA1F-A1EF4146FC19}',  # 시작 메뉴
    '{A4115719-D62E-491D-AA7C-E74B8BE3B067}',  # 모든 사용자 시작 메뉴
    '{AB5FB87B-7CE2-4F83-915D-550846C9537B}',  # 카메라 앨범
    '{B7BEDE81-DF94-4682-A7D8-57A52620B86F}',  # 스크린샷
)


# ── 경로 정규화 ───────────────────────────────────────────────
def _strip_prefix(path):
    s = os.fspath(path)
    if s.startswith('\\\\?\\UNC\\'):
        return '\\\\' + s[8:]
    if s.startswith('\\\\?\\') or s.startswith('\\\\.\\'):
        return s[4:]
    return s


def norm(path):
    """경로를 비교 가능한 정규형으로 만든다.

    ..\\ 로 상위 폴더를 탈출하거나, 심볼릭 링크·정션으로 보호 경로를 우회하는 것을 막으려면
    문자열 비교 전에 반드시 실경로로 풀어야 한다. 비교 전용이다(소문자로 바뀐다).
    """
    s = _strip_prefix(path)
    try:
        r = os.path.realpath(os.path.abspath(s))
    except Exception:
        r = os.path.abspath(s)
    return os.path.normcase(_strip_prefix(r)).rstrip('\\')


def _lex(path):
    """링크를 풀지 않은 정규형. 환경변수 경로가 정션을 거칠 때 양쪽 모두와 비교하려고 쓴다."""
    return os.path.normcase(os.path.abspath(_strip_prefix(path))).rstrip('\\')


def _is_drive_root(p):
    # 'c:' 처럼 드라이브만 남은 정규형
    return len(p) <= 3 and len(p) >= 2 and p[1] == ':'


def _registry_profile_paths():
    """다른 사용자 프로필을 포함한 모든 프로필 경로(읽기만)."""
    out = []
    try:
        import winreg
        key = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            for name in ('ProfilesDirectory', 'Default', 'Public'):
                try:
                    out.append(os.path.expandvars(winreg.QueryValueEx(k, name)[0]))
                except OSError:
                    pass
            i = 0
            while True:
                try:
                    sid = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sid) as sk:
                        out.append(os.path.expandvars(winreg.QueryValueEx(sk, 'ProfileImagePath')[0]))
                except OSError:
                    continue
    except Exception as e:
        log.debug(f"프로필 목록 읽기 실패: {e}")
    return out


# ── 절대 삭제 금지 경로 ────────────────────────────────────────
def _protected_roots():
    """통째로 지우면 안 되는 폴더. 링크를 푼 형태와 안 푼 형태를 모두 담는다."""
    env = os.environ.get
    raw = [
        env('SystemRoot'), env('windir'),
        env('ProgramFiles'), env('ProgramFiles(x86)'), env('ProgramW6432'),
        env('CommonProgramFiles'), env('CommonProgramFiles(x86)'), env('CommonProgramW6432'),
        env('ProgramData'), env('ALLUSERSPROFILE'), env('APPDATA'), env('LOCALAPPDATA'),
        env('USERPROFILE'), env('PUBLIC'),
        env('TEMP'), env('TMP'),
        env('OneDrive'), env('OneDriveConsumer'), env('OneDriveCommercial'),
    ]
    home = env('USERPROFILE') or ''
    if home:
        # 사용자 개인 데이터 폴더 자체는 통째로 지워지면 안 된다
        raw += [os.path.join(home, d) for d in
                ('Documents', 'Desktop', 'Downloads', 'Pictures', 'Videos',
                 'Music', 'OneDrive', 'Favorites', 'Links', 'Contacts',
                 'Saved Games', 'Searches', 'AppData')]
    raw += [_known_folder(g) for g in _KNOWN_FOLDERS]
    raw += _registry_profile_paths()

    out = set()
    for p in raw:
        if not p:
            continue
        for form in (_lex, norm):
            try:
                f = form(p)
            except Exception:
                continue
            # 드라이브 루트는 따로 막는다. 여기 넣으면 모든 경로의 '상위' 판정이 꼬인다.
            if f and not _is_drive_root(f):
                out.add(f)
    return frozenset(out)


try:
    PROTECTED_DIRS = _protected_roots()
except Exception as _e:   # 목록을 못 만들어도 import 는 되어야 한다. 대신 삭제 쪽에서 더 막는다.
    log.warning(f"보호 경로 목록 생성 실패: {_e}")
    PROTECTED_DIRS = frozenset()

# 이 폴더들은 '잔여물'로 취급해서도 안 된다. 통째로 날리면 복구가 사실상 불가능하다.
NEVER_LEFTOVER = {
    'microsoft', 'windows', 'windowsapps', 'packages', 'temp', 'tmp',
    'common files', 'internet explorer', 'windows defender', 'windows nt',
    'winsxs', 'system32', 'syswow64', 'drivers', 'driverstore',
    'google', 'mozilla', 'intel', 'amd', 'nvidia', 'realtek', 'qualcomm',
    'steam', 'steamlibrary', 'epic games', 'ea games', 'ubisoft',
    'battle.net', 'gog galaxy', 'riot games', 'origin',
    'onedrive', 'dropbox', 'box', 'icloud',
}

# 드라이브 루트 바로 아래에 있으면 그 안쪽 전체가 시스템 영역인 이름
_ROOT_SYSTEM_NAMES = {
    'windows', '$recycle.bin', 'system volume information', 'recovery', 'boot', 'efi',
    '$windows.~bt', '$windows.~ws', '$winreagent', '$sysreset', 'config.msi',
    'pagefile.sys', 'hiberfil.sys', 'swapfile.sys', 'bootmgr', 'bootnxt', 'bootsect.bak',
    'dumpstack.log', 'dumpstack.log.tmp',
}


def _system_areas():
    env = os.environ.get
    raw = [env('SystemRoot'), env('windir'), _known_folder('{F38BF404-1D43-42F2-9305-67DE0B28FC23}')]
    for pf in (env('ProgramFiles'), env('ProgramW6432')):
        if pf:
            raw += [os.path.join(pf, 'WindowsApps'), os.path.join(pf, 'ModifiableWindowsApps')]
    if env('ProgramData'):
        raw.append(os.path.join(env('ProgramData'), 'Microsoft', 'Windows'))
    out = set()
    for p in raw:
        if not p:
            continue
        for form in (_lex, norm):
            try:
                f = form(p)
            except Exception:
                continue
            if f and not _is_drive_root(f):
                out.add(f)
    return frozenset(out)


try:
    SYSTEM_AREAS = _system_areas()
except Exception as _e:
    log.warning(f"시스템 영역 목록 생성 실패: {_e}")
    SYSTEM_AREAS = frozenset()


def _forms(path):
    forms = set()
    for f in (norm, _lex):
        try:
            forms.add(f(path))
        except Exception:
            pass
    return forms


def _is_users_dir_or_profile(p):
    # <드라이브>:\Users 와 그 바로 아래(각 사용자 프로필, Public, Default)
    parts = p.split('\\')
    return len(parts) in (2, 3) and _is_drive_root(parts[0]) and parts[1] == 'users'


def is_protected(path):
    """이 경로를 통째로 지우면 시스템이나 사용자 데이터가 망가지는가.

    보호 폴더 '자신' 과 그 '상위' 폴더(C:\\Users, OneDrive 루트 등)를 막는다.
    보호 폴더 '안쪽' 의 개별 항목은 여기서 막지 않는다 — 앱 잔여물이 그 안에 있기 때문이다.
    Windows 폴더처럼 안쪽 전체가 금지인 곳은 is_system_area() 가 맡는다.
    """
    try:
        forms = _forms(path)
    except Exception:
        return True
    if not forms:
        return True
    for p in forms:
        if not p or _is_drive_root(p) or len(p) <= 3:      # "C:\" 같은 드라이브 루트
            return True
        if p.startswith('\\\\'):
            # 네트워크 공유 루트(\\server\share) 자체
            if len([x for x in p[2:].split('\\') if x]) <= 2:
                return True
        if p in PROTECTED_DIRS:
            return True
        # 보호 폴더의 상위(예: C:\Users, 바탕 화면이 들어 있는 OneDrive 폴더)
        prefix = p + '\\'
        if any(d.startswith(prefix) for d in PROTECTED_DIRS):
            return True
        if _is_users_dir_or_profile(p):
            return True
        if os.path.basename(p) in NEVER_LEFTOVER:
            return True
    return False


def is_system_area(path):
    """Windows 폴더처럼 안쪽 어디라도 사용자 기능으로 지우면 안 되는 곳인가."""
    try:
        forms = _forms(path)
    except Exception:
        return True
    for p in forms:
        for root in SYSTEM_AREAS:
            if p == root or p.startswith(root + '\\'):
                return True
        parts = p.split('\\')
        if len(parts) >= 2 and _is_drive_root(parts[0]) and parts[1] in _ROOT_SYSTEM_NAMES:
            return True
    return False


def is_inside(path, root):
    """path 가 root 안에 있는가. 문자열 startswith 만 쓰면
    C:\\ProgramData2 가 C:\\ProgramData 안에 있다고 잘못 판정한다."""
    p, r = norm(path), norm(root)
    if not r:
        return False
    return p == r or p.startswith(r + os.sep)


# ── 재분석 지점·자리표시자 ────────────────────────────────────
def is_link_like(st):
    """정션·심볼릭 링크·마운트 지점처럼 다른 경로를 가리키는가 (lstat 결과로 판정).

    태그를 모르는 재분석 지점도 링크로 본다. 클라우드 파일(OneDrive)은 링크가 아니다.
    """
    attrs = getattr(st, 'st_file_attributes', 0) or 0
    if not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(st, 'st_reparse_tag', 0) or 0
    return tag == 0 or bool(tag & _NAME_SURROGATE_BIT)


def is_cloud_placeholder(st):
    """내용이 PC 에 없는 클라우드 자리표시자인가. 읽으면 내려받기가 시작된다."""
    return bool((getattr(st, 'st_file_attributes', 0) or 0) & CLOUD_PLACEHOLDER_ATTRS)


# ── 드라이브·휴지통 정보 (읽기만) ─────────────────────────────
def volume_root(path):
    """경로가 속한 볼륨의 루트(C:\\, 폴더에 마운트된 볼륨이면 그 폴더)."""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        if _kernel32().GetVolumePathNameW(str(path), buf, 1024):
            r = buf.value
            return r if r.endswith('\\') else r + '\\'
    except Exception:
        pass
    d = os.path.splitdrive(str(path))[0]
    return (d + '\\') if d else None


def letter_drive_type(path):
    """드라이브 문자만 보고 종류를 판정한다. 끊긴 네트워크 드라이브에서도 기다리지 않는다."""
    d = os.path.splitdrive(str(path))[0]
    if len(d) != 2 or d[1] != ':':
        return 'unknown'
    try:
        return _DRIVE_TYPE_NAMES.get(_kernel32().GetDriveTypeW(d + '\\'), 'unknown')
    except Exception:
        return 'unknown'


def drive_type(path):
    """'fixed' | 'removable' | 'network' | 'cdrom' | 'ramdisk' | 'unknown'"""
    root = volume_root(path)
    if not root:
        return 'unknown'
    if root.startswith('\\\\') and not root.startswith('\\\\?\\'):
        return 'network'
    try:
        return _DRIVE_TYPE_NAMES.get(_kernel32().GetDriveTypeW(root), 'unknown')
    except Exception:
        return 'unknown'


def logical_drives():
    """드라이브 문자 루트 목록 ['C:\\', 'D:\\', ...]."""
    try:
        mask = _kernel32().GetLogicalDrives()
    except Exception:
        return ['C:\\']
    return [f"{chr(65 + i)}:\\" for i in range(26) if mask & (1 << i)]


def is_subst_drive(root):
    """subst 로 만든 가상 드라이브인가. 실제 볼륨의 폴더를 한 번 더 보여줄 뿐이다."""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        if _kernel32().QueryDosDeviceW(str(root)[:2], buf, 1024):
            return buf.value.startswith('\\??\\')
    except Exception:
        pass
    return False


def volume_guid(root):
    """'{3f85356e-...}' 형태의 볼륨 GUID. 모르면 None."""
    try:
        r = str(root)
        if not r.endswith('\\'):
            r += '\\'
        buf = ctypes.create_unicode_buffer(64)
        if _kernel32().GetVolumeNameForVolumeMountPointW(r, buf, 64):
            v = buf.value
            a, b = v.find('{'), v.find('}')
            if a != -1 and b > a:
                return v[a:b + 1].lower()
    except Exception:
        pass
    return None


def _reg_dword(hive, path, name):
    try:
        import winreg
        with winreg.OpenKey(hive, path) as k:
            v, t = winreg.QueryValueEx(k, name)
            return int(v) if t == winreg.REG_DWORD else None
    except Exception:
        return None


def _recycle_policy():
    """(휴지통이 정책으로 꺼졌는가, 정책상 최대 크기 %)"""
    import winreg
    pol = r'Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'
    disabled, pct = False, None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        if _reg_dword(hive, pol, 'NoRecycleFiles') == 1:
            disabled = True
        v = _reg_dword(hive, pol, 'RecycleBinSize')
        if v is not None and 0 <= v <= 100:
            pct = v if pct is None else min(pct, v)
    return disabled, pct


def recycle_bin_limit(path):
    """path 가 있는 볼륨의 휴지통이 받아 주는 최대 바이트와, 받을 수 없으면 그 이유.

    반환: (limit_bytes, reason). reason 이 None 이 아니면 limit 은 0 이다.
    최대 크기는 사용자 설정(BitBucket MaxCapacity)을 읽고, 모르면 보수적으로 잡는다.
    """
    root = volume_root(path)
    dtype = drive_type(path)
    if dtype != 'fixed':
        return 0, _DRIVE_TYPE_REASON.get(dtype, _DRIVE_TYPE_REASON['unknown'])
    import winreg
    disabled, pct = _recycle_policy()
    if disabled:
        return 0, '정책으로 휴지통이 꺼져 있습니다'

    guid = volume_guid(root)
    max_mb = nuke = None
    if guid:
        key = r'Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume' + '\\' + guid
        max_mb = _reg_dword(winreg.HKEY_CURRENT_USER, key, 'MaxCapacity')
        nuke = _reg_dword(winreg.HKEY_CURRENT_USER, key, 'NukeOnDelete')
    if nuke == 1:
        return 0, '이 드라이브는 휴지통을 쓰지 않도록 설정돼 있습니다'

    try:
        total = shutil.disk_usage(root).total
    except Exception:
        total = 0
    if max_mb is None:
        cap = total * _DEFAULT_BIN_PERCENT // 100
    else:
        cap = max_mb * 1024 * 1024
    if pct is not None:
        cap = min(cap, total * pct // 100)
    cap = int(cap * _BIN_SAFETY)
    if cap <= 0:
        return 0, '휴지통 크기를 확인할 수 없습니다'
    return cap, None


def fmt_bytes(n):
    mb = n / (1024 ** 2)
    return f"{mb / 1024:.1f}GB" if mb >= 1024 else f"{mb:.0f}MB"


def _measure(path):
    """(바이트, 전부 셌는가). 링크 안으로는 들어가지 않는다.

    일부를 못 읽었으면 실제 크기가 더 클 수 있으므로 complete=False 로 알린다.
    """
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return 0, False
    if not st.st_file_attributes & FILE_ATTRIBUTE_DIRECTORY:
        return st.st_size, True
    total, complete = 0, True
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            complete = False
            continue
        with it:
            for e in it:
                try:
                    s = e.stat(follow_symlinks=False)
                except OSError:
                    complete = False
                    continue
                if is_link_like(s):
                    continue        # 링크는 가리키는 대상이 아니라 링크 자신만 옮겨진다
                if s.st_file_attributes & FILE_ATTRIBUTE_DIRECTORY:
                    stack.append(e.path)
                else:
                    total += s.st_size
    return total, complete


def _size_of(path):
    return _measure(path)[0]


def _shell_path(path):
    """셸에 넘길 경로. 상위 폴더의 링크는 풀고, 마지막 이름은 그대로 둔다.

    소문자로 바꾸지 않는다 — 휴지통은 넘긴 경로를 원래 위치로 기록하므로,
    소문자로 넘기면 복원할 때 파일 이름이 바뀐다.
    """
    s = os.path.abspath(_strip_prefix(path)).rstrip('\\')
    parent, name = os.path.split(s)
    try:
        parent = _strip_prefix(os.path.realpath(parent))
    except Exception:
        pass
    return os.path.join(parent, name)


_SHELL_ERRORS = {
    2: '파일을 찾을 수 없습니다',
    3: '경로를 찾을 수 없습니다',
    5: '접근이 거부되었습니다',
    32: '다른 프로그램이 사용 중입니다',
    0x78: '접근이 거부되었습니다',
    0x7C: '경로가 올바르지 않습니다',
    0x4C7: '취소되었습니다(영구 삭제 확인에서 거절)',
}


def _shell_recycle(path):
    """셸로 한 항목을 휴지통에 보낸다. 반환: (셸 반환값, 중단 여부)"""
    buf = ctypes.create_unicode_buffer(path + '\0')   # pFrom 은 이중 널로 끝나야 한다
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.wintypes.LPCWSTR)
    op.pTo = None
    op.fFlags = _RECYCLE_FLAGS
    op.fAnyOperationsAborted = False
    res = _shell32().SHFileOperationW(ctypes.byref(op))
    return res, bool(op.fAnyOperationsAborted)


_recycle_lock = threading.Lock()


def to_recycle_bin(paths):
    """파일/폴더를 휴지통으로 보낸다.

    반환: {"ok": [...], "failed": [{path, reason}], "bytes": n,
           "not_recyclable": [{path, reason}]}
      - ok             : 휴지통으로 옮긴 경로(호출부가 넘긴 문자열 그대로)
      - failed         : 보호 경로라 거부했거나, 옮기다 실패한 항목
      - not_recyclable : 휴지통에 들어가지 않는 항목(이동식·네트워크 드라이브, 휴지통 꺼짐,
                         휴지통 최대 크기 초과, 온라인 전용 파일). 전혀 건드리지 않았다.
      - bytes          : 휴지통으로 옮긴 크기. 휴지통을 비우기 전까지 디스크 공간은 그대로다.
    """
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, (list, tuple)):
        return {"ok": [], "failed": [{"path": paths, "reason": "잘못된 입력"}],
                "bytes": 0, "not_recyclable": []}

    with _recycle_lock:
        return _to_recycle_bin_locked(list(paths))


def _to_recycle_bin_locked(paths):
    ok, failed, not_recyclable = [], [], []
    candidates = []          # (원래 경로, 셸 경로, 비교 키)
    seen = set()

    for p in paths:
        try:
            if not isinstance(p, str) or not p.strip():
                failed.append({"path": p, "reason": "잘못된 경로"})
                continue
            if p.startswith('\\\\') or p.startswith('//'):
                if p[2:4] in ('?\\', '.\\', '?/', './') and not p.upper().startswith('\\\\?\\UNC\\'):
                    failed.append({"path": p, "reason": "지원하지 않는 경로 형식"})
                else:
                    not_recyclable.append({"path": p, "reason": "네트워크 경로에는 휴지통이 없습니다"})
                continue
            if not os.path.isabs(p) or ':' in p[2:]:
                failed.append({"path": p, "reason": "잘못된 경로"})
                continue
            # 파일에 손대기 전에 드라이브 종류부터 본다(끊긴 네트워크 드라이브에서 멈추지 않도록)
            letter_type = letter_drive_type(p)
            if letter_type != 'fixed':
                not_recyclable.append({"path": p, "reason": _DRIVE_TYPE_REASON.get(
                    letter_type, _DRIVE_TYPE_REASON['unknown'])})
                continue
            if not os.path.lexists(p):
                failed.append({"path": p, "reason": "존재하지 않음"})
                continue
            st = os.stat(p, follow_symlinks=False)
            if is_link_like(st):
                # 링크를 풀어서 지우면 링크가 가리키는 원본 폴더가 사라진다
                failed.append({"path": p, "reason": "링크(정션·심볼릭 링크)는 건드리지 않습니다"})
                continue
            shell_path = _shell_path(p)
            if shell_path.startswith('\\\\'):
                not_recyclable.append({"path": p, "reason": "네트워크 경로에는 휴지통이 없습니다"})
                continue
            if is_protected(p) or is_system_area(p):
                failed.append({"path": p, "reason": "보호된 시스템/사용자 폴더"})
                log.warning(f"보호 경로 삭제 거부: {p}")
                continue
            if is_cloud_placeholder(st):
                not_recyclable.append({"path": p, "reason": "온라인 전용 파일이라 PC 휴지통에 들어가지 않습니다"})
                continue
            key = norm(p)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((p, shell_path, key))
        except Exception as e:
            failed.append({"path": p, "reason": str(e)})

    # 상위 폴더와 그 안의 항목이 함께 오면 상위만 옮긴다(안쪽은 함께 옮겨진다)
    by_len = sorted(candidates, key=lambda c: len(c[2]))
    top_keys, covered = [], {}
    for c in by_len:
        parent = next((k for k in top_keys if c[2].startswith(k + '\\')), None)
        if parent:
            covered[c[2]] = parent
        else:
            top_keys.append(c[2])

    # 휴지통에 실제로 들어가는지 확인한다. 한 번에 보내는 양도 합산한다 —
    # 휴지통이 넘치면 Windows 는 오래된 항목부터 영구 삭제하므로, 이번에 보낸 것끼리
    # 서로 밀어내면 '휴지통으로 보냄' 이라고 보고한 파일이 사라진다.
    limits, used = {}, {}
    targets = []             # (원래 경로, 셸 경로, 키, 크기)
    for p, shell_path, key in candidates:
        if key in covered:
            continue
        try:
            root = volume_root(shell_path) or ''
            vkey = volume_guid(root) or root.lower()
            if vkey not in limits:
                limits[vkey] = recycle_bin_limit(shell_path)
            limit, why = limits[vkey]
            if why:
                not_recyclable.append({"path": p, "reason": why})
                continue
            size, complete = _measure(shell_path)
            if not complete:
                not_recyclable.append({"path": p, "reason": "크기를 모두 확인할 수 없어 휴지통에 들어가는지 알 수 없습니다"})
                continue
            if size > limit:
                not_recyclable.append({"path": p, "reason": f"휴지통 최대 크기({fmt_bytes(limit)})보다 커서 휴지통에 들어가지 않습니다"})
                continue
            if used.get(vkey, 0) + size > limit:
                not_recyclable.append({"path": p, "reason": "한 번에 옮기는 양이 휴지통 크기를 넘습니다. 나눠서 지우세요"})
                continue
            used[vkey] = used.get(vkey, 0) + size
            targets.append((p, shell_path, key, size))
        except Exception as e:
            failed.append({"path": p, "reason": str(e)})

    freed = 0
    done_keys = set()
    for p, shell_path, key, size in targets:
        try:
            res, aborted = _shell_recycle(shell_path)
        except Exception as e:
            failed.append({"path": p, "reason": str(e)})
            continue
        # 반환값만 믿지 않는다. 실제로 사라졌는지 확인한다.
        if os.path.lexists(shell_path):
            reason = _SHELL_ERRORS.get(res, f"셸 오류 코드 {res}") if res else "옮기지 못했습니다(취소됨)"
            failed.append({"path": p, "reason": reason})
        else:
            ok.append(p)
            done_keys.add(key)
            freed += size
            log.info(f"휴지통으로 이동: {shell_path} ({size} bytes)")
            if res != 0 or aborted:
                log.warning(f"셸이 오류({res})를 돌려줬지만 항목은 사라졌다: {shell_path}")

    for p, shell_path, key in candidates:
        parent = covered.get(key)
        if parent is None:
            continue
        if parent in done_keys:
            ok.append(p)       # 상위 폴더와 함께 옮겨졌다(크기는 상위에 포함)
        else:
            failed.append({"path": p, "reason": "상위 폴더를 옮기지 못했습니다"})

    return {"ok": ok, "failed": failed, "bytes": freed if ok else 0,
            "not_recyclable": not_recyclable}


def permanent_delete(paths, reason):
    """휴지통을 쓸 수 없는 경우에만 쓰는 영구 삭제.

    호출부는 reason 을 반드시 적어야 한다. 왜 복구 불가능한 삭제가 필요한지
    코드에 남기지 않으면 나중에 아무도 판단할 수 없다.
    임시 파일(%TEMP%)처럼 휴지통에 넣는 것이 오히려 디스크를 더 먹는 경우가 이에 해당한다.
    """
    if isinstance(paths, str):
        paths = [paths]
    ok, failed, freed = [], [], 0
    for p in paths:
        try:
            if not isinstance(p, str) or not os.path.lexists(p):
                continue
            if p.startswith('\\\\') or p.startswith('//'):
                failed.append({"path": p, "reason": "네트워크·장치 경로"})
                continue
            if is_protected(p) or is_system_area(p):
                failed.append({"path": p, "reason": "보호된 경로"})
                continue
            if is_link_like(os.stat(p, follow_symlinks=False)):
                failed.append({"path": p, "reason": "링크(정션·심볼릭 링크)"})
                continue
            sz = _size_of(p)
            if os.path.isfile(p):
                os.unlink(p)
            else:
                shutil.rmtree(p, ignore_errors=False)
            ok.append(p)
            freed += sz
        except Exception as e:
            failed.append({"path": p, "reason": str(e)})
    log.info(f"영구 삭제({reason}): 성공 {len(ok)} 실패 {len(failed)}")
    return {"ok": ok, "failed": failed, "bytes": freed}
