"""
APEX CARE — 프로그램 제거 및 잔여물 정리.

이전 구현의 치명적 결함과 수정 내용:

1. 잔여물 탐색이 앱 이름의 '첫 단어'만 써서 폴더명에 부분 일치시켰다.
   'Adobe Acrobat' 을 지우려 하면 검색어가 'adobe' 가 되어 Adobe 폴더 6개
   (실측 22.8GB — 포토샵·프리미어 포함)가 전부 잔여물로 잡혔고,
   'Steam' 은 게임 라이브러리 7.1GB 가 통째로 잡혔다.
   프론트는 이 목록을 전부 shutil.rmtree 로 넘겼다.
   → 레지스트리의 InstallLocation 을 1순위로 쓰고, 없을 때만 엄격한 이름 대조를 한다.
     부분 일치는 더 이상 쓰지 않는다.

2. 삭제가 shutil.rmtree 였다. 휴지통을 거치지 않아 복구가 불가능했다.
   → safe_delete.to_recycle_bin 으로 바꿨다.

3. UninstallString 을 shell=True 로 그대로 실행했다.
   → CommandLineToArgvW 로 파싱해 shell 없이 실행한다.

4. 제거가 실제로 됐는지 확인하지 않고 성공을 반환했다.
   → 프로세스 기동을 확인하고, 제거 완료 여부는 별도로 확인할 수 있게 했다.
"""

import ctypes
import logging
import os
import re
import subprocess
import winreg

from backend import safe_delete

log = logging.getLogger('Uninstaller')

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def _clean(s):
    return s.replace('\x00', '').strip() if isinstance(s, str) else s


def _read(subkey, name, default=''):
    """값을 읽는다. REG_EXPAND_SZ 는 %windir% 같은 환경 변수를 펼친다(Windows '앱 및 기능' 과 같다).

    예전에는 펼치지 않아 '%windir%\\system32\\sdbinst.exe' 같은 제거 명령이 실행되지 않았고,
    '제거 프로그램을 찾을 수 없습니다' 라는 틀린 안내가 떴다.
    """
    try:
        value, vtype = winreg.QueryValueEx(subkey, name)
    except Exception:
        return default
    if vtype == getattr(winreg, 'REG_EXPAND_SZ', 2) and isinstance(value, str):
        try:
            value = winreg.ExpandEnvironmentStrings(value)
        except Exception:
            value = os.path.expandvars(value)
    return _clean(value)


# 표시 이름 → 프로그램이 등록한 InstallLocation·게시자. 목록을 읽을 때마다 채운다(이 프로세스 동안 유지).
# 제거가 끝나면 등록 정보가 지워지므로, 잔여물 탐색은 제거 전에 읽어 둔 이 값을 쓴다.
_known_locations = {}
_known_publishers = {}


