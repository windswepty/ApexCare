"""
APEX CARE — 기본 앱 정리 · 수집 정책 (디블로터)

하는 일은 두 종류다.
  1. 기본 앱(Appx) 제거
     명시한 패키지 이름만, APEX CARE 를 실행한 계정에서만 지운다.
     다른 계정, 앞으로 만들 계정, Windows 이미지(프로비저닝)는 건드리지 않는다.
     지우기 전에 패키지 정보를 debloat_removed.json 에 기록하고,
     restore_removed_apps() 가 그 기록으로 되살린다.
  2. 정책·서비스 변경 (진단 데이터, Cortana)
     system_state 를 거쳐 원래 값을 기록하고, 쓴 뒤 다시 읽어 확인한다.
     복구 센터(restore_group('debloat'))에서 되돌린다.

예전 코드가 한 일 (다시 하지 말 것):
  - '*zune*' 같은 와일드카드로 Remove-AppxPackage -AllUsers 와
    Remove-AppxProvisionedPackage 를 실행했다. Windows 11 의 기본 '미디어 플레이어'
    (Microsoft.ZuneMusic)까지 모든 계정과 새 계정에서 지웠다.
  - reg add /f 로 정책을 원래 값 기록 없이 덮어썼다. 되돌릴 방법이 없었다.
  - 설치돼 있지 않은 앱도 '제거 완료' 로 보고했다.
  - shell=True 로 PowerShell 을 띄워, 시간 초과 때 cmd.exe 만 죽고 PowerShell 은 남았다.
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
import winreg

log = logging.getLogger('Debloater')
CREATE_NO_WINDOW = 0x08000000

GROUP = 'debloat'      # system_state 저널의 그룹 이름. 복구 센터가 이 이름으로 묶어 보여준다.

APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
REMOVED_PATH = os.path.join(APPDATA_DIR, 'debloat_removed.json')

QUERY_TIMEOUT_SEC = 60
# Appx 제거는 디스크 속도에 따라 1분을 넘기기도 한다. 30초는 정상 동작을 시간 초과로 오인한다.
APPX_TIMEOUT_SEC = 180
RESTORE_TIMEOUT_SEC = 300

# 패키지 이름·전체 이름에 쓰이는 문자만 허용한다. 와일드카드(* ? [ ])는 들어갈 수 없다.
_PKG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._~\-]{1,200}$')


# ─────────────────────────────────────────────
# 항목 정의
# ─────────────────────────────────────────────
# 앱은 와일드카드가 아니라 정확한 패키지 이름(Name)으로만 찾는다.
# 게임 로그인(XboxIdentityProvider), Game Bar, 새 Xbox 앱(GamingApp),
# 미디어 플레이어(ZuneMusic)처럼 지우면 곤란한 패키지는 넣지 않는다.

APPX_ITEMS = [
    {"id": "bing", "name": "MSN 뉴스·날씨 (Bing 앱)",
     "packages": ["Microsoft.BingNews", "Microsoft.BingWeather",
                  "Microsoft.BingFinance", "Microsoft.BingSports"],
     "note": ""},
    {"id": "zune", "name": "영화 및 TV",
     "packages": ["Microsoft.ZuneVideo"],
     "note": "Windows 11 의 '미디어 플레이어'(Microsoft.ZuneMusic)는 건드리지 않습니다."},
    {"id": "solitaire", "name": "Microsoft Solitaire Collection",
     "packages": ["Microsoft.MicrosoftSolitaireCollection"], "note": ""},
    {"id": "skype", "name": "Skype",
     "packages": ["Microsoft.SkypeApp"], "note": ""},
    {"id": "maps", "name": "Windows 지도",
     "packages": ["Microsoft.WindowsMaps"], "note": ""},
    {"id": "yourphone", "name": "휴대폰과 연결",
     "packages": ["Microsoft.YourPhone"], "note": ""},
    {"id": "3dbuilder", "name": "3D Builder",
     "packages": ["Microsoft.3DBuilder"], "note": ""},
    {"id": "feedback", "name": "피드백 허브",
     "packages": ["Microsoft.WindowsFeedbackHub"], "note": ""},
    {"id": "xbox", "name": "Xbox 본체 도우미 (옛 Xbox 앱)",
     "packages": ["Microsoft.XboxApp"],
     "note": "게임 로그인, Game Bar, 새 Xbox 앱은 건드리지 않습니다."},
]

_TELEMETRY_PATH = r"SOFTWARE\Policies\Microsoft\Windows\DataCollection"
_CORTANA_PATH = r"SOFTWARE\Policies\Microsoft\Windows\Windows Search"
_DIAGTRACK_PATH = r"SYSTEM\CurrentControlSet\Services\DiagTrack"

POLICY_ITEMS = [
    {"id": "telemetry", "name": "진단 데이터(원격 분석) 줄이기",
     "changes": [
         {"type": "registry", "hive": "HKLM", "path": _TELEMETRY_PATH,
          "name": "AllowTelemetry", "value": 0,
          "label": "정책 AllowTelemetry = 0",
          "why": "디블로터: 진단 데이터 정책(AllowTelemetry=0)"},
         {"type": "service", "service": "DiagTrack", "start": "disabled", "startValue": 4,
          "label": "DiagTrack(연결된 사용자 환경 및 원격 분석) 서비스 → 사용 안 함",
          "why": "디블로터: DiagTrack 서비스 사용 안 함"},
     ]},
    {"id": "cortana", "name": "Cortana 끄기",
     "changes": [
         {"type": "registry", "hive": "HKLM", "path": _CORTANA_PATH,
          "name": "AllowCortana", "value": 0,
          "label": "정책 AllowCortana = 0",
          "why": "디블로터: Cortana 정책(AllowCortana=0)"},
     ]},
]

# 예전 이름을 유지한다(외부에서 참조할 수 있다). 내용은 위 두 목록이다.
DEBLOAT_SAFE_LIST = (
    [dict(x, kind='appx') for x in APPX_ITEMS] +
    [dict(x, kind='policy') for x in POLICY_ITEMS]
)
_ITEMS_BY_ID = {x['id']: x for x in DEBLOAT_SAFE_LIST}


# ─────────────────────────────────────────────
# 상태
# ─────────────────────────────────────────────

def _idle_state():
    return {
        "running": False,
        "progress_pct": 0,
        "current_task": "",
        "error": None,
        "succeeded": [],
        "failed": [],
        "skipped": [],
        "results": [],
    }


_debloat_state = _idle_state()
_state_lock = threading.Lock()     # 시작 판정과 상태 교체
_op_lock = threading.Lock()        # 제거와 되살리기가 동시에 돌지 않게
_removed_lock = threading.RLock()  # debloat_removed.json 읽기-수정-쓰기


def is_busy():
    """제거나 되살리기가 진행 중인지. 창 닫기 가드가 쓴다."""
    return bool(_debloat_state.get("running")) or _op_lock.locked()


# ─────────────────────────────────────────────
# PowerShell 실행
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

# -AllUsers 를 쓰지 않는다. 이 프로세스를 실행한 계정에서만 지운다.
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
        return b.decode('mbcs', errors='replace')


def _kill_tree(proc):
    """시간 초과 때 PowerShell 과 그 자식까지 확실히 끝낸다."""
    try:
        import psutil
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            pass
    except ImportError:
        root = os.environ.get('SystemRoot') or r'C:\Windows'
        try:
            subprocess.run([os.path.join(root, 'System32', 'taskkill.exe'),
                            '/PID', str(int(proc.pid)), '/T', '/F'],
                           shell=False, capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=15)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.communicate(timeout=10)
    except Exception:
        pass


def _run_ps_json(body, arg, timeout):
    """스크립트를 실행하고 (ok, rows, error) 를 돌려준다.

    시간이 지나면 프로세스 트리를 정리하고 subprocess.TimeoutExpired 를 그대로 올린다.
    호출한 쪽은 '시간 초과 = 실패' 로 단정하지 말고 실제 상태를 다시 확인해야 한다.
    Appx 작업은 AppX 배포 서비스가 하므로 PowerShell 이 죽어도 끝까지 진행될 수 있다.
    """
    script = _PS_PRELUDE + body + _PS_EMIT
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    env = dict(os.environ)
    env[_ARG_ENV] = json.dumps(arg, ensure_ascii=True)
    cmd = [_powershell_exe(), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]

    proc = subprocess.Popen(cmd, shell=False, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, creationflags=CREATE_NO_WINDOW)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        raise

    text = _decode(out)
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
            return True, [r for r in (rows or []) if isinstance(r, dict)], None
    msg = (_decode(err).strip() or text.strip() or f'종료 코드 {proc.returncode}')
    return False, [], msg[-400:]


def _clean_names(names):
    return [n for n in names if isinstance(n, str) and _PKG_RE.match(n)]


def _query_packages(names):
    """정확한 패키지 이름으로 현재 계정에 설치된 패키지를 찾는다. 읽기만 한다."""
    names = _clean_names(names)
    if not names:
        return True, [], None
    try:
        return _run_ps_json(_PS_QUERY, {'names': names}, QUERY_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False, [], '설치 상태 확인이 시간 안에 끝나지 않았습니다'
    except Exception as e:
        return False, [], str(e)


# ─────────────────────────────────────────────
# 제거 기록 (debloat_removed.json)
# ─────────────────────────────────────────────

def _load_removed():
    """기록을 읽는다. 읽을 수 없으면 None (그때는 제거하지 않는다).

    파일이 깨졌으면 조용히 버리지 않고 옆에 보존한 뒤 빈 기록으로 시작한다.
    """
    try:
        with open(REMOVED_PATH, 'r', encoding='utf-8') as f:
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
            dst = f"{REMOVED_PATH}.corrupt-{i}"
            if not os.path.exists(dst):
                try:
                    os.replace(REMOVED_PATH, dst)
                    log.error(f"깨진 기록을 {dst} 로 옮겼습니다")
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
    if not os.environ.get('APPDATA'):
        log.error("APPDATA 경로를 알 수 없어 제거 기록을 저장하지 않습니다")
        return False
    tmp = REMOVED_PATH + '.tmp'
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, REMOVED_PATH)
        return True
    except Exception as e:
        log.error(f"제거 기록 저장 실패: {e}")
        try:
            os.remove(tmp)      # 우리가 만든 임시 파일만 지운다
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
                'name': p['name'],
                'fullName': p['fullName'],
                'familyName': p['familyName'],
                'installLocation': p.get('installLocation') or '',
                'itemId': item['id'],
                'label': item['name'],
                'account': account,
                'removedAt': now,
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
        if len(data['apps']) == before:
            return True
        return _save_removed(data)


def _windowsapps_roots():
    pf = os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles') or r'C:\Program Files'
    root = os.environ.get('SystemRoot') or r'C:\Windows'
    return [os.path.join(pf, 'WindowsApps'), os.path.join(root, 'SystemApps')]


def _manifest_path(install_location):
    """되살릴 때 쓸 AppxManifest.xml 경로. 앱 설치 폴더 밖이거나 파일이 없으면 None.

    기록 파일은 사용자 폴더에 있어 다른 프로그램이 고칠 수 있다.
    그래서 경로를 믿지 않고 Windows 앱 설치 폴더 안인지 다시 확인한다.
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
    """이 앱이 제거한 패키지 목록. 되살리기 화면과 전체 되돌리기가 쓴다."""
    with _removed_lock:
        data = _load_removed()
    if not data:
        return []
    out = []
    for a in data['apps']:
        e = dict(a)
        e['manifestFound'] = _manifest_path(a.get('installLocation')) is not None
        out.append(e)
    return out


