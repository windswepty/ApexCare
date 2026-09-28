"""
APEX CARE - Windows 기본 앱 제거 · 원격 분석 정책.

두 종류의 항목이 있다.
  - 정책(원격 분석, Cortana): 레지스트리·서비스 변경. system_state 저널을 거쳐
    원래 값을 기록하므로 복구 센터에서 되돌릴 수 있다.
  - 앱 제거(Appx): 정확한 패키지 이름으로, APEX CARE 를 실행한 계정에서만 지운다.
    지우기 전에 debloat_removed.json 에 기록하고, restore_removed_apps() 가 그 기록으로
    앱 설치 폴더의 AppxManifest.xml 을 다시 등록해 되살린다. 설치 파일이 사라졌으면
    되살릴 수 없으므로 Microsoft Store 로 안내한다.

예전 구현이 한 일 (다시 하지 말 것):
  - '*zune*' 같은 와일드카드로 Remove-AppxPackage -AllUsers 와 Remove-AppxProvisionedPackage 를
    실행했다. Windows 11 의 기본 '미디어 플레이어'(Microsoft.ZuneMusic)까지 모든 계정과
    앞으로 만들 계정에서 지웠고, 설치 파일까지 사라져 되살릴 수 없었다.
  - 설치돼 있지 않은 앱도 '제거 완료' 로 보고했다.
  - 정책 항목을 'reg add' 로 셸에서 바로 썼다. 원래 값이 기록되지 않았고 shell=True 였다.
"""
import base64
import ctypes
import json
import logging
import os
import re
import subprocess
import threading
import time

log = logging.getLogger('Debloater')
CREATE_NO_WINDOW = 0x08000000
DEBLOAT_GROUP = 'debloat'

QUERY_TIMEOUT_SEC = 60
# Appx 제거는 디스크 속도에 따라 1분을 넘기는 일이 흔하다. 30초는 정상 동작을 시간 초과로 오인한다.
APPX_TIMEOUT_SEC = 180
RESTORE_TIMEOUT_SEC = 300
REMOVED_NAME = 'debloat_removed.json'

# 패키지 이름·전체 이름에 쓰이는 문자만 허용한다. 와일드카드(* ? [ ])는 들어갈 수 없다.
_PKG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._~\-]{1,200}$')

_APPX_NOTE = ("현재 계정에서만 제거합니다. 이 화면의 '제거한 앱' 에서 되살릴 수 있고, "
              "설치 파일이 사라졌으면 Microsoft Store 에서 다시 설치합니다.")

