"""
APEX CARE — 프로그램 제거 및 잔여물 정리.

예전 사고: 앱 이름의 첫 단어를 폴더명에 부분 일치시켜 'Adobe Acrobat' 제거가 Adobe 폴더
22.8GB 를, 'Steam' 이 게임 라이브러리를 잔여물로 잡았고 shutil.rmtree 로 지웠다.
UI 가 넘긴 UninstallString 을 shell=True 로 관리자 권한 실행하기도 했다.

지금 지키는 것:

1. UI 는 앱 id(하이브+키 경로)만 넘긴다. 실행할 명령은 백엔드가 레지스트리에서 다시 읽는다.
   id 는 get_installed_apps() 가 서버 측에 보관한 것만 받는다.
2. 제거 명령은 셸 없이, 실행 파일을 절대 경로로 못 박아 실행한다. 이름만 적힌 실행 파일은
   System32·Windows 에서만 찾는다(현재 폴더·PATH 에 놓인 가짜 exe 방지).
   HKCU 출처, 명령 해석기(cmd·powershell 등), Program Files·Windows 밖 실행 파일은 경고로 알린다.
   확인 창에서 본 명령과 실행 직전에 다시 읽은 명령이 다르면 실행하지 않는다.
3. Windows 프로그램 목록에서 사라진 것이 확인돼야 잔여물을 찾는다.
   예전에는 언인스톨러를 취소해도 아직 설치된 앱 폴더를 '찌꺼기'로 잡았다.
4. 잔여물 후보는 허용 루트(Program Files·ProgramData·AppData)의 바로 아래 폴더뿐이다.
   다른 설치 앱이 쓰는 폴더, 이름이 같은 다른 앱의 폴더, 실행 중인 프로그램이 든 폴더는 뺀다.
   사용자 데이터로 보이는 폴더와 AppData 폴더는 기본 선택 해제다.
5. 정리는 직전 검색 결과 중 사용자가 고른 것만 휴지통으로 옮긴다.
"""

import logging
import os
import re
import stat
import subprocess
import threading
import time
import winreg

from backend import safe_delete

log = logging.getLogger('Uninstaller')

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
]
_HIVE_NAME = {winreg.HKEY_LOCAL_MACHINE: 'HKLM', winreg.HKEY_CURRENT_USER: 'HKCU'}

# 32비트로 묶여도 64비트 보기로 읽는다. WOW6432Node 는 위 목록에서 경로로 따로 읽는다.
_KEY_READ = winreg.KEY_READ | getattr(winreg, 'KEY_WOW64_64KEY', 0)

_PREVIEW_TTL = 15 * 60       # 확인 창에서 본 명령의 유효 시간
_SCAN_TTL = 30 * 60          # 잔여물 검색 결과의 유효 시간
_SESSION_TTL = 24 * 3600
_EARLY_EXIT_WAIT = 1.5       # 실행 직후 즉시 실패를 가려내려고 기다리는 시간(초)

# 명령줄 전체를 다시 해석하는 실행기. shell=False 여도 'cmd.exe /c A & B' 는 B 까지 실행된다.
_INTERPRETERS = {
    'cmd.exe', 'powershell.exe', 'pwsh.exe', 'wscript.exe', 'cscript.exe',
    'mshta.exe', 'rundll32.exe', 'regsvr32.exe',
}

_GUID_RE = re.compile(r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}')
_DRIVE_ABS = re.compile(r'^[A-Za-z]:[\\/]')
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# 사용자가 만든 데이터로 보이는 표지. 하나라도 있으면 기본 선택에서 뺀다.
_DATA_DIRS = {
    'saves', 'save', 'savegames', 'savedgames', 'saved games', 'savedata', 'save data',
    'profiles', 'profile', 'screenshots', 'worlds', 'backups', 'backup', 'userdata',
    'user data', 'recordings', 'projects', 'documents', 'my documents',
    'photos', 'pictures', 'videos', 'music', 'downloads', 'desktop',
}
_DATA_EXTS = {
    # 문서
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.hwp', '.hwpx', '.pdf',
    '.odt', '.ods', '.odp', '.rtf',
    # 사진·영상
    '.jpg', '.jpeg', '.heic', '.heif', '.raw', '.cr2', '.cr3', '.nef', '.arw', '.dng',
    '.psd', '.tif', '.tiff', '.mp4', '.mov', '.mkv', '.avi',
    # 게임 세이브·메일·작업 파일·비밀 저장소
    '.sav', '.save', '.savegame', '.pst', '.ost', '.eml', '.mbox',
    '.blend', '.prproj', '.aep', '.kra', '.xcf', '.flp', '.als', '.cpr', '.ptx', '.sketch',
    '.kdbx', '.wallet', '.sqlite',
}
_DATA_FILES = {
    'wallet.dat', 'key4.db', 'logins.json', 'places.sqlite', 'login data', 'bookmarks',
    'ccgamemanager.dat', 'cclocallevels.dat',
}

_lock = threading.RLock()
_entries = {}    # id -> 레지스트리 항목 (마지막 목록 조회 결과)
_session = {}    # id -> {'preview', 'proc', 'launchedAt', 'verifiedAt', 'entry'}
_scans = {}      # id -> {'at', 'items': {norm 경로: 항목}}
_busy = 0


# ─────────────────────────────────────────────
# 레지스트리
# ─────────────────────────────────────────────

def _clean(s):
    return s.replace('\x00', '').strip() if isinstance(s, str) else s


