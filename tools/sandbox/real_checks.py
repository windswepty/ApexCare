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
    # 원래 값 기록은 관리자만 쓰는 PC 저널(HKLM)에 있어야 한다. 계정 파일에 있으면 일반 권한 프로그램이 고칠 수 있다.
    from backend import machine_store
    machine = (machine_store.read('Journal') or {}).get('entries', {})
    if ss._PLAN_KEY not in machine:
        out.append('게이밍: 원래 전원 플랜 기록이 PC 저널(HKLM\\SOFTWARE\\APEX CARE)에 없습니다')
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
    search = r'SOFTWARE\Policies\Microsoft\Windows\Windows Search'
    # 샌드박스에는 처음부터 AllowCortana=0 이 있어, 그대로 두면 같은 값을 다시 쓰고 지우는 경로가 돌지 않는다.
    # 이 점검 동안만 지웠다가 끝에 원래대로 둔다.
    cortana_orig = reg_get('HKLM', search, 'AllowCortana')
    if cortana_orig is not None:
        reg_del('HKLM', search, 'AllowCortana')
    try:
        return _debloat_policy_round_trip(debloater, ss, search)
    finally:
        if cortana_orig is not None:
            reg_set('HKLM', search, 'AllowCortana', cortana_orig, winreg.REG_DWORD)


def _debloat_policy_round_trip(debloater, ss, search):
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
    if reg_get('HKLM', search, 'AllowCortana') != 0:
        problems.append('AllowCortana 가 0 이 아닙니다')
    if ss.service_start_type('DiagTrack') not in (None, 'disabled'):
        problems.append(f"DiagTrack 이 사용 안 함이 아닙니다 ({ss.service_start_type('DiagTrack')})")
    r = ss.restore_group(debloater.DEBLOAT_GROUP)
    if not r['ok']:
        problems.append(f"복구 실패: {r['failed']}")
    if reg_get('HKLM', search, 'AllowCortana') is not None:
        problems.append('원래 없던 AllowCortana 가 복구 뒤에도 남았습니다')
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
        if not ifaces:
            problems.append('Nagle 을 바꿀 네트워크 어댑터를 찾지 못했습니다(점검하지 못함)')
        # 모든 어댑터에 두 값이 다 써져야 한다. 예전에는 '어느 어댑터든 TCPNoDelay' 만 봐서 일부 실패도 통과했다
        bad = [(i, n) for i in ifaces for n in ('TcpAckFrequency', 'TCPNoDelay')
               if reg_get('HKLM', f'{base}\\{i}', n) != 1]
        if bad:
            problems.append(f'Nagle 값이 1 이 아닌 어댑터: {bad[:4]}')
        applied = game_booster._booster_state.get('appliedBoosts', [])
        if any('일부 실패' in str(x) for x in applied):
            problems.append(f'부스트가 일부 실패를 표시했습니다: {applied}')
        game_booster._exit_boost_mode()
        from backend import system_state as ss
        if any(e.get('group') == game_booster.BOOST_GROUP for e in ss.pending_changes().values()):
            problems.append('게임이 끝난 뒤에도 부스트 기록이 남았습니다')
    finally:
        config_manager.save_config(saved)
    return verdict(problems, diff(before, snapshot('nagle_after')))


def _orphan_ping(addr):
    """부모 없는 ping 을 띄워 PID 를 돌려준다. 이 점검의 자식으로 띄우면 앱이 '자기 프로세스' 로 보고 막는다(맞는 동작).
    PowerShell 이 띄우고 먼저 끝나게 해, 사용자가 따로 실행한 프로그램과 같은 처지로 만든다."""
    ping = os.path.join(os.environ['SystemRoot'], 'System32', 'PING.EXE')
    r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                        f"(Start-Process -FilePath '{ping}' -ArgumentList '-t','{addr}' "
                        "-WindowStyle Hidden -PassThru).Id"],
                       shell=False, capture_output=True, text=True, errors='replace',
                       creationflags=CREATE_NO_WINDOW, timeout=60)
    return int(r.stdout.strip().splitlines()[-1])


# 게임 도중의 앱: 부스트(Nagle·게이밍 전원 모드·백그라운드 앱 낮추기)를 적용하고 준비됐다고 알린 뒤 기다린다.
# 점검이 TerminateProcess 로 끝낸다(작업 관리자의 '작업 끝내기' 와 같다 — 정리 코드가 돌지 않는다).
_CRASH_CHILD = '''
import sys, time
sys.path.insert(0, sys.argv[1])
from backend import game_booster, process_boost
game_booster._enter_boost_mode()
r = process_boost.set_priority(int(sys.argv[2]), 'idle', owner='boost')
with open(sys.argv[3], 'w', encoding='utf-8') as f:
    f.write(repr((r.get('ok'), r.get('message'), game_booster._booster_state.get('appliedBoosts'))))
time.sleep(600)
'''

# 다시 실행한 앱: main.py 와 같이 Api 를 만들고(지난 세션 정리가 여기서 돈다) 정리한 뒤 끝난다
_RESTART_CHILD = '''
import sys
sys.path.insert(0, sys.argv[1])
from backend.api import Api
api = Api(None)
api._cleanup()
'''


@check('게임 부스트: 게임 도중 앱이 강제 종료돼도 다시 켜면 Nagle·전원 모드·낮춘 앱 우선순위가 원래대로')
def boost_crash_recovery():
    import psutil
    from backend import config_manager, game_booster, perf_modes, system_state as ss
    before = snapshot('crash_before')
    problems = []
    cfg = config_manager.load_config()
    saved = dict(cfg)
    pid = _orphan_ping('127.0.0.5')
    child = None
    ready = os.path.join(OUT, 'crash_ready.txt')
    env = dict(os.environ, PYTHONUTF8='1')
    try:
        if os.path.exists(ready):
            os.remove(ready)
        time.sleep(1)
        nice_before = psutil.Process(pid).nice()
        r = perf_modes.apply_mode('eco')                 # 게임 전 모드: 에코(저장된 모드)
        if not r.get('success'):
            problems.append(f"에코 적용: {r.get('message')}")
        eco = snapshot('crash_eco')
        cfg.update(boost_disable_nagle=True, boost_auto_power_mode=True, boost_timer_resolution=False,
                   boost_tame_background=False)
        config_manager.save_config(cfg)
        config_manager.set_booster_state(False)          # 다시 켤 때 감지 루프가 새 게임 세션을 만들지 않게

        with open(os.path.join(OUT, 'crash_child.log'), 'w', encoding='utf-8') as log:
            child = subprocess.Popen([sys.executable, '-c', _CRASH_CHILD, REPO, str(pid), ready], shell=False,
                                     stdout=log, stderr=log, env=env, cwd=REPO, creationflags=CREATE_NO_WINDOW)
            if not _wait(lambda: os.path.exists(ready) or child.poll() is not None, 180) or not os.path.exists(ready):
                return 'FAIL', '게임 도중 상태를 만들지 못했습니다(crash_child.log 참고)', []
            time.sleep(1)
            with open(ready, encoding='utf-8') as f:
                applied = f.read()
            child.kill()                                 # 비정상 종료: 정리 코드가 돌지 않는다
            child.wait(30)

        # 정말 '게임 도중' 상태가 남았는지부터 본다. 아니면 아래 복구 확인이 아무것도 시험하지 않는다
        if reg_get('HKLM', MM, 'SystemResponsiveness') != 10:
            problems.append(f'준비: 게이밍 전원 모드가 적용되지 않았습니다 ({applied})')
        if not any(e.get('group') == game_booster.BOOST_GROUP for e in ss.pending_changes().values()):
            problems.append(f'준비: Nagle 기록이 없습니다 ({applied})')
        if psutil.Process(pid).nice() != psutil.IDLE_PRIORITY_CLASS:
            problems.append(f'준비: 백그라운드 앱을 낮추지 못했습니다 ({applied})')
        if config_manager.get_boost_restore_mode() != 'eco':
            problems.append('준비: 게임 전 모드(에코) 기록이 없습니다')

        r = subprocess.run([sys.executable, '-c', _RESTART_CHILD, REPO], shell=False, capture_output=True,
                           env=env, cwd=REPO, creationflags=CREATE_NO_WINDOW, timeout=300)
        if r.returncode != 0:
            problems.append(f'다시 실행 실패 {r.returncode}: {r.stderr.decode("utf-8", "replace")[-300:]}')
        if psutil.Process(pid).nice() != nice_before:
            problems.append(f'낮춘 앱의 우선순위가 돌아오지 않았습니다 (지금 {psutil.Process(pid).nice()})')
        if any(e.get('group') == game_booster.BOOST_GROUP for e in ss.pending_changes().values()):
            problems.append('Nagle 기록이 남았습니다(되돌리지 않음)')
        if config_manager.get_boost_restore_mode():
            problems.append('게임 전 모드 기록이 남았습니다')
        if config_manager.get_optimization_mode() != 'eco':
            problems.append(f'저장된 모드가 에코가 아닙니다 ({config_manager.get_optimization_mode()})')
        left = diff(eco, snapshot('crash_recovered'))
        if left:
            problems.append(f'다시 켠 뒤 상태가 게임 전(에코)과 다릅니다 ({len(left)}줄)')
            return 'FAIL', '; '.join(problems), left
    finally:
        if child is not None and child.poll() is None:
            child.kill()
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass
        config_manager.save_config(saved)
        r = perf_modes.apply_mode('standard')
        if not r.get('success'):
            problems.append(f"표준 되돌리기: {r.get('message')}")
    return verdict(problems, diff(before, snapshot('crash_after')))


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


