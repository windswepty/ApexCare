"""
APEX CARE — 되돌릴 수 있는 삭제 계층.

이 앱의 모든 삭제는 이 모듈을 거친다. 이유는 하나다.
상업용 최적화 도구에서 사용자 파일을 휴지통도 거치지 않고 지우는 것은 허용되지 않는다.
복구 수단이 없는 삭제는 버그 하나가 곧바로 사용자 데이터 소실로 이어진다.

제공하는 것:
  - to_recycle_bin()  : 휴지통으로 보낸다(복구 가능). 기본 경로.
  - permanent_delete(): 휴지통을 못 쓰는 경우에만 쓰는 최후 수단. 호출부가 명시적으로 선택해야 한다.
  - is_protected()    : 절대 건드리면 안 되는 경로인지 판정한다.
  - classify_path()   : 경로가 무엇인지(시스템/사용자문서/앱데이터/임시) 알려준다.

Windows 셸 API(SHFileOperationW)를 쓴다. FOF_ALLOWUNDO 플래그가 휴지통 경유를 보장한다.
"""

import ctypes
import ctypes.wintypes
import logging
import os

log = logging.getLogger('SafeDelete')

# ── SHFileOperationW 상수 ─────────────────────────────────────
FO_DELETE = 0x0003
FOF_SILENT = 0x0004          # 진행 대화상자 숨김
FOF_NOCONFIRMATION = 0x0010  # "정말 지울까요" 묻지 않음 (우리가 이미 물어봤다)
FOF_ALLOWUNDO = 0x0040       # ★ 휴지통 경유 — 이게 없으면 영구 삭제다
FOF_NOERRORUI = 0x0400       # 오류 대화상자 숨김 (반환값으로 처리)
FOF_NOCONFIRMMKDIR = 0x0200


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


# ── 절대 삭제 금지 경로 ────────────────────────────────────────
# 소문자로 비교한다. 경로가 이 중 하나와 같거나 그 '바로 그 폴더'이면 거부한다.
def _protected_roots():
    env = os.environ.get
    raw = [
        env('SystemRoot'), env('windir'),
        env('ProgramFiles'), env('ProgramFiles(x86)'), env('ProgramW6432'),
        env('ProgramData'), env('APPDATA'), env('LOCALAPPDATA'),
        env('USERPROFILE'), env('PUBLIC'), env('SystemDrive'),
        env('TEMP'), env('TMP'),
    ]
    home = env('USERPROFILE') or ''
    if home:
        # 사용자 개인 데이터 폴더 자체는 통째로 지워지면 안 된다
        raw += [os.path.join(home, d) for d in
                ('Documents', 'Desktop', 'Downloads', 'Pictures', 'Videos',
                 'Music', 'OneDrive', 'Favorites', 'Links', 'Contacts',
                 'Saved Games', 'Searches')]
    out = set()
    for p in raw:
        if p:
            out.add(os.path.normpath(p).rstrip('\\').lower())
    return out


PROTECTED_DIRS = _protected_roots()

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


def norm(path):
    """경로를 비교 가능한 정규형으로 만든다.

    ..\\ 로 상위 폴더를 탈출하거나, 심볼릭 링크로 보호 경로를 우회하는 것을 막으려면
    문자열 비교 전에 반드시 실경로로 풀어야 한다.
    """
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path))).rstrip('\\')
    except Exception:
        return os.path.normcase(os.path.abspath(path)).rstrip('\\')


def is_protected(path):
    """이 경로를 통째로 지우면 시스템이나 사용자 데이터가 망가지는가."""
    p = norm(path)
    if not p or len(p) <= 3:      # "C:\" 같은 드라이브 루트
        return True
    if p in PROTECTED_DIRS:
        return True
    # 드라이브 루트 바로 아래 한 단계(C:\Windows 등)도 거부
    parent = os.path.dirname(p)
    if len(parent) <= 3 and os.path.basename(p).lower() in NEVER_LEFTOVER:
        return True
    if os.path.basename(p).lower() in NEVER_LEFTOVER:
        return True
    return False


def is_inside(path, root):
    """path 가 root 안에 있는가. 문자열 startswith 만 쓰면
    C:\\ProgramData2 가 C:\\ProgramData 안에 있다고 잘못 판정한다."""
    p, r = norm(path), norm(root)
    if not r:
        return False
    return p == r or p.startswith(r + os.sep)


def to_recycle_bin(paths):
    """파일/폴더를 휴지통으로 보낸다.

    반환: {"ok": [...], "failed": [{path, reason}], "bytes": n}
    보호 경로는 거부하고 failed 에 이유와 함께 담는다.
    """
    if isinstance(paths, str):
        paths = [paths]

    ok, failed, freed = [], [], 0
    targets = []

    for p in paths:
        try:
            if not p or not os.path.exists(p):
                failed.append({"path": p, "reason": "존재하지 않음"})
                continue
            if is_protected(p):
                failed.append({"path": p, "reason": "보호된 시스템/사용자 폴더"})
                log.warning(f"보호 경로 삭제 거부: {p}")
                continue
            targets.append(norm(p))
        except Exception as e:
            failed.append({"path": p, "reason": str(e)})

    if not targets:
        return {"ok": ok, "failed": failed, "bytes": 0}

    # 삭제 전에 크기를 재둔다. 지운 뒤에는 잴 수 없다.
    for t in targets:
        try:
            freed += _size_of(t)
        except Exception:
            pass

    # pFrom 은 이중 널로 끝나는 문자열 목록이다
    buf = '\0'.join(targets) + '\0\0'
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = buf
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    op.fAnyOperationsAborted = False

    try:
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as e:
        return {"ok": [], "failed": failed + [{"path": t, "reason": str(e)} for t in targets], "bytes": 0}

    if res == 0 and not op.fAnyOperationsAborted:
        ok = targets
    else:
        # 부분 성공일 수 있다. 실제로 사라졌는지 확인해서 가른다.
        for t in targets:
            if os.path.exists(t):
                failed.append({"path": t, "reason": f"셸 오류 코드 {res}"})
            else:
                ok.append(t)

    # 아무것도 못 지웠으면 확보 용량도 0 이어야 한다
    return {"ok": ok, "failed": failed, "bytes": freed if ok else 0}


def _size_of(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dp, _, fs in os.walk(path):
        for f in fs:
            fp = os.path.join(dp, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except Exception:
                pass
    return total


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
            if not os.path.exists(p):
                continue
            if is_protected(p):
                failed.append({"path": p, "reason": "보호된 경로"})
                continue
            sz = _size_of(p)
            if os.path.isfile(p):
                os.unlink(p)
            else:
                import shutil
                shutil.rmtree(p, ignore_errors=False)
            ok.append(p)
            freed += sz
        except Exception as e:
            failed.append({"path": p, "reason": str(e)})
    log.info(f"영구 삭제({reason}): 성공 {len(ok)} 실패 {len(failed)}")
    return {"ok": ok, "failed": failed, "bytes": freed}