def _read(subkey, name, default=''):
    try:
        return _clean(winreg.QueryValueEx(subkey, name)[0])
    except Exception:
        return default


def _str(v):
    return v if isinstance(v, str) else ''


def _int(v):
    return v if isinstance(v, int) else 0


def _expand(s):
    if not isinstance(s, str):
        return ''
    try:
        return winreg.ExpandEnvironmentStrings(s)
    except Exception:
        return s


def _entry_from_key(hkey, base, sub_name, sub):
    hive = _HIVE_NAME.get(hkey, 'HK?')
    key_path = base + '\\' + sub_name
    return {
        'id': hive + '\\' + key_path,
        'hkey': hkey,
        'hive': hive,
        'keyPath': key_path,
        'keyName': sub_name,
        'name': _str(_read(sub, 'DisplayName')),
        'publisher': _str(_read(sub, 'Publisher')),
        'installDate': _str(_read(sub, 'InstallDate')),
        'sizeKB': _int(_read(sub, 'EstimatedSize', 0)),
        'uninstallString': _str(_read(sub, 'UninstallString')),
        'quietUninstall': _str(_read(sub, 'QuietUninstallString')),
        'modifyPath': _str(_read(sub, 'ModifyPath')),
        'installLocation': _str(_read(sub, 'InstallLocation')),
        'displayIcon': _str(_read(sub, 'DisplayIcon')),
        'systemComponent': _int(_read(sub, 'SystemComponent', 0)),
        'parentKeyName': _str(_read(sub, 'ParentKeyName')),
        'noRemove': _int(_read(sub, 'NoRemove', 0)),
    }


def _read_entry(hkey, key_path):
    """키 하나를 다시 읽는다. 없으면 None. 읽기 권한 오류 등은 OSError 로 올린다."""
    base, _, sub_name = key_path.rpartition('\\')
    try:
        with winreg.OpenKey(hkey, key_path, 0, _KEY_READ) as sub:
            return _entry_from_key(hkey, base, sub_name, sub)
    except FileNotFoundError:
        return None


def _scan_registry():
    """Uninstall 키의 모든 하위 키. 숨은 구성 요소도 포함한다(교차 검사용)."""
    out = []
    for hkey, path in UNINSTALL_KEYS:
        try:
            key = winreg.OpenKey(hkey, path, 0, _KEY_READ)
        except FileNotFoundError:
            continue
        except OSError as e:
            log.warning(f"레지스트리 키 읽기 실패 {path}: {e}")
            continue
        with key:
            try:
                count = winreg.QueryInfoKey(key)[0]
            except OSError as e:
                log.warning(f"레지스트리 키 정보 읽기 실패 {path}: {e}")
                continue
            for i in range(count):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, sub_name, 0, _KEY_READ) as sub:
                        out.append(_entry_from_key(hkey, path, sub_name, sub))
                except OSError as e:
                    log.debug(f"하위 키 읽기 실패: {e}")
    return out


def _is_listed(e):
    """Windows '앱' 목록에 보이는 항목만 제거 대상으로 보여 준다."""
    return bool(e['name'] and e['uninstallString']
                and e['systemComponent'] != 1
                and not e['parentKeyName']
                and e['noRemove'] != 1)


def _public(e):
    hkcu = e['hive'] == 'HKCU'
    return {
        "id": e['id'],
        "name": e['name'],
        "publisher": e['publisher'],
        "installDate": e['installDate'],
        "sizeMB": round(e['sizeKB'] / 1024) if e['sizeKB'] else 0,
        "uninstallString": e['uninstallString'],   # 표시용. 실행은 id 로만 한다.
        "installLocation": e['installLocation'],
        "quietUninstall": e['quietUninstall'],
        "source": e['hive'],
        "userInstall": hkcu,
    }


def _prune_locked():
    now = time.time()
    for k in [k for k, s in _scans.items() if now - s['at'] > _SCAN_TTL]:
        _scans.pop(k, None)
    for k, s in list(_session.items()):
        proc = s.get('proc')
        alive = proc is not None and proc.poll() is None
        last = max(s.get('launchedAt') or 0, s.get('verifiedAt') or 0,
                   (s.get('preview') or {}).get('at') or 0)
        if not alive and now - last > _SESSION_TTL:
            _session.pop(k, None)


def _lookup(app_id):
    """서버가 보관한 항목만 돌려준다. UI 가 임의의 키를 지정할 수 없다."""
    if not isinstance(app_id, str) or not app_id:
        return None
    with _lock:
        e = _entries.get(app_id)
        if e is None:
            e = (_session.get(app_id) or {}).get('entry')
        return dict(e) if e else None


def get_installed_apps():
    """설치된 프로그램 목록.

    각 항목의 'id' 는 하이브+키 경로다. 이후 제거·확인·잔여물 정리는 이 id 로만 한다.
    """
    fresh, apps, seen = {}, [], set()
    for e in _scan_registry():
        if not _is_listed(e):
            continue
        dedupe = (e['name'].lower(), e['uninstallString'].lower())
        if dedupe in seen:
            continue
        seen.add(dedupe)
        fresh[e['id']] = e
        apps.append(_public(e))

    with _lock:
        # 제거 프로그램을 띄운 항목은 _session 에 따로 남아 있어 목록이 바뀌어도 잃지 않는다
        _entries.clear()
        _entries.update(fresh)
        _prune_locked()

    apps.sort(key=lambda x: x["name"].lower())
    return apps