# ─── 클라우드 동기화(OneDrive 등)의 '온라인 전용' 파일 ───
# OneDrive 와 같은 Windows 클라우드 파일 API(cldapi)로 동기화 폴더를 만들고 내용이 없는 자리 표시자 파일을 둔다.
# 누가 내용을 읽으면 Windows 가 공급자에게 '내려받기(FETCH_DATA)' 를 요청한다. 그 요청 수를 세어, 앱의 검사가
# 내려받기를 일으키지 않는지 본다(OneDrive 계정·네트워크 없이 같은 상황을 만든다. 샌드박스에서 확인).

class _GUID(ctypes.Structure):
    _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16), ('Data3', ctypes.c_uint16),
                ('Data4', ctypes.c_ubyte * 8)]


class _CF_SYNC_REGISTRATION(ctypes.Structure):
    _fields_ = [('StructSize', ctypes.c_uint32), ('ProviderName', ctypes.c_wchar_p),
                ('ProviderVersion', ctypes.c_wchar_p), ('SyncRootIdentity', ctypes.c_void_p),
                ('SyncRootIdentityLength', ctypes.c_uint32), ('FileIdentity', ctypes.c_void_p),
                ('FileIdentityLength', ctypes.c_uint32), ('ProviderId', _GUID)]


class _CF_POLICY(ctypes.Structure):
    _fields_ = [('Primary', ctypes.c_uint16), ('Modifier', ctypes.c_uint16)]


class _CF_SYNC_POLICIES(ctypes.Structure):
    _fields_ = [('StructSize', ctypes.c_uint32), ('Hydration', _CF_POLICY), ('Population', _CF_POLICY),
                ('InSync', ctypes.c_uint32), ('HardLink', ctypes.c_uint32), ('PlaceholderManagement', ctypes.c_uint32)]


_CF_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)


class _CF_CALLBACK_REGISTRATION(ctypes.Structure):
    _fields_ = [('Type', ctypes.c_uint32), ('Callback', _CF_CALLBACK)]


class _FILE_BASIC_INFO(ctypes.Structure):
    _fields_ = [('CreationTime', ctypes.c_int64), ('LastAccessTime', ctypes.c_int64),
                ('LastWriteTime', ctypes.c_int64), ('ChangeTime', ctypes.c_int64), ('FileAttributes', ctypes.c_uint32)]


class _CF_FS_METADATA(ctypes.Structure):
    _fields_ = [('BasicInfo', _FILE_BASIC_INFO), ('FileSize', ctypes.c_int64)]


class _CF_PLACEHOLDER_CREATE_INFO(ctypes.Structure):
    _fields_ = [('RelativeFileName', ctypes.c_wchar_p), ('FsMetadata', _CF_FS_METADATA),
                ('FileIdentity', ctypes.c_void_p), ('FileIdentityLength', ctypes.c_uint32),
                ('Flags', ctypes.c_uint32), ('Result', ctypes.c_int32), ('CreateUsn', ctypes.c_int64)]


class _CloudRoot:
    """샌드박스 안의 점검용 동기화 폴더. 사용자 프로필 아래는 샌드박스에서 등록이 거부돼(E_INVALIDARG) C:\\ 바로 아래에 둔다."""

    def __init__(self, root):
        import uuid
        self.root, self.fetches, self.key, self.registered = root, [], ctypes.c_int64(), False
        self.cf = ctypes.WinDLL('cldapi', use_last_error=True)
        for fn in ('CfRegisterSyncRoot', 'CfConnectSyncRoot', 'CfCreatePlaceholders', 'CfDisconnectSyncRoot',
                   'CfUnregisterSyncRoot'):
            getattr(self.cf, fn).restype = ctypes.c_long
        os.makedirs(root, exist_ok=True)
        reg = _CF_SYNC_REGISTRATION(ctypes.sizeof(_CF_SYNC_REGISTRATION), 'ApexSbxCloud', '1.0', None, 0, None, 0,
                                    _GUID.from_buffer_copy(uuid.uuid4().bytes_le))
        pol = _CF_SYNC_POLICIES(ctypes.sizeof(_CF_SYNC_POLICIES), _CF_POLICY(2, 0), _CF_POLICY(2, 0), 0, 0, 0)
        self._check('CfRegisterSyncRoot', self.cf.CfRegisterSyncRoot(root, ctypes.byref(reg), ctypes.byref(pol), 0))
        self.registered = True
        self._cb = _CF_CALLBACK(lambda info, params: self.fetches.append(time.time()))
        self._table = (_CF_CALLBACK_REGISTRATION * 2)(_CF_CALLBACK_REGISTRATION(0, self._cb),       # FETCH_DATA
                                                      _CF_CALLBACK_REGISTRATION(0xFFFFFFFF, _CF_CALLBACK()))
        self._check('CfConnectSyncRoot',
                    self.cf.CfConnectSyncRoot(root, self._table, None, 0, ctypes.byref(self.key)))

    @staticmethod
    def _check(what, hr):
        if hr != 0:
            raise OSError(f'{what} 실패 0x{hr & 0xFFFFFFFF:08X}')

    def placeholders(self, names, size):
        """내용 없이 크기만 있는 '온라인 전용' 파일들(동기화됨 표시)"""
        now = int((time.time() + 11644473600) * 10 ** 7)
        ident = ctypes.create_string_buffer(b'apex-sbx')
        infos = (_CF_PLACEHOLDER_CREATE_INFO * len(names))()
        for i, n in enumerate(names):
            infos[i].RelativeFileName = n
            infos[i].FsMetadata.BasicInfo = _FILE_BASIC_INFO(now, now, now, now, 0x80)
            infos[i].FsMetadata.FileSize = size
            infos[i].FileIdentity = ctypes.cast(ident, ctypes.c_void_p)
            infos[i].FileIdentityLength = 8
            infos[i].Flags = 0x2                          # CF_PLACEHOLDER_CREATE_FLAG_MARK_IN_SYNC
        done = ctypes.c_uint32()
        self._check('CfCreatePlaceholders', self.cf.CfCreatePlaceholders(self.root, infos, len(names), 0,
                                                                         ctypes.byref(done)))
        return [os.path.join(self.root, n) for n in names]

    def close(self):
        if self.key.value:
            self.cf.CfDisconnectSyncRoot(self.key)
            self.key = ctypes.c_int64()
        if self.registered:
            self.cf.CfUnregisterSyncRoot(self.root)        # 자리 표시자도 함께 사라진다
            self.registered = False