def _store_hint(entry):
    label = entry.get('label') or entry.get('name') or ''
    return f"Microsoft Store 에서 '{label}' 을(를) 검색해 다시 설치할 수 있습니다."


def restore_removed_apps(names=None):
    """제거한 앱을 되살린다.

    names: None 이면 전부. 아니면 패키지 이름·패밀리 이름·전체 이름 중 하나가 맞는 것만.
    Add-AppxPackage -DisableDevelopmentMode -Register <설치 폴더>\\AppxManifest.xml 로
    다시 등록하고, 등록 뒤 실제로 설치돼 있는지 다시 확인한다.
    설치 파일이 이미 정리돼 없으면 Microsoft Store 로 안내한다.
    """
    if _debloat_state.get("running"):
        return {'success': False, 'restored': [], 'failed': [],
                'message': '앱 제거가 진행 중입니다. 끝난 뒤 다시 시도해 주세요.'}
    if not _op_lock.acquire(blocking=False):
        return {'success': False, 'restored': [], 'failed': [],
                'message': '다른 작업이 진행 중입니다. 끝난 뒤 다시 시도해 주세요.'}
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
        wanted = {str(n).lower() for n in (names or []) if isinstance(n, str)}
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
        fam = str(e.get('familyName', '')).lower()
        if fam and fam in installed:
            restored.append(e.get('label') or e.get('name'))     # 이미 설치돼 있다
            forget.append(e.get('fullName'))
            continue
        manifest = _manifest_path(e.get('installLocation'))
        if not manifest:
            failed.append({'name': e.get('name'), 'label': e.get('label'),
                           'reason': '설치 파일이 남아 있지 않습니다. ' + _store_hint(e)})
            continue
        to_register.append((e, manifest))

    reg_errors = {}
    if to_register:
        try:
            ok_r, rrows, rerr = _run_ps_json(
                _PS_REGISTER, {'manifests': [m for _, m in to_register]}, RESTORE_TIMEOUT_SEC)
            if ok_r:
                for r in rrows:
                    if not r.get('ok'):
                        reg_errors[str(r.get('manifest', '')).lower()] = r.get('error') or ''
            else:
                for _, m in to_register:
                    reg_errors[m.lower()] = rerr or ''
        except subprocess.TimeoutExpired:
            for _, m in to_register:
                reg_errors[m.lower()] = '시간 초과'
        except Exception as ex:
            for _, m in to_register:
                reg_errors[m.lower()] = str(ex)

        # 등록 명령의 성패를 믿지 않는다. 실제로 설치돼 있는지 다시 확인한다.
        ok2, rows2, err2 = _query_packages(sorted({e.get('name', '') for e, _ in to_register}))
        now_installed = {str(r.get('familyName', '')).lower() for r in rows2 if not r.get('error')}
        for e, m in to_register:
            fam = str(e.get('familyName', '')).lower()
            if ok2 and fam in now_installed:
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
# 레지스트리 읽기 (현재 상태 표시용 — 쓰지 않는다)
# ─────────────────────────────────────────────

