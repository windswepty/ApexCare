"""
APEX CARE — Windows 샌드박스 안에서 진짜 Windows 에 대고 돌리는 자동 점검.

pytest(tests/)는 가짜 Windows 위에서 논리만 본다. 이 스크립트는 샌드박스의 진짜 레지스트리·전원 API·
서비스·Appx·파일 시스템에 앱의 백엔드를 그대로 돌려 "적용 → 되돌리기 → 처음과 같은가" 를 확인한다.
처음과 같은지는 tools/snapshot_state.ps1 로 뜬 상태를 비교해 판단한다.

**샌드박스 밖에서는 실행을 거부한다.** 시스템을 바꾸는 코드라 개발 PC 에서 돌면 안 된다.
실행: tools/sandbox/start_sandbox_check.ps1 (샌드박스를 띄우고 이 스크립트를 자동으로 돌린다)
결과: 출력 폴더의 report.md · report.json · snap/*.txt
"""

import os
import sys

SANDBOX_USER = 'WDAGUtilityAccount'


def refuse_outside_sandbox():
    """샌드박스 계정이고 실행 스크립트가 표시(APEX_SANDBOX=1)를 남겼을 때만 통과한다."""
    user = os.environ.get('USERNAME', '')
    if user != SANDBOX_USER or os.environ.get('APEX_SANDBOX') != '1':
        sys.stderr.write(f"이 스크립트는 Windows 샌드박스 안에서만 돕니다(현재 계정 {user!r}). "
                         "시스템을 바꾸는 점검이라 개발 PC 에서는 실행하지 않습니다.\n")
        sys.exit(2)


if __name__ == '__main__':
    refuse_outside_sandbox()           # 다른 무엇을 import 하기 전에 막는다

import ctypes  # noqa: E402
import difflib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.environ.get('APEX_OUT') or r'C:\apex\out'
SNAP_PS1 = os.path.join(REPO, 'tools', 'snapshot_state.ps1')
CREATE_NO_WINDOW = 0x08000000


# ─────────────────────────────────────────────
# 상태 스냅숏과 비교
# ─────────────────────────────────────────────

def snapshot(name):
    """snapshot_state.ps1 로 상태를 떠서 줄 목록으로. [APEX CARE] 부분(앱 자체 기록)은 뺀다."""
    path = os.path.join(OUT, 'snap', f'{name}.txt')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', SNAP_PS1, '-Out', path],
                   shell=False, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=300)
    with open(path, encoding='utf-8-sig') as f:
        lines = f.read().splitlines()
    out, skip = [], False
    for line in lines:
        if line.startswith('['):
            skip = line.startswith('[APEX CARE]')
        if not skip:
            out.append(line)
    return out


def diff(a, b):
    return [d for d in difflib.unified_diff(a, b, lineterm='', n=0) if d[:1] in '+-' and d[:3] not in ('---', '+++')]


# ─────────────────────────────────────────────
# 점검 실행 틀
# ─────────────────────────────────────────────

RESULTS = []


def check(name):
    def wrap(fn):
        def run():
            t0 = time.time()
            try:
                status, detail, changes = fn()
            except Exception:
                status, detail, changes = 'FAIL', traceback.format_exc(limit=6), []
            RESULTS.append({'name': name, 'status': status, 'detail': detail,
                            'diff': changes[:60], 'seconds': round(time.time() - t0, 1)})
            print(f"[{status}] {name} ({RESULTS[-1]['seconds']}s) {detail.splitlines()[0] if detail else ''}", flush=True)
        run.__name__ = fn.__name__
        CHECKS.append(run)
        return run
    return wrap


CHECKS = []


def verdict(problems, changes):
    """문제 목록과 원래 상태와의 차이로 결과를 정한다."""
    if problems or changes:
        return 'FAIL', '; '.join(problems) or '되돌린 뒤 상태가 처음과 다릅니다', changes
    return 'PASS', '', []


# ─────────────────────────────────────────────
# 레지스트리 도우미 (점검 준비·정리용)
# ─────────────────────────────────────────────

import winreg  # noqa: E402