@check('저장공간: OneDrive 같은 온라인 전용 파일은 대용량·중복 검사와 삭제가 건드리지 않음(내려받기 요청 0회)')
def cloud_only_files():
    import threading
    from backend import file_finder
    big = 600 * 1024 * 1024
    cloud_dir, local_dir = r'C:\ApexSbxCloud', r'C:\ApexSbxLocal'
    problems = []
    cloud = None
    os.makedirs(local_dir, exist_ok=True)
    local = [os.path.join(local_dir, n) for n in ('local_big.bin', 'local_dup_a.bin', 'local_dup_b.bin')]
    try:
        # 대조군: 로컬 파일은 검사에 잡혀야 한다(검사가 그 폴더를 실제로 본다는 증거)
        with open(local[0], 'wb') as f:
            f.truncate(big)
        for p in local[1:]:
            with open(p, 'wb') as f:
                f.write(b'apex' * (4 * 1024 * 1024))           # 16MB, 두 파일 내용이 같다
        cloud = _CloudRoot(cloud_dir)
        files = cloud.placeholders(['cloud_a.mkv', 'cloud_b.mkv'], big)
        attrs = {p: os.lstat(p).st_file_attributes for p in files}
        if not all(a & 0x400000 for a in attrs.values()):
            return 'FAIL', f'준비: 온라인 전용 표시가 없습니다 {[hex(a) for a in attrs.values()]}', []

        large = {x['path'].lower() for x in file_finder.scan_large_files(min_mb=500)}
        if local[0].lower() not in large:
            problems.append('대조군: 로컬 대용량 파일이 대용량 검사에 나오지 않았습니다(검사가 그 폴더를 보지 않음)')
        if large & {p.lower() for p in files}:
            problems.append('온라인 전용 파일이 대용량 목록에 나왔습니다')
        dups = {x['path'].lower() for x in file_finder.scan_duplicates()}
        if not {p.lower() for p in local[1:]} <= dups:
            problems.append('대조군: 내용이 같은 로컬 파일이 중복 검사에 나오지 않았습니다')
        if dups & {p.lower() for p in files}:
            problems.append('온라인 전용 파일이 중복 목록에 나왔습니다')
        r = file_finder.delete_files([files[0]])
        if r.get('deleted') or not os.path.exists(files[0]):
            problems.append(f'온라인 전용 파일을 지웠습니다(클라우드 원본이 지워짐): {r}')
        if cloud.fetches:
            problems.append(f'검사·삭제가 내려받기를 {len(cloud.fetches)}번 일으켰습니다')
        if not all(os.lstat(p).st_file_attributes & 0x400000 for p in files):
            problems.append('검사 뒤 온라인 전용 파일이 내려받아진 상태로 바뀌었습니다')

        # 대조군: 내용을 읽으면 내려받기 요청이 실제로 잡혀야 한다(위의 '0번' 이 의미가 있다는 증거)
        before = len(cloud.fetches)

        def read_one():
            try:
                with open(files[1], 'rb') as f:
                    f.read(1)
            except OSError:
                pass                                       # 공급자가 답하지 않아 실패한다(정상)
        threading.Thread(target=read_one, daemon=True).start()
        _wait(lambda: len(cloud.fetches) > before, 15)
        if len(cloud.fetches) == before:
            problems.append('대조군: 파일을 읽어도 내려받기 요청이 잡히지 않았습니다(이 점검이 볼 수 없음)')
    finally:
        if cloud is not None:
            cloud.close()                                  # 읽던 스레드는 연결이 끊기면 실패로 끝난다
        for p in local:
            if os.path.exists(p):
                os.remove(p)                               # 이 점검이 만든 파일만 지운다
        for d in (cloud_dir, local_dir):
            try:
                os.rmdir(d)
            except OSError:
                pass
    return verdict(problems, [])


@check('프로세스 우선순위: 바꾸고 원래대로, 시스템 프로세스는 거부')
def priority():
    import psutil
    from backend import process_boost
    ping = os.path.join(os.environ['SystemRoot'], 'System32', 'PING.EXE')
    pid = _orphan_ping('127.0.0.3')
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
        # 이름마다 한 번씩 시험한다. 예전에는 처음 찾은 하나(PID 가 작은 csrss)만 보고 끝내 explorer 는 시험하지 않았다
        protected = ('csrss.exe', 'explorer.exe', 'svchost.exe')
        tested = set()
        for proc in psutil.process_iter(['name']):
            name = (proc.info['name'] or '').lower()
            if name in protected and name not in tested:
                tested.add(name)
                if process_boost.set_priority(proc.pid, 'idle').get('ok'):
                    problems.append(f"{proc.info['name']} 의 우선순위를 바꿨습니다")
        if set(protected) - tested:
            problems.append(f"시스템 프로세스 거부를 시험하지 못했습니다: {sorted(set(protected) - tested)}")
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
        # 호스트에서 복사해 등록한 스토어 앱은 지우면 설치 파일이 사라져 왕복 점검에 쓸 수 없다
        if (r.get('isFramework') or r.get('nonRemovable') or not debloater._PKG_RE.match(name) or name in _STORE_APPS
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


# 호스트(start_sandbox_check.ps1)가 결과 폴더에 복사해 둔 스토어 앱을 샌드박스의 WindowsApps 로 옮겨 이 계정에 등록한다.
# 스토어 서명 그대로라 실제 PC 의 스토어 앱과 같다(서명 종류 Store, 개발자 모드 아님 — 샌드박스에서 확인).
# 프로비저닝되지 않고 이 계정에만 설치되므로 '스토어에서 받아 이 계정에만 설치한 앱' 의 처지다.
_PS_REGISTER_STAGED = r"""
$ErrorActionPreference = 'Continue'
$wa = $env:APEXSBX_WA
takeown.exe /f $wa /a | Out-Null
icacls.exe $wa /grant '*S-1-5-32-544:(OI)(CI)F' | Out-Null
# Windows PowerShell 5.1 의 ConvertFrom-Json 은 JSON 배열을 한 덩어리로 넘긴다. @() 로 감싸면 '배열 하나짜리 배열' 이
# 되어 항목 이름이 비었다(24회차). 파이프로 풀어 항목별로 받는다.
$pk = @(Get-Content -LiteralPath (Join-Path $env:APEXSBX_STAGE 'packages.json') -Raw | ConvertFrom-Json | ForEach-Object { $_ })
foreach ($p in $pk) {
  $dst = Join-Path $wa $p.full
  if (-not (Test-Path -LiteralPath $dst)) {
    robocopy.exe (Join-Path $env:APEXSBX_STAGE $p.full) $dst /E /R:0 /W:0 /NFL /NDL /NJH /NJS /NP | Out-Null
  }
}
$order = @($pk | Where-Object { $_.fw }) + @($pk | Where-Object { -not $_.fw -and $_.full -match '_x64__' })
foreach ($p in $order) {
  if (Get-AppxPackage -Name $p.name | Where-Object PackageFullName -eq $p.full) { continue }
  try {
    Add-AppxPackage -Register (Join-Path (Join-Path $wa $p.full) 'AppxManifest.xml') -DisableDevelopmentMode -ErrorAction Stop
    Write-Output "OK $($p.full)"
  } catch { Write-Output "FAIL $($p.full): $($_.Exception.Message.Split([Environment]::NewLine)[0])" }
}
"""
_STORE_APPS = ('Microsoft.BingNews', 'Microsoft.BingWeather', 'Microsoft.ZuneVideo', 'Microsoft.ZuneMusic')
_STAGED = {}


def _register_staged_appx():
    """(이 계정에 설치된 점검용 스토어 앱 이름 집합, 설명). 한 번만 등록한다."""
    if 'done' in _STAGED:
        return _STAGED['done']
    from backend import debloater
    stage = os.path.join(OUT, 'appx_stage')
    if not os.path.isfile(os.path.join(stage, 'packages.json')):
        _STAGED['done'] = (set(), '호스트 PC 에 디블로터 목록의 스토어 앱이 없어 복사하지 않았습니다')
        return _STAGED['done']
    env = dict(os.environ, APEXSBX_STAGE=stage, APEXSBX_WA=debloater._windowsapps_roots()[0])
    r = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', _PS_REGISTER_STAGED],
                       shell=False, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors='replace',
                       env=env, creationflags=CREATE_NO_WINDOW, timeout=900)
    ok, rows, err = debloater._query_packages(list(_STORE_APPS))
    names = {x['name'] for x in rows if not x.get('error')} if ok else set()
    _STAGED['done'] = (names, ((r.stdout or '') + (r.stderr or '')).strip()[-600:] or (err or ''))
    return _STAGED['done']


@check('디블로터 앱: 이 계정에서 제거 → 기록 → 되살리기')
def appx_round_trip():
    from backend import debloater
    _register_staged_appx()
    item, note = None, ''
    # 되살릴 수 있는(설치 파일이 남는) 목록 앱으로 왕복을 본다. 이 계정에만 설치된 앱은 지우면 설치 파일이
    # 사라져 되살릴 수 없다(그 경우는 다음 점검이 본다).
    st = debloater.get_install_state()
    for x in debloater.DEBLOAT_SAFE_LIST:
        if x['kind'] == 'appx' and st.get('items', {}).get(x['id']) == 'installed' \
                and st.get('restorable', {}).get(x['id']) is True:
            item = x
            break
    if not item:
        item, installed = _sandbox_appx_item()
        if not item:
            return 'SKIP', f'제거·되살리기에 쓸 앱이 없습니다. 설치된 앱: {installed}', []
        note = f"목록의 앱 중 되살릴 수 있는(Windows 기본 설치) 앱이 없어 {item['packages'][0]} 로 확인했습니다. "
    account = debloater._current_account()
    problems = []
    why = debloater._account_problem(account)
    if why:
        return 'FAIL', f'계정 판정이 제거를 막았습니다: {why}', []

    ok, rows, err = debloater._query_packages(item['packages'])
    if not ok:
        return 'FAIL', f'설치 상태 확인 실패: {err}', []
    original = {r['familyName'].lower(): r['fullName'] for r in rows if not r.get('error')}
    # 설치 파일이 남는 앱(Windows 이미지에 들어 있음)이라고 미리 알아봐야 한다. 화면이 '되살릴 수 있음' 으로 보여 준다
    kept = debloater._files_kept([r for r in rows if not r.get('error')])
    if not kept or not all(v is True for v in kept.values()):
        problems.append(f'되살릴 수 있는 앱인데 미리 알아본 결과가 다릅니다: {kept}')
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