# ─────────────────────────────────────────────
# 제거 명령 해석
# ─────────────────────────────────────────────

def _system_dirs():
    root = os.environ.get('SystemRoot') or os.environ.get('windir') or r'C:\Windows'
    return [os.path.join(root, 'System32'), root]


def _trusted_dirs():
    env = os.environ.get
    return [d for d in (env('ProgramFiles'), env('ProgramFiles(x86)'), env('ProgramW6432'),
                        env('SystemRoot') or env('windir')) if d]


def _wow64_alternative(p):
    """32비트 설치 프로그램이 적은 System32 경로는 실제로 SysWOW64 를 가리킨다."""
    sysdir = _system_dirs()[0]
    low, pre = p.lower(), sysdir.lower() + '\\'
    if low.startswith(pre):
        return os.path.join(os.path.dirname(sysdir), 'SysWOW64', p[len(pre):])
    return None


def _locate(text, wow64=False):
    """실행 파일(.exe)의 절대 경로. 못 찾으면 None.

    이름만 있으면 System32·Windows 에서만 찾는다. CreateProcess 에 이름만 넘기면
    이 앱의 폴더와 현재 폴더를 먼저 뒤지는데, 관리자 권한 프로세스에서는 위험하다.
    상대 경로·UNC·드라이브 루트 바로 아래(C:\\Program.exe 같은) 파일은 받지 않는다.
    """
    t = (text or '').strip()
    if not t:
        return None
    names = [t] if t.lower().endswith('.exe') else [t + '.exe']
    if not re.search(r'[\\/]', t):
        for d in _system_dirs():
            for n in names:
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    return p
        return None
    if not _DRIVE_ABS.match(t):
        return None
    for c in names:
        p = os.path.normpath(c)
        if len(os.path.dirname(p).rstrip('\\/')) <= 2:
            return None
        if os.path.isfile(p):
            return p
        alt = _wow64_alternative(p) if wow64 else None
        if alt and os.path.isfile(alt):
            return alt
    return None


def _not_found(text):
    return (f"제거 프로그램을 찾을 수 없습니다: {text}\n"
            "이미 삭제됐거나 경로가 바뀌었을 수 있습니다. Windows 설정 > 앱에서 제거해 보세요.")


def _parse_command(raw, wow64=False):
    """(실행 파일 절대 경로, 나머지 인자 문자열, 오류) 를 돌려준다.

    나머지 인자는 원문 그대로 둔다. 인자 배열로 쪼갰다가 다시 이으면 따옴표 모양이 바뀌어
    제거 프로그램이 인자를 다르게 읽을 수 있다. 실행 파일만 절대 경로로 고정한다.
    """
    s = _expand(raw).strip()
    if not s:
        return None, '', '제거 명령이 비어 있습니다.'
    if s.startswith('"'):
        end = s.find('"', 1)
        if end < 0:
            return None, '', '제거 명령의 따옴표가 닫혀 있지 않습니다.'
        text, rest = s[1:end], s[end + 1:]
        exe = _locate(text, wow64)
        return (exe, rest, None) if exe else (None, rest, _not_found(text))

    # 따옴표 없는 경로 — 'C:\Program Files\App\unins000.exe /S'
    m = re.match(r'(.+?\.exe)(?=\s|$)', s, re.IGNORECASE)
    if m:
        exe = _locate(m.group(1), wow64)
        if exe:
            return exe, s[m.end():], None
    # 확장자 없이 적힌 경우. 긴 것부터 잘라 본다(짧은 것부터 보면 C:\Program 이 먼저 걸린다).
    cuts = [x.start() for x in re.finditer(r'\s', s)] + [len(s)]
    for pos in reversed(cuts):
        exe = _locate(s[:pos], wow64)
        if exe:
            return exe, s[pos:], None
    first = m.group(1) if m else s.split(None, 1)[0]
    return None, s[len(first):], _not_found(first)


def _build_command(entry):
    """실제로 실행할 명령줄과 경고를 만든다."""
    raw = entry.get('uninstallString') or ''
    warnings = []
    if entry.get('hive') == 'HKCU':
        warnings.append("현재 사용자 영역(HKCU)에 등록된 항목입니다. 관리자 권한 없이도 바꿀 수 있는 "
                        "위치라, 아래 명령이 이 프로그램의 제거 명령이 맞는지 확인하세요.")
    wow64 = 'wow6432node' in (entry.get('keyPath') or '').lower()
    exe, rest, err = _parse_command(raw, wow64)
    out = {'ok': False, 'command': _expand(raw).strip(), 'registryCommand': raw,
           'executable': exe or '', 'warnings': warnings, 'error': err, 'msi': False}
    if err:
        return out

    base = os.path.basename(exe).lower()
    if base == 'msiexec.exe':
        # MSI 는 제품 코드만 뽑아 /X(제거)로 다시 만든다. /I(설치·복구)가 적힌 경우가 많다.
        m = _GUID_RE.search(rest) or _GUID_RE.search(entry.get('keyName') or '')
        if not m:
            out['error'] = 'MSI 제품 코드를 찾지 못해 실행하지 않았습니다. Windows 설정 > 앱에서 제거해 보세요.'
            return out
        exe = os.path.join(_system_dirs()[0], 'msiexec.exe')
        if not os.path.isfile(exe):
            out['error'] = _not_found(exe)
            return out
        cmdline = f'"{exe}" /X{m.group(0)}'
        out['msi'] = True
    else:
        rest = rest.rstrip()
        if rest and not rest[0].isspace():
            rest = ' ' + rest
        cmdline = f'"{exe}"{rest}'

    if base in _INTERPRETERS:
        warnings.append(f"{os.path.basename(exe)} 로 명령을 실행합니다. 명령 안에 적힌 다른 명령도 "
                        "관리자 권한으로 함께 실행되니 전체를 확인하세요.")
    if not any(safe_delete.is_inside(exe, d) for d in _trusted_dirs()):
        warnings.append(f"제거 프로그램이 Program Files·Windows 폴더 밖에 있습니다: {exe}")

    out.update(ok=True, command=cmdline, executable=exe, error=None)
    return out