# 앱은 와일드카드가 아니라 정확한 패키지 이름으로만 찾는다. 게임 로그인(XboxIdentityProvider),
# Game Bar, 새 Xbox 앱(GamingApp), 미디어 플레이어(ZuneMusic)처럼 지우면 곤란한 패키지는 넣지 않는다.
DEBLOAT_SAFE_LIST = [
    {"id": "bing", "name": "MSN 뉴스·날씨 (Bing 앱)", "kind": "appx",
     "packages": ["Microsoft.BingNews", "Microsoft.BingWeather",
                  "Microsoft.BingFinance", "Microsoft.BingSports"],
     "note": _APPX_NOTE},
    {"id": "zune", "name": "영화 및 TV", "kind": "appx",
     "packages": ["Microsoft.ZuneVideo"],
     "note": "Windows 11 의 '미디어 플레이어'(Microsoft.ZuneMusic)는 건드리지 않습니다. " + _APPX_NOTE},
    {"id": "solitaire", "name": "Microsoft Solitaire Collection", "kind": "appx",
     "packages": ["Microsoft.MicrosoftSolitaireCollection"], "note": _APPX_NOTE},
    {"id": "skype", "name": "Skype", "kind": "appx",
     "packages": ["Microsoft.SkypeApp"], "note": _APPX_NOTE},
    {"id": "maps", "name": "Windows 지도", "kind": "appx",
     "packages": ["Microsoft.WindowsMaps"], "note": _APPX_NOTE},
    {"id": "yourphone", "name": "휴대폰과 연결 (Phone Link)", "kind": "appx",
     "packages": ["Microsoft.YourPhone"], "note": _APPX_NOTE},
    {"id": "3dbuilder", "name": "3D Builder", "kind": "appx",
     "packages": ["Microsoft.3DBuilder"], "note": _APPX_NOTE},
    {"id": "feedback", "name": "피드백 허브", "kind": "appx",
     "packages": ["Microsoft.WindowsFeedbackHub"], "note": _APPX_NOTE},
    {"id": "xbox", "name": "Xbox 콘솔 도우미 (구 Xbox 앱)", "kind": "appx",
     "packages": ["Microsoft.XboxApp"],
     "note": "게임 로그인, Xbox Game Bar, 새 Xbox 앱은 건드리지 않습니다. " + _APPX_NOTE},
    {"id": "telemetry", "name": "Windows 원격 분석 (Telemetry) 줄이기", "kind": "policy",
     "note": "원격 분석 정책을 최소로 두고 DiagTrack 서비스를 '사용 안 함'으로 바꿉니다(다음 부팅부터). 복구 센터에서 되돌릴 수 있습니다."},
    {"id": "cortana", "name": "Cortana 끄기", "kind": "policy",
     "note": "Cortana 사용 안 함 정책을 켭니다. 복구 센터에서 되돌릴 수 있습니다."},
]
for _it in DEBLOAT_SAFE_LIST:
    # UI 가 쓰는 키. reversible = 복구 센터에서 되돌림, restorable = 이 화면에서 되살림(설치 파일이 남아 있을 때)
    _it["reversible"] = _it["kind"] == "policy"
    _it["restorable"] = _it["kind"] == "appx"
    _it["pattern"] = ", ".join(_it.get("packages", [])) or "policy"      # 예전 키
_ITEMS_BY_ID = {x["id"]: x for x in DEBLOAT_SAFE_LIST}

# 한 항목에 패키지가 여럿이면 '제거한 앱' 목록에 같은 이름이 여러 줄 보인다. 패키지마다 앱 이름을 붙여 구분한다.
PACKAGE_APP_NAMES = {
    "Microsoft.BingNews": "뉴스", "Microsoft.BingWeather": "날씨",
    "Microsoft.BingFinance": "금융", "Microsoft.BingSports": "스포츠",
}


def _idle_state():
    return {"running": False, "progress_pct": 0, "current_task": "", "error": None,
            "succeeded": [], "failed": [], "skipped": []}


_debloat_state = _idle_state()
_state_lock = threading.Lock()      # 시작 판정과 상태 교체
_op_lock = threading.Lock()         # 제거와 되살리기가 동시에 돌지 않게
_removed_lock = threading.RLock()   # debloat_removed.json 읽기-수정-쓰기


# ─────────────────────────────────────────────
# PowerShell
# ─────────────────────────────────────────────
# 인자는 명령줄에 끼워 넣지 않고 환경 변수(JSON)로 넘긴다. 스크립트는 -EncodedCommand 로
# 넘겨 따옴표 해석 문제를 없앤다. 출력은 항상 {"ok":..., "rows":[...]} 한 줄이다.

_ARG_ENV = 'APEX_DEBLOAT_ARG'