@check('디블로터 앱(호스트의 실제 스토어 앱): 이 계정에만 설치된 앱은 되살릴 수 없다고 미리 알리고, 영화 및 TV 를 지워도 미디어 플레이어는 그대로')
def appx_store_only():
    from backend import debloater
    names, log = _register_staged_appx()
    need = {'Microsoft.ZuneVideo', 'Microsoft.ZuneMusic', 'Microsoft.BingNews'}
    if not need <= names:
        return 'SKIP', f'점검할 스토어 앱을 등록하지 못했습니다(등록됨 {sorted(names)}): {log}', []
    account = debloater._current_account()
    problems, removed_full = [], []
    try:
        st = debloater.get_install_state()
        for iid in ('bing', 'zune'):
            if st['items'].get(iid) != 'installed':
                problems.append(f"{iid}: 설치돼 있는데 {st['items'].get(iid)} 로 보입니다")
            if st.get('restorable', {}).get(iid) is not False:
                problems.append(f"{iid}: 이 계정에만 설치된 앱인데 되살릴 수 없다고 알리지 않습니다 "
                                f"(restorable={st.get('restorable', {}).get(iid)})")
        for iid in ('zune', 'bing'):
            item = debloater._ITEMS_BY_ID[iid]
            ok, rows, _ = debloater._query_packages(item['packages'])
            removed_full += [x['fullName'] for x in rows if not x.get('error')]
            status, detail = debloater._apply_appx_item(item, account)
            if status != 'removed':
                problems.append(f"{item['name']} 제거: {status} {detail}")
        ok, rows, err = debloater._query_packages(list(_STORE_APPS))
        now = {x['name'] for x in rows if not x.get('error')} if ok else None
        if now is None:
            problems.append(f'제거 뒤 설치 상태를 확인하지 못했습니다: {err}')
        else:
            if 'Microsoft.ZuneMusic' not in now:
                problems.append('영화 및 TV 를 지우자 미디어 플레이어(ZuneMusic)도 사라졌습니다')
            if now - {'Microsoft.ZuneMusic'}:
                problems.append(f'제거 뒤에도 남았습니다: {sorted(now - {"Microsoft.ZuneMusic"})}')

        # 미리 알린 대로 Windows 가 설치 파일을 지운다 → '제거한 앱' 은 설치 파일 없음, 되살리기는 Store 로 안내
        def recs():
            return [a for a in debloater.get_removed_apps() if a.get('fullName') in removed_full]
        _wait(lambda: not any(a.get('manifestFound') for a in recs()), 60)
        if len(recs()) != len(removed_full):
            problems.append(f'제거 기록이 {len(recs())}개입니다(지운 패키지 {len(removed_full)}개)')
        if any(a.get('manifestFound') for a in recs()):
            problems.append('설치 파일이 남았습니다 — 되살릴 수 없다고 알린 것이 틀렸습니다')
        r = debloater.restore_removed_apps(list(_STORE_APPS))
        if r.get('success') or not r.get('failed') \
                or not all('Microsoft Store' in str(f.get('reason')) for f in r['failed']):
            problems.append(f"되살리기 결과가 사실과 다릅니다: {r.get('message')} {r.get('failed')}")
        if r.get('restored'):
            problems.append(f"되살릴 수 없는 앱을 되살렸다고 했습니다: {r['restored']}")
    finally:
        if removed_full:
            debloater._forget_removed(removed_full)       # 이 점검이 남긴 기록만 뺀다(다음 점검에 섞이지 않게)
    return verdict(problems, [])


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
        if _machine_key_exists():
            problems.append(r'전부 되돌렸는데 PC 쪽 기록(HKLM\SOFTWARE\APEX CARE)이 남았습니다')
        return verdict(problems, diff(before, snapshot('uninstall_after')))
    finally:
        reg_del('HKCU', RUN_U, 'ApexSbxUninst')


def _machine_key_exists():
    from backend import machine_store
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, machine_store.KEY, 0,
                                       winreg.KEY_READ | winreg.KEY_WOW64_64KEY))
        return True
    except FileNotFoundError:
        return False


@check('저널: 예전 계정 저널은 관리자만 쓰는 PC 저널로 한 번 옮기고, 그 뒤 계정 파일에 써 넣은 PC 쪽 기록은 쓰지 않음')
def journal_location():
    from backend import machine_store, system_state as ss
    key = r'SOFTWARE\ApexSbxJournal'
    evil = 'ApexSbxEvil'
    before = snapshot('journal_before')
    problems = []

    def write_account_file(entries):
        os.makedirs(ss.APPDATA_DIR, exist_ok=True)
        with open(ss.JOURNAL_PATH, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'entries': entries}, f)

    def entry(path, name, value, vtype):
        return {'kind': 'registry', 'group': 'sbx_journal', 'hive': 'HKLM', 'path': path, 'name': name,
                'existed': True, 'value': value, 'type': vtype, 'created_keys': []}

    def machine_entries():
        try:
            return (machine_store.read('Journal') or {}).get('entries', {})
        except machine_store.Unreadable as e:
            problems.append(f'PC 저널을 읽지 못했습니다: {e}')
            return {}

    try:
        # 예전 버전: 원래 7 인 값을 1 로 바꾸고 계정 파일에 기록해 두었다
        reg_set('HKLM', key, 'Tuned', 1, winreg.REG_DWORD)
        legacy_key = f'reg:HKLM\\{key}\\Tuned'
        write_account_file({legacy_key: entry(key, 'Tuned', 7, winreg.REG_DWORD)})
        if legacy_key not in ss.pending_changes():
            problems.append('예전 계정 저널의 기록을 이어 쓰지 못했습니다')
        if legacy_key not in machine_entries():
            problems.append('예전 기록이 PC 저널로 옮겨지지 않았습니다')
        with open(ss.JOURNAL_PATH, encoding='utf-8') as f:
            if legacy_key in json.load(f).get('entries', {}):
                problems.append('옮긴 기록이 계정 파일에 남았습니다')

        # 옮긴 뒤 일반 권한 프로그램이 계정 파일에 PC 쪽 기록을 써 넣는다
        evil_key = f'reg:HKLM\\{RUN_M}\\{evil}'
        write_account_file({evil_key: entry(RUN_M, evil, r'C:\Windows\System32\notepad.exe', winreg.REG_SZ)})
        if evil_key in ss.pending_changes():
            problems.append('옮긴 뒤 계정 파일에 써 넣은 PC 쪽 기록을 썼습니다')
        r = ss.restore_group('sbx_journal')
        if not r.get('ok'):
            problems.append(f"되돌리기 실패: {r.get('failed')}")
        if reg_get('HKLM', RUN_M, evil) is not None:
            problems.append('계정 파일에 써 넣은 값을 관리자 권한으로 HKLM 에 썼습니다')
        if reg_get('HKLM', key, 'Tuned') != 7:
            problems.append(f"예전 기록으로 되돌리지 못했습니다 ({reg_get('HKLM', key, 'Tuned')})")
    finally:
        reg_del('HKLM', RUN_M, evil)
        reg_del('HKLM', key, 'Tuned')
        try:
            winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, key, winreg.KEY_WOW64_64KEY, 0)
        except OSError:
            pass
        write_account_file({})
    return verdict(problems, diff(before, snapshot('journal_after')))


