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
    out += _expect_power(want, '게이밍', [(ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, 2, 'CPU 부스트 모드'),
                                        (ss.SUB_PROCESSOR, ss.PERFEPP, 0, 'EPP'),
                                        (ss.SUB_PCIEXPRESS, ss.PCIE_ASPM, 0, 'PCIe 절전')])
    return out


def _expect_power(plan, mode, items):
    """새 전원 항목이 AC·DC 모두 기대값인지. 이 PC(샌드박스)에 없는 항목은 건너뛴다(모드도 건너뛴다)."""
    from backend import system_state as ss
    out = []
    for sub, setting, want, name in items:
        for ac in (True, False):
            code, v = ss._read_power_raw(plan, sub, setting, ac)
            if code == ss._ERROR_FILE_NOT_FOUND:
                continue
            if v != want:
                out.append(f"{mode}: {name}({'AC' if ac else 'DC'})가 {want} 가 아닙니다 ({v})")
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
    out += _expect_power(want, '에코', [(ss.SUB_PROCESSOR, ss.PERFBOOSTMODE, 0, 'CPU 부스트 모드'),
                                      (ss.SUB_PROCESSOR, ss.PERFEPP, 80, 'EPP'),
                                      (ss.SUB_PCIEXPRESS, ss.PCIE_ASPM, 2, 'PCIe 절전')])
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


@check('시작 프로그램: 시작프로그램 폴더의 바로 가기 끄기·켜기·전부 원래대로 (파일은 그대로)')
def startup_folder():
    from backend import optimizer, perf_modes
    problems = []
    created = []
    try:
        for tag, name in (('FOLDER', 'ApexSbxFolder.lnk'), ('FOLDER_ALL', 'ApexSbxFolderAll.lnk')):
            folder = optimizer._startup_folder(tag)
            if not folder:
                problems.append(f'{tag} 시작프로그램 폴더를 찾지 못했습니다')
                continue
            path = os.path.join(folder, name)
            with open(path, 'wb') as f:
                f.write(b'apex sandbox check')          # 점검용 빈 파일(실행되지 않는다)
            created.append((tag, name, path))
        base = snapshot('startup_folder_base')
        for tag, name, path in created:
            r = optimizer.toggle_startup_app(f'{tag}:{name}', False)
            if not r.get('success'):
                problems.append(f'{tag}:{name} 끄기 실패: {r.get("message")}')
            if not os.path.exists(path):
                problems.append(f'끄기가 바로 가기 파일을 지웠습니다: {path}')
        state = {a['id']: a['enabled'] for a in optimizer.get_startup_apps()}
        for tag, name, _ in created:
            if state.get(f'{tag}:{name}') is not False:
                problems.append(f'끈 뒤 목록 상태가 다릅니다: {tag}:{name} → {state.get(f"{tag}:{name}")}')
        for tag, name, _ in created:
            optimizer.toggle_startup_app(f'{tag}:{name}', True)
        changes = diff(base, snapshot('startup_folder_on_again'))
        if changes:
            problems.append('다시 켠 뒤 상태가 처음과 다릅니다')
        for tag, name, _ in created:
            optimizer.toggle_startup_app(f'{tag}:{name}', False)
        r = perf_modes.revert_everything()
        if not r.get('success'):
            problems.append(f"전부 원래대로 실패: {r.get('message')}")
        return verdict(problems, changes + diff(base, snapshot('startup_folder_after_revert')))
    finally:
        for _, _, path in created:
            try:
                os.remove(path)                          # 이 점검이 만든 파일만 지운다
            except OSError:
                pass


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
        # 점검 준비로 만든 예전 버전 키도 지운다(비었을 때만). 남기면 다음 점검의 '처음 상태' 가 달라진다.
        from backend import system_state as ss
        for path in (legacy + r'\_origin', legacy, r'Software\APEXCARE'):
            ss._delete_key_if_empty('HKCU', path)


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
    with open(junk, 'wb') as f:
        f.write(b'j' * (2 * 1024 * 1024))           # 확보 용량이 '지운 파일 크기' 로 잡히는지 보려고 2MB
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
        # 확보 용량은 지운 파일 크기의 합이다(드라이브 여유 공간 차이가 아니다). 2MB 파일을 지웠으면 2MB 이상.
        if not isinstance(st.get('freed_mb'), (int, float)) or st['freed_mb'] < 2.0:
            problems.append(f"확보 용량이 지운 크기보다 작게 보고됐습니다: {st.get('freed_mb')}MB")
        log = os.path.join(config_manager.APPDATA_DIR, 'skipped_files.log')
        if h is None:
            problems.append('잠금 파일을 만들지 못해 건너뛴 로그는 확인하지 못했습니다')
        elif not (os.path.exists(log) and 'apex_check_locked.tmp' in open(log, encoding='utf-8').read()):
            problems.append('잠긴 파일이 건너뛴 로그에 없습니다')
        elif not st.get('skipped_count'):
            problems.append(f"잠긴 파일이 건너뛴 개수에 없습니다: {st.get('skipped_count')}")
        desktop_log = os.path.join(os.path.expanduser('~'), 'Desktop', 'APEX_Skipped_Files.log')
        if os.path.exists(desktop_log):
            problems.append('바탕화면에 로그가 생겼습니다')
    finally:
        if h is not None:
            kernel32.CloseHandle(ctypes.c_void_p(h))
        if os.path.isdir(link):
            os.rmdir(link)                        # 정션 자체만 지운다(대상 폴더는 그대로)
    return verdict(problems, [])