HIVE = {'HKCU': winreg.HKEY_CURRENT_USER, 'HKLM': winreg.HKEY_LOCAL_MACHINE}
RUN_U = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_M = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
MM = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'


def reg_set(hive, path, name, value, vtype=winreg.REG_SZ):
    with winreg.CreateKeyEx(HIVE[hive], path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, vtype, value)


def reg_del(hive, path, name):
    try:
        with winreg.OpenKey(HIVE[hive], path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def reg_get(hive, path, name):
    from backend import system_state as ss
    ok, v, _ = ss.read_registry(hive, path, name)
    return v if ok else None


# ─────────────────────────────────────────────
# 점검 항목
# ─────────────────────────────────────────────

@check('환경 정보')
def env_info():
    from backend import perf_modes, system_state as ss
    info = {
        'admin': perf_modes.is_admin(),
        'plans': ss.available_plans(),
        'active': ss.active_plan_guid(),
        'services': {s: ss.service_start_type(s) for s in ('SysMain', 'WSearch', 'DiagTrack')},
    }
    status = 'PASS' if info['admin'] else 'FAIL'
    return status, json.dumps(info, ensure_ascii=False), []


def _mode_round_trip(modes, expect):
    from backend import perf_modes, system_state as ss
    before = snapshot(f"mode_{'_'.join(modes)}_before")
    problems = []
    for m in modes:
        r = perf_modes.apply_mode(m)
        if not r.get('success'):
            bad = [f"{s['name']}: {s.get('detail')}" for s in r.get('steps', []) if not s.get('ok')]
            problems.append(f"{m} 적용: {r.get('message')} {bad}")
        if m in expect:
            problems += [p for p in expect[m]() if p]
    r = perf_modes.apply_mode('standard')
    if not r.get('success'):
        problems.append(f"표준 되돌리기: {r.get('message')}")
    if any(e.get('group') == perf_modes.MODE_GROUP for e in ss.pending_changes().values()):
        problems.append('표준으로 돌아온 뒤에도 성능 모드 저널 항목이 남았습니다')
    return verdict(problems, diff(before, snapshot(f"mode_{'_'.join(modes)}_after")))


def _expect_gaming():
    from backend import system_state as ss
    out = []
    if reg_get('HKLM', MM, 'SystemResponsiveness') != 10:
        out.append('게이밍: SystemResponsiveness 가 10 이 아닙니다')
    if reg_get('HKLM', MM, 'NetworkThrottlingIndex') != 0xFFFFFFFF:
        out.append('게이밍: NetworkThrottlingIndex 가 0xFFFFFFFF 가 아닙니다')
    plans = ss.available_plans()
    want = ss.PLAN_HIGH_PERF if ss.PLAN_HIGH_PERF in plans else ss.PLAN_BALANCED
    if ss.active_plan_guid() != want:
        out.append(f'게이밍: 활성 플랜이 {want} 가 아닙니다 ({ss.active_plan_guid()})')
    if ss._read_power_value(want, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, True) != 100:
        out.append('게이밍: CPU 최소 속도(AC)가 100 이 아닙니다')
    return out


def _expect_eco():
    from backend import system_state as ss
    plans = ss.available_plans()
    want = ss.PLAN_POWER_SAVER if ss.PLAN_POWER_SAVER in plans else ss.PLAN_BALANCED
    out = []
    if ss.active_plan_guid() != want:
        out.append(f'에코: 활성 플랜이 {want} 가 아닙니다')
    if ss._read_power_value(want, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX, False) != 70:
        out.append('에코: CPU 최대 속도(DC)가 70 이 아닙니다')
    if reg_get('HKLM', MM, 'NetworkThrottlingIndex') != _ORIGINAL_THROTTLE[0]:
        out.append('에코: NetworkThrottlingIndex 가 원래 값이 아닙니다(게이밍 값이 남음)')
    return out


_ORIGINAL_THROTTLE = [None]


@check('성능 모드: 게이밍 → 표준')
def mode_gaming():
    _ORIGINAL_THROTTLE[0] = reg_get('HKLM', MM, 'NetworkThrottlingIndex')
    return _mode_round_trip(['gaming'], {'gaming': _expect_gaming})


@check('성능 모드: 에코 → 표준')
def mode_eco():
    return _mode_round_trip(['eco'], {'eco': _expect_eco})


@check('성능 모드: 게이밍 → 에코 → 표준 (겹쳐 쌓이지 않음)')
def mode_stack():
    return _mode_round_trip(['gaming', 'eco'], {'gaming': _expect_gaming, 'eco': _expect_eco})


@check('디블로터 정책: 원격 분석·Cortana → 복구')
def debloat_policy():
    from backend import debloater, system_state as ss
    before = snapshot('policy_before')
    problems = []
    ok, why = debloater._apply_telemetry_policy()
    if not ok:
        problems.append(f'원격 분석 적용 실패: {why}')
    ok, why = debloater._apply_cortana_policy()
    if not ok:
        problems.append(f'Cortana 적용 실패: {why}')
    if reg_get('HKLM', r'SOFTWARE\Policies\Microsoft\Windows\DataCollection', 'AllowTelemetry') != 0:
        problems.append('AllowTelemetry 가 0 이 아닙니다')
    if ss.service_start_type('DiagTrack') not in (None, 'disabled'):
        problems.append(f"DiagTrack 이 사용 안 함이 아닙니다 ({ss.service_start_type('DiagTrack')})")
    r = ss.restore_group(debloater.DEBLOAT_GROUP)
    if not r['ok']:
        problems.append(f"복구 실패: {r['failed']}")
    return verdict(problems, diff(before, snapshot('policy_after')))


@check('맞춤 튜닝(저사양): SysMain 만 끄고 복구')
def hw_tuning():
    from backend import optimizer, system_state as ss
    before = snapshot('tuning_before')
    wsearch = ss.service_start_type('WSearch')
    r = optimizer.apply_hardware_tailored_tuning(2, 4, consent=True)
    problems = [f"{s['name']}: {s['detail']}" for s in r.get('steps', []) if not s['ok'] and 'SysMain' in s['name']]
    if ss.service_start_type('SysMain') not in (None, 'disabled'):
        problems.append(f"SysMain 이 사용 안 함이 아닙니다 ({ss.service_start_type('SysMain')})")
    if ss.service_start_type('WSearch') != wsearch:
        problems.append('WSearch 가 바뀌었습니다')
    back = optimizer.restore_tailored_service_config()
    if not back.get('success'):
        problems.append(f"복구 실패: {back.get('message')}")
    return verdict(problems, diff(before, snapshot('tuning_after')))


@check('시작 프로그램: 끄기·켜기·전부 원래대로 (StartupApproved)')
def startup():
    from backend import optimizer, perf_modes
    reg_set('HKCU', RUN_U, 'ApexSbxUser', r'C:\Windows\System32\notepad.exe')
    reg_set('HKLM', RUN_M, 'ApexSbxMachine', r'C:\Windows\System32\notepad.exe')
    try:
        base = snapshot('startup_base')
        problems = []
        for app_id in ('HKCU:ApexSbxUser', 'HKLM:ApexSbxMachine'):
            r = optimizer.toggle_startup_app(app_id, False)
            if not r.get('success'):
                problems.append(f'{app_id} 끄기 실패: {r.get("message")}')
        tag_state = {a['id']: a['enabled'] for a in optimizer.get_startup_apps()}
        if tag_state.get('HKCU:ApexSbxUser') is not False or tag_state.get('HKLM:ApexSbxMachine') is not False:
            problems.append(f'끈 뒤 목록 상태가 다릅니다: {tag_state}')
        if reg_get('HKCU', RUN_U, 'ApexSbxUser') is None:
            problems.append('끄기가 Run 값을 지웠습니다')
        for app_id in ('HKCU:ApexSbxUser', 'HKLM:ApexSbxMachine'):
            optimizer.toggle_startup_app(app_id, True)
        changes = diff(base, snapshot('startup_on_again'))
        if changes:
            problems.append('다시 켠 뒤 상태가 처음과 다릅니다')
        for app_id in ('HKCU:ApexSbxUser', 'HKLM:ApexSbxMachine'):
            optimizer.toggle_startup_app(app_id, False)
        r = perf_modes.revert_everything()
        if not r.get('success'):
            problems.append(f"전부 원래대로 실패: {r.get('message')}")
        return verdict(problems, changes + diff(base, snapshot('startup_after_revert')))
    finally:
        reg_del('HKCU', RUN_U, 'ApexSbxUser')
        reg_del('HKLM', RUN_M, 'ApexSbxMachine')


@check('시작 프로그램: 예전 버전이 숨긴 항목을 원래 위치로 되살림')
def startup_legacy():
    from backend import optimizer, system_state as ss
    legacy = r'Software\APEXCARE\DisabledStartup'
    reg_set('HKCU', legacy, 'ApexSbxOld', r'C:\Windows\System32\notepad.exe')
    reg_set('HKCU', legacy + r'\_origin', 'ApexSbxOld', 'HKLM|' + RUN_M)
    try:
        problems = []
        r = optimizer.toggle_startup_app('LEGACY:ApexSbxOld', True)
        if not r.get('success'):
            problems.append(f"켜기 실패: {r.get('message')}")
        if reg_get('HKLM', RUN_M, 'ApexSbxOld') != r'C:\Windows\System32\notepad.exe':
            problems.append('HKLM Run 에 되살아나지 않았습니다')
        if optimizer._approved_state('HKLM', 'ApexSbxOld') == 'disabled':
            problems.append('되살렸지만 꺼져 있습니다')
        if reg_get('HKCU', legacy, 'ApexSbxOld') is not None:
            problems.append('예전 기록이 남았습니다')
        if any(k for k, e in ss.pending_changes().items() if 'ApexSbxOld' in k):
            problems.append('저널에 남았습니다')
        return verdict(problems, [])
    finally:
        reg_del('HKLM', RUN_M, 'ApexSbxOld')
        reg_del('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run', 'ApexSbxOld')
        reg_del('HKCU', legacy, 'ApexSbxOld')
        reg_del('HKCU', legacy + r'\_origin', 'ApexSbxOld')


@check('게임 부스트: Nagle 끄기 → 게임 종료 때 원래대로')
def boost_nagle():
    from backend import config_manager, game_booster
    before = snapshot('nagle_before')
    cfg = config_manager.load_config()
    saved = dict(cfg)
    cfg.update(boost_disable_nagle=True, boost_timer_resolution=False, boost_tame_background=False,
               boost_auto_power_mode=False)
    config_manager.save_config(cfg)
    problems = []
    try:
        game_booster._enter_boost_mode()
        ifaces = game_booster._nagle_interfaces()
        base = game_booster._NAGLE_BASE
        if not any(reg_get('HKLM', f'{base}\\{i}', 'TCPNoDelay') == 1 for i in ifaces):
            problems.append('어느 어댑터에도 TCPNoDelay=1 이 쓰이지 않았습니다')
        game_booster._exit_boost_mode()
    finally:
        config_manager.save_config(saved)
    return verdict(problems, diff(before, snapshot('nagle_after')))


@check('정크 정리: %TEMP% 안 정션 너머 파일은 남고, 잠긴 파일은 앱 데이터 폴더에 기록')
def junk_junction():
    import _winapi
    from backend import config_manager, optimizer
    temp = os.environ['TEMP']
    docs = r'C:\apex_docs_check'
    link = os.path.join(temp, 'apex_junction_check')
    os.makedirs(docs, exist_ok=True)
    user_files = [os.path.join(docs, n) for n in ('important.log', 'notes', 'photo.bak')]
    for p in user_files:
        with open(p, 'w') as f:
            f.write('user data')
    junk = os.path.join(temp, 'apex_check_junk.tmp')
    with open(junk, 'w') as f:
        f.write('junk')
    locked_path = os.path.join(temp, 'apex_check_locked.tmp')
    with open(locked_path, 'w') as f:
        f.write('in use')
    problems = []
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    h = None
    try:
        _winapi.CreateJunction(docs, link)
        # 잠금: 공유 없이 열어 두면 다른 누구도(정크 정리도) 지울 수 없다
        h = kernel32.CreateFileW(locked_path, 0x80000000, 0, None, 3, 0x80, None)
        if h in (None, ctypes.c_void_p(-1).value):
            h = None
        optimizer.clean_junk_background([1], cancel_event=None)
        st = optimizer.get_junk_clean_status()
        if st.get('status') != 'success':
            problems.append(f"정리 상태: {st}")
        missing = [p for p in user_files if not os.path.exists(p)]
        if missing:
            problems.append(f'정션 너머 사용자 파일이 지워졌습니다: {missing}')
        if os.path.exists(junk):
            problems.append('정크 파일이 남았습니다')
        log = os.path.join(config_manager.APPDATA_DIR, 'skipped_files.log')
        if h is None:
            problems.append('잠금 파일을 만들지 못해 건너뛴 로그는 확인하지 못했습니다')
        elif not (os.path.exists(log) and 'apex_check_locked.tmp' in open(log, encoding='utf-8').read()):
            problems.append('잠긴 파일이 건너뛴 로그에 없습니다')
        desktop_log = os.path.join(os.path.expanduser('~'), 'Desktop', 'APEX_Skipped_Files.log')
        if os.path.exists(desktop_log):
            problems.append('바탕화면에 로그가 생겼습니다')
    finally:
        if h is not None:
            kernel32.CloseHandle(ctypes.c_void_p(h))
        if os.path.isdir(link):
            os.rmdir(link)                        # 정션 자체만 지운다(대상 폴더는 그대로)
    return verdict(problems, [])


@check('프로세스 우선순위: 바꾸고 원래대로, 시스템 프로세스는 거부')
def priority():
    import psutil
    from backend import process_boost
    p = subprocess.Popen([os.path.join(os.environ['SystemRoot'], 'System32', 'PING.EXE'), '-t', '127.0.0.1'],
                         shell=False, stdout=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    problems = []
    try:
        time.sleep(1)
        before = psutil.Process(p.pid).nice()
        r = process_boost.set_priority(p.pid, 'high')
        if not r.get('ok') or psutil.Process(p.pid).nice() != psutil.HIGH_PRIORITY_CLASS:
            problems.append(f'높음으로 바꾸지 못했습니다: {r}')
        process_boost.restore(p.pid)
        if psutil.Process(p.pid).nice() != before:
            problems.append('원래 우선순위로 돌아오지 않았습니다')
        for proc in psutil.process_iter(['name']):
            if (proc.info['name'] or '').lower() in ('csrss.exe', 'explorer.exe'):
                if process_boost.set_priority(proc.pid, 'idle').get('ok'):
                    problems.append(f"{proc.info['name']} 의 우선순위를 바꿨습니다")
                break
    finally:
        p.kill()                                   # 이 점검이 띄운 ping 만 끝낸다
    return verdict(problems, [])


@check('디블로터 앱: 이 계정에서 제거 → 되살리기')
def appx_round_trip():
    from backend import debloater
    item = None
    for x in debloater.DEBLOAT_SAFE_LIST:
        if x['kind'] == 'appx':
            ok, rows, _ = debloater._query_packages(x['packages'])
            if ok and [r for r in rows if not r.get('error')]:
                item = x
                break
    if not item:
        return 'SKIP', '샌드박스에 목록의 앱이 설치돼 있지 않습니다', []
    before = snapshot('appx_before')
    problems = []
    status, detail = debloater._apply_appx_item(item, debloater._current_account())
    if status != 'removed':
        problems.append(f"{item['name']} 제거: {status} {detail}")
    r = debloater.restore_removed_apps()
    if not r.get('success'):
        problems.append(f"되살리기: {r.get('message')} {r.get('failed')}")
    return verdict(problems, diff(before, snapshot('appx_after')))


@check('APEX CARE 제거 전 되돌리기: main.py --revert-for-uninstall')
def uninstall_revert():
    from backend import debloater, optimizer, perf_modes, uninstall_prep
    reg_set('HKCU', RUN_U, 'ApexSbxUninst', r'C:\Windows\System32\notepad.exe')
    try:
        before = snapshot('uninstall_before')
        problems = []
        perf_modes.apply_mode('gaming')
        debloater._apply_telemetry_policy()
        optimizer.toggle_startup_app('HKCU:ApexSbxUninst', False)
        env = dict(os.environ, PYTHONUTF8='1')
        r = subprocess.run([sys.executable, os.path.join(REPO, 'main.py'), '--revert-for-uninstall'],
                           shell=False, capture_output=True, env=env, cwd=REPO,
                           creationflags=CREATE_NO_WINDOW, timeout=300)
        if r.returncode != 0:
            problems.append(f'종료 코드 {r.returncode}: {r.stderr.decode("utf-8", "replace")[-300:]}')
        try:
            res = json.load(open(uninstall_prep.result_path(), encoding='utf-8'))
            if not res.get('success'):
                problems.append(f"결과 파일: {res.get('failed')}")
        except Exception as e:
            problems.append(f'결과 파일을 읽지 못했습니다: {e}')
        return verdict(problems, diff(before, snapshot('uninstall_after')))
    finally:
        reg_del('HKCU', RUN_U, 'ApexSbxUninst')


@check('원클릭 최적화: Windows Update 캐시·Prefetch 는 건드리지 않음')
def one_click():
    from backend import optimizer

    def count(path):
        try:
            return sum(len(fs) for _, _, fs in os.walk(path))
        except OSError:
            return None
    root = os.environ['SystemRoot']
    wu, pf = os.path.join(root, 'SoftwareDistribution', 'Download'), os.path.join(root, 'Prefetch')
    marker = os.path.join(wu, 'apex_check_marker.tmp')
    os.makedirs(wu, exist_ok=True)
    with open(marker, 'w') as f:
        f.write('x')
    before = (count(wu), count(pf))
    optimizer._run_deep_optimization()
    st = optimizer.get_deep_optimization_status()
    problems = []
    if (count(wu), count(pf)) != before or not os.path.exists(marker):
        problems.append(f'Windows Update 캐시·Prefetch 파일 수가 바뀌었습니다 {before} → {(count(wu), count(pf))}')
    plan = [p['name'] for p in optimizer.get_deep_optimization_plan()['steps']]
    if [s['name'] for s in st.get('steps', [])] != plan:
        problems.append('결과 단계 이름이 계획과 다릅니다')
    try:
        os.remove(marker)
    except OSError:
        pass
    detail = '; '.join(f"{s['name']}={'성공' if s['ok'] else '실패'}({s.get('detail', '')})" for s in st.get('steps', []))
    status, why, changes = verdict(problems, [])
    return status, (why + ' ' + detail).strip(), changes


# ─────────────────────────────────────────────

def write_report(started):
    counts = {s: sum(1 for r in RESULTS if r['status'] == s) for s in ('PASS', 'FAIL', 'SKIP')}
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump({'started': started, 'counts': counts, 'results': RESULTS}, f, ensure_ascii=False, indent=1)
    lines = [f'# APEX CARE 샌드박스 점검 결과', '',
             f"시작 {started} · 통과 {counts['PASS']} · 실패 {counts['FAIL']} · 건너뜀 {counts['SKIP']}", '',
             '| 결과 | 점검 | 시간(초) |', '|---|---|---|']
    lines += [f"| {r['status']} | {r['name']} | {r['seconds']} |" for r in RESULTS]
    for r in RESULTS:
        if r['status'] != 'PASS' or r['name'] == '환경 정보':
            lines += ['', f"## {r['status']} — {r['name']}", '', '```', r['detail'] or '(설명 없음)', '```']
            if r['diff']:
                lines += ['', '처음과 다른 줄:', '', '```', *r['diff'], '```']
    with open(os.path.join(OUT, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    refuse_outside_sandbox()
    sys.path.insert(0, REPO)
    os.makedirs(OUT, exist_ok=True)
    started = time.strftime('%Y-%m-%d %H:%M:%S')
    for run in CHECKS:
        run()
        write_report(started)                      # 중간에 멈춰도 여기까지의 결과는 남는다
    return 1 if any(r['status'] == 'FAIL' for r in RESULTS) else 0


if __name__ == '__main__':
    sys.exit(main())