@check('제거 전 되돌리기: 로그아웃한 다른 계정이 끈 시작 프로그램을 그 계정의 레지스트리에서 되돌림')
def other_account_startup():
    """샌드박스에서만: 버리는 지역 계정과 프로필을 만들고, 그 계정의 NTUSER.DAT 에 '꺼짐' 표시를 써 둔 뒤
    제거 전 되돌리기(_revert_other_accounts)가 하이브를 올려 지우고 반드시 내리는지 본다."""
    import secrets
    from backend import uninstall_prep
    sysroot = os.environ.get('SystemRoot') or r'C:\Windows'
    net = os.path.join(sysroot, 'System32', 'net.exe')
    user = 'apexsbxkid'
    approved = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
    disabled = b'\x03\x00\x00\x00' + b'\x11' * 8
    problems, sid, home = [], None, None
    before = snapshot('other_account_before')

    def hive_value(ntuser):
        temp = 'APEXSBX_' + secrets.token_hex(4)
        uninstall_prep._load_hive(temp, ntuser)
        try:
            with winreg.OpenKey(winreg.HKEY_USERS, temp + '\\' + approved) as k:
                return winreg.QueryValueEx(k, 'ApexSbxKid')[0]
        except FileNotFoundError:
            return None
        finally:
            if not uninstall_prep._unload_hive(temp):
                problems.append(f'점검용으로 올린 {temp} 를 내리지 못했습니다')

    try:
        # 암호가 14자를 넘으면 net.exe 가 Y/N 을 물어 창 없이 실패한다('올바른 응답이 제공되지 않았습니다'). 14자로 맞춘다
        pw = 'Ax9!' + secrets.token_hex(5)
        r = subprocess.run([net, 'user', user, pw, '/add'], shell=False,
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
        if r.returncode != 0:
            return 'FAIL', f'점검용 계정을 만들지 못했습니다: {r.stderr.decode("cp949", "replace")[-200:]}', []
        ps = os.path.join(sysroot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        r = subprocess.run([ps, '-NoProfile', '-Command', f'(Get-LocalUser {user}).SID.Value'], shell=False,
                           capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=60)
        sid = (r.stdout or '').strip()
        buf = ctypes.create_unicode_buffer(260)
        ue = ctypes.WinDLL('userenv', use_last_error=True)
        ue.CreateProfile.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        hr = ue.CreateProfile(sid, user, buf, 260)
        home = buf.value
        ntuser = os.path.join(home, 'NTUSER.DAT') if home else ''
        if hr != 0 or not os.path.isfile(ntuser):
            return 'FAIL', f'점검용 프로필을 만들지 못했습니다 (CreateProfile 0x{hr & 0xFFFFFFFF:08X}, {home})', []
        if not uninstall_prep._enable_privileges('SeBackupPrivilege', 'SeRestorePrivilege'):
            return 'FAIL', '레지스트리 하이브를 올릴 권한을 켜지 못했습니다', []

        # 그 계정이 APEX CARE 로 시작 프로그램을 꺼 둔 상태: 하이브에 '꺼짐' 표시, 그 계정의 저널에 '원래 없었음'
        temp = 'APEXSBX_' + secrets.token_hex(4)
        uninstall_prep._load_hive(temp, ntuser)
        try:
            with winreg.CreateKeyEx(winreg.HKEY_USERS, temp + '\\' + approved, 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, 'ApexSbxKid', 0, winreg.REG_BINARY, disabled)
        finally:
            if not uninstall_prep._unload_hive(temp):
                problems.append('준비 중에 올린 하이브를 내리지 못했습니다')
        journal = os.path.join(home, 'AppData', 'Roaming', 'APEX_CARE_DATA', 'system_state.json')
        os.makedirs(os.path.dirname(journal), exist_ok=True)
        with open(journal, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'entries': {f'reg:HKCU\\{approved}\\ApexSbxKid': {
                'kind': 'registry', 'group': 'startup:HKCU:ApexSbxKid', 'hive': 'HKCU', 'path': approved,
                'name': 'ApexSbxKid', 'existed': False, 'value': None, 'type': 3, 'created_keys': []}}}, f)
        if hive_value(ntuser) != disabled:
            problems.append('준비: 그 계정 하이브에 꺼짐 표시가 써지지 않았습니다')

        steps = [x for x in uninstall_prep._revert_other_accounts() if user in x['name']]
        if not steps or not steps[0]['ok']:
            problems.append(f'되돌리기 결과: {steps}')
        if hive_value(ntuser) is not None:
            problems.append('되돌린 뒤에도 그 계정 하이브에 꺼짐 표시가 남았습니다')
        with open(journal, encoding='utf-8') as f:
            if json.load(f).get('entries'):
                problems.append('그 계정의 저널에 되돌린 기록이 남았습니다')
        left = _temp_hives()
        if left:
            problems.append(f'올린 하이브가 남았습니다: {left}')

        # 그 계정이 다시 로그인하면 자기 프로필로 열려야 한다. 하이브를 내리지 못했거나 망가뜨렸으면 Windows 가
        # 임시 프로필(C:\Users\TEMP)로 연다(점검표 13-7 의 '임시 프로필로 열리지 않는다').
        seen = r'C:\Users\Public\apexsbx_profile.txt'
        if os.path.exists(seen):
            os.remove(seen)
        cmd = os.path.join(sysroot, 'System32', 'cmd.exe')
        _, why = _run_as(user, pw, cmd, f'/c echo %USERPROFILE%> {seen}', wait=True)
        try:
            with open(seen, encoding='mbcs', errors='replace') as f:
                opened = f.read().strip()
        except OSError:
            opened = None
        if not opened:
            problems.append(f'되돌린 뒤 그 계정으로 로그온하지 못했습니다: {why}')
        elif os.path.normcase(opened) != os.path.normcase(home):
            problems.append(f'되돌린 뒤 그 계정이 자기 프로필이 아닌 {opened} 로 열렸습니다(임시 프로필)')
    finally:
        if sid:
            _wait(lambda: not _hku_loaded(sid), 60)          # 로그온으로 올라온 프로필이 내려가야 지울 수 있다
            try:
                ue = ctypes.WinDLL('userenv', use_last_error=True)
                ue.DeleteProfileW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
                ue.DeleteProfileW(sid, None, None)
            except Exception as e:
                problems.append(f'점검용 프로필을 지우지 못했습니다: {e}')
        subprocess.run([net, 'user', user, '/delete'], shell=False, capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=60)
    return verdict(problems, diff(before, snapshot('other_account_after')))


def _temp_hives():
    """HKU 에 올라와 있는 이 앱·점검의 임시 하이브 이름들"""
    left, i = [], 0
    while True:
        try:
            n = winreg.EnumKey(winreg.HKEY_USERS, i)
        except OSError:
            break
        if n.upper().startswith(('APEXCARE_', 'APEXSBX_')):
            left.append(n)
        i += 1
    return left


def _hku_loaded(sid):
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_USERS, sid))
        return True
    except OSError:
        return False


# 다른 계정으로 프로그램 하나를 띄운다(보조 로그온, 프로필 로드). 그동안 그 계정의 레지스트리가 HKU\<SID> 에 올라와
# 빠른 사용자 전환으로 로그인해 있는 것과 같은 처지가 된다. 암호는 명령줄이 아니라 환경 변수로 넘긴다.
_PS_RUN_AS = (
    "$p = ConvertTo-SecureString $env:APEXSBX_PW -AsPlainText -Force; "
    "$c = New-Object System.Management.Automation.PSCredential($env:APEXSBX_USER, $p); "
    "$a = @{ FilePath = $env:APEXSBX_EXE; ArgumentList = $env:APEXSBX_ARGS; Credential = $c; LoadUserProfile = $true; "
    "WorkingDirectory = $env:APEXSBX_DIR; WindowStyle = 'Hidden'; PassThru = $true }; "
    "if ($env:APEXSBX_WAIT -eq '1') { $a.Wait = $true }; "
    "(Start-Process @a).Id | Set-Content -LiteralPath $env:APEXSBX_OUT -Encoding ascii"
)