def _format_install_date(raw):
    """레지스트리의 InstallDate(보통 20240115)를 2024-01-15 로. 형식이 다르면 그대로."""
    s = str(raw or '').strip()
    if re.fullmatch(r'(19|20)\d{6}', s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def get_installed_apps():
    """설치된 프로그램 목록.

    InstallLocation 을 함께 읽는다. 잔여물 탐색이 추측 대신 이 값을 쓴다.
    """
    apps, seen, app_id = [], set(), 0

    for hkey, path in UNINSTALL_KEYS:
        try:
            with winreg.OpenKey(hkey, path) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                            name = _read(sub, "DisplayName")
                            if not name or name in seen:
                                continue
                            uninstall_string = _read(sub, "UninstallString")
                            if not uninstall_string:
                                continue
                            # 시스템 업데이트 항목은 목록에서 뺀다
                            if _read(sub, "SystemComponent") == 1 or _read(sub, "ParentKeyName"):
                                continue

                            size_kb = 0
                            try:
                                size_kb = winreg.QueryValueEx(sub, "EstimatedSize")[0]
                            except Exception:
                                pass

                            seen.add(name)
                            app_id += 1
                            location = _read(sub, "InstallLocation")
                            if isinstance(location, str) and location.strip():
                                # 제거가 끝나면 레지스트리에서 사라진다. 잔여물 탐색이 쓰도록 기억해 둔다.
                                _known_locations[name] = location.strip().strip('"')
                            pub = _read(sub, "Publisher")
                            if isinstance(pub, str) and pub.strip():
                                _known_publishers[name] = pub.strip()
                            apps.append({
                                "id": str(app_id),
                                "name": name,
                                "publisher": _read(sub, "Publisher"),
                                "installDate": _format_install_date(_read(sub, "InstallDate")),
                                "sizeMB": round(size_kb / 1024) if isinstance(size_kb, int) and size_kb > 0 else 0,
                                "uninstallString": uninstall_string,
                                "installLocation": location if isinstance(location, str) else '',
                                "quietUninstall": _read(sub, "QuietUninstallString"),
                                # 이 계정에만 설치된 프로그램(HKCU). 그 제거 프로그램은 일반 권한으로 바꿔 넣을 수 있다
                                "scope": 'user' if hkey == winreg.HKEY_CURRENT_USER else 'machine',
                            })
                    except Exception as e:
                        log.debug(f"하위 키 읽기 실패: {e}")
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning(f"레지스트리 키 읽기 실패 {path}: {e}")

    apps.sort(key=lambda x: x["name"].lower())
    return apps


def _split_command(cmdline):
    """Windows 규칙대로 명령줄을 인자 배열로 나눈다.

    shell=True 를 쓰면 UninstallString 안의 & | > 같은 문자가 셸 메타문자로
    해석된다. CommandLineToArgvW 는 Windows 자신이 쓰는 파서라 결과가 정확하고,
    이렇게 나눈 배열을 shell=False 로 넘기면 셸이 개입할 여지가 없어진다.
    """
    try:
        argc = ctypes.c_int()
        ctypes.windll.shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        argv = ctypes.windll.shell32.CommandLineToArgvW(cmdline, ctypes.byref(argc))
        if not argv:
            return None
        try:
            return [argv[i] for i in range(argc.value)]
        finally:
            ctypes.windll.kernel32.LocalFree(argv)
    except Exception as e:
        log.warning(f"명령줄 파싱 실패: {e}")
        return None


def uninstall_by_name(app_name):
    """목록에 있는 프로그램의 제거 프로그램을 실행한다. 명령줄은 레지스트리에서 직접 읽는다.

    예전에는 화면이 넘긴 UninstallString 을 그대로 실행했다. 관리자 권한 창이 UI 에서 온 문자열을
    명령으로 실행하면 안 된다. 이제 화면은 이름만 넘기고, 명령은 백엔드가 레지스트리에서 찾는다.
    """
    if not isinstance(app_name, str) or not app_name.strip():
        return {"success": False, "message": "프로그램 이름이 올바르지 않습니다."}
    match = next((a for a in get_installed_apps() if a['name'] == app_name), None)
    if not match:
        return {"success": False,
                "message": f"'{app_name}' 을(를) 설치된 프로그램 목록에서 찾지 못했습니다. 이미 제거되었을 수 있습니다."}
    return run_uninstall(match['uninstallString'], user_scope=match.get('scope') == 'user')


def _admin_only_path(path):
    """관리자만 쓸 수 있는 곳(Program Files·Windows 폴더) 안의 파일인가. 실경로로 판단한다."""
    try:
        real = safe_delete.norm(path)
    except Exception:
        return False
    roots = [os.environ.get(v) for v in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'SystemRoot')]
    return any(r and safe_delete.is_inside(real, safe_delete.norm(r)) for r in roots)


def _open_apps_settings():
    """Windows 설정 → 앱을 연다(실패해도 안내 문구는 그대로 보여 준다)."""
    try:
        os.startfile('ms-settings:appsfeatures')
    except Exception as e:
        log.debug(f"설정 앱을 열지 못했습니다: {e}")