@check('SFC 출력: UTF-16 으로 나오는 결과 문장을 깨지지 않게 읽음')
def sfc_output_encoding():
    # sfc /? 는 도움말만 출력하고 아무것도 검사·복구하지 않는다. 파이프로 받으면 UTF-16 으로 나오는지와
    # 앱이 그것을 글자로 푸는지만 본다(진짜 /scannow 는 몇 분 걸리고 시스템 파일을 고칠 수 있어 돌리지 않는다).
    from backend import system_repair
    r = subprocess.run([os.path.join(os.environ['SystemRoot'], 'System32', 'sfc.exe'), '/?'],
                       shell=False, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
    text = system_repair.decode_console_output(r.stdout)
    problems = []
    if not text.strip():
        problems.append('sfc 출력이 비었습니다')
    if '\x00' in text:
        problems.append('해독한 글자에 NUL 이 남았습니다(UTF-16 을 코드 페이지로 읽음)')
    if 'SCANNOW' not in text.upper():
        problems.append(f'도움말에 SCANNOW 가 보이지 않습니다: {text[:200]!r}')
    return verdict(problems, [])


@check('프로그램 삭제: 아직 설치된 프로그램의 폴더는 잔여물로 찾지 않음')
def leftover_guard():
    from backend import uninstaller
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ApexSbxLeftoverCheck'
    name = 'Apex Sandbox Leftover Check'
    folder = os.path.join(os.environ['LOCALAPPDATA'], 'ApexSbxLeftoverCheck')
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'app.dat'), 'w') as f:
        f.write('program file')
    reg_set('HKCU', key, 'DisplayName', name)
    reg_set('HKCU', key, 'UninstallString', r'C:\Windows\System32\notepad.exe')
    reg_set('HKCU', key, 'InstallLocation', folder)
    problems = []
    try:
        uninstaller.get_installed_apps()                      # 화면이 목록을 띄울 때처럼 설치 경로를 기억시킨다
        r = uninstaller.scan_leftovers(name)
        if not r.get('stillInstalled') or r.get('items'):
            problems.append(f'설치된 채로 잔여물을 찾았습니다: {r}')
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)       # 제거가 끝난 것처럼 등록 정보를 지운다
        r = uninstaller.scan_leftovers(name)
        paths = [os.path.normcase(i['path']) for i in r.get('items', [])]
        if os.path.normcase(folder) not in paths:
            problems.append(f'제거 뒤 설치 폴더를 찾지 못했습니다: {r}')
        c = uninstaller.clean_leftovers([folder])
        if not c.get('success') or os.path.exists(folder):
            problems.append(f'남은 폴더를 휴지통으로 보내지 못했습니다: {c}')
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass
        if os.path.isdir(folder):
            import shutil
            shutil.rmtree(folder, ignore_errors=True)         # 이 점검이 만든 폴더만 지운다
    return verdict(problems, [])


