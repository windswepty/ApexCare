"""
APEX CARE — 프로세스 우선순위 조정과 '원래대로' 복구.

기존 game_booster 의 문제:

1. 복구가 원래 값이 아니라 NORMAL 로 되돌렸다.
   _restore_processes 는 현재 우선순위가 IDLE 일 때만 NORMAL 로 바꿨다.
   원래 BELOW_NORMAL 로 돌던 백그라운드 작업이나, HIGH 로 돌던 오디오 앱은
   복구 후 엉뚱한 우선순위를 갖게 된다. 게다가 다른 프로그램이 그 사이
   우선순위를 바꿨으면 복구 자체가 건너뛰어졌다.
   → 바꾸기 전 값을 기록하고 정확히 그 값으로 되돌린다.

2. 에코 억제가 포그라운드 외 '모든' 사용자 프로세스를 IDLE 로 내렸다.
   변수 이름은 current_heavy_pids 인데 CPU 임계값이 전혀 없었다.
   백신, 백업, 음악 재생, 컴파일, 영상 렌더링, 다운로드가 전부 굼떠진다.
   → 실제로 CPU 를 쓰고 있는 프로세스만, 그것도 임계값을 넘을 때만 건드린다.

3. 보호 목록이 약했다. process_guard 에 37개짜리 목록이 있는데
   에코 억제는 그걸 쓰지 않고 자체 17개 + 인라인 10개만 봤다.
   → 모든 판단을 process_guard.check_controllable 단일 관문으로 보낸다.
"""

import logging

import psutil

from backend import process_guard

log = logging.getLogger('ProcessBoost')

# 이름만으로는 process_guard 가 막지 않지만, 우선순위를 낮추면
# 사용자가 바로 불편을 겪는 부류. 에코 억제 대상에서 제외한다.
NEVER_THROTTLE = {
    # 보안 — 실시간 검사가 느려지면 보호 수준이 떨어진다
    'avp.exe', 'avgnt.exe', 'avguard.exe', 'ashdisp.exe', 'avastsvc.exe',
    'mbam.exe', 'mbamservice.exe', 'nortonsecurity.exe', 'ns.exe',
    'bdagent.exe', 'vsserv.exe', 'ekrn.exe', 'egui.exe',
    'v3svc.exe', 'v3main.exe', 'ahnsd.exe',          # 국내 백신(V3)
    'alyac.exe', 'ayagent.aye', 'ayrtsrv.aye',       # 알약
    # 소리 — 우선순위를 낮추면 끊긴다
    'audiodg.exe', 'rtkngui64.exe', 'ravcpl64.exe', 'nahimicservice.exe',
    'voicemeeter.exe', 'equalizerapo.exe',
    # 통화·화면공유 — 끊기면 즉시 체감된다
    'discord.exe', 'zoom.exe', 'teams.exe', 'ms-teams.exe', 'skype.exe',
    'obs64.exe', 'obs32.exe', 'streamlabs obs.exe',
    # 백업·동기화 — 중단되면 데이터 정합성 문제가 생길 수 있다
    'onedrive.exe', 'dropbox.exe', 'googledrivesync.exe', 'googledrivefs.exe',
    'megasync.exe', 'nextcloud.exe', 'backupexec.exe', 'acronis*',
    # 입력기 — 한글 입력이 끊기면 아무것도 못 한다
    'imekrmig.exe', 'chsime.exe', 'tsf3g.exe',
}

# 우선순위 이름 ↔ psutil 상수
PRIORITY_BY_NAME = {
    'idle': psutil.IDLE_PRIORITY_CLASS,
    'below_normal': psutil.BELOW_NORMAL_PRIORITY_CLASS,
    'normal': psutil.NORMAL_PRIORITY_CLASS,
    'above_normal': psutil.ABOVE_NORMAL_PRIORITY_CLASS,
    'high': psutil.HIGH_PRIORITY_CLASS,
}
NAME_BY_PRIORITY = {v: k for k, v in PRIORITY_BY_NAME.items()}