def get_uninstall_preview(app_id):
    """제거 전에 보여 줄 명령과 경고.

    레지스트리를 지금 다시 읽어 만든다. run_uninstall 은 여기서 확인한 명령과
    같을 때만 실행한다.
    """
    fail = {'ok': False, 'command': '', 'registryCommand': '', 'executable': '',
            'warnings': [], 'name': '', 'publisher': '', 'source': ''}
    entry = _lookup(app_id)
    if not entry:
        return {**fail, 'error': '프로그램 정보를 찾지 못했습니다. 목록을 새로 고친 뒤 다시 시도하세요.'}
    fail.update(name=entry['name'], publisher=entry['publisher'], source=entry['hive'])
    try:
        fresh = _read_entry(entry['hkey'], entry['keyPath'])
    except OSError as e:
        return {**fail, 'error': f'레지스트리를 읽지 못했습니다: {e}'}
    if not fresh or not fresh['uninstallString']:
        return {**fail, 'error': '등록 정보가 사라졌습니다. 이미 제거됐을 수 있습니다. 목록을 새로 고치세요.'}

    built = _build_command(fresh)
    if built['ok']:
        with _lock:
            s = _session.setdefault(app_id, {})
            s['preview'] = {'command': built['command'], 'executable': built['executable'],
                            'at': time.time()}
    return {
        'ok': built['ok'],
        'error': built['error'],
        'name': fresh['name'] or entry['name'],
        'publisher': fresh['publisher'],
        'source': fresh['hive'],
        'command': built['command'],
        'registryCommand': built['registryCommand'],
        'executable': built['executable'],
        'warnings': built['warnings'],
    }


def run_uninstall(app_id):
    """제거 프로그램을 실행한다.

    UI 가 준 문자열이 아니라 레지스트리를 다시 읽어 실행한다. 셸을 거치지 않는다.
    실행 직후 잠깐 기다려 곧바로 실패하는 경우를 가려낸다. 대부분의 제거 프로그램은
    자체 창을 띄우므로, 제거가 끝났는지는 verify_uninstalled() 로 따로 확인한다.
    """
    def fail(msg):
        return {"success": False, "launched": False, "message": msg}

    entry = _lookup(app_id)
    if not entry:
        return fail("프로그램 정보를 찾지 못했습니다. 목록을 새로 고친 뒤 다시 시도하세요.")

    with _lock:
        s = _session.get(app_id) or {}
        proc = s.get('proc')
        if proc is not None and proc.poll() is None:
            return fail("이 프로그램의 제거 프로그램이 이미 실행 중입니다.")
        preview = s.get('preview')
    if not preview or time.time() - preview['at'] > _PREVIEW_TTL:
        return fail("먼저 제거 확인 창에서 실행할 명령을 확인하세요.")

    try:
        fresh = _read_entry(entry['hkey'], entry['keyPath'])
    except OSError as e:
        return fail(f"레지스트리를 읽지 못했습니다: {e}")
    if not fresh or not fresh['uninstallString']:
        return fail("등록 정보가 사라졌습니다. 이미 제거됐을 수 있습니다. 목록을 새로 고치세요.")

    built = _build_command(fresh)
    if not built['ok']:
        return fail(built['error'])
    if built['command'] != preview['command'] or built['executable'] != preview['executable']:
        with _lock:
            (_session.get(app_id) or {}).pop('preview', None)
        log.warning(f"제거 명령이 확인 뒤 바뀜: {preview['command']!r} -> {built['command']!r}")
        return fail("확인한 뒤 제거 명령이 바뀌었습니다. 다시 확인하세요.")

    exe, cmdline = built['executable'], built['command']
    cwd = os.path.dirname(exe)
    try:
        # executable 로 실행 파일을 고정하고, 명령줄은 확인 창에 보여 준 그대로 넘긴다
        proc = subprocess.Popen(cmdline, executable=exe, shell=False,
                                cwd=cwd if os.path.isdir(cwd) else None, close_fds=True)
    except FileNotFoundError:
        return fail(_not_found(exe))
    except OSError as e:
        return fail(f"제거 프로그램 실행 실패: {e}")

    with _lock:
        s = _session.setdefault(app_id, {})
        s.update(proc=proc, launchedAt=time.time(), verifiedAt=None, entry=fresh)
        s.pop('preview', None)          # 확인은 한 번만 쓴다
        _scans.pop(app_id, None)
    log.info(f"제거 프로그램 실행: {fresh['name']} ({fresh['id']}) pid={proc.pid}")

    try:
        code = proc.wait(timeout=_EARLY_EXIT_WAIT)
    except subprocess.TimeoutExpired:
        code = None
    return _launch_result(proc, code, built['msi'], cmdline)