def _reg_read(path, name):
    """HKLM 값을 읽는다. ('ok', 값) / ('no_value', None) / ('no_key', None) / ('error', 메시지)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            try:
                val, _ = winreg.QueryValueEx(k, name)
                return 'ok', val
            except FileNotFoundError:
                return 'no_value', None
    except FileNotFoundError:
        return 'no_key', None
    except Exception as e:
        return 'error', str(e)


def _edition_id():
    st, v = _reg_read(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "EditionID")
    return v if st == 'ok' and isinstance(v, str) else ''


def _telemetry_zero_honored():
    """AllowTelemetry=0(보안 수준)은 Enterprise·Education·IoT·Server 에서만 적용된다.
    Home·Pro 는 0 을 1(필수 진단 데이터)로 취급한다."""
    ed = _edition_id().lower()
    return ed.startswith(('enterprise', 'education', 'iotenterprise', 'server'))


def _telemetry_note():
    if _telemetry_zero_honored():
        return "설정 앱의 '진단 및 피드백' 항목이 '조직에서 관리' 로 잠깁니다."
    return ("이 Windows 에디션(Home·Pro)은 완전히 끌 수 없고 '필수 진단 데이터' 만 보냅니다. "
            "설정 앱의 '진단 및 피드백' 항목이 '조직에서 관리' 로 잠깁니다.")


def _change_state(ch):
    """변경 한 건의 현재 상태: {'applied': bool, 'missing': bool, 'error': str}."""
    if ch['type'] == 'registry':
        st, v = _reg_read(ch['path'], ch['name'])
        if st == 'error':
            return {'applied': False, 'missing': False, 'error': v}
        return {'applied': st == 'ok' and v == ch['value'], 'missing': False, 'error': ''}
    st, v = _reg_read(_DIAGTRACK_PATH if ch['service'] == 'DiagTrack'
                      else rf"SYSTEM\CurrentControlSet\Services\{ch['service']}", 'Start')
    if st == 'no_key':
        return {'applied': False, 'missing': True, 'error': ''}
    if st == 'error':
        return {'applied': False, 'missing': False, 'error': v}
    return {'applied': st == 'ok' and v == ch['startValue'], 'missing': False, 'error': ''}


def _system_state():
    try:
        from backend import system_state
        return system_state
    except Exception as e:
        log.error(f"system_state 를 불러오지 못했습니다: {e}")
        return None


def _journaled(ch):
    """이 변경의 원래 값이 system_state 저널에 기록돼 있는지(=복구 센터에서 되돌릴 수 있는지)."""
    ss = _system_state()
    if ss is None or not hasattr(ss, 'pending_changes'):
        return False
    try:
        entries = ss.pending_changes() or {}
    except Exception:
        return False
    for key, e in entries.items():
        if not isinstance(e, dict):
            continue
        kind = e.get('kind')
        if ch['type'] == 'registry':
            if (kind == 'registry'
                    and str(e.get('hive', '')).upper() == ch['hive']
                    and str(e.get('path', '')).lower() == ch['path'].lower()
                    and str(e.get('name', '')).lower() == ch['name'].lower()):
                return True
        else:
            svc = ch['service'].lower()
            if kind == 'service' and (
                    str(e.get('service') or e.get('name') or '').lower() == svc
                    or svc in str(key).lower()):
                return True
            if (kind == 'registry'
                    and str(e.get('path', '')).lower() == rf"system\currentcontrolset\services\{svc}"
                    and str(e.get('name', '')).lower() == 'start'):
                return True
    return False


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


def _desktop_account():
    """지금 바탕 화면(explorer.exe)을 쓰는 계정. 다른 관리자 계정으로 승격해 실행하면
    APEX CARE 계정과 달라진다. 알 수 없으면 ''."""
    try:
        import psutil
        me = psutil.Process()
        my_session = None
        try:
            my_session = ctypes.c_ulong()
            if not ctypes.windll.kernel32.ProcessIdToSessionId(me.pid, ctypes.byref(my_session)):
                my_session = None
        except Exception:
            my_session = None
        for p in psutil.process_iter(['name']):
            if (p.info.get('name') or '').lower() != 'explorer.exe':
                continue
            if my_session is not None:
                sid = ctypes.c_ulong()
                if ctypes.windll.kernel32.ProcessIdToSessionId(p.pid, ctypes.byref(sid)) \
                        and sid.value != my_session.value:
                    continue
            try:
                return (p.username() or '').split('\\')[-1]
            except Exception:
                continue
    except Exception:
        pass
    return ''


# ─────────────────────────────────────────────
# 목록 · 미리보기
# ─────────────────────────────────────────────

def _public_item(item):
    if item['kind'] == 'appx':
        return {
            'id': item['id'], 'name': item['name'], 'kind': 'appx',
            'pattern': ', '.join(item['packages']),     # 예전 키. 이제 정확한 패키지 이름이다.
            'packages': list(item['packages']),
            'changes': [f"{p} 제거 (현재 계정)" for p in item['packages']],
            'note': item.get('note', ''),
            'revert': "이 화면의 '제거한 앱' 에서 되살립니다.",
        }
    note = _telemetry_note() if item['id'] == 'telemetry' else \
        "정책 키가 생겨 관련 설정이 '조직에서 관리' 로 잠깁니다."
    return {
        'id': item['id'], 'name': item['name'], 'kind': 'policy',
        'pattern': ', '.join(ch['label'] for ch in item['changes']),
        'packages': [],
        'changes': [ch['label'] for ch in item['changes']],
        'note': note,
        'revert': '원래 값을 기록해 두며, 복구 센터에서 되돌립니다.',
    }


def get_debloat_list():
    return [_public_item(x) for x in DEBLOAT_SAFE_LIST]


def get_debloat_preview():
    """각 항목의 현재 상태를 읽기만 해서 돌려준다. 시스템을 바꾸지 않는다.

    반환: {ok, error, account, desktopAccount, items: {id: {...}}}
      앱:   state = installed | not_installed | unknown, installed = [{name, fullName}]
      정책: state = applied | partial | not_applied | unknown, recorded(복구 센터 기록 여부),
            steps = [{label, applied, recorded, missing}]
    """
    all_names = sorted({n for it in APPX_ITEMS for n in it['packages']})
    ok, rows, err = _query_packages(all_names)
    items = {}
    for it in APPX_ITEMS:
        if not ok:
            items[it['id']] = {'state': 'unknown', 'installed': [], 'detail': err or ''}
            continue
        mine = [r for r in rows if r.get('query') in it['packages']]
        errs = [r for r in mine if r.get('error')]
        found = [{'name': r.get('name'), 'fullName': r.get('fullName')}
                 for r in mine if not r.get('error')]
        if found:
            state = 'installed'
        elif errs:
            state = 'unknown'
        else:
            state = 'not_installed'
        items[it['id']] = {'state': state, 'installed': found,
                           'detail': errs[0].get('error', '') if errs else ''}

    for it in POLICY_ITEMS:
        steps = []
        for ch in it['changes']:
            st = _change_state(ch)
            steps.append({'label': ch['label'], 'applied': st['applied'],
                          'missing': st['missing'], 'error': st['error'],
                          'recorded': _journaled(ch)})
        relevant = [s for s in steps if not s['missing']]
        if any(s['error'] for s in relevant):
            state = 'unknown'
        elif relevant and all(s['applied'] for s in relevant):
            state = 'applied'
        elif any(s['applied'] for s in relevant):
            state = 'partial'
        else:
            state = 'not_applied'
        items[it['id']] = {'state': state, 'steps': steps,
                           'recorded': any(s['recorded'] for s in steps)}

    return {'ok': ok, 'error': err or '', 'account': _current_account(),
            'desktopAccount': _desktop_account(), 'items': items}


def get_debloat_status():
    s = _debloat_state
    out = dict(s)
    for k in ('succeeded', 'failed', 'skipped', 'results'):
        out[k] = list(s.get(k) or [])
    return out


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────

def _apply_appx_item(item, account):
    """앱 항목 하나를 제거한다. 설치 확인 → 기록 → 제거 → 다시 확인."""
    res = {'id': item['id'], 'name': item['name'], 'kind': 'appx',
           'status': 'failed', 'detail': '', 'packages': []}

    ok, rows, err = _query_packages(item['packages'])
    if not ok:
        res['detail'] = f'설치 상태를 확인하지 못해 제거하지 않았습니다: {err}'
        return res

    query_errors = [r for r in rows if r.get('error')]
    found = [r for r in rows if not r.get('error') and r.get('fullName')
             and _PKG_RE.match(str(r.get('fullName')))]
    for r in query_errors:
        res['packages'].append({'name': r.get('query'), 'fullName': '', 'status': 'failed',
                                'detail': f"설치 상태 확인 실패: {r.get('error')}"})

    blocked = [r for r in found if r.get('nonRemovable') or r.get('isFramework')]
    targets = [r for r in found if r not in blocked]
    for r in blocked:
        res['packages'].append({'name': r.get('name'), 'fullName': r.get('fullName'),
                                'status': 'failed', 'detail': 'Windows 가 제거를 막아 둔 패키지입니다'})

    if not found and not query_errors:
        res['status'] = 'not_installed'
        res['detail'] = '설치돼 있지 않습니다 (변경 없음)'
        return res

    removed, failed = [], [p for p in res['packages'] if p['status'] == 'failed']
    if targets:
        # 되살릴 수 있게 지우기 전에 기록한다. 기록을 못 하면 지우지 않는다.
        if not _record_removed(targets, item, account):
            for r in targets:
                res['packages'].append({'name': r.get('name'), 'fullName': r.get('fullName'),
                                        'status': 'failed',
                                        'detail': '제거 기록을 저장하지 못해 지우지 않았습니다'})
            res['detail'] = '제거 기록을 저장하지 못해 지우지 않았습니다'
            return res

        remove_errors, timed_out = {}, False
        try:
            ok_r, rrows, rerr = _run_ps_json(
                _PS_REMOVE, {'fullNames': [r['fullName'] for r in targets]}, APPX_TIMEOUT_SEC)
            if ok_r:
                for r in rrows:
                    if not r.get('ok'):
                        remove_errors[r.get('fullName')] = r.get('error') or ''
            else:
                for r in targets:
                    remove_errors[r['fullName']] = rerr or ''
        except subprocess.TimeoutExpired:
            timed_out = True
        except Exception as e:
            for r in targets:
                remove_errors[r['fullName']] = str(e)

        # 명령의 반환값을 믿지 않는다. 남아 있는지 직접 다시 확인한다.
        ok2, rows2, err2 = _query_packages(item['packages'])
        if not ok2:
            for r in targets:
                res['packages'].append({
                    'name': r.get('name'), 'fullName': r.get('fullName'), 'status': 'unknown',
                    'detail': ('시간 초과. ' if timed_out else '') +
                              f'제거됐는지 확인하지 못했습니다: {err2}'})
            res['status'] = 'unknown'
            res['detail'] = '제거됐는지 확인하지 못했습니다. 잠시 뒤 다시 확인해 주세요.'
            return res   # 기록은 남겨 둔다. 되살리기가 설치 여부를 다시 확인한다.

        still = {str(r.get('familyName', '')).lower() for r in rows2 if not r.get('error')}
        not_removed = []
        for r in targets:
            if str(r.get('familyName', '')).lower() in still:
                why = remove_errors.get(r['fullName']) or ('시간 초과' if timed_out else '제거되지 않았습니다')
                p = {'name': r.get('name'), 'fullName': r.get('fullName'),
                     'status': 'failed', 'detail': why}
                failed.append(p)
                not_removed.append(r['fullName'])
            else:
                p = {'name': r.get('name'), 'fullName': r.get('fullName'),
                     'status': 'removed', 'detail': '오래 걸렸지만 제거됨' if timed_out else ''}
                removed.append(p)
            res['packages'].append(p)
        if not_removed and not _forget_removed(not_removed):
            log.warning("지워지지 않은 패키지를 제거 기록에서 빼지 못했습니다")

    if removed and not failed:
        res['status'] = 'removed'
        res['detail'] = ', '.join(p['name'] for p in removed) + ' 제거함'
    elif removed:
        res['status'] = 'partial'
        res['detail'] = (f"{len(removed)}개 제거, {len(failed)}개 실패: " +
                         '; '.join(f"{p['name']} — {p['detail']}" for p in failed))
    else:
        res['status'] = 'failed'
        res['detail'] = '; '.join(f"{p['name']} — {p['detail']}" for p in failed) or '제거하지 못했습니다'
    return res


def _apply_policy_item(item):
    """정책·서비스 항목 하나를 적용한다. 모든 변경은 system_state 를 거친다."""
    res = {'id': item['id'], 'name': item['name'], 'kind': 'policy',
           'status': 'failed', 'detail': '', 'steps': []}

    ss = _system_state()
    needs = {'set_registry'} if all(c['type'] == 'registry' for c in item['changes']) \
        else {'set_registry', 'set_service_start'}
    missing = [n for n in needs if ss is None or not hasattr(ss, n)]
    if missing:
        # 한쪽만 바뀐 상태를 만들지 않도록 아무것도 바꾸지 않는다.
        res['detail'] = '원래 값을 기록하는 기능을 쓸 수 없어 바꾸지 않았습니다'
        return res

    for ch in item['changes']:
        step = {'label': ch['label'], 'status': 'failed', 'detail': ''}
        cur = _change_state(ch)
        if cur['missing']:
            step.update(status='missing', detail='이 PC 에 없는 서비스입니다 (변경 없음)')
        elif cur['applied']:
            step.update(status='already', detail='이미 적용돼 있습니다 (변경 없음)')
        else:
            try:
                if ch['type'] == 'registry':
                    r = ss.set_registry(ch['hive'], ch['path'], ch['name'], ch['value'],
                                        GROUP, why=ch['why'])
                else:
                    r = ss.set_service_start(ch['service'], ch['start'], GROUP, why=ch['why'])
                r = r if isinstance(r, dict) else {}
                if r.get('ok'):
                    step['status'] = 'applied'
                    if ch['type'] == 'service':
                        step['detail'] = '다음 재부팅부터 시작되지 않습니다 (지금 실행 중인 서비스는 멈추지 않음)'
                    elif item['id'] == 'telemetry' and not _telemetry_zero_honored():
                        step['detail'] = "이 에디션에서는 '필수 진단 데이터' 수준으로 적용됩니다"
                else:
                    step['detail'] = str(r.get('error') or r.get('reason') or '적용하지 못했습니다')
            except Exception as e:
                step['detail'] = str(e)
        res['steps'].append(step)

    sts = [s['status'] for s in res['steps']]
    applied = sts.count('applied')
    failed = [s for s in res['steps'] if s['status'] == 'failed']
    if failed and applied:
        res['status'] = 'partial'
    elif failed:
        res['status'] = 'failed'
    elif applied:
        res['status'] = 'applied'
    else:
        res['status'] = 'already'
    res['detail'] = '; '.join(f"{s['label']}: {s['detail'] or '적용함'}"
                              for s in res['steps'] if s['status'] in ('applied', 'failed')) \
        or '이미 적용돼 있습니다 (변경 없음)'
    return res


_STATUS_OK = ('removed', 'applied')
_STATUS_SKIP = ('not_installed', 'already')


def _run_debloater(selected_ids):
    st = _debloat_state      # start_debloater 가 스레드를 띄우기 전에 새 상태로 바꿔 두었다
    with _op_lock:
        try:
            total = len(selected_ids)
            if total == 0:
                st["progress_pct"] = 100
                st["current_task"] = "선택된 항목이 없습니다."
                return

            account = _current_account()
            results, succeeded, failed, skipped = [], [], [], []

            for i, item_id in enumerate(selected_ids):
                item = _ITEMS_BY_ID.get(item_id)
                if not item:
                    r = {'id': item_id, 'name': str(item_id), 'kind': 'unknown',
                         'status': 'failed', 'detail': '알 수 없는 항목입니다'}
                else:
                    verb = '제거 중' if item['kind'] == 'appx' else '적용 중'
                    st["current_task"] = f"{item['name']} {verb}..."
                    log.info(f"Debloat: {item['name']} ({item_id})")
                    # 항목 하나가 실패해도 나머지는 계속 처리한다.
                    try:
                        if item['kind'] == 'appx':
                            r = _apply_appx_item(item, account)
                        else:
                            r = _apply_policy_item(item)
                    except Exception as e:
                        log.warning(f"Debloat 실패: {item['name']} -> {e}")
                        r = {'id': item_id, 'name': item['name'], 'kind': item['kind'],
                             'status': 'failed', 'detail': str(e)}

                results.append(r)
                if r['status'] in _STATUS_OK:
                    succeeded.append(r['name'])
                elif r['status'] in _STATUS_SKIP:
                    skipped.append(f"{r['name']} ({r['detail']})")
                else:
                    failed.append(f"{r['name']} ({r['detail']})" if r.get('detail') else r['name'])

                st["results"] = list(results)
                st["progress_pct"] = int((i + 1) / total * 100)

            st["succeeded"] = succeeded
            st["failed"] = failed
            st["skipped"] = skipped
            st["progress_pct"] = 100

            # 실제 결과를 그대로 보고한다. 변경이 없던 항목은 성공으로 세지 않는다.
            parts = []
            if succeeded:
                parts.append(f"{len(succeeded)}개 완료")
            if failed:
                parts.append(f"{len(failed)}개 실패")
            if skipped:
                parts.append(f"{len(skipped)}개 변경 없음")
            st["current_task"] = ', '.join(parts) or '변경한 항목이 없습니다.'
            log.info(f"Debloater finished. ok={len(succeeded)} failed={len(failed)} skipped={len(skipped)}")

        except Exception as e:
            st["error"] = str(e)
            st["current_task"] = f"오류 발생: {e}"
            log.warning(f"Debloater exception: {e}")
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