def _run_as(user, pw, exe, args, wait=False):
    """다른 계정으로 프로그램을 띄운다(그 계정의 프로필을 올린다). (PID|None, 실패 설명)

    출력을 파이프로 받지 않는다. 그 계정으로 띄운 프로그램이 PowerShell 의 출력 파이프를 물려받아 붙들고 있어,
    파이프로 받으면 그 프로그램이 끝날 때까지 기다렸다(22회차 샌드박스에서 ping -t 로 멈춤). PID 는 파일로 받는다.
    """
    system32 = os.path.join(os.environ.get('SystemRoot') or r'C:\Windows', 'System32')
    ps = os.path.join(system32, 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    pid_file = os.path.join(OUT, f'runas_{user}_pid.txt')
    err_file = os.path.join(OUT, f'runas_{user}.log')
    if os.path.exists(pid_file):
        os.remove(pid_file)
    env = dict(os.environ, APEXSBX_PW=pw, APEXSBX_USER=user, APEXSBX_EXE=exe, APEXSBX_ARGS=args,
               APEXSBX_DIR=system32, APEXSBX_OUT=pid_file, APEXSBX_WAIT='1' if wait else '0')
    with open(err_file, 'w', encoding='utf-8') as log:
        subprocess.run([ps, '-NoProfile', '-Command', _PS_RUN_AS], shell=False, stdin=subprocess.DEVNULL,
                       stdout=log, stderr=log, env=env, cwd=system32, creationflags=CREATE_NO_WINDOW,
                       timeout=180)
    try:
        with open(pid_file, encoding='ascii') as f:
            return int(f.read().strip()), ''
    except (OSError, ValueError):
        with open(err_file, encoding='utf-8', errors='replace') as f:
            return None, f.read()[-300:]


@check('제거 전 되돌리기: 로그인해 있는 다른 계정(빠른 사용자 전환)이 끈 시작 프로그램을 그 계정의 레지스트리에서 되돌림')
def other_account_signed_in():
    """샌드박스에서만: 버리는 지역 계정으로 프로그램을 띄워 그 계정의 하이브가 올라온 상태에서, 제거 전 되돌리기가
    올라온 하이브(HKU\\<SID>)를 그대로 고치는지(파일을 따로 올리지 않는지) 본다."""
    import secrets
    from backend import uninstall_prep
    sysroot = os.environ.get('SystemRoot') or r'C:\Windows'
    system32 = os.path.join(sysroot, 'System32')
    net = os.path.join(system32, 'net.exe')
    ps = os.path.join(system32, 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    user = 'apexsbxon'
    pw = 'Ax9!' + secrets.token_hex(5)            # 14자 이하(넘으면 net.exe 가 Y/N 을 묻는다)
    approved = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
    disabled = b'\x03\x00\x00\x00' + b'\x22' * 8
    problems, sid, pid, created = [], None, None, False
    before = snapshot('signed_in_before')

    def value_now():
        try:
            with winreg.OpenKey(winreg.HKEY_USERS, sid + '\\' + approved) as k:
                return winreg.QueryValueEx(k, 'ApexSbxOn')[0]
        except FileNotFoundError:
            return None

    try:
        r = subprocess.run([net, 'user', user, pw, '/add'], shell=False,
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
        if r.returncode != 0:
            return 'FAIL', f'점검용 계정을 만들지 못했습니다: {r.stderr.decode("cp949", "replace")[-200:]}', []
        created = True
        r = subprocess.run([ps, '-NoProfile', '-Command', f'(Get-LocalUser {user}).SID.Value'], shell=False,
                           capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=60)
        sid = (r.stdout or '').strip()
        pid, why = _run_as(user, pw, os.path.join(system32, 'PING.EXE'), '-t 127.0.0.6')
        if not pid:
            return 'FAIL', f'그 계정으로 프로그램을 띄우지 못했습니다: {why}', []
        if not sid or not _wait(lambda: _hku_loaded(sid), 60):
            return 'FAIL', f'그 계정의 레지스트리가 올라오지 않았습니다 (SID {sid!r})', []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList' + '\\' + sid) as k:
            home = os.path.expandvars(winreg.QueryValueEx(k, 'ProfileImagePath')[0])

        # 그 계정이 APEX CARE 로 시작 프로그램을 꺼 둔 상태: 올라온 하이브에 '꺼짐' 표시, 그 계정의 저널에 '원래 없었음'
        with winreg.CreateKeyEx(winreg.HKEY_USERS, sid + '\\' + approved, 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, 'ApexSbxOn', 0, winreg.REG_BINARY, disabled)
        journal = os.path.join(home, 'AppData', 'Roaming', 'APEX_CARE_DATA', 'system_state.json')
        os.makedirs(os.path.dirname(journal), exist_ok=True)
        with open(journal, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'entries': {f'reg:HKCU\\{approved}\\ApexSbxOn': {
                'kind': 'registry', 'group': 'startup:HKCU:ApexSbxOn', 'hive': 'HKCU', 'path': approved,
                'name': 'ApexSbxOn', 'existed': False, 'value': None, 'type': 3, 'created_keys': []}}}, f)
        if value_now() != disabled:
            problems.append('준비: 그 계정 레지스트리에 꺼짐 표시가 써지지 않았습니다')

        steps = [x for x in uninstall_prep._revert_other_accounts() if user in x['name']]
        if not steps or not steps[0]['ok']:
            problems.append(f'되돌리기 결과: {steps}')
        if value_now() is not None:
            problems.append('되돌린 뒤에도 그 계정 레지스트리에 꺼짐 표시가 남았습니다')
        with open(journal, encoding='utf-8') as f:
            if json.load(f).get('entries'):
                problems.append('그 계정의 저널에 되돌린 기록이 남았습니다')
        if not _hku_loaded(sid):
            problems.append('로그인해 있는 계정의 레지스트리가 내려갔습니다')
        left = _temp_hives()
        if left:
            problems.append(f'로그인해 있는데 레지스트리 파일을 따로 올렸습니다: {left}')
    finally:
        if pid:
            # 다른 계정의 프로세스라 taskkill 로 끝낸다
            subprocess.run([os.path.join(system32, 'taskkill.exe'), '/PID', str(pid), '/F'], shell=False,
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
        if sid:
            _wait(lambda: not _hku_loaded(sid), 60)          # 프로필이 내려가야 지울 수 있다
            try:
                ue = ctypes.WinDLL('userenv', use_last_error=True)
                ue.DeleteProfileW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
                ue.DeleteProfileW(sid, None, None)
            except Exception as e:
                problems.append(f'점검용 프로필을 지우지 못했습니다: {e}')
        if created:
            subprocess.run([net, 'user', user, '/delete'], shell=False, capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=60)
    return verdict(problems, diff(before, snapshot('signed_in_after')))


@check('PC 건강 진단: 디스크 상태·부팅 기록·배터리·보고서·네트워크 속도를 관리자 권한으로 읽고 아무것도 바꾸지 않음')
def health_read_only():
    from backend import health, system_monitor
    before = snapshot('health_before')
    problems, info = [], []
    r = health.disk_health()
    if not r['ok']:
        problems.append(f"디스크 상태를 읽지 못했습니다: {r.get('error')}")
    elif not r['disks']:
        # 샌드박스의 가상 디스크는 Windows 저장소 관리(Get-PhysicalDisk)에 보이지 않는다(26회차 확인).
        # 조회는 오류 없이 끝났고, 화면은 '알려 준 디스크가 없습니다' 로 보여 준다.
        info.append('샌드박스는 물리 디스크를 알려 주지 않아 디스크 값은 실제 PC 에서만 볼 수 있습니다')
    for d in r.get('disks', []):
        info.append(f"{d['name']}: {d['health']} 온도={d['temperatureC']} 수명={d['wearPct']} 시간={d['powerOnHours']}")
        if d['health'] not in ('정상', '주의', '위험', '알 수 없음'):
            problems.append(f'건강 상태 표시가 이상합니다: {d}')
    b = health.boot_history()
    if not b['ok']:
        problems.append(f"부팅 기록을 읽지 못했습니다: {b.get('error')}")
    info.append(f"부팅 기록 {len(b.get('boots', []))}건 {b.get('note') or ''}")
    bt = health.battery()
    if not bt['ok']:
        problems.append(f"배터리 정보를 읽지 못했습니다: {bt.get('error')}")
    info.append(f"배터리 {len(bt.get('batteries', []))}개")
    # 보고서: 저장 창 없이 내용만 만들어 본다(실제 값으로 만들다 멈추거나 오류 나지 않는지)
    from backend import report
    html = report.build_html(report.collect())
    if '<h1>PC 상태 보고서</h1>' not in html:
        problems.append('보고서 내용을 만들지 못했습니다')
    info.append(f'보고서 {len(html):,}자')
    system_monitor.net_rates()
    time.sleep(1.2)
    down, up = system_monitor.net_rates()
    if not (isinstance(down, (int, float)) and isinstance(up, (int, float)) and down >= 0 and up >= 0):
        problems.append(f'네트워크 속도를 재지 못했습니다: {down}, {up}')
    status, why, changes = verdict(problems, diff(before, snapshot('health_after')))
    return status, (why + ' ' + ' / '.join(info)).strip(), changes


@check('앱 아이콘 색: 진짜 창의 아이콘을 바꾸고, 기본으로 돌리면 처음 아이콘으로')
def window_icon_real():
    """샌드박스의 진짜 창(tkinter)에 WM_SETICON 을 걸어 본다. 이 앱의 창 대신 같은 Win32 창을 쓴다."""
    import tkinter
    from backend import window_icon
    root = tkinter.Tk()
    problems = []
    try:
        root.title('APEXSBX icon')
        root.update()
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        u = window_icon._user32()
        get = lambda which: u.SendMessageW(hwnd, window_icon._WM_GETICON, which, 0)   # noqa: E731
        first = (get(1), get(0))
        with open(os.path.join(REPO, 'public', 'icon.png'), 'rb') as f:
            png = f.read()
        if not window_icon.apply(hwnd, png):
            problems.append('PNG 로 창 아이콘을 바꾸지 못했습니다')
        changed = (get(1), get(0))
        if changed == first or not all(changed):
            problems.append(f'창 아이콘이 바뀌지 않았습니다: {first} → {changed}')
        if not window_icon.apply(hwnd, png) or (get(1), get(0)) == changed:
            problems.append('두 번째로 바꾸지 못했습니다(앞서 만든 아이콘을 지우고 새로 걸어야 한다)')
        window_icon.apply(hwnd, None)
        if (get(1), get(0)) != first:
            problems.append(f'기본으로 돌려도 처음 아이콘이 아닙니다: {first} → {(get(1), get(0))}')
    finally:
        root.destroy()
    return verdict(problems, [])


@check('복원 지점: 변경 전에 만들고, 만들었는지는 Windows 의 목록으로 확인한다(못 만들면 그 이유를 말한다)')
def restore_point_real():
    """진짜 Checkpoint-Computer 를 부른다. 샌드박스는 시스템 보호가 없을 수 있어 '못 만듦' 도 정상 결과다.
    확인하는 것: 멈추지 않고 끝나는지, '만들었음' 이라고 하면 실제로 목록에 새 지점이 있는지."""
    from backend import restore_point
    t0 = time.time()
    r = restore_point.before_change('샌드박스 점검')
    took = round(time.time() - t0, 1)
    problems = []
    if not isinstance(r, dict) or not r.get('message'):
        problems.append(f'결과 형식이 올바르지 않습니다: {r}')
        return verdict(problems, [])
    if r.get('created'):
        ps = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                             '@(Get-ComputerRestorePoint | Where-Object { $_.Description -like "APEX CARE: 샌드박스 점검*" }).Count'],
                            capture_output=True, text=True, errors='replace', timeout=120)
        if (ps.stdout or '').strip() in ('', '0'):
            problems.append(f"'만들었음' 이라고 했지만 목록에 없습니다: {ps.stdout!r} {ps.stderr[-200:]!r}")
    status, why, changes = verdict(problems, [])
    return status, (why + f" 결과: {r['message']} ({took}초)").strip(), changes


@check('앱 아이콘 색: 고정한 작업 표시줄 단추(바로 가기)만 바꾸고, 기본으로 돌리면 원래대로')
def pinned_icon_real():
    """샌드박스에 처음부터 고정된 Edge 를 'APEX CARE' 로 보고 바꿔 본다(점검에서는 exe 경로만 Edge 로 바꾼다).
    2026-10-04 실험: 바로 가기 아이콘을 바꾸고 알리면 작업 표시줄 단추가 곧바로 다시 그려졌다."""
    from backend import config_manager, shortcut_icon as si
    folder = si.pinned_dir()
    edge = os.path.join(folder, 'Microsoft Edge.lnk')
    if not os.path.exists(edge):
        return 'SKIP', f'고정된 Edge 바로 가기가 없습니다({folder})', []
    with si._Com():
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith('.lnk'))
        before = {n: si.read_link(os.path.join(folder, n)) for n in names}
    target = before['Microsoft Edge.lnk'][0]
    real_own = si._own_exe
    si._own_exe = lambda: target
    problems = []
    try:
        with open(os.path.join(REPO, 'public', 'icon-tile.png'), 'rb') as f:
            png = f.read()
        r = si.apply_pngs([png])
        if not r.get('success') or r.get('changed') != 1:
            problems.append(f'바꾸지 못했습니다: {r}')
        with si._Com():
            now = {n: si.read_link(os.path.join(folder, n)) for n in names}
        icon = now['Microsoft Edge.lnk'][1][0]
        if not (icon and os.path.basename(icon).startswith(si._PREFIX) and os.path.exists(icon)):
            problems.append(f'Edge 바로 가기 아이콘이 이 앱의 아이콘 파일이 아닙니다: {now["Microsoft Edge.lnk"]}')
        others = [n for n in names if n != 'Microsoft Edge.lnk' and now[n] != before[n]]
        if others:
            problems.append(f'다른 단추까지 바뀌었습니다: {others}')
        if now['Microsoft Edge.lnk'][0] != target:
            problems.append('바로 가기 대상이 바뀌었습니다')
        rec = config_manager.load_config().get(si.CONFIG_KEY) or {}
        if list(rec.get(edge) or []) != list(before['Microsoft Edge.lnk'][1]):
            problems.append(f'원래 아이콘 기록이 다릅니다: {rec}')
        r = si.restore()
        with si._Com():
            after = {n: si.read_link(os.path.join(folder, n)) for n in names}
        if not r.get('success') or after != before:
            problems.append(f'기본으로 돌려도 원래와 다릅니다: {r} {after.get("Microsoft Edge.lnk")}')
        if si.CONFIG_KEY in config_manager.load_config() or os.path.exists(icon or ''):
            problems.append('되돌린 뒤 기록이나 아이콘 파일이 남았습니다')
    finally:
        si._own_exe = real_own
        if si._records():
            si.restore()
    return verdict(problems, [])


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