def _launch_result(proc, code, is_msi, cmdline):
    res = {"success": True, "launched": True, "pid": proc.pid, "exitCode": code, "command": cmdline}
    if code is None:
        res["message"] = "제거 프로그램을 실행했습니다. 창의 안내에 따라 제거를 마친 뒤 '제거 완료 확인'을 누르세요."
    elif code == 0:
        res["message"] = ("제거 프로그램이 바로 끝났습니다(종료 코드 0). 다른 창이 떠 있으면 안내에 따라 "
                          "마친 뒤 '제거 완료 확인'을 누르세요.")
    elif is_msi and code in (3010, 1641):
        res["message"] = f"제거 프로그램이 끝났습니다. 다시 시작해야 마무리됩니다(종료 코드 {code})."
    elif is_msi and code == 1602:
        res.update(success=False, message="제거가 취소됐습니다(종료 코드 1602).")
    elif is_msi and code == 1605:
        res.update(success=False,
                   message="Windows Installer 에 이 제품이 설치돼 있지 않다고 나옵니다(종료 코드 1605). "
                           "등록 정보만 남은 상태일 수 있습니다.")
    else:
        res.update(success=False,
                   message=f"제거 프로그램이 바로 종료됐습니다(종료 코드 {code}). 제거되지 않았을 수 있습니다.")
    return res


# ─────────────────────────────────────────────
# 제거 확인
# ─────────────────────────────────────────────

def _verify(app_id, entry, entries=None):
    with _lock:
        proc = (_session.get(app_id) or {}).get('proc')
    running = proc is not None and proc.poll() is None

    try:
        cur = _read_entry(entry['hkey'], entry['keyPath'])
    except OSError as e:
        return {"uninstalled": False, "stillRunning": running,
                "message": f"설치 상태를 확인하지 못했습니다: {e}"}
    if cur and cur['name']:
        return {"uninstalled": False, "stillRunning": running,
                "message": "아직 Windows 프로그램 목록에 남아 있습니다. "
                           + ("제거 프로그램이 아직 실행 중입니다." if running else "제거를 마친 뒤 다시 확인하세요.")}

    if entries is None:
        entries = _scan_registry()
    name = (entry.get('name') or '').strip().lower()
    same = [e for e in entries
            if e['id'] != entry['id'] and e['name'] and e['name'].strip().lower() == name]
    if same:
        return {"uninstalled": False, "stillRunning": running,
                "message": "같은 이름의 항목이 아직 등록돼 있습니다(목록에 보이지 않는 구성 요소일 수 있습니다)."}
    if running:
        return {"uninstalled": False, "stillRunning": True,
                "message": "등록 정보는 지워졌지만 제거 프로그램이 아직 실행 중입니다. 끝난 뒤 다시 확인하세요."}

    with _lock:
        s = _session.setdefault(app_id, {})
        s.setdefault('entry', entry)
        s['verifiedAt'] = time.time()
    return {"uninstalled": True, "stillRunning": False,
            "message": "Windows 프로그램 목록에서 사라진 것을 확인했습니다."}


def verify_uninstalled(app_id):
    """레지스트리에서 사라졌는지 확인한다.

    제거가 끝나지 않았는데 잔여물 정리를 진행하면, 아직 쓰이고 있는 폴더를 지우게 된다.
    """
    entry = _lookup(app_id)
    if not entry:
        return {"uninstalled": False, "stillRunning": False,
                "message": "프로그램 정보를 찾지 못했습니다. 목록을 새로 고친 뒤 다시 시도하세요."}
    return _verify(app_id, entry)


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


def _clean_path(s):
    """InstallLocation 값 정리: 환경 변수 전개, 따옴표 제거. 로컬 절대 경로만."""
    s = _expand(s or '').strip().strip('"').strip()
    if not _DRIVE_ABS.match(s):
        return ''
    return os.path.normpath(s)


def _icon_path(s):
    """DisplayIcon — '"C:\\x\\app.exe",0' 형태에서 파일 경로만."""
    s = _expand(s or '').strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        s = s[1:end] if end > 0 else s[1:]
    else:
        m = re.match(r'^(.*?),\s*-?\d+\s*$', s)
        if m:
            s = m.group(1)
    s = s.strip()
    return s if _DRIVE_ABS.match(s) else ''


def _command_path(cmd):
    """명령줄의 실행 파일 경로(존재 여부는 따지지 않는다). 교차 검사용."""
    s = _expand(cmd or '').strip()
    if not s:
        return ''
    if s.startswith('"'):
        end = s.find('"', 1)
        p = s[1:end] if end > 0 else s[1:]
    else:
        m = re.match(r'(.+?\.exe)(?=\s|$)', s, re.IGNORECASE)
        p = m.group(1) if m else s.split(None, 1)[0]
    p = p.strip()
    return p if _DRIVE_ABS.match(p) else ''


def _allowed_roots():
    """잔여물을 찾고 지울 수 있는 루트. (원래 경로, norm 경로, 사용자 데이터 영역 여부)"""
    env = os.environ.get
    raw = [(env('ProgramFiles'), False), (env('ProgramFiles(x86)'), False),
           (env('ProgramW6432'), False), (env('ProgramData'), False),
           (env('APPDATA'), True), (env('LOCALAPPDATA'), True)]
    if env('LOCALAPPDATA'):
        # 사용자별 설치 프로그램의 기본 위치
        raw.append((os.path.join(env('LOCALAPPDATA'), 'Programs'), True))
    out, seen = [], set()
    for r, user in raw:
        if not r or not os.path.isdir(r):
            continue
        n = safe_delete.norm(r)
        if n in seen:
            continue
        seen.add(n)
        out.append((r, n, user))
    return out