@check('삭제 안전: 정션은 휴지통으로 보내지 않고, 가리키는 원래 폴더도 그대로')
def link_guard():
    import _winapi
    import shutil
    from backend import safe_delete, uninstaller
    base = os.path.join(os.environ['LOCALAPPDATA'], 'ApexSbxLinkCheck')
    real = os.path.join(base, 'RealData')
    link = os.path.join(base, 'LinkToData')
    holder = os.path.join(base, 'Holder')
    os.makedirs(real, exist_ok=True)
    os.makedirs(holder, exist_ok=True)
    with open(os.path.join(real, 'save.dat'), 'wb') as f:
        f.write(b'x' * 4096)
    _winapi.CreateJunction(real, link)
    _winapi.CreateJunction(real, os.path.join(holder, 'inner'))
    problems = []
    try:
        r = safe_delete.to_recycle_bin([link])
        if r.get('ok') or not os.path.lexists(link) or not os.path.exists(os.path.join(real, 'save.dat')):
            problems.append(f'정션을 지우려 했습니다: {r}')
        c = uninstaller.clean_leftovers([link])
        if c.get('deleted') or not os.path.exists(os.path.join(real, 'save.dat')):
            problems.append(f'잔여물 정리가 정션 너머를 지웠습니다: {c}')
        # 정션을 품은 폴더는 휴지통으로 보내도 된다. 정션은 링크째 옮겨지고 원래 폴더는 남아야 한다.
        size = safe_delete.walk_size(holder)
        if size != 0:
            problems.append(f'정션 너머 크기를 셌습니다: {size} 바이트')
        r = safe_delete.to_recycle_bin([holder])
        if not r.get('ok') or os.path.exists(holder):
            problems.append(f'정션을 품은 폴더를 휴지통으로 보내지 못했습니다: {r}')
        if not os.path.exists(os.path.join(real, 'save.dat')):
            problems.append('폴더를 휴지통으로 보냈더니 안의 정션이 가리키던 파일이 사라졌습니다')
    finally:
        if os.path.lexists(link):
            os.rmdir(link)                                     # 정션만 지운다(가리키는 폴더는 그대로)
        shutil.rmtree(base, ignore_errors=True)                # 이 점검이 만든 폴더만 지운다
    return verdict(problems, [])


@check('삭제 안전: 휴지통에 들어가지 않는 대상(휴지통 사용 안 함·휴지통보다 큼)은 지우지 않음')
def recycle_guard():
    import shutil
    from backend import safe_delete
    base = os.path.join(os.environ['LOCALAPPDATA'], 'ApexSbxRecycleCheck')
    os.makedirs(base, exist_ok=True)
    target = os.path.join(base, 'keep.bin')
    with open(target, 'wb') as f:
        f.write(b'x' * 4096)
    problems = []
    dtype, guid, total = safe_delete._volume_info(target)
    if dtype != safe_delete.DRIVE_FIXED or not guid or not total:
        problems.append(f'볼륨 정보를 읽지 못했습니다: {(dtype, guid, total)}')
    key = safe_delete._BITBUCKET + '\\' + (guid or '')
    old = reg_get('HKCU', key, 'NukeOnDelete')
    try:
        if guid:
            reg_set('HKCU', key, 'NukeOnDelete', 1, winreg.REG_DWORD)     # '휴지통 사용 안 함' 으로 바꿔 본다
            r = safe_delete.to_recycle_bin([target])
            if r.get('ok') or not os.path.exists(target):
                problems.append(f'휴지통을 쓰지 않는 드라이브에서 파일을 지웠습니다(영구 삭제): {r}')
        # 휴지통보다 큰 대상(크기만 키워 판정)
        if safe_delete.recycle_block_reason(target, 10 ** 15) is None:
            problems.append('휴지통보다 큰 대상을 거부하지 않았습니다')
    finally:
        if guid:
            if old is None:
                reg_del('HKCU', key, 'NukeOnDelete')
            else:
                reg_set('HKCU', key, 'NukeOnDelete', old[0] if isinstance(old, tuple) else old, winreg.REG_DWORD)
    # 원래 설정에서는 휴지통으로 간다(복구 가능)
    r = safe_delete.to_recycle_bin([target])
    if not r.get('ok') or os.path.exists(target):
        problems.append(f'평소 설정에서 휴지통으로 보내지 못했습니다: {r}')
    shutil.rmtree(base, ignore_errors=True)                          # 이 점검이 만든 폴더만 지운다
    return verdict(problems, [])