def run_uninstall(uninstall_string, user_scope=False):
    """제거 프로그램을 실행한다.

    셸을 거치지 않는다. 대부분의 언인스톨러는 자체 UI 를 띄우므로 기동만 확인하고
    반환한다. 실제 제거 완료 여부는 verify_uninstalled() 로 따로 확인해야 한다.
    """
    if not uninstall_string or not isinstance(uninstall_string, str):
        return {"success": False, "message": "제거 명령이 비어 있습니다."}

    args = _split_command(uninstall_string)
    if not args:
        return {"success": False, "message": "제거 명령을 해석하지 못했습니다."}

    exe = args[0]
    # MSI 는 /I(설치)를 /X(제거)로 바꿔야 한다.
    # 문자열 전체에 replace 를 걸면 경로 안의 '/i' 까지 망가지므로 인자 단위로 바꾼다.
    if os.path.basename(exe).lower().startswith('msiexec'):
        # 실제 문자열은 '/I{GUID}' 처럼 스위치와 값이 붙어 있는 경우가 대부분이라
        # 정확히 '/i' 인 인자만 찾으면 아무것도 바뀌지 않는다. 접두사 형태도 처리한다.
        def _to_uninstall(a):
            if a.lower() in ('/i', '-i'):
                return '/x'
            if len(a) > 2 and a[0] in '/-' and a[1] in 'iI':
                return a[0] + 'x' + a[2:]
            return a
        args = [_to_uninstall(a) for a in args]

    if not os.path.isabs(args[0]):
        # 'MsiExec.exe /X{…}' 처럼 이름만 적힌 제거 명령. 이름만 넘기면 CreateProcess 가 '현재 폴더' 를 System32 보다
        # 먼저 찾는다(관리자 권한 실행). Windows 폴더의 도구일 때만 그 절대 경로로 실행한다.
        from backend.system_repair import sys_tool
        candidate = sys_tool(os.path.basename(args[0]) if args[0].lower().endswith('.exe') else args[0] + '.exe')
        if not os.path.isfile(candidate):
            return {"success": False,
                    "message": f"제거 명령의 실행 파일 위치가 적혀 있지 않습니다: {exe}\n"
                               "Windows 의 '설정 → 앱' 에서 제거해 주세요."}
        args = [candidate] + args[1:]

    if user_scope or not _admin_only_path(args[0]):
        # 이 계정에만 설치된 프로그램이거나 제거 프로그램이 사용자 폴더(%LOCALAPPDATA%, C:\Games 같은 곳)에 있다.
        # 그 exe 는 일반 권한 프로그램도 바꿔 넣을 수 있어, 관리자 권한인 이 앱이 실행하면 권한을 넘겨주게 된다.
        # Windows 설정 → 앱은 이런 제거 프로그램을 일반 권한으로 실행한다. 그쪽을 열어 준다.
        _open_apps_settings()
        return {"success": False, "needsSettings": True,
                "message": "이 프로그램은 사용자 폴더에 설치돼 있어 APEX CARE(관리자 권한)가 제거 프로그램을 실행하지 않습니다. "
                           "열린 Windows 설정 → 앱에서 제거한 뒤 '제거를 마쳤습니다' 를 누르면 남은 폴더를 찾아 드립니다."}

    try:
        proc = subprocess.Popen(args, shell=False)
    except FileNotFoundError:
        return {"success": False,
                "message": f"제거 프로그램을 찾을 수 없습니다: {exe}\n"
                           "이미 삭제되었거나 경로가 바뀌었을 수 있습니다."}
    except Exception as e:
        return {"success": False, "message": f"제거 프로그램 실행 실패: {e}"}

    return {
        "success": True,
        "pid": proc.pid,
        "message": "제거 프로그램을 실행했습니다. 화면의 안내를 따라 제거를 마쳐 주세요.",
    }