# pid -> {'priority': 원래 우선순위, 'name': 프로세스명, 'created': 생성 시각, 'owner': 누가 바꿨나}
#
# created: PID 는 재사용된다. 게임이 끝나고 그 PID 를 다른 프로세스가 물려받으면
#   '원래대로' 가 엉뚱한 프로세스의 우선순위를 바꾼다. 생성 시각이 같을 때만 같은 프로세스다.
# owner: 'user'(게이밍 탭에서 직접), 'boost'(게임 부스트), 'eco'(에코 억제).
#   게임이 끝났다고 사용자가 직접 바꾼 것까지 되돌리면 안 된다.
_original = {}


def _never_throttle(name):
    n = (name or '').lower()
    if n in NEVER_THROTTLE:
        return True
    # acronis* 같은 접두사 항목
    return any(p.endswith('*') and n.startswith(p[:-1]) for p in NEVER_THROTTLE)


def _same_process(pid, entry):
    try:
        return psutil.Process(pid).create_time() == entry.get('created')
    except Exception:
        return False


def snapshot(pid, name=None, owner='user'):
    """바꾸기 전 원래 우선순위를 기록한다. 이미 기록돼 있으면 덮어쓰지 않는다.

    덮어쓰면 우리가 설정한 IDLE 이 '원래 값'으로 굳어 영영 복구할 수 없다.
    system_state 가 레지스트리에 대해 하는 것과 같은 원칙이다.
    기록이 있어도 PID 가 재사용된 다른 프로세스라면 옛 기록을 버리고 새로 적는다.
    """
    entry = _original.get(pid)
    if entry is not None:
        if _same_process(pid, entry):
            if owner == 'user':
                entry['owner'] = 'user'      # 사용자가 직접 손댔다. 자동 복구 대상에서 뺀다.
            return True
        _original.pop(pid, None)
    try:
        p = psutil.Process(pid)
        _original[pid] = {'priority': p.nice(), 'name': name or p.name(),
                          'created': p.create_time(), 'owner': owner}
        return True
    except Exception:
        return False


def owner_of(pid):
    entry = _original.get(pid)
    return entry.get('owner') if entry else None


def set_priority(pid, priority_name, reason='', owner='user'):
    """우선순위를 바꾼다. process_guard 를 반드시 통과해야 한다.

    원래 값을 기록하지 못하면 바꾸지 않는다. 되돌릴 수 없는 변경이 된다.
    """
    if priority_name not in PRIORITY_BY_NAME:
        return {'ok': False, 'reason': f'알 수 없는 우선순위: {priority_name}'}

    ok, safe_pid, proc_name, err = process_guard.check_controllable(pid, action='priority')
    if not ok:
        return {'ok': False, 'reason': err, 'name': proc_name}

    if not snapshot(safe_pid, proc_name, owner):
        return {'ok': False, 'name': proc_name,
                'reason': '원래 우선순위를 읽지 못해 바꾸지 않았습니다.'}
    target = PRIORITY_BY_NAME[priority_name]
    try:
        psutil.Process(safe_pid).nice(target)
    except psutil.AccessDenied:
        return {'ok': False, 'name': proc_name,
                'reason': f"'{proc_name}' 의 우선순위를 바꿀 권한이 없습니다. "
                          "관리자 권한으로 실행하면 가능할 수 있습니다."}
    except psutil.NoSuchProcess:
        _original.pop(safe_pid, None)
        return {'ok': False, 'name': proc_name, 'reason': '프로세스가 이미 종료되었습니다.'}
    except Exception as e:
        return {'ok': False, 'name': proc_name, 'reason': str(e)}

    # 반환값을 믿지 않고 되읽어 확인한다
    try:
        after = psutil.Process(safe_pid).nice()
    except Exception:
        after = None
    if after != target:
        return {'ok': False, 'name': proc_name,
                'reason': f'설정 후 확인에 실패했습니다 (현재 {NAME_BY_PRIORITY.get(after, after)})'}

    log.info(f"우선순위 변경: {proc_name}({safe_pid}) -> {priority_name} {reason}")
    return {'ok': True, 'name': proc_name, 'priority': priority_name}