@check('프로세스 우선순위: 바꾸고 원래대로, 시스템 프로세스는 거부')
def priority():
    import psutil
    from backend import process_boost
    # 이 점검의 자식으로 띄우면 앱이 '자기 프로세스' 로 보고 막는다(맞는 동작). PowerShell 이 띄우고 먼저 끝나게 해
    # 부모 없는 프로세스로 만든다. 사용자가 따로 실행한 프로그램과 같은 처지다.
    ping = os.path.join(os.environ['SystemRoot'], 'System32', 'PING.EXE')
    r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                        f"(Start-Process -FilePath '{ping}' -ArgumentList '-t','127.0.0.3' "
                        "-WindowStyle Hidden -PassThru).Id"],
                       shell=False, capture_output=True, text=True, errors='replace',
                       creationflags=CREATE_NO_WINDOW, timeout=60)
    pid = int(r.stdout.strip().splitlines()[-1])
    problems = []
    try:
        time.sleep(1)
        before = psutil.Process(pid).nice()
        r = process_boost.set_priority(pid, 'high')
        if not r.get('ok') or psutil.Process(pid).nice() != psutil.HIGH_PRIORITY_CLASS:
            problems.append(f'높음으로 바꾸지 못했습니다: {r}')
        process_boost.restore(pid)
        if psutil.Process(pid).nice() != before:
            problems.append('원래 우선순위로 돌아오지 않았습니다')
        # 게임 부스트가 낮춘 채 앱이 비정상 종료된 경우: 파일 기록으로 다음 실행 때 되돌린다
        r = process_boost.set_priority(pid, 'idle', owner='boost')
        if not r.get('ok'):
            problems.append(f'부스트로 낮추지 못했습니다: {r}')
        process_boost._original.clear()                  # 비정상 종료(메모리 기록이 사라짐)
        n, bad = process_boost.recover_after_crash()
        if n != 1 or bad or psutil.Process(pid).nice() != before:
            problems.append(f'비정상 종료 뒤 원래 우선순위로 되돌리지 못했습니다: {n}건, {bad}, '
                            f'지금 {psutil.Process(pid).nice()}')
        # 이 점검이 직접 띄운 자식은 앱이 자기 프로세스로 보고 막아야 한다
        child = subprocess.Popen([ping, '-t', '127.0.0.4'], shell=False, stdout=subprocess.DEVNULL,
                                 creationflags=CREATE_NO_WINDOW)
        try:
            if process_boost.set_priority(child.pid, 'high').get('ok'):
                problems.append('자기 자식 프로세스의 우선순위를 바꿨습니다')
        finally:
            child.kill()
        for proc in psutil.process_iter(['name']):
            if (proc.info['name'] or '').lower() in ('csrss.exe', 'explorer.exe'):
                if process_boost.set_priority(proc.pid, 'idle').get('ok'):
                    problems.append(f"{proc.info['name']} 의 우선순위를 바꿨습니다")
                break
    finally:
        try:
            psutil.Process(pid).kill()             # 이 점검이 띄운 ping 만 끝낸다
        except psutil.Error:
            pass
    return verdict(problems, [])