def verify_uninstalled(app_name):
    """레지스트리에 아직 남아 있는지 확인한다.

    제거가 끝나지 않았는데 잔여물 정리를 진행하면, 아직 쓰이고 있는 폴더를 지우게 된다.
    """
    still_there = any(a['name'] == app_name for a in get_installed_apps())
    return {
        "uninstalled": not still_there,
        "message": ("제거가 확인되었습니다." if not still_there else
                    "아직 프로그램 목록에 남아 있습니다. 제거가 끝난 뒤 다시 확인해 주세요."),
    }


# ─────────────────────────────────────────────
# 잔여물 탐색
# ─────────────────────────────────────────────

def _normalize(s):
    """이름 비교용 정규화. 괄호 주석과 버전 표기를 없앤다.

    버전으로 인정하는 것은 '점이 있는 숫자'(22.01, 3.12.1)나 'v' 가 붙은 숫자뿐이다.
    예전에는 \\b\\d+\\b 로 독립된 숫자를 전부 지웠는데, '-' 가 단어 경계라서
    '7-Zip' 의 7 까지 사라져 'zip' 이 됐다. 그러면 'Zip' 이라는 무관한 폴더와
    이름이 일치해 엉뚱한 폴더가 삭제 후보로 올라간다.
    """
    s = re.sub(r'\(.*?\)', ' ', s or '')                # (x64), (ko) 등
    s = re.sub(r'\s+v?\d+(?:\.\d+)+\b', ' ', s)         # 22.01, 3.12.1, v1.2
    s = re.sub(r'\s+v\d+\b', ' ', s)                    # v8
    s = re.sub(r'[^0-9a-z가-힣]+', '', s.lower())
    return s


FOLDER_SIZE_CAP = 40 * 1024 ** 3


def _folder_size(path, cap_bytes=FOLDER_SIZE_CAP):
    """폴더 크기(바이트)와 끝까지 세지 않고 멈췄는지.

    너무 큰 폴더는 cap_bytes 를 넘으면 세기를 멈춘다. 그때의 합계는 실제 크기가 아니라
    '이 이상' 이므로 capped=True 로 알린다. 예전에는 멈춘 값을 정확한 크기처럼 보여 줬다.
    링크·정션 너머는 세지 않는다(휴지통으로 보내도 그쪽 파일은 지워지지 않는다).
    """
    try:
        return safe_delete.walk_size(path, cap_bytes=cap_bytes)
    except Exception:
        return 0, False


_COMPANY_SUFFIX = re.compile(r'\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|gmbh|ag|sa|bv|'
                             r'pty|plc|srl|software|technologies|technology)\b\.?', re.I)


def _shared_folder_reason(location, app_name, publisher):
    """등록된 설치 경로가 이 프로그램만의 폴더가 아니면 그 이유. 이 프로그램만의 폴더면 None.

    Adobe Premiere Pro·After Effects·Media Encoder 는 InstallLocation 에 자기 폴더가 아니라
    'C:\\Program Files\\Adobe' 를 적는다(이 개발 PC 에서 확인). 그대로 믿으면 Creative Cloud·Acrobat 까지
    '확실한 잔여물' 로 휴지통에 갔다. 제조사 폴더, 다른 프로그램도 등록한 폴더, 다른 프로그램의 설치 경로를
    품은 폴더는 통째로 올리지 않는다.
    """
    loc = safe_delete.norm(location)
    for other, oloc in _known_locations.items():
        if other == app_name or not oloc:
            continue
        o = safe_delete.norm(oloc)
        if o == loc:
            return f"다른 프로그램('{other}')도 같은 폴더를 설치 경로로 등록함"
        if o.startswith(loc + os.sep):
            return f"다른 프로그램('{other}')의 설치 폴더를 품고 있음"
    folder = _normalize(os.path.basename(loc))
    company = _normalize(_COMPANY_SUFFIX.sub(' ', publisher or ''))
    # 제품 이름이 회사 이름과 같으면(Discord, Rainmeter) 그 폴더가 제품 폴더다. 다를 때만 제조사 폴더로 본다.
    if folder and company and folder == company and folder != _normalize(app_name):
        return f"게시자({publisher}) 이름의 제조사 공용 폴더"
    return None