def _icon_step(problems, what, title):
    """제목이 title 인 창에 앱 아이콘이 걸려 있는지(WM_GETICON). 없으면 작업 표시줄에 Windows 기본 아이콘이 보인다.
    아이콘이 없어도 설치·제거 점검은 계속한다(문제로만 남긴다)."""
    import ctypes.wintypes as wt
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u.SendMessageW.restype = ctypes.c_ssize_t
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title and u.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    u.EnumWindows(each, 0)
    icons = [(u.SendMessageW(h, 0x7F, 1, 0), u.SendMessageW(h, 0x7F, 0, 0)) for h in found]
    if not found:
        problems.append(f'{what}: 창을 찾지 못해 아이콘을 확인하지 못했습니다')
    elif not any(big and small for big, small in icons):
        problems.append(f'{what}: 창 아이콘이 없습니다(작업 표시줄에 Windows 기본 아이콘이 보임) {icons}')
    return True


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
    return os.path.join(os.environ.get('PUBLIC') or r'C:\Users\Public', 'Desktop', 'APEX CARE.lnk')


def _start_menu_shortcut():
    return os.path.join(os.environ.get('ProgramData') or r'C:\ProgramData',
                        'Microsoft', 'Windows', 'Start Menu', 'Programs', 'APEX CARE.lnk')


def _program_files_dir():
    return os.path.join(os.environ.get('ProgramW6432') or os.environ['ProgramFiles'], 'APEX CARE')


def _plant_legacy_install():
    """예전 버전(사용자 폴더 설치)을 흉내 낸다. 새 설치가 이것을 정리하는지 본다."""
    old = os.path.join(os.environ['LOCALAPPDATA'], 'APEX CARE')
    os.makedirs(old, exist_ok=True)
    for name in ('APEX CARE.exe', 'APEX CARE Uninstaller.exe'):
        with open(os.path.join(old, name), 'wb') as f:          # 내용은 상관없다(정리되는지만 본다)
            f.write(b'MZ placeholder')
    reg_set('HKCU', UNINSTALL_KEY, 'DisplayName', 'APEX CARE')
    reg_set('HKCU', UNINSTALL_KEY, 'InstallLocation', old)
    return old


@check('설치 마법사 → 제거 프로그램: 설치, 제거 전 되돌리기(빌드한 exe), 흔적 정리')
def install_uninstall():
    setup = os.path.join(DIST, f'APEX CARE Setup {_app_version()}.exe')
    if not os.path.isfile(setup):
        return 'SKIP', f'설치 파일이 없습니다: {setup} (build_all.bat 로 만든 뒤 다시 돌리세요)', []
    from backend import optimizer, perf_modes, uninstall_prep
    install_dir = _program_files_dir()
    app_exe = os.path.join(install_dir, 'APEX CARE.exe')
    uninst_exe = os.path.join(install_dir, 'APEX CARE Uninstaller.exe')
    if os.path.exists(install_dir) or reg_get('HKLM', UNINSTALL_KEY, 'DisplayName') is not None:
        return 'FAIL', '점검 전에 이미 설치돼 있습니다(샌드박스가 깨끗하지 않음)', []
    built = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(setup)))
    problems = []
    legacy_dir = _plant_legacy_install()

    # ── 설치: 사용권 동의 → 다음 → 다음(설치) → 완료 화면에서 '실행하기' 끄고 종료
    win = '설치 - APEX CARE'
    proc = subprocess.Popen([setup], shell=False, cwd=DIST)
    try:
        ok = (_ui_step(problems, '사용권 동의', win, 'select', '조항에 동의합니다', 90)
              and _icon_step(problems, '설치 마법사 창', win)
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
        'DisplayVersion': reg_get('HKLM', UNINSTALL_KEY, 'DisplayVersion'),
        'InstallLocation': reg_get('HKLM', UNINSTALL_KEY, 'InstallLocation'),
        'UninstallString': reg_get('HKLM', UNINSTALL_KEY, 'UninstallString'),
        'shortcut': os.path.exists(_desktop_shortcut()),
        'startMenu': os.path.exists(_start_menu_shortcut()),
    }
    # 예전 버전의 사용자 폴더 설치는 정리됐어야 한다(그 exe 가 바꿔치기 대상으로 남지 않게)
    if os.path.exists(os.path.join(legacy_dir, 'APEX CARE.exe')) or os.path.isdir(legacy_dir):
        problems.append(f'예전 사용자 폴더 설치가 남았습니다: {legacy_dir}')
    if reg_get('HKCU', UNINSTALL_KEY, 'DisplayName') is not None:
        problems.append('예전 버전의 프로그램 목록 항목(HKCU)이 남았습니다')
    if not (installed['shortcut'] and installed['startMenu']):
        problems.append(f'모든 사용자용 바로 가기가 없습니다: {installed}')
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
            if (_ui_step(problems, '삭제 확인 창', 'APEX CARE 삭제', 'wait', r'^(Yes|예)', 60)
                    and _icon_step(problems, '제거 프로그램의 확인 창', 'APEX CARE 삭제')
                    and _ui_step(problems, '삭제 확인', 'APEX CARE 삭제', 'click', r'^(Yes|예)', 10)):
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
                     and reg_get('HKLM', UNINSTALL_KEY, 'DisplayName') is None, 90)
        # 결과 창(모든 에디션에서 뜨는 PowerShell 메시지 상자)이 떠야 한다. 예전 'msg *' 는 Home 에 없었다.
        if gone:
            if _ui_step(problems, "제거 완료 안내 창", 'APEX CARE', 'wait', '제거되었습니다', 60):
                # 메시지 상자의 '확인' 은 UI Automation 에 Pane 으로 보여 누를 수 없다. 사용자가 확인을 누른 것처럼
                # 그 창을 띄운 PowerShell(배치가 띄운 것)만 끝낸다. 그래야 배치가 이어서 자기 폴더를 지운다.
                import psutil
                for p in psutil.process_iter(['name', 'cmdline']):
                    try:
                        cmd = ' '.join(p.info['cmdline'] or [])
                        if (p.info['name'] or '').lower() == 'powershell.exe' and '-EncodedCommand' in cmd:
                            p.terminate()
                    except psutil.Error:
                        pass
        if not gone:
            import psutil
            left = sorted(os.listdir(install_dir)) if os.path.isdir(install_dir) else []
            alive = sorted({p.info['name'] for p in psutil.process_iter(['name'])
                            if (p.info['name'] or '').lower().startswith(('apex care', 'cmd.exe'))})
            problems.append(f"제거 뒤에도 남았습니다: 폴더={os.path.exists(install_dir)} 남은 파일={left} "
                            f"목록 키={reg_get('HKLM', UNINSTALL_KEY, 'DisplayName') is not None} 실행 중={alive}")
        if os.path.exists(_desktop_shortcut()) or os.path.exists(_start_menu_shortcut()):
            problems.append('바로 가기가 남았습니다')
        if _machine_key_exists():
            problems.append(r'PC 쪽 기록(HKLM\SOFTWARE\APEX CARE)이 남았습니다')
        # 정리 배치는 %SystemRoot%\Temp 아래 자기 폴더째 지워져야 한다
        temp_root = os.path.join(os.environ['SystemRoot'], 'Temp')
        def bat_dirs():
            return [n for n in os.listdir(temp_root) if n.startswith('apexcare-uninst-')]
        _wait(lambda: not bat_dirs(), 20)
        left_bat = bat_dirs()
        if left_bat:
            problems.append(f'정리 배치 폴더가 남았습니다: {left_bat}')
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