def _root_of(n, roots):
    """n 이 어느 허용 루트의 '바로 아래' 폴더인지. 아니면 None."""
    parent = os.path.dirname(n)
    for root in roots:
        if parent == root[1]:
            return root
    return None


def _is_reparse(path):
    try:
        return bool(os.lstat(path).st_file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return True     # 확인하지 못하면 링크로 보고 건드리지 않는다


class _Guard:
    """아직 설치된 다른 프로그램이 쓰는 경로·이름."""

    def __init__(self, others, root_norms):
        self.paths = []     # (norm 경로, 앱 이름) — 이 경로를 품은 폴더는 후보가 될 수 없다
        self.homes = []     # 다른 앱의 설치 폴더 — 이 안의 폴더도 후보가 될 수 없다
        self.names = {}     # 정규화 이름 -> 표시 이름
        for e in others:
            label = e['name'] or e['keyName']
            if e['name']:
                nn = _normalize(e['name'])
                if nn:
                    self.names.setdefault(nn, e['name'])
            loc = _clean_path(e['installLocation'])
            if loc:
                n = safe_delete.norm(loc)
                self.paths.append((n, label))
                # 루트 자체를 설치 폴더로 적어 둔 엉성한 항목 때문에 모든 후보가 막히지 않게
                if n not in root_norms and not safe_delete.is_protected(loc):
                    self.homes.append((n, label))
            for p in (_icon_path(e['displayIcon']), _command_path(e['uninstallString']),
                      _command_path(e['quietUninstall']), _command_path(e['modifyPath'])):
                if p:
                    self.paths.append((safe_delete.norm(p), label))

    def conflict(self, n):
        pre = n + os.sep
        for p, label in self.paths:
            if p == n or p.startswith(pre):
                return f"설치된 다른 프로그램({label})이 이 폴더를 씁니다."
        for h, label in self.homes:
            if n.startswith(h + os.sep):
                return f"설치된 다른 프로그램({label})의 설치 폴더 안에 있습니다."
        nn = _normalize(os.path.basename(n))
        if nn in self.names:
            return f"설치된 다른 프로그램({self.names[nn]})과 이름이 같은 폴더입니다."
        return None


def _running_exes():
    try:
        import psutil
    except Exception:
        return []
    out = []
    for p in psutil.process_iter(['exe', 'name']):
        try:
            exe = p.info.get('exe')
            if exe:
                out.append((safe_delete.norm(exe), p.info.get('name') or os.path.basename(exe)))
        except Exception:
            continue
    return out


def _context(entry, entries):
    roots = _allowed_roots()
    root_norms = {r[1] for r in roots}
    others = [e for e in entries if e['id'] != entry['id']]
    return {'roots': roots, 'rootNorms': root_norms,
            'guard': _Guard(others, root_norms), 'running': _running_exes()}


def _candidate_problem(shown, n, ctx):
    """후보가 될 수 없는 이유. 문제가 없으면 (None, 루트)."""
    if not os.path.isdir(shown):
        return "폴더가 없습니다.", None
    if _is_reparse(shown):
        return "링크(정션·심볼릭 링크)라 건드리지 않습니다.", None
    if n in ctx['rootNorms']:
        return "최상위 폴더 자체라 건드리지 않습니다.", None
    root = _root_of(n, ctx['roots'])
    if root is None:
        return "정리 범위(Program Files·ProgramData·AppData 바로 아래 폴더) 밖입니다.", None
    if safe_delete.is_protected(shown):
        return "보호 폴더입니다.", None
    c = ctx['guard'].conflict(n)
    if c:
        return c, None
    pre = n + os.sep
    for exe_n, pname in ctx['running']:
        if exe_n.startswith(pre):
            return f"실행 중인 프로그램({pname})이 이 폴더에 있습니다.", None
    return None, root


def _inspect(path, max_entries=300_000, max_seconds=5.0):
    """(크기 바이트, 사용자 데이터 표지 목록, 끝까지 확인했는지). 링크는 따라가지 않는다."""
    total, hints, seen = 0, [], set()
    complete = True
    count = 0
    deadline = time.monotonic() + max_seconds
    stack = [path]

    def hint(h):
        if h not in seen and len(hints) < 8:
            seen.add(h)
            hints.append(h)

    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            complete = False            # 못 읽은 폴더가 있으면 내용을 안다고 할 수 없다
            continue
        stop = False
        with it:
            for e in it:
                count += 1
                if count > max_entries or time.monotonic() > deadline:
                    stop = True
                    break
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if getattr(st, 'st_file_attributes', 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
                    continue
                low = e.name.lower()
                if stat.S_ISDIR(st.st_mode):
                    if low in _DATA_DIRS:
                        hint(e.name + '\\')
                    stack.append(e.path)
                else:
                    total += st.st_size
                    if low in _DATA_FILES:
                        hint(e.name)
                    else:
                        ext = os.path.splitext(low)[1]
                        if ext in _DATA_EXTS:
                            hint('*' + ext)
        if stop:
            complete = False
            break
    return total, hints, complete


def find_leftovers(app_id):
    """제거된 프로그램의 남은 폴더를 찾는다.

    반환: {ok, error, appName, items:[...], excluded:[{path, reason}], notes:[...]}
    items 항목: path, sizeMB, sizeBytes, confidence('certain'|'likely'), reason,
               location('program'|'appdata'), locationLabel, userData, userDataHints,
               inspected, selected(기본 선택)

    아직 설치돼 있으면 거부한다. 후보는 두 가지뿐이다.
      1) 프로그램이 등록한 InstallLocation — 루트 바로 아래이고 폴더 이름이 프로그램 이름과
         같을 때만. 'C:\\Program Files\\Adobe' 처럼 여러 제품이 함께 쓰는 상위 폴더를
         InstallLocation 으로 적는 설치 프로그램이 실제로 있다.
      2) 정규화한 '전체 이름' 과 루트 바로 아래 폴더 이름이 정확히 같을 때. 부분 일치는 쓰지 않는다.
    """
    out = {'ok': False, 'error': None, 'appName': '', 'items': [], 'excluded': [], 'notes': []}
    entry = _lookup(app_id)
    if not entry:
        out['error'] = "프로그램 정보를 찾지 못했습니다. 목록을 새로 고친 뒤 다시 시도하세요."
        return out
    out['appName'] = entry['name']

    entries = _scan_registry()
    v = _verify(app_id, entry, entries)
    if not v['uninstalled']:
        out['error'] = "제거가 확인되지 않아 남은 폴더를 찾지 않았습니다. " + v['message']
        return out

    ctx = _context(entry, entries)
    notes, excluded, found = out['notes'], out['excluded'], []
    target = _normalize(entry['name'])

    # 1순위 — 프로그램이 등록한 설치 경로
    loc = _clean_path(entry['installLocation'])
    if loc and os.path.isdir(loc):
        ln = safe_delete.norm(loc)
        if ln in ctx['rootNorms'] or safe_delete.is_protected(loc):
            notes.append(f"등록된 설치 경로가 {loc} 자체라 쓰지 않았습니다.")
        elif _root_of(ln, ctx['roots']) is None:
            notes.append(f"등록된 설치 폴더가 남아 있습니다: {loc} — 자동 정리 범위"
                         "(Program Files·ProgramData·AppData 바로 아래 폴더) 밖이라 목록에 올리지 않았습니다.")
        elif not target or _normalize(os.path.basename(loc)) != target:
            excluded.append({'path': loc,
                             'reason': "등록된 설치 폴더지만 폴더 이름이 프로그램 이름과 달라 뺐습니다"
                                       "(여러 제품이 함께 쓰는 폴더일 수 있습니다)."})
        else:
            found.append((loc, 'certain', '프로그램이 등록한 설치 폴더'))

    # 2순위 — 이름이 정확히 같은 폴더
    if len(target) < 4:
        notes.append("프로그램 이름이 짧아 이름으로는 찾지 않았습니다.")
    elif target in ctx['guard'].names:
        notes.append(f"이름이 같은 다른 프로그램({ctx['guard'].names[target]})이 설치돼 있어 "
                     "이름으로는 찾지 않았습니다.")
    else:
        for raw, _, _ in ctx['roots']:
            try:
                names = os.listdir(raw)
            except OSError as e:
                log.warning(f"폴더 목록 읽기 실패 {raw}: {e}")
                continue
            for item in names:
                if item.startswith('.'):
                    continue        # .minecraft 같은 점 폴더는 대개 사용자 데이터다
                if _normalize(item) == target:
                    found.append((os.path.join(raw, item), 'likely', '프로그램 이름과 폴더 이름이 같음'))

    seen, items, index = set(), [], {}
    for path, conf, why in found:
        try:
            # 정션을 거친 등록 경로(C:\Users\옛이름\...)도 실제 위치로 보여 준다
            shown = os.path.realpath(os.path.normpath(path))
        except OSError:
            shown = os.path.normpath(path)
        n = safe_delete.norm(shown)
        if n in seen:
            continue
        seen.add(n)
        problem, root = _candidate_problem(shown, n, ctx)
        if problem:
            excluded.append({'path': shown, 'reason': problem})
            continue
        size, hints, complete = _inspect(shown)
        user_root = root[2]
        item = {
            "path": shown,
            "sizeMB": round(size / (1024 ** 2), 1),
            "sizeBytes": size,
            "confidence": conf,
            "reason": why,
            "location": 'appdata' if user_root else 'program',
            "locationLabel": '사용자 데이터 폴더(AppData)' if user_root else '프로그램 폴더',
            "userData": bool(hints),
            "userDataHints": hints,
            "inspected": complete,
            # 등록된 설치 폴더이고, AppData 가 아니고, 사용자 데이터 표지가 없고, 끝까지 확인했을 때만
            "selected": conf == 'certain' and not user_root and not hints and complete,
        }
        items.append(item)
        index[n] = item

    with _lock:
        _scans[app_id] = {'at': time.time(), 'items': index}
    out.update(ok=True, items=items)
    return out


def _fmt_bytes(b):
    mb = b / (1024 ** 2)
    return f"{mb / 1024:.2f}GB" if mb >= 1024 else f"{mb:.1f}MB"


def is_busy():
    """잔여 폴더를 휴지통으로 옮기는 중인지. 창 닫기 경고에 쓴다."""
    with _lock:
        return _busy > 0


def clean_leftovers(app_id, paths=None):
    """고른 잔여 폴더를 휴지통으로 옮긴다.

    직전 find_leftovers(app_id) 결과에 있던 경로만 받는다. 지우기 직전에 제거 여부,
    허용 루트의 바로 아래인지, 다른 설치 앱과 겹치는지를 다시 확인한다.
    반환: {success, partial, deleted, moved:[경로], freedMB, failed:[{path, reason}],
           notRecyclable:[{path, reason}], message}
    """
    global _busy
    res = {"success": False, "partial": False, "deleted": 0, "moved": [], "freedMB": 0,
           "failed": [], "notRecyclable": [], "message": ""}

    if not isinstance(app_id, str) or not app_id:
        res['message'] = "어느 프로그램의 폴더인지 알 수 없어 아무것도 옮기지 않았습니다."
        return res
    if not isinstance(paths, (list, tuple)) or not paths:
        res['message'] = "선택된 폴더가 없습니다."
        return res

    with _lock:
        scan = _scans.get(app_id)
        scan_items = dict(scan['items']) if scan and time.time() - scan['at'] <= _SCAN_TTL else None
    if scan_items is None:
        res['message'] = "남은 폴더 찾기를 다시 실행한 뒤 고르세요. 아무것도 옮기지 않았습니다."
        return res
    entry = _lookup(app_id)
    if not entry:
        res['message'] = "프로그램 정보를 찾지 못해 아무것도 옮기지 않았습니다."
        return res

    entries = _scan_registry()
    v = _verify(app_id, entry, entries)
    if not v['uninstalled']:
        res['message'] = "제거가 확인되지 않아 아무것도 옮기지 않았습니다. " + v['message']
        return res
    ctx = _context(entry, entries)

    targets, rejected, taken = [], [], set()
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            rejected.append({"path": str(p), "reason": "잘못된 경로"})
            continue
        try:
            n = safe_delete.norm(p)
        except Exception:
            rejected.append({"path": p, "reason": "경로를 해석하지 못했습니다."})
            continue
        item = scan_items.get(n)
        if item is None:
            rejected.append({"path": p, "reason": "직전 검색 결과에 없는 경로라 건드리지 않았습니다."})
            continue
        if n in taken:
            continue
        problem, _ = _candidate_problem(item['path'], n, ctx)
        if problem:
            rejected.append({"path": item['path'], "reason": problem})
            continue
        taken.add(n)
        targets.append((n, item))      # UI 문자열이 아니라 서버가 보관한 경로를 쓴다

    if not targets:
        res['failed'] = rejected
        res['message'] = "옮길 수 있는 폴더가 없어 아무것도 옮기지 않았습니다."
        return res

    with _lock:
        _busy += 1
    try:
        rb = safe_delete.to_recycle_bin([item['path'] for _, item in targets])
    except Exception as e:
        log.error(f"휴지통 이동 실패: {e}")
        rb = {"ok": [], "failed": [{"path": item['path'], "reason": f"휴지통 이동 실패: {e}"}
                                   for _, item in targets], "bytes": 0}
    finally:
        with _lock:
            _busy -= 1

    shown_of = {n: item['path'] for n, item in targets}

    def _n(p):
        try:
            return safe_delete.norm(p)
        except Exception:
            return None

    def reported(lst):
        """to_recycle_bin 이 돌려준 {path, reason} 을 원래 표기 경로로 바꾼다."""
        out, ns = [], set()
        for x in lst or []:
            x = dict(x) if isinstance(x, dict) else {"path": str(x), "reason": ""}
            n = _n(x.get('path'))
            if n:
                ns.add(n)
                x['path'] = shown_of.get(n, x.get('path'))
            out.append(x)
        return out, ns

    ok_n = {n for n in (_n(p) for p in rb.get('ok') or []) if n}
    rb_failed, failed_n = reported(rb.get('failed'))
    not_rec, not_rec_n = reported(rb.get('not_recyclable'))
    failed = list(rejected) + rb_failed
    accounted = ok_n | failed_n | not_rec_n

    moved = []
    for n, item in targets:
        still = os.path.exists(item['path'])
        if n in ok_n and not still:
            moved.append((n, item))
        elif n in ok_n:
            failed.append({"path": item['path'], "reason": "휴지통으로 옮긴 뒤에도 폴더가 남아 있습니다."})
        elif n not in accounted:
            failed.append({"path": item['path'],
                           "reason": "옮기지 못했습니다." if still else
                                     "폴더가 사라졌지만 휴지통으로 옮겨졌는지 확인하지 못했습니다."})

    freed = sum(item['sizeBytes'] for _, item in moved)
    with _lock:
        cur = _scans.get(app_id)
        if cur:
            for n, _ in moved:
                cur['items'].pop(n, None)

    parts = []
    if moved:
        parts.append(f"{len(moved)}개 폴더를 휴지통으로 옮겼습니다(약 {_fmt_bytes(freed)}). "
                     "휴지통에서 복구할 수 있습니다.")
    else:
        parts.append("아무 폴더도 옮기지 못했습니다.")
    if not_rec:
        parts.append(f"{len(not_rec)}개는 휴지통에 넣을 수 없어 건드리지 않았습니다.")
    if failed:
        parts.append(f"{len(failed)}개는 옮기지 못했습니다.")

    res.update(
        success=bool(moved) and not failed and not not_rec,
        partial=bool(moved) and bool(failed or not_rec),
        deleted=len(moved),
        moved=[item['path'] for _, item in moved],
        freedMB=round(freed / (1024 ** 2), 1),
        failed=failed,
        notRecyclable=not_rec,
        message=" ".join(parts),
    )
    log.info(f"잔여물 정리({entry['name']}): 이동 {len(moved)} 실패 {len(failed)} 휴지통 불가 {len(not_rec)}")
    return res
