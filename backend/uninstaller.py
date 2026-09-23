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
    try:
        return _clean(winreg.QueryValueEx(subkey, name)[0])
    except Exception:
        return default


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
                            apps.append({
                                "id": str(app_id),
                                "name": name,
                                "publisher": _read(sub, "Publisher"),
                                "installDate": _read(sub, "InstallDate"),
                                "sizeMB": round(size_kb / 1024) if size_kb else 0,
                                "uninstallString": uninstall_string,
                                "installLocation": _read(sub, "InstallLocation"),
                                "quietUninstall": _read(sub, "QuietUninstallString"),
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


def run_uninstall(uninstall_string):
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


def _folder_size(path, cap_bytes=40 * 1024 ** 3):
    total = 0
    try:
        for dp, _, fs in os.walk(path):
            for f in fs:
                fp = os.path.join(dp, f)
                try:
                    if not os.path.islink(fp):
                        total += os.path.getsize(fp)
                except Exception:
                    pass
            if total > cap_bytes:
                break
    except Exception:
        pass
    return total


def find_leftovers(app_name, install_location='', publisher=''):
    """제거 후 남은 폴더를 찾는다.

    이전 구현은 앱 이름의 첫 단어를 폴더명에 '부분 일치' 시켜서, Acrobat 하나를
    지우려다 Adobe 제품군 전체(22.8GB)가 잡혔다. 이제 두 가지 방법만 쓴다.

      1순위: 레지스트리 InstallLocation — 프로그램이 스스로 신고한 설치 경로다.
             추측이 아니므로 가장 안전하다.
      2순위: 정규화한 '전체 이름' 과 폴더명이 정확히 일치할 때만.
             부분 일치는 쓰지 않는다.

    어느 쪽이든 safe_delete 의 보호 경로 판정을 통과해야 목록에 오른다.
    """
    out = []
    seen = set()

    def add(path, confidence, why):
        p = safe_delete.norm(path)
        if p in seen or not os.path.isdir(path):
            return
        if safe_delete.is_protected(path):
            log.info(f"잔여물 후보에서 제외(보호 경로): {path}")
            return
        seen.add(p)
        out.append({
            "path": path,
            "sizeMB": round(_folder_size(path) / (1024 ** 2), 2),
            "confidence": confidence,   # 'certain' | 'likely'
            "reason": why,
        })

    # 1순위 — 프로그램이 신고한 설치 경로
    if install_location and os.path.isdir(install_location):
        add(install_location, 'certain', '프로그램이 등록한 설치 경로')

    target = _normalize(app_name)
    if len(target) < 4:
        # 너무 짧은 이름은 오탐이 많다. 추측 탐색을 하지 않는다.
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


def clean_leftovers(paths):
    """잔여 폴더를 휴지통으로 보낸다.

    영구 삭제가 아니다. 잘못 잡힌 폴더가 섞여 있어도 사용자가 되돌릴 수 있어야 한다.
    """
    if not paths:
        return {"success": True, "freedMB": 0, "deleted": 0, "failed": [],
                "message": "선택된 항목이 없습니다."}

    allowed = [os.environ.get(v, '') for v in
               ('APPDATA', 'LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData')]
    allowed = [a for a in allowed if a]

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
        targets.append(p)

    res = safe_delete.to_recycle_bin(targets)
    failed = rejected + res['failed']

    return {
        "success": bool(res['ok']) or not targets,
        "freedMB": round(res['bytes'] / (1024 ** 2), 2),
        "deleted": len(res['ok']),
        "failed": failed,
        "message": (f"{len(res['ok'])}개 폴더를 휴지통으로 보냈습니다."
                    + (f" {len(failed)}개는 건너뛰었습니다." if failed else "")
                    + " 휴지통에서 복구할 수 있습니다."),
    }