def find_leftovers(app_name, install_location='', publisher=''):
    """제거 후 남은 폴더를 찾는다.

    이전 구현은 앱 이름의 첫 단어를 폴더명에 '부분 일치' 시켜서, Acrobat 하나를
    지우려다 Adobe 제품군 전체(22.8GB)가 잡혔다. 이제 두 가지 방법만 쓴다.

      1순위: 레지스트리 InstallLocation — 프로그램이 스스로 신고한 설치 경로다.
             추측이 아니므로 가장 안전하다.
      2순위: 정규화한 '전체 이름' 과 폴더명이 정확히 일치할 때만.
             부분 일치는 쓰지 않는다.

    어느 쪽이든 safe_delete 의 보호 경로 판정을 통과해야 하고, 정리 단계가 허용하는 폴더
    (AppData·Program Files·ProgramData) 안이어야 목록에 오른다. 목록에 보여 놓고 정리에서
    거부하면 사용자는 '지웠다' 고 믿게 된다. 아직 설치된 다른 프로그램의 설치 경로를 품은 폴더도 뺀다.
    """
    out = []
    seen = set()
    roots = _leftover_roots()
    installed_now = {a['name'] for a in get_installed_apps()}
    others = [safe_delete.norm(loc) for n, loc in _known_locations.items()
              if n != app_name and n in installed_now and loc]

    def add(path, confidence, why):
        p = safe_delete.norm(path)
        if p in seen or not os.path.isdir(path):
            return
        if safe_delete.is_link_like(path):
            log.info(f"잔여물 후보에서 제외(다른 위치로 이어진 링크): {path}")
            return
        if safe_delete.is_protected(path):
            log.info(f"잔여물 후보에서 제외(보호 경로): {path}")
            return
        if not any(safe_delete.is_inside(path, r) for r in roots):
            log.info(f"잔여물 후보에서 제외(정리할 수 있는 폴더 밖): {path}")
            return
        if any(o == p or o.startswith(p + os.sep) for o in others):
            log.info(f"잔여물 후보에서 제외(설치된 다른 프로그램이 이 안에 있음): {path}")
            return
        seen.add(p)
        size, capped = _folder_size(path)
        out.append({
            "path": path,
            "sizeMB": round(size / (1024 ** 2), 2),
            "sizeCapped": capped,       # True 면 sizeMB 는 '이 이상' 이다
            "confidence": confidence,   # 'certain' | 'likely'
            "reason": why,
        })

    target = _normalize(app_name)

    # 1순위 — 프로그램이 신고한 설치 경로(인자로 받지 않았으면 제거 전에 읽어 둔 값)
    install_location = install_location or _known_locations.get(app_name, '')
    publisher = publisher or _known_publishers.get(app_name, '')
    if install_location and os.path.isdir(install_location):
        shared = _shared_folder_reason(install_location, app_name, publisher)
        if not shared:
            add(install_location, 'certain', '프로그램이 등록한 설치 경로')
        else:
            log.info(f"등록된 설치 경로를 통째로 올리지 않음({shared}): {install_location}")
            # 공용 폴더 안에서 프로그램 이름과 정확히 같은 하위 폴더만 후보로 본다
            if len(target) >= 4:
                try:
                    for item in os.listdir(install_location):
                        full = os.path.join(install_location, item)
                        if os.path.isdir(full) and _normalize(item) == target:
                            add(full, 'likely', '프로그램 이름과 폴더명이 일치(공용 설치 폴더 안)')
                except OSError:
                    pass

    if len(target) < 4:
        # 너무 짧은 이름은 오탐이 많다. 추측 탐색을 하지 않는다.
        return out
    if any(_normalize(n) == target for n in installed_now if n != app_name):
        # 버전만 다른 같은 제품이 아직 설치돼 있다(Python 3.12 를 지우는데 3.13 이 남음).
        # 이름이 같은 폴더(%APPDATA%\\Python 등)는 그 버전도 쓰는 공용 데이터다. 이름으로 찾지 않는다.
        return out

    search_dirs = [os.environ.get(v, '') for v in
                   ('APPDATA', 'LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData')]

    for base in search_dirs:
        if not base or not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except Exception as e:
            log.warning(f"폴더 목록 읽기 실패 {base}: {e}")
            continue

        for item in entries:
            full = os.path.join(base, item)
            if not os.path.isdir(full):
                continue
            # 정확히 일치할 때만. 부분 일치는 허용하지 않는다.
            if _normalize(item) == target:
                add(full, 'likely', '프로그램 이름과 폴더명이 일치')

    return out