# 샌드박스에는 디블로터 목록의 앱(Bing 뉴스 등)이 없다. 그때는 샌드박스에 있는 다른 앱 하나로
# 같은 코드 경로(설치 확인 → 기록 → 이 계정에서 제거 → 매니페스트 재등록 → 설치 재확인)를 돌린다.
# 제품의 디블로터 목록은 바꾸지 않는다. 대상 지정은 이 점검 안에서만 한다.
_SANDBOX_APPX_PREFERRED = (
    'Microsoft.WindowsCalculator', 'Microsoft.WindowsAlarms', 'Microsoft.MicrosoftStickyNotes',
    'Microsoft.WindowsSoundRecorder', 'Microsoft.ScreenSketch', 'Microsoft.Paint', 'Microsoft.WindowsNotepad',
    'Microsoft.Windows.Photos', 'Microsoft.WindowsCamera', 'Microsoft.GetHelp', 'Microsoft.Getstarted',
)
# 샌드박스에는 스토어 앱이 하나도 없고 SystemApps 의 시스템 앱만 있다(4회차에서 확인). 그중 지워도 샌드박스의
# 다른 점검에 영향이 없는 작은 대화 상자류만 쓴다. SystemApps 에서는 이 목록 밖의 앱을 고르지 않는다.
_SANDBOX_SYSTEMAPPS_OK = (
    'Microsoft.Windows.XGpuEjectDialog', 'Microsoft.Windows.NarratorQuickStart', 'Microsoft.Windows.CapturePicker',
    'Microsoft.Windows.PinningConfirmationDialog', 'Microsoft.Windows.SecureAssessmentBrowser',
    'Microsoft.Windows.ParentalControls', 'Microsoft.MicrosoftEdgeDevToolsClient',
    'Microsoft.Windows.PrintQueueActionCenter', 'Microsoft.Windows.PeopleExperienceHost',
)
# 지우면 다른 앱 설치·보안 화면이 망가질 수 있는 것은 고르지 않는다(샌드박스라도 뒤 점검에 영향이 간다)
_SANDBOX_APPX_AVOID = ('store', 'appinstaller', 'desktopappinstaller', 'sechealth', 'windowsterminal',
                       'shellexperience', 'startmenu', 'client.', 'windows.cbs', 'aad.', 'accountscontrol')

_PS_LIST_ALL = r"""
foreach ($p in @(Get-AppxPackage)) {
  [void]$out.Add([ordered]@{
    name = [string]$p.Name; fullName = [string]$p.PackageFullName; familyName = [string]$p.PackageFamilyName
    installLocation = [string]$p.InstallLocation
    nonRemovable = [bool]$p.NonRemovable; isFramework = [bool]$p.IsFramework
  })
}
"""


def _sandbox_appx_item():
    """샌드박스에 설치된 앱 중 점검에 쓸 것 하나. (item, 설치된 이름 목록). 없으면 item 은 None."""
    from backend import debloater
    ok, rows, err = debloater._run_ps_json(_PS_LIST_ALL, {}, debloater.QUERY_TIMEOUT_SEC)
    if not ok:
        raise RuntimeError(f'설치된 앱 목록을 읽지 못했습니다: {err}')
    windowsapps, systemapps = (os.path.normcase(r) + os.sep for r in debloater._windowsapps_roots())
    usable, seen = {}, []
    for r in rows:
        name = str(r.get('name') or '')
        loc = os.path.normcase(str(r.get('installLocation') or ''))
        seen.append(f"{name}{' [F]' if r.get('isFramework') else ''}{' [고정]' if r.get('nonRemovable') else ''}")
        if (r.get('isFramework') or r.get('nonRemovable') or not debloater._PKG_RE.match(name)
                or any(a in name.lower() for a in _SANDBOX_APPX_AVOID)
                or debloater._manifest_path(r.get('installLocation')) is None):
            continue
        if loc.startswith(windowsapps) or (loc.startswith(systemapps) and name in _SANDBOX_SYSTEMAPPS_OK):
            usable[name] = r
    names = sorted(seen)
    pick = (next((n for n in _SANDBOX_APPX_PREFERRED if n in usable), None)
            or next((n for n in sorted(usable) if n not in _SANDBOX_SYSTEMAPPS_OK), None)
            or next((n for n in _SANDBOX_SYSTEMAPPS_OK if n in usable), None))
    if not pick:
        return None, names
    return {'id': 'sandbox-check', 'name': f'점검용 앱 {pick}', 'kind': 'appx', 'packages': [pick]}, names