_PS_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$arg = $env:APEX_DEBLOAT_ARG | ConvertFrom-Json
$out = New-Object System.Collections.ArrayList
"""

_PS_EMIT = r"""
ConvertTo-Json -InputObject ([ordered]@{ ok = $true; rows = @($out) }) -Compress -Depth 5
"""

# 읽기만 한다. -AllUsers 를 쓰지 않는다: 이 계정에 설치된 것만 본다.
_PS_QUERY = r"""
foreach ($n in @($arg.names)) {
  try {
    foreach ($p in @(Get-AppxPackage -Name $n -ErrorAction Stop)) {
      [void]$out.Add([ordered]@{
        query = [string]$n; name = [string]$p.Name
        fullName = [string]$p.PackageFullName; familyName = [string]$p.PackageFamilyName
        installLocation = [string]$p.InstallLocation
        nonRemovable = [bool]$p.NonRemovable; isFramework = [bool]$p.IsFramework
      })
    }
  } catch {
    [void]$out.Add([ordered]@{ query = [string]$n; error = [string]$_.Exception.Message })
  }
}
"""

# 이 계정에서만 지운다. 다른 계정·Windows 이미지(프로비저닝)는 건드리지 않아 설치 파일이 남는다.
_PS_REMOVE = r"""
foreach ($f in @($arg.fullNames)) {
  try {
    Remove-AppxPackage -Package $f -ErrorAction Stop
    [void]$out.Add([ordered]@{ fullName = [string]$f; ok = $true; error = '' })
  } catch {
    [void]$out.Add([ordered]@{ fullName = [string]$f; ok = $false; error = [string]$_.Exception.Message })
  }
}
"""

_PS_REGISTER = r"""
foreach ($m in @($arg.manifests)) {
  try {
    Add-AppxPackage -DisableDevelopmentMode -Register $m -ErrorAction Stop
    [void]$out.Add([ordered]@{ manifest = [string]$m; ok = $true; error = '' })
  } catch {
    [void]$out.Add([ordered]@{ manifest = [string]$m; ok = $false; error = [string]$_.Exception.Message })
  }
}
"""


def _powershell_exe():
    """Windows PowerShell 절대 경로. 32비트 파이썬이면 Sysnative 로 64비트 쪽을 쓴다."""
    root = os.environ.get('SystemRoot') or r'C:\Windows'
    sysnative = os.path.join(root, 'Sysnative', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    if os.path.exists(sysnative):
        return sysnative
    return os.path.join(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')


def _decode(b):
    if not b:
        return ''
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('mbcs' if os.name == 'nt' else 'latin-1', errors='replace')


def _run_ps_json(body, arg, timeout):
    """스크립트를 실행하고 (ok, rows, error) 를 돌려준다. 셸을 거치지 않는다.

    시간이 지나면 subprocess.TimeoutExpired 를 그대로 올린다. 호출한 쪽은 '시간 초과 = 실패' 로
    단정하지 말고 실제 상태를 다시 확인해야 한다. Appx 작업은 배포 서비스가 해서 끝까지 갈 수 있다.
    """
    script = _PS_PRELUDE + body + _PS_EMIT
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    env = dict(os.environ)
    env[_ARG_ENV] = json.dumps(arg, ensure_ascii=True)
    r = subprocess.run([_powershell_exe(), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                       shell=False, stdin=subprocess.DEVNULL, capture_output=True, env=env,
                       creationflags=CREATE_NO_WINDOW, timeout=timeout)
    text = _decode(r.stdout)
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                data = json.loads(line)
            except ValueError:
                break
            rows = data.get('rows')
            if isinstance(rows, dict):
                rows = [rows]
            return True, [x for x in (rows or []) if isinstance(x, dict)], None
    msg = _decode(r.stderr).strip() or text.strip() or f'종료 코드 {r.returncode}'
    return False, [], msg[-400:]


def _query_packages(names):
    """정확한 패키지 이름으로 현재 계정에 설치된 패키지를 찾는다. 읽기만 한다. (ok, rows, error)"""
    names = [n for n in names if isinstance(n, str) and _PKG_RE.match(n)]
    if not names:
        return True, [], None
    try:
        return _run_ps_json(_PS_QUERY, {'names': names}, QUERY_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False, [], '설치 상태 확인이 시간 안에 끝나지 않았습니다'
    except Exception as e:
        return False, [], str(e) or type(e).__name__


# ─────────────────────────────────────────────
# 계정
# ─────────────────────────────────────────────

def _current_account():
    """이 프로세스를 실행한 계정 이름. 앱 제거는 이 계정에만 적용된다."""
    try:
        buf = ctypes.create_unicode_buffer(257)
        size = ctypes.c_ulong(257)
        if ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(size)):
            return buf.value
    except Exception:
        pass
    return os.environ.get('USERNAME', '')


def _desktop_accounts():
    """바탕 화면(explorer.exe)을 쓰는 계정 이름들(소문자). 알 수 없으면 빈 집합.

    다른 관리자 계정으로 승격해 APEX CARE 를 실행하면 '현재 계정' 이 바탕 화면 사용자와 달라진다.
    그때 지우면 사용자의 앱은 그대로인데 '제거함' 으로 보고하게 된다.
    """
    names = set()
    try:
        import psutil
        for p in psutil.process_iter(['name', 'username']):
            if (p.info.get('name') or '').lower() == 'explorer.exe':
                user = (p.info.get('username') or '').split('\\')[-1].strip().lower()
                if user:
                    names.add(user)
    except Exception:
        pass
    return names


# ─────────────────────────────────────────────
# 제거 기록 (debloat_removed.json)
# ─────────────────────────────────────────────

def _removed_path():
    from backend import config_manager
    return os.path.join(config_manager.APPDATA_DIR, REMOVED_NAME)


def _load_removed():
    """기록을 읽는다. 읽을 수 없으면 None (그때는 제거하지 않는다).

    깨졌으면 조용히 버리지 않고 옆에 보존한 뒤 빈 기록으로 시작한다.
    """
    path = _removed_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('apps'), list):
            data['apps'] = [a for a in data['apps'] if isinstance(a, dict)]
            return data
        raise ValueError('형식이 맞지 않습니다')
    except FileNotFoundError:
        return {'version': 1, 'apps': []}
    except (ValueError, UnicodeDecodeError) as e:
        log.error(f"제거 기록이 깨졌습니다: {e}")
        for i in range(1, 100):
            dst = f"{path}.corrupt-{i}"
            if not os.path.exists(dst):
                try:
                    os.replace(path, dst)
                    return {'version': 1, 'apps': []}
                except OSError as e2:
                    log.error(f"깨진 기록을 옮기지 못했습니다: {e2}")
                    return None
        return None
    except OSError as e:
        log.error(f"제거 기록을 읽지 못했습니다: {e}")
        return None


def _save_removed(data):
    """원자적으로 쓴다. 쓰다가 죽어도 이전 기록이 남는다."""
    path = _removed_path()
    tmp = path + '.tmp'
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception as e:
        log.error(f"제거 기록 저장 실패: {e}")
        try:
            os.remove(tmp)            # 우리가 만든 임시 파일만 지운다
        except OSError:
            pass
        return False


def _record_removed(pkgs, item, account):
    """지우기 '전에' 기록한다. 기록을 못 하면 False 이고, 그때는 지우지 않는다."""
    with _removed_lock:
        data = _load_removed()
        if data is None:
            return False
        known = {a.get('fullName') for a in data['apps']}
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        for p in pkgs:
            if p['fullName'] in known:
                continue
            data['apps'].append({
                'name': p['name'], 'fullName': p['fullName'], 'familyName': p['familyName'],
                'installLocation': p.get('installLocation') or '',
                'itemId': item['id'], 'label': item['name'],
                'account': account, 'removedAt': now,
            })
        return _save_removed(data)


def _forget_removed(full_names):
    """실제로는 지워지지 않았거나 되살린 패키지를 기록에서 뺀다."""
    full_names = set(full_names)
    if not full_names:
        return True
    with _removed_lock:
        data = _load_removed()
        if data is None:
            return False
        before = len(data['apps'])
        data['apps'] = [a for a in data['apps'] if a.get('fullName') not in full_names]
        return True if len(data['apps']) == before else _save_removed(data)


def _windowsapps_roots():
    pf = os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles') or r'C:\Program Files'
    root = os.environ.get('SystemRoot') or r'C:\Windows'
    return [os.path.join(pf, 'WindowsApps'), os.path.join(root, 'SystemApps')]


def _manifest_path(install_location):
    """되살릴 때 등록할 AppxManifest.xml. Windows 앱 설치 폴더 밖이거나 파일이 없으면 None.

    기록 파일은 사용자 폴더에 있어 다른 프로그램이 고칠 수 있다. 경로를 믿지 않고
    실경로가 WindowsApps·SystemApps 안인지 다시 확인한다. 관리자 권한으로 아무 매니페스트나
    등록하게 두면 안 된다.
    """
    if not isinstance(install_location, str) or not install_location.strip():
        return None
    if any(c in install_location for c in '*?[]"\'`$;|&<>\r\n'):
        return None
    try:
        loc = os.path.normcase(os.path.realpath(install_location))
        inside = False
        for r in _windowsapps_roots():
            rr = os.path.normcase(os.path.realpath(r))
            try:
                if os.path.commonpath([loc, rr]) == rr and loc != rr:
                    inside = True
                    break
            except ValueError:
                continue
        if not inside:
            return None
        manifest = os.path.join(os.path.realpath(install_location), 'AppxManifest.xml')
        return manifest if os.path.isfile(manifest) else None
    except Exception:
        return None


def get_removed_apps():
    """이 앱이 제거한 패키지 목록. 되살리기 화면이 쓴다."""
    with _removed_lock:
        data = _load_removed()
    out = []
    for a in (data or {}).get('apps', []):
        e = dict(a)
        e['manifestFound'] = _manifest_path(a.get('installLocation')) is not None
        e['appName'] = PACKAGE_APP_NAMES.get(str(a.get('name') or ''), '')
        out.append(e)
    return out


def _store_hint(entry):
    label = entry.get('label') or entry.get('name') or ''
    return f"Microsoft Store 에서 '{label}' 을(를) 검색해 다시 설치할 수 있습니다."


# ─────────────────────────────────────────────
# 앱 제거
# ─────────────────────────────────────────────

def _apply_appx_item(item, account):
    """앱 항목 하나를 제거한다. 설치 확인 → 기록 → 제거 → 다시 확인.

    반환: ('removed'|'not_installed'|'failed'|'unknown', 설명)
    """
    ok, rows, err = _query_packages(item['packages'])
    if not ok:
        return 'failed', f'설치 상태를 확인하지 못해 제거하지 않았습니다: {err}'

    problems = [f"{r.get('query')}: 설치 상태 확인 실패 ({r.get('error')})" for r in rows if r.get('error')]
    found = [r for r in rows if not r.get('error') and _PKG_RE.match(str(r.get('fullName') or ''))]
    blocked = [r for r in found if r.get('nonRemovable') or r.get('isFramework')]
    targets = [r for r in found if r not in blocked]
    problems += [f"{r.get('name')}: Windows 가 제거를 막아 둔 패키지입니다" for r in blocked]

    if not found and not problems:
        return 'not_installed', '설치돼 있지 않습니다 (변경 없음)'
    if not targets:
        return 'failed', '; '.join(problems)

    # 되살릴 수 있게 지우기 전에 기록한다. 기록을 못 하면 지우지 않는다.
    if not _record_removed(targets, item, account):
        return 'failed', '제거 기록을 저장하지 못해 지우지 않았습니다'

    errors, timed_out = {}, False
    try:
        ok_r, rrows, rerr = _run_ps_json(_PS_REMOVE, {'fullNames': [r['fullName'] for r in targets]},
                                         APPX_TIMEOUT_SEC)
        if ok_r:
            errors = {r.get('fullName'): r.get('error') or '' for r in rrows if not r.get('ok')}
        else:
            errors = {r['fullName']: rerr or '' for r in targets}
    except subprocess.TimeoutExpired:
        timed_out = True
    except Exception as e:
        errors = {r['fullName']: str(e) for r in targets}

    # 명령의 반환값을 믿지 않는다. 남아 있는지 직접 다시 확인한다.
    ok2, rows2, err2 = _query_packages(item['packages'])
    if not ok2:
        # 기록은 남겨 둔다. 되살리기가 설치 여부를 다시 확인한다.
        return 'unknown', (('시간 초과. ' if timed_out else '') + f'제거됐는지 확인하지 못했습니다: {err2}')
    still = {str(r.get('familyName', '')).lower() for r in rows2 if not r.get('error')}
    removed, not_removed = [], []
    for r in targets:
        if str(r.get('familyName', '')).lower() in still:
            why = errors.get(r['fullName']) or ('시간 초과' if timed_out else '제거되지 않았습니다')
            problems.append(f"{r['name']}: {why}")
            not_removed.append(r['fullName'])
        else:
            removed.append(r['name'])
    if not_removed and not _forget_removed(not_removed):
        log.warning("지워지지 않은 패키지를 제거 기록에서 빼지 못했습니다")

    if removed and not problems:
        return 'removed', ', '.join(removed) + ' 제거함'
    if removed:
        return 'failed', f"{len(removed)}개 제거, 실패: " + '; '.join(problems)
    return 'failed', '; '.join(problems) or '제거하지 못했습니다'


# ─────────────────────────────────────────────
# 되살리기
# ─────────────────────────────────────────────

def restore_removed_apps(names=None):
    """제거한 앱을 되살린다.

    names: None 이면 전부. 아니면 패키지 이름·패밀리 이름·전체 이름 중 하나가 맞는 것만.
    Add-AppxPackage -DisableDevelopmentMode -Register <설치 폴더>\\AppxManifest.xml 로 다시 등록하고,
    등록 뒤 실제로 설치돼 있는지 다시 확인한다. 되살린 것만 기록에서 뺀다.
    """
    if _debloat_state.get("running") or not _op_lock.acquire(blocking=False):
        return {'success': False, 'restored': [], 'failed': [],
                'message': '다른 정리 작업이 진행 중입니다. 끝난 뒤 다시 시도해 주세요.'}
    try:
        return _restore_removed_locked(names)
    except Exception as e:
        log.warning(f"앱 되살리기 오류: {e}")
        return {'success': False, 'restored': [], 'failed': [],
                'message': f'되살리기 중 오류가 났습니다: {e}'}
    finally:
        _op_lock.release()


def _restore_removed_locked(names):
    entries = get_removed_apps()
    if names is not None:
        if isinstance(names, str):
            names = [names]
        wanted = {n.lower() for n in (names or []) if isinstance(n, str)}
        entries = [e for e in entries
                   if {str(e.get(k, '')).lower() for k in ('name', 'familyName', 'fullName')} & wanted]
    if not entries:
        return {'success': True, 'restored': [], 'failed': [], 'nothingToRestore': True,
                'message': '되살릴 앱이 없습니다.'}

    ok, rows, err = _query_packages(sorted({e.get('name', '') for e in entries}))
    if not ok:
        # 지금 상태를 모르면 아무것도 하지 않는다. 기록도 그대로 둔다.
        return {'success': False, 'restored': [],
                'failed': [{'name': e.get('name'), 'label': e.get('label'),
                            'reason': f'설치 상태를 확인하지 못했습니다: {err}'} for e in entries],
                'message': f'설치 상태를 확인하지 못해 되살리지 않았습니다: {err}'}

    installed = {str(r.get('familyName', '')).lower() for r in rows if not r.get('error')}
    restored, failed, forget, to_register = [], [], [], []
    me = _current_account().lower()

    for e in entries:
        acc = str(e.get('account') or '')
        if acc and me and acc.lower() != me:
            # 다른 계정에서 지운 앱을 이 계정에 등록하면 '되살렸다' 고 잘못 보고하게 된다.
            failed.append({'name': e.get('name'), 'label': e.get('label'),
                           'reason': f'다른 계정({acc})에서 제거한 앱입니다. 그 계정으로 실행해 되살려 주세요.'})
            continue
        if str(e.get('familyName', '')).lower() in installed:
            restored.append(e.get('label') or e.get('name'))      # 이미 설치돼 있다
            forget.append(e.get('fullName'))
            continue
        manifest = _manifest_path(e.get('installLocation'))
        if not manifest:
            failed.append({'name': e.get('name'), 'label': e.get('label'),
                           'reason': '설치 파일이 남아 있지 않습니다. ' + _store_hint(e)})
            continue
        to_register.append((e, manifest))

    if to_register:
        reg_errors = {}
        try:
            ok_r, rrows, rerr = _run_ps_json(_PS_REGISTER, {'manifests': [m for _, m in to_register]},
                                             RESTORE_TIMEOUT_SEC)
            if ok_r:
                reg_errors = {str(r.get('manifest', '')).lower(): r.get('error') or ''
                              for r in rrows if not r.get('ok')}
            else:
                reg_errors = {m.lower(): rerr or '' for _, m in to_register}
        except subprocess.TimeoutExpired:
            reg_errors = {m.lower(): '시간 초과' for _, m in to_register}
        except Exception as ex:
            reg_errors = {m.lower(): str(ex) for _, m in to_register}

        # 등록 명령의 성패를 믿지 않는다. 실제로 설치돼 있는지 다시 확인한다.
        ok2, rows2, err2 = _query_packages(sorted({e.get('name', '') for e, _ in to_register}))
        now_installed = {str(r.get('familyName', '')).lower() for r in rows2 if not r.get('error')}
        for e, m in to_register:
            if ok2 and str(e.get('familyName', '')).lower() in now_installed:
                restored.append(e.get('label') or e.get('name'))
                forget.append(e.get('fullName'))
            else:
                why = reg_errors.get(m.lower()) or (
                    f'확인 실패: {err2}' if not ok2 else '등록 뒤에도 설치돼 있지 않습니다')
                failed.append({'name': e.get('name'), 'label': e.get('label'),
                               'reason': f'{why} {_store_hint(e)}'.strip()})

    if forget and not _forget_removed(forget):
        log.warning("되살린 앱을 기록에서 빼지 못했습니다 (다음 시도 때 다시 확인합니다)")

    if failed and restored:
        msg = (f"{len(restored)}개 되살림, {len(failed)}개 실패. "
               "실패한 앱은 Microsoft Store 에서 다시 설치할 수 있습니다.")
    elif failed:
        msg = "되살리지 못했습니다. Microsoft Store 에서 다시 설치할 수 있습니다."
    else:
        msg = f"{len(restored)}개 앱을 되살렸습니다."
    return {'success': not failed, 'restored': restored, 'failed': failed, 'message': msg}


# ─────────────────────────────────────────────
# 정책 (system_state 저널)
# ─────────────────────────────────────────────

def _apply_telemetry_policy():
    """원격 분석 정책 + DiagTrack 서비스. 모두 저널에 원래 값을 기록한다. (ok, 사유)"""
    from backend import system_state as ss
    reasons = []
    r = ss.set_registry('HKLM', r'SOFTWARE\Policies\Microsoft\Windows\DataCollection',
                        'AllowTelemetry', 0, group=DEBLOAT_GROUP,
                        why='디블로터: 원격 분석 수준 최소화 정책 (AllowTelemetry=0)')
    if not r.get('ok'):
        reasons.append(f"정책: {r.get('reason')}")
    # 서비스는 시작 유형만 바꾼다(다음 부팅부터 반영). 실행 중인 서비스를 즉시 멈추면
    # 그 상태는 기록·복구할 수 없다. 이 PC 에 없는 서비스면 건너뛴다.
    if ss.service_start_type('DiagTrack') is not None:
        r = ss.set_service_start('DiagTrack', 'disabled', DEBLOAT_GROUP,
                                 why="디블로터: 원격 분석 서비스(DiagTrack) '사용 안 함'")
        if not r.get('ok'):
            reasons.append(f"DiagTrack: {r.get('reason')}")
    return (not reasons), '; '.join(reasons)


def _apply_cortana_policy():
    from backend import system_state as ss
    r = ss.set_registry('HKLM', r'SOFTWARE\Policies\Microsoft\Windows\Windows Search',
                        'AllowCortana', 0, group=DEBLOAT_GROUP,
                        why='디블로터: Cortana 사용 안 함 정책 (AllowCortana=0)')
    return bool(r.get('ok')), r.get('reason', '')


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────

def get_debloat_list():
    return DEBLOAT_SAFE_LIST


def get_debloat_status():
    return _debloat_state


def is_busy():
    """앱 제거나 되살리기가 진행 중인지. 창을 닫기 전에 확인한다(도중에 끝나면 기록과 실제가 어긋난다)."""
    return bool(_debloat_state.get("running")) or _op_lock.locked()


def _account_problem(account):
    """앱 제거를 막아야 할 계정 문제. 없으면 None."""
    desktop = _desktop_accounts()
    if not account:
        return '이 프로그램을 실행한 계정을 알 수 없어 앱을 제거하지 않았습니다'
    if desktop and account.lower() not in desktop:
        return (f"APEX CARE 가 다른 계정({account})으로 실행 중입니다. 바탕 화면 계정"
                f"({', '.join(sorted(desktop))})의 앱은 이 계정에서 지울 수 없어 제거하지 않았습니다")
    return None


def _run_debloater(selected_ids):
    st = _debloat_state          # start_debloater 가 스레드를 띄우기 전에 새 상태로 바꿔 두었다
    with _op_lock:
        try:
            total = len(selected_ids)
            if total == 0:
                st["progress_pct"] = 100
                st["current_task"] = "선택된 항목이 없습니다."
                return

            account = _current_account()
            account_problem = None
            if any(_ITEMS_BY_ID.get(i, {}).get('kind') == 'appx' for i in selected_ids):
                account_problem = _account_problem(account)
            succeeded, failed, skipped = [], [], []

            for i, item_id in enumerate(selected_ids):
                item = _ITEMS_BY_ID.get(item_id)
                if not item:
                    continue
                st["current_task"] = f"{item['name']} {'제거' if item['kind'] == 'appx' else '적용'} 중..."
                log.info(f"Debloating: {item['name']} (ID: {item_id})")

                # 항목 하나가 실패하거나 시간을 초과해도 나머지 항목은 계속 처리한다.
                try:
                    if item['kind'] == 'appx':
                        status, reason = ('failed', account_problem) if account_problem \
                            else _apply_appx_item(item, account)
                    elif item_id == 'telemetry':
                        ok, reason = _apply_telemetry_policy()
                        status = 'removed' if ok else 'failed'
                    else:
                        ok, reason = _apply_cortana_policy()
                        status = 'removed' if ok else 'failed'
                except Exception as e:
                    log.warning(f"✗ Debloat failed: {item['name']} -> {e}")
                    status, reason = 'failed', str(e) or type(e).__name__

                if status == 'removed':
                    succeeded.append(item["name"])
                elif status == 'not_installed':
                    skipped.append(f"{item['name']} ({reason})")
                else:
                    failed.append(f"{item['name']} ({reason})" if reason else item["name"])

                st["progress_pct"] = int(((i + 1) / total) * 100)

            st.update(progress_pct=100, succeeded=succeeded, failed=failed, skipped=skipped)
            # 실제 결과를 그대로 보고한다. 변경이 없던 항목은 성공으로 세지 않는다.
            parts = []
            if succeeded:
                parts.append(f"{len(succeeded)}개 완료")
            if failed:
                parts.append(f"{len(failed)}개 실패: {', '.join(failed)}")
            if skipped:
                parts.append(f"{len(skipped)}개 변경 없음")
            st["current_task"] = ' / '.join(parts) or '변경한 항목이 없습니다.'
            log.info(f"Debloater finished. ok={len(succeeded)} failed={len(failed)} skipped={len(skipped)}")
        except Exception as e:
            st["error"] = str(e)
            st["current_task"] = f"오류 발생: {e}"
            log.warning(f"⚠ Debloater exception: {e}")
        finally:
            st["running"] = False


def start_debloater(selected_ids):
    global _debloat_state
    if not isinstance(selected_ids, (list, tuple)):
        return {"success": False, "message": "선택 목록 형식이 올바르지 않습니다."}
    ids = []
    for x in selected_ids:
        if isinstance(x, str) and x not in ids:
            ids.append(x)
    with _state_lock:
        if _debloat_state["running"] or _op_lock.locked():
            return {"success": False, "message": "이미 다른 정리 작업이 진행 중입니다."}
        st = _idle_state()
        st.update(running=True, current_task="시작 중...")
        _debloat_state = st
        try:
            threading.Thread(target=_run_debloater, args=(ids,), daemon=True).start()
        except Exception as e:
            st.update(running=False, error=str(e), current_task=f"오류 발생: {e}")
            return {"success": False, "message": f"시작하지 못했습니다: {e}"}
    return {"success": True}