def restore(pid):
    """기록해둔 원래 우선순위로 되돌린다."""
    entry = _original.pop(pid, None)
    if not entry:
        return {'ok': False, 'reason': '기록된 원래 값이 없습니다.'}
    if not _same_process(pid, entry):
        # 이미 끝났거나 PID 를 다른 프로세스가 물려받았다. 되돌릴 대상이 없다.
        return {'ok': True, 'name': entry['name'], 'reason': '프로세스가 이미 종료됨'}
    try:
        psutil.Process(pid).nice(entry['priority'])
        return {'ok': True, 'name': entry['name'],
                'priority': NAME_BY_PRIORITY.get(entry['priority'], entry['priority'])}
    except psutil.NoSuchProcess:
        return {'ok': True, 'name': entry['name'], 'reason': '프로세스가 이미 종료됨'}
    except Exception as e:
        # 복구에 실패하면 기록을 되살려 다음에 다시 시도할 수 있게 한다
        _original[pid] = entry
        return {'ok': False, 'name': entry['name'], 'reason': str(e)}


def restore_all():
    """조정했던 모든 프로세스를 원래 우선순위로 되돌린다."""
    results = [restore(pid) for pid in list(_original.keys())]
    ok = [r for r in results if r['ok']]
    failed = [r for r in results if not r['ok']]
    return {'ok': not failed, 'restored': len(ok), 'failed': failed}


def adjusted_count():
    return len(_original)


def _is_game(name):
    """실행 중인 게임인가. 게임은 어떤 경우에도 우선순위를 낮추면 안 된다.

    CPU 를 가장 많이 쓰는 프로세스가 대개 게임이므로, CPU 순으로 고르면
    게임이 1순위 억제 대상이 된다. 에코 모드가 게임을 느리게 만드는 셈이다.
    """
    try:
        from backend.game_booster import GAMES_LIST
        return (name or '').lower() in GAMES_LIST
    except Exception:
        return False


def find_throttle_candidates(foreground_pid, cpu_threshold=3.0, limit=40):
    """에코 모드에서 우선순위를 낮출 만한 프로세스를 고른다.

    예전에는 포그라운드가 아닌 모든 사용자 프로세스를 대상으로 삼았다.
    여기서는 '실제로 CPU 를 쓰고 있는' 것만 고른다. 유휴 상태인 앱의
    우선순위를 낮춰봐야 얻는 것은 없고, 그 앱이 깨어날 때 느려지기만 한다.
    """
    out = []
    for p in psutil.process_iter(['pid', 'name', 'username']):
        try:
            pid = p.info['pid']
            name = (p.info['name'] or '').lower()
            if pid == foreground_pid or not name:
                continue
            if _never_throttle(name) or _is_game(name):
                continue
            # 시스템 계정으로 도는 것은 건드리지 않는다
            user = p.info['username'] or ''
            if 'system' in user.lower() or 'service' in user.lower():
                continue
            # process_guard 가 막는 것은 애초에 후보가 아니다
            ok, _, _, _ = process_guard.check_controllable(pid, action='priority')
            if not ok:
                continue
            cpu = p.cpu_percent(None)      # 직전 호출 이후 평균
            if cpu < cpu_threshold:
                continue
            out.append({'pid': pid, 'name': p.info['name'], 'cpu': round(cpu, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    out.sort(key=lambda x: x['cpu'], reverse=True)
    return out[:limit]


def prime_cpu_measurement():
    """cpu_percent(None) 은 첫 호출에서 항상 0.0 을 돌려준다.

    이 함수를 한 번 돌려 기준점을 잡아두지 않으면 첫 순회에서 모든 프로세스가
    0% 로 보여 아무것도 선택되지 않거나, 반대로 임계값을 0 으로 두면
    전부 선택되는 문제가 생긴다.
    """
    for p in psutil.process_iter(['pid']):
        try:
            p.cpu_percent(None)
        except Exception:
            pass