# ─────────────────────────────────────────────
# 재부팅 (점검표 3-4)
# ─────────────────────────────────────────────
# 샌드박스는 안에서 다시 시작해도 상태가 남고, 로그온 명령(run_in_sandbox.cmd)이 다시 돈다(샌드박스에서 확인).
# 모든 점검이 끝나면 게이밍 모드를 적용하고 상태를 결과 폴더에 적은 뒤 종료 코드 REBOOT_EXIT 로 끝난다.
# run_in_sandbox.cmd 가 그것을 보고 샌드박스를 다시 시작하고, 다시 돈 이 스크립트가 reboot_state.json 을 보고 확인을 이어 간다.

REBOOT_EXIT = 50
REBOOT_STATE = os.path.join(OUT, 'reboot_state.json')
REBOOT_NAME = '성능 모드: 게이밍 → 재부팅 → 값 유지, 앱을 다시 켜도 원래 값 기록 그대로, 표준으로 되돌리면 처음과 같음'


def _boot_epoch():
    k = ctypes.windll.kernel32
    k.GetTickCount64.restype = ctypes.c_uint64
    return time.time() - k.GetTickCount64() / 1000


def _originals():
    """PC 저널의 원래 값 기록(저장 시각 같은 부가 정보는 뺀다)"""
    from backend import machine_store, system_state as ss
    out = {}
    for k, e in ((machine_store.read('Journal') or {}).get('entries', {}) or {}).items():
        out[k] = {f: e.get(f) for f in ('kind',) + ss._ORIGINAL_FIELDS.get(e.get('kind'), ())}
    return json.loads(json.dumps(out))


def reboot_before():
    """재부팅 전 준비. 준비했으면 True(그 뒤 재부팅). 실패는 결과에 남긴다."""
    from backend import perf_modes, system_state as ss
    t0 = time.time()
    try:
        before = snapshot('reboot_before')
        r = perf_modes.apply_mode('gaming')
        if not r.get('success'):
            perf_modes.apply_mode('standard')
            raise RuntimeError(f"게이밍 적용 실패: {r.get('message')}")
        bad = _expect_gaming()
        if bad:
            perf_modes.apply_mode('standard')
            raise RuntimeError('; '.join(bad))
        with open(REBOOT_STATE, 'w', encoding='utf-8') as f:
            json.dump({'boot': _boot_epoch(), 'plan': ss.active_plan_guid(), 'originals': _originals(),
                       'snap': before, 'seconds': round(time.time() - t0, 1)}, f, ensure_ascii=False)
        print('[REBOOT] 게이밍 모드를 적용했습니다. 샌드박스를 다시 시작합니다.', flush=True)
        return True
    except Exception:
        RESULTS.append({'name': REBOOT_NAME, 'status': 'FAIL', 'detail': traceback.format_exc(limit=6),
                        'diff': [], 'seconds': round(time.time() - t0, 1)})
        return False


def reboot_after(state):
    from backend import config_manager, perf_modes, system_state as ss
    t0 = time.time()
    problems, changes = [], []
    try:
        if abs(_boot_epoch() - state['boot']) < 5:
            problems.append('샌드박스가 다시 시작되지 않았습니다(부팅 시각이 같음)')

        def same_as_before(when):
            if ss.active_plan_guid() != state['plan']:
                problems.append(f"{when}: 활성 전원 플랜이 바뀌었습니다 ({ss.active_plan_guid()} ≠ {state['plan']})")
            problems.extend(f'{when}: {p}' for p in _expect_gaming())
            if config_manager.get_optimization_mode() != 'gaming':
                problems.append(f"{when}: 저장된 모드가 {config_manager.get_optimization_mode()} 입니다")
            if _originals() != state['originals']:
                problems.append(f'{when}: PC 저널의 원래 값 기록이 바뀌었습니다(되돌리면 원래대로 가지 않음)')

        same_as_before('재부팅 직후(앱 실행 전)')
        # 앱을 켠다(저장된 모드를 다시 적용한다). 원래 값을 게이밍 값으로 덮어쓰면 안 된다
        env = dict(os.environ, PYTHONUTF8='1')
        r = subprocess.run([sys.executable, '-c', _RESTART_CHILD, REPO], shell=False, capture_output=True,
                           env=env, cwd=REPO, creationflags=CREATE_NO_WINDOW, timeout=300)
        if r.returncode != 0:
            problems.append(f'앱 시작 실패 {r.returncode}: {r.stderr.decode("utf-8", "replace")[-300:]}')
        same_as_before('재부팅 뒤 앱을 켠 다음')

        r = perf_modes.apply_mode('standard')
        if not r.get('success'):
            problems.append(f"표준 되돌리기: {r.get('message')}")
        changes = diff(state['snap'], snapshot('reboot_after'))
    except Exception:
        problems.append(traceback.format_exc(limit=6))
    status, detail, changes = verdict(problems, changes)
    RESULTS.append({'name': REBOOT_NAME, 'status': status, 'detail': detail, 'diff': changes[:60],
                    'seconds': round(state.get('seconds', 0) + time.time() - t0, 1)})
    print(f"[{status}] {REBOOT_NAME} ({RESULTS[-1]['seconds']}s) {detail.splitlines()[0] if detail else ''}", flush=True)


def main():
    refuse_outside_sandbox()
    sys.path.insert(0, REPO)
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(REBOOT_STATE):
        # 재부팅 뒤 다시 불렸다. 지난 결과에 재부팅 점검만 더한다. 상태 파일은 먼저 지운다(다시 돌아도 반복하지 않게).
        with open(REBOOT_STATE, encoding='utf-8') as f:
            state = json.load(f)
        os.remove(REBOOT_STATE)
        with open(os.path.join(OUT, 'report.json'), encoding='utf-8') as f:
            prev = json.load(f)
        RESULTS.extend(prev.get('results', []))
        reboot_after(state)
        write_report(prev.get('started', ''))
        return 1 if any(r['status'] == 'FAIL' for r in RESULTS) else 0
    started = time.strftime('%Y-%m-%d %H:%M:%S')
    for run in CHECKS:
        run()
        write_report(started)                      # 중간에 멈춰도 여기까지의 결과는 남는다
    if reboot_before():
        write_report(started)
        return REBOOT_EXIT
    write_report(started)
    return 1 if any(r['status'] == 'FAIL' for r in RESULTS) else 0


if __name__ == '__main__':
    sys.exit(main())