@check('디블로터 앱: 이 계정에서 제거 → 기록 → 되살리기')
def appx_round_trip():
    from backend import debloater
    item, note = None, ''
    for x in debloater.DEBLOAT_SAFE_LIST:
        if x['kind'] == 'appx':
            ok, rows, _ = debloater._query_packages(x['packages'])
            if ok and [r for r in rows if not r.get('error')]:
                item = x
                break
    if not item:
        item, installed = _sandbox_appx_item()
        if not item:
            return 'SKIP', f'제거·되살리기에 쓸 앱이 없습니다. 설치된 앱: {installed}', []
        note = f"목록의 앱이 없어 {item['packages'][0]} 로 확인했습니다. "
    account = debloater._current_account()
    problems = []
    why = debloater._account_problem(account)
    if why:
        return 'FAIL', f'계정 판정이 제거를 막았습니다: {why}', []

    ok, rows, err = debloater._query_packages(item['packages'])
    if not ok:
        return 'FAIL', f'설치 상태 확인 실패: {err}', []
    original = {r['familyName'].lower(): r['fullName'] for r in rows if not r.get('error')}
    before = snapshot('appx_before')

    status, detail = debloater._apply_appx_item(item, account)
    if status != 'removed':
        problems.append(f"{item['name']} 제거: {status} {detail}")
    ok, rows, err = debloater._query_packages(item['packages'])
    if not ok or [r for r in rows if not r.get('error')]:
        problems.append(f'제거 뒤에도 설치돼 있습니다(또는 확인 실패: {err})')
    recorded = {a.get('fullName'): a for a in debloater.get_removed_apps()}
    for fam, full in original.items():
        a = recorded.get(full)
        if not a:
            problems.append(f'{full} 이 제거 기록에 없습니다')
        elif (a.get('account') or '').lower() != account.lower() or not a.get('manifestFound'):
            problems.append(f"제거 기록이 이상합니다: account={a.get('account')} manifestFound={a.get('manifestFound')}")

    r = debloater.restore_removed_apps(item['packages'])
    if not r.get('success'):
        problems.append(f"되살리기: {r.get('message')} {r.get('failed')}")
    ok, rows, err = debloater._query_packages(item['packages'])
    now = {r['familyName'].lower(): r['fullName'] for r in rows if not r.get('error')} if ok else {}
    if now != original:
        problems.append(f'되살린 뒤 설치 상태가 처음과 다릅니다: {original} → {now}')
    left = [a.get('fullName') for a in debloater.get_removed_apps() if a.get('fullName') in original.values()]
    if left:
        problems.append(f'되살렸는데 제거 기록에 남았습니다: {left}')
    status, why, changes = verdict(problems, diff(before, snapshot('appx_after')))
    return status, (note + why).strip(), changes


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
# 설치 마법사 → 제거 프로그램 (빌드한 설치 파일 그대로)
# ─────────────────────────────────────────────
# 창은 tools/sandbox/ui_drive.ps1 이 UI Automation 으로 누른다. 설치 프로그램에 무인 설치 옵션을 만들지 않는다.

DIST = os.environ.get('APEX_DIST') or r'C:\apex\dist'
UI_PS1 = os.path.join(REPO, 'tools', 'sandbox', 'ui_drive.ps1')
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\APEX CARE'