def _leftover_roots():
    """잔여물을 찾고 지울 수 있는 폴더(이 안의 하위 폴더만). 이 밖은 건드리지 않는다."""
    roots = [os.environ.get(v, '') for v in
             ('APPDATA', 'LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData')]
    return [r for r in roots if r]


def scan_leftovers(app_name):
    """화면이 부르는 잔여물 탐색. 프로그램이 아직 설치돼 있으면 찾지 않는다.

    예전에는 '삭제 완료! 찌꺼기 스캔하기' 를 누르면 제거가 끝났는지 보지 않고 찾았다.
    제거 창을 닫았거나 취소했으면, 아직 쓰이는 프로그램 폴더가 '잔여물' 로 올라와
    휴지통으로 갈 수 있었다.
    반환: {success, stillInstalled, items, message}
    """
    if not isinstance(app_name, str) or not app_name.strip():
        return {"success": False, "stillInstalled": False, "items": [],
                "message": "프로그램 이름이 올바르지 않습니다."}
    check = verify_uninstalled(app_name)
    if not check["uninstalled"]:
        return {"success": False, "stillInstalled": True, "items": [],
                "message": f"'{app_name}' 이(가) 아직 설치된 프로그램 목록에 있습니다. "
                           "제거 창에서 제거를 마친 뒤 다시 눌러 주세요."}
    items = find_leftovers(app_name)
    return {"success": True, "stillInstalled": False, "items": items,
            "message": (f"남은 폴더 {len(items)}개를 찾았습니다." if items else "남은 폴더가 없습니다.")}


def clean_leftovers(paths):
    """잔여 폴더를 휴지통으로 보낸다.

    영구 삭제가 아니다. 잘못 잡힌 폴더가 섞여 있어도 사용자가 되돌릴 수 있어야 한다.
    """
    if not paths:
        return {"success": True, "freedMB": 0, "deleted": 0, "failed": [],
                "message": "선택된 항목이 없습니다."}

    allowed = _leftover_roots()
    installed = [safe_delete.norm(a['installLocation']) for a in get_installed_apps()
                 if a.get('installLocation')]

    targets, rejected = [], []
    for p in paths:
        if not isinstance(p, str) or not os.path.isdir(p):
            rejected.append({"path": p, "reason": "폴더가 존재하지 않습니다"})
            continue
        # 허용된 루트 '안' 인지 확인한다. startswith 만 쓰면
        # C:\ProgramData2 가 C:\ProgramData 안이라고 잘못 판정된다.
        if not any(safe_delete.is_inside(p, root) for root in allowed):
            rejected.append({"path": p, "reason": "허용된 폴더 범위 밖"})
            continue
        np_ = safe_delete.norm(p)
        if any(loc == np_ or loc.startswith(np_ + os.sep) for loc in installed):
            rejected.append({"path": p, "reason": "설치된 프로그램이 쓰는 폴더"})
            continue
        targets.append(p)

    res = safe_delete.to_recycle_bin(targets)
    failed = rejected + res['failed']

    return {
        "success": bool(res['ok']) or not failed,
        "freedMB": round(res['bytes'] / (1024 ** 2), 2),
        "deleted": len(res['ok']),
        "failed": failed,
        "message": (f"{len(res['ok'])}개 폴더를 휴지통으로 보냈습니다."
                    + (f" {len(failed)}개는 건너뛰었습니다." if failed else "")
                    + " 휴지통에서 복구할 수 있습니다."),
    }