def ui(window, action, name='', timeout=30):
    """ui_drive.ps1 을 한 번 부른다. {'ok', 'error', 'names'}"""
    args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', UI_PS1,
            '-Window', window, '-Action', action, '-TimeoutSec', str(timeout)]
    if name:
        args += ['-Name', name]
    r = subprocess.run(args, shell=False, capture_output=True, text=True, errors='replace',
                       creationflags=CREATE_NO_WINDOW, timeout=timeout + 90)
    for line in reversed((r.stdout or '').splitlines()):
        if line.strip().startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {'ok': False, 'error': ((r.stderr or '') + (r.stdout or '')).strip()[-400:], 'names': []}


def _ui_step(problems, what, window, action, name='', timeout=30):
    res = ui(window, action, name, timeout)
    if not res.get('ok'):
        problems.append(f"{what}: {res.get('error')} 보인 컨트롤={res.get('names', [])[:25]}")
    return bool(res.get('ok'))


def _app_version():
    import re
    with open(os.path.join(REPO, 'tools', 'setup_wizard.py'), encoding='utf-8') as f:
        return re.search(r"^APP_VERSION = '([^']+)'", f.read(), re.M).group(1)


def _wait(cond, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(1)
    return cond()


def _desktop_shortcut():
    return os.path.join(os.environ['USERPROFILE'], 'Desktop', 'APEX CARE.lnk')


@check('설치 마법사 → 제거 프로그램: 설치, 제거 전 되돌리기(빌드한 exe), 흔적 정리')
def install_uninstall():
    setup = os.path.join(DIST, f'APEX CARE Setup {_app_version()}.exe')
    if not os.path.isfile(setup):
        return 'SKIP', f'설치 파일이 없습니다: {setup} (build_all.bat 로 만든 뒤 다시 돌리세요)', []
    from backend import optimizer, perf_modes, uninstall_prep
    install_dir = os.path.join(os.environ['LOCALAPPDATA'], 'APEX CARE')
    app_exe = os.path.join(install_dir, 'APEX CARE.exe')
    uninst_exe = os.path.join(install_dir, 'APEX CARE Uninstaller.exe')
    if os.path.exists(install_dir) or reg_get('HKCU', UNINSTALL_KEY, 'DisplayName') is not None:
        return 'FAIL', '점검 전에 이미 설치돼 있습니다(샌드박스가 깨끗하지 않음)', []
    built = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(setup)))
    problems = []

    # ── 설치: 사용권 동의 → 다음 → 다음(설치) → 완료 화면에서 '실행하기' 끄고 종료
    win = '설치 - APEX CARE'
    proc = subprocess.Popen([setup], shell=False, cwd=DIST)
    try:
        ok = (_ui_step(problems, '사용권 동의', win, 'select', '조항에 동의합니다', 90)
              and _ui_step(problems, '다음(사용권)', win, 'click', '다음')
              and _ui_step(problems, '준비 화면', win, 'wait', '대상 위치')
              and _ui_step(problems, '다음(설치 시작)', win, 'click', '다음')
              and _ui_step(problems, '완료 화면', win, 'wait', '실행하기', 120)
              and _ui_step(problems, "'실행하기' 끄기", win, 'uncheck', '실행하기')
              and _ui_step(problems, '종료', win, 'click', '종료'))
        if ok and not _wait(lambda: proc.poll() is not None, 60):
            problems.append('종료를 눌렀는데 설치 마법사가 끝나지 않았습니다')
    finally:
        if proc.poll() is None:
            proc.kill()                            # 이 점검이 띄운 설치 마법사만 끝낸다
    if problems:
        return 'FAIL', f'설치 파일 {built}. ' + '; '.join(problems), []

    installed = {
        'exe': os.path.isfile(app_exe), 'uninstaller': os.path.isfile(uninst_exe),
        'DisplayVersion': reg_get('HKCU', UNINSTALL_KEY, 'DisplayVersion'),
        'InstallLocation': reg_get('HKCU', UNINSTALL_KEY, 'InstallLocation'),
        'UninstallString': reg_get('HKCU', UNINSTALL_KEY, 'UninstallString'),
        'shortcut': os.path.exists(_desktop_shortcut()),
    }
    if not (installed['exe'] and installed['uninstaller']):
        problems.append(f'설치 폴더에 파일이 없습니다: {installed}')
    if installed['DisplayVersion'] != _app_version():
        problems.append(f"프로그램 목록의 버전이 {installed['DisplayVersion']} 입니다")
    if os.path.normcase(installed['InstallLocation'] or '') != os.path.normcase(install_dir):
        problems.append(f"InstallLocation 이 다릅니다: {installed['InstallLocation']}")
    if os.path.normcase(installed['UninstallString'] or '') != os.path.normcase(f'"{uninst_exe}"'):
        problems.append(f"UninstallString 이 다릅니다: {installed['UninstallString']}")
    if problems:
        return 'FAIL', '; '.join(problems), []

    # ── 바꿔 둔 뒤 제거: 제거 프로그램이 설치된 exe(PyInstaller 빌드)로 되돌리는지 본다
    reg_set('HKCU', RUN_U, 'ApexSbxInstalled', r'C:\Windows\System32\notepad.exe')
    try:
        before = snapshot('install_before_changes')
        perf_modes.apply_mode('gaming')
        optimizer.toggle_startup_app('HKCU:ApexSbxInstalled', False)
        try:
            os.remove(uninstall_prep.result_path())
        except OSError:
            pass
        proc = subprocess.Popen([uninst_exe], shell=False, cwd=install_dir)
        try:
            if _ui_step(problems, '삭제 확인', 'APEX CARE 삭제', 'click', r'^(Yes|예)', 60):
                # 되돌리기(최대 300초)가 끝나면 제거 프로그램이 끝나거나, 실패 목록 창을 띄운다
                done = _wait(lambda: proc.poll() is not None
                             or ui('설정을 모두 되돌리지 못했습니다', 'exists', timeout=1).get('ok'), 330)
                if proc.poll() is None:
                    names = ui('설정을 모두 되돌리지 못했습니다', 'names', timeout=2).get('names', [])
                    problems.append(f'되돌리기 실패 창이 떴습니다: {names[:10]}' if done
                                    else '제거 프로그램이 330초 안에 끝나지 않았습니다')
                    _ui_step(problems, "실패 창 '아니요'", '설정을 모두 되돌리지 못했습니다', 'click', r'^(No|아니요)', 5)
        finally:
            if proc.poll() is None:
                proc.kill()
        try:
            res = json.load(open(uninstall_prep.result_path(), encoding='utf-8'))
            if not res.get('success'):
                problems.append(f"설치된 exe 의 되돌리기 결과: {res.get('failed')}")
        except Exception as e:
            problems.append(f'설치된 exe 가 되돌리기 결과를 남기지 않았습니다: {e}')

        # 제거 프로그램이 띄운 배치 파일이 2초 뒤 폴더·바로 가기·프로그램 목록 키를 지운다
        gone = _wait(lambda: not os.path.exists(install_dir)
                     and reg_get('HKCU', UNINSTALL_KEY, 'DisplayName') is None, 90)
        if not gone:
            import psutil
            left = sorted(os.listdir(install_dir)) if os.path.isdir(install_dir) else []
            alive = sorted({p.info['name'] for p in psutil.process_iter(['name'])
                            if (p.info['name'] or '').lower().startswith(('apex care', 'cmd.exe'))})
            problems.append(f"제거 뒤에도 남았습니다: 폴더={os.path.exists(install_dir)} 남은 파일={left} "
                            f"목록 키={reg_get('HKCU', UNINSTALL_KEY, 'DisplayName') is not None} 실행 중={alive}")
        if os.path.exists(_desktop_shortcut()):
            problems.append('바탕 화면 바로 가기가 남았습니다')
        changes = diff(before, snapshot('install_after_uninstall'))
    finally:
        reg_del('HKCU', RUN_U, 'ApexSbxInstalled')
    status, why, changes = verdict(problems, changes)
    return status, f"설치 파일 {built}. {why}".strip(), changes


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
