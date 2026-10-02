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

import json
import logging
import os
import tempfile
import threading
import time

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
    # 통화·메신저·화면공유 — 끊기면 즉시 체감된다(카카오톡 보이스톡·페이스톡 포함)
    'discord.exe', 'zoom.exe', 'teams.exe', 'ms-teams.exe', 'skype.exe',
    'kakaotalk.exe', 'line.exe', 'slack.exe', 'telegram.exe', 'whatsapp.exe',
    'webex.exe', 'ciscocollabhost.exe',
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
# ecoqos: 이 앱이 EcoQoS(효율 모드)를 건 프로세스. 되돌릴 때 시스템 관리로 돌려준다.
_original = {}
_state_lock = threading.RLock()

# 부스트·에코가 바꾼 것은 파일에도 남긴다. 앱이 비정상 종료되면 메모리 기록이 사라져, 낮춘 앱이
# IDLE·효율 모드로 남고 다시 켰을 때 그 IDLE 이 '원래 값' 으로 굳었다. 다음 실행 때 이 파일로 되돌린다.
_STATE_NAME = 'process_priority.json'


def _state_path():
    from backend import config_manager
    return os.path.join(config_manager.APPDATA_DIR, _STATE_NAME)


def _persist():
    """자동(owner boost·eco)으로 바꾼 기록만 파일에 쓴다. 실패해도 동작은 이어 간다(로그만)."""
    with _state_lock:
        data = {str(pid): e for pid, e in _original.items() if e.get('owner') in ('boost', 'eco')}
        tmp = None
        try:
            path = _state_path()
            if not data:
                if os.path.exists(path):
                    os.remove(path)          # 우리가 만든 기록 파일만 지운다
                return
            fd, tmp = tempfile.mkstemp(prefix='process_priority.', suffix='.tmp', dir=os.path.dirname(path))
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            os.replace(tmp, path)
            tmp = None
        except Exception as e:
            log.warning(f"우선순위 기록을 파일에 남기지 못했습니다: {e}")
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def recover_after_crash():
    """지난 실행이 비정상 종료돼 남은 자동 변경(부스트·에코)을 되돌린다. (되돌린 수, 실패 목록)

    같은 프로세스(생성 시각이 같음)일 때만 되돌린다. 이미 끝났거나 PID 가 재사용됐으면 건너뛴다.
    """
    path = _state_path()
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return 0, []
    except (OSError, ValueError) as e:
        return 0, [f'기록을 읽지 못했습니다: {e}']
    restored, failed = 0, []
    with _state_lock:
        for spid, entry in (data.items() if isinstance(data, dict) else []):
            try:
                pid = int(spid)
            except (TypeError, ValueError):
                continue
            if not isinstance(entry, dict) or pid in _original:
                continue
            bad = _invalid_recovery_entry(pid, entry)
            if bad:
                failed.append(f"{entry.get('name', pid) if isinstance(entry.get('name'), str) else pid}: {bad}")
                continue
            _original[pid] = entry
            r = restore(pid)
            if r['ok'] and not r.get('reason'):
                restored += 1
            elif not r['ok']:
                failed.append(f"{entry.get('name', pid)}: {r.get('reason', '실패')}")
        _persist()
    return restored, failed


def _invalid_recovery_entry(pid, entry):
    """복구 파일의 기록이 이 앱이 남긴 모양이 아니면 그 이유. 맞으면 None.

    그 파일은 같은 계정의 일반 권한 프로그램도 쓸 수 있다. 검증 없이 쓰면 관리자 권한으로 실시간(REALTIME)
    우선순위를 걸거나, 관문이 막는 시스템 프로세스(dwm·audiodg 등)를 IDLE 로 낮출 수 있었다.
    """
    if entry.get('owner') not in ('boost', 'eco'):
        return '기록 형식이 올바르지 않아 건너뛰었습니다'
    prio = entry.get('priority')
    if isinstance(prio, bool) or prio not in PRIORITY_BY_NAME.values():
        return '기록 형식이 올바르지 않아 건너뛰었습니다'
    created = entry.get('created')
    if isinstance(created, bool) or not isinstance(created, (int, float)):
        return '기록 형식이 올바르지 않아 건너뛰었습니다'
    ok, _, _, err = process_guard.check_controllable(pid, action='priority')
    if ok:
        return None
    try:
        psutil.Process(pid)
    except psutil.NoSuchProcess:
        return None         # 이미 끝났다. restore 가 '종료됨' 으로 정리한다
    except psutil.Error:
        pass
    return err or '건드릴 수 없는 프로세스라 건너뛰었습니다'


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
    반환: 'new'(이번에 기록함) · 'existing'(이미 있음) · None(읽지 못함)
    """
    entry = _original.get(pid)
    if entry is not None:
        if _same_process(pid, entry):
            if owner == 'user':
                entry['owner'] = 'user'      # 사용자가 직접 손댔다. 자동 복구 대상에서 뺀다.
            return 'existing'
        _original.pop(pid, None)
    try:
        p = psutil.Process(pid)
        _original[pid] = {'priority': p.nice(), 'name': name or p.name(),
                          'created': p.create_time(), 'owner': owner}
        return 'new'
    except Exception:
        return None


def owner_of(pid):
    entry = _original.get(pid)
    return entry.get('owner') if entry else None


def set_priority(pid, priority_name, reason='', owner='user', created=None):
    """우선순위를 바꾼다. process_guard 를 반드시 통과해야 한다.

    원래 값을 기록하지 못하면 바꾸지 않는다. 되돌릴 수 없는 변경이 된다.
    created: 화면이 목록에서 본 프로세스의 생성 시각. 주면 지금 그 PID 가 같은 프로세스일 때만 바꾼다.
    """
    if priority_name not in PRIORITY_BY_NAME:
        return {'ok': False, 'reason': f'알 수 없는 우선순위: {priority_name}'}

    ok, safe_pid, proc_name, err = process_guard.check_controllable(pid, action='priority')
    if not ok:
        return {'ok': False, 'reason': err, 'name': proc_name}
    if created is not None:
        # 목록을 본 뒤 그 프로세스가 끝나고 다른 프로그램이 같은 PID 를 받았으면 그 프로그램을 바꾸게 된다
        try:
            same = abs(psutil.Process(safe_pid).create_time() - float(created)) < 0.01
        except (TypeError, ValueError, psutil.Error):
            same = False
        if not same:
            return {'ok': False, 'name': proc_name,
                    'reason': '목록을 본 뒤 그 프로세스가 끝나 다른 프로그램이 같은 번호를 받았습니다. 목록을 새로 고쳐 주세요.'}

    with _state_lock:
        existing = _original.get(safe_pid)
        if (owner != 'user' and existing and existing.get('owner') == 'user'
                and _same_process(safe_pid, existing)):
            # 사용자가 게이밍 탭에서 직접 바꾼 프로세스다. 부스트·에코가 덮어쓰면 사용자의 선택이 사라지고,
            # 기록의 owner 가 'user' 라서 게임이 끝나도 되돌려지지 않았다.
            return {'ok': False, 'name': proc_name, 'reason': '사용자가 직접 바꾼 우선순위라 건드리지 않았습니다.'}
        made = snapshot(safe_pid, proc_name, owner)
        if not made:
            return {'ok': False, 'name': proc_name,
                    'reason': '원래 우선순위를 읽지 못해 바꾸지 않았습니다.'}

        def drop_new():
            # 이번 호출이 만든 기록은 바꾸지 못했으면 지운다. 남기면 '조정된 프로세스 1개' 가 계속 보이고
            # 되돌리기는 같은 이유로 늘 실패했다.
            if made == 'new':
                _original.pop(safe_pid, None)

        target = PRIORITY_BY_NAME[priority_name]
        try:
            psutil.Process(safe_pid).nice(target)
        except psutil.AccessDenied:
            drop_new()
            # 이 앱은 늘 관리자 권한으로 돈다. 그래도 거부되면 보호된 프로세스다.
            return {'ok': False, 'name': proc_name,
                    'reason': f"'{proc_name}' 은 보호된 프로세스라 Windows 가 우선순위 변경을 막았습니다."}
        except psutil.NoSuchProcess:
            _original.pop(safe_pid, None)
            return {'ok': False, 'name': proc_name, 'reason': '프로세스가 이미 종료되었습니다.'}
        except Exception as e:
            drop_new()
            return {'ok': False, 'name': proc_name, 'reason': str(e)}

        # 반환값을 믿지 않고 되읽어 확인한다
        try:
            after = psutil.Process(safe_pid).nice()
        except Exception:
            after = None
        if after != target:
            entry = _original.get(safe_pid)
            if made == 'new' and entry and after == entry.get('priority'):
                _original.pop(safe_pid, None)        # 아무것도 바뀌지 않았다
            return {'ok': False, 'name': proc_name,
                    'reason': f'설정 후 확인에 실패했습니다 (현재 {NAME_BY_PRIORITY.get(after, after)})'}
        entry = _original.get(safe_pid)
        if owner == 'user' and entry and entry.get('ecoqos'):
            # 부스트·에코가 낮추며 건 효율 모드(EcoQoS). 사용자가 직접 우선순위를 고르면 기록이 사용자 것이 되어
            # 게임이 끝나도 되돌리지 않으므로, 여기서 풀지 않으면 '높음' 을 골라도 효율 모드에 묶인 채 남았다.
            _release_ecoqos(safe_pid)
            entry.pop('ecoqos', None)
        _persist()

    log.info(f"우선순위 변경: {proc_name}({safe_pid}) -> {priority_name} {reason}")
    return {'ok': True, 'name': proc_name, 'priority': priority_name}


def mark_ecoqos(pid):
    """이 앱이 이 프로세스의 EcoQoS(효율 모드)를 바꿨다고 기록한다. 되돌릴 때 시스템 관리로 돌려준다."""
    with _state_lock:
        entry = _original.get(pid)
        if entry is not None:
            entry['ecoqos'] = True
            _persist()


def _release_ecoqos(pid):
    try:
        from backend import game_booster
        game_booster._set_process_power_throttling(pid, None)
    except Exception as e:
        log.debug(f"EcoQoS 되돌리기 실패 (PID {pid}): {e}")


def restore(pid):
    """기록해둔 원래 우선순위로 되돌린다. 이 앱이 건 EcoQoS 도 시스템 관리로 돌려준다.

    예전에는 우선순위만 되돌려, '되돌리기' 를 누른 뒤에도 그 앱이 끝날 때까지 효율 모드로 남았다.
    """
    with _state_lock:
        entry = _original.pop(pid, None)
        if not entry:
            return {'ok': False, 'reason': '기록된 원래 값이 없습니다.'}
        if not _same_process(pid, entry):
            # 이미 끝났거나 PID 를 다른 프로세스가 물려받았다. 되돌릴 대상이 없다(EcoQoS 도 건드리지 않는다).
            _persist()
            return {'ok': True, 'name': entry['name'], 'reason': '프로세스가 이미 종료됨'}
        try:
            psutil.Process(pid).nice(entry['priority'])
        except psutil.NoSuchProcess:
            _persist()
            return {'ok': True, 'name': entry['name'], 'reason': '프로세스가 이미 종료됨'}
        except psutil.AccessDenied:
            _original[pid] = entry          # 다시 시도할 수 있게 남긴다
            return {'ok': False, 'name': entry['name'],
                    'reason': '보호된 프로세스라 Windows 가 우선순위 변경을 막았습니다.'}
        except Exception as e:
            # 복구에 실패하면 기록을 되살려 다음에 다시 시도할 수 있게 한다
            _original[pid] = entry
            return {'ok': False, 'name': entry['name'], 'reason': str(e)}
        if entry.get('ecoqos'):
            _release_ecoqos(pid)
        _persist()
        return {'ok': True, 'name': entry['name'],
                'priority': NAME_BY_PRIORITY.get(entry['priority'], entry['priority'])}


def restore_all():
    """조정했던 모든 프로세스를 원래 우선순위로 되돌린다.

    이미 끝난 프로세스는 되돌린 수(restored)에 넣지 않고 gone 으로 따로 센다.
    예전에는 둘을 합쳐 'N개를 원래 우선순위로 되돌렸습니다' 라고 해 숫자가 부풀었다.
    """
    results = [restore(pid) for pid in list(_original.keys())]
    gone = [r for r in results if r['ok'] and r.get('reason')]
    ok = [r for r in results if r['ok'] and not r.get('reason')]
    failed = [r for r in results if not r['ok']]
    return {'ok': not failed, 'restored': len(ok), 'gone': len(gone), 'failed': failed}


def adjusted_count():
    """지금 실행 중이면서 우선순위를 바꿔 둔 프로세스 수. 끝난 프로세스의 기록은 정리한다.

    끝난 프로세스는 되돌릴 대상이 없다. 세면 복구 센터에 '조정된 프로세스 N개' 가 계속 남는다.
    """
    with _state_lock:
        dropped = False
        for pid, entry in list(_original.items()):
            if not _same_process(pid, entry):
                _original.pop(pid, None)
                dropped = True
        if dropped:
            _persist()
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


# 자체 CPU 표본. psutil 의 Process.cpu_percent 는 process_iter 가 캐시한 객체에 기준점을 두는데,
# 게이밍 화면의 프로세스 목록(system_monitor)도 같은 객체를 써서 그쪽이 부를 때마다 기준점이 바뀌었다.
# 그래서 몇 ms 짜리 구간으로 판정하기도 했다. 여기서는 따로 기록하고, 1초 이상 지난 구간만 쓴다.
_cpu_samples = {}          # pid -> (생성 시각, 누적 CPU 초, 잰 시각)
_MIN_SAMPLE_SEC = 1.0


def _now():
    return time.monotonic()


def sample_cpu(p):
    """직전 표본 이후 이 프로세스의 CPU 사용률. 작업 관리자와 같은 단위(전체 CPU 의 %).

    첫 표본이거나 1초가 안 지났으면 None(판정하지 않는다). 예전 기준은 코어 하나를 100% 로 보는 값이라,
    16스레드 PC 에서 작업 관리자 0.3% 인 앱도 '바쁜 앱' 으로 낮췄다.
    """
    pid = p.pid
    try:
        created = p.create_time()
        t = p.cpu_times()
    except Exception:
        _cpu_samples.pop(pid, None)
        return None
    total = t.user + t.system
    now = _now()
    prev = _cpu_samples.get(pid)
    if prev and prev[0] == created and now - prev[2] < _MIN_SAMPLE_SEC:
        return None                       # 구간이 너무 짧다. 기준점은 그대로 둔다
    _cpu_samples[pid] = (created, total, now)
    if not prev or prev[0] != created:
        return None
    cpus = psutil.cpu_count(logical=True) or 1
    return max(0.0, (total - prev[1]) / (now - prev[2]) / cpus * 100)


def foreground_group(fg_pid):
    """지금 쓰고 있는 창의 프로세스와 그 자식·같은 실행 파일 프로세스.

    브라우저·Electron 앱은 창을 가진 프로세스와 화면을 그리는 렌더러·GPU 프로세스가 따로다.
    창의 PID 하나만 빼면 지금 보고 있는 앱의 렌더러가 '바쁜 백그라운드 앱' 으로 낮춰졌다.
    """
    if not fg_pid:
        return set()
    group = {fg_pid}
    exe = ''
    try:
        fp = psutil.Process(fg_pid)
        group |= {c.pid for c in fp.children(recursive=True)}
        try:
            exe = (fp.exe() or '').lower()
        except Exception:
            exe = ''
    except Exception:
        return group
    if exe:
        for p in psutil.process_iter(['pid', 'exe']):
            try:
                if (p.info.get('exe') or '').lower() == exe:
                    group.add(p.info['pid'])
            except Exception:
                continue
    return group


def find_throttle_candidates(foreground_pid, cpu_threshold=3.0, limit=40):
    """에코 모드·게임 부스트에서 우선순위를 낮출 만한 프로세스를 고른다.

    '실제로 CPU 를 쓰고 있는' 것만 고른다(작업 관리자 기준 cpu_threshold % 이상, 1초 이상 잰 평균).
    유휴 상태인 앱의 우선순위를 낮춰봐야 얻는 것은 없고, 그 앱이 깨어날 때 느려지기만 한다.
    지금 쓰는 창의 앱 묶음, 사용자가 직접 우선순위를 바꾼 프로세스는 건드리지 않는다.
    """
    out = []
    fg = foreground_group(foreground_pid)
    alive = set()
    for p in psutil.process_iter(['pid', 'name', 'username']):
        try:
            pid = p.info['pid']
            alive.add(pid)
            name = (p.info['name'] or '').lower()
            if pid in fg or not name:
                continue
            if _never_throttle(name) or _is_game(name):
                continue
            if owner_of(pid) == 'user':
                continue
            # 시스템 계정으로 도는 것은 건드리지 않는다
            user = p.info['username'] or ''
            if 'system' in user.lower() or 'service' in user.lower():
                continue
            # CPU 를 먼저 본다. 관문(process_guard)은 부모 프로세스를 거슬러 올라가며 프로세스 목록 전체를 여러 번
            # 다시 읽어서, 예전처럼 모든 앱에 먼저 부르면 게임 중 5초마다 몇 초씩 CPU 를 썼다. 기준점은 모든 앱에 갱신된다.
            cpu = sample_cpu(p)
            if cpu is None or cpu < cpu_threshold:
                continue
            # process_guard 가 막는 것은 애초에 후보가 아니다(바꾸기 직전 set_priority 가 다시 확인한다)
            ok, _, _, _ = process_guard.check_controllable(pid, action='priority')
            if not ok:
                continue
            out.append({'pid': pid, 'name': p.info['name'], 'cpu': round(cpu, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    for pid in [k for k in _cpu_samples if k not in alive]:
        _cpu_samples.pop(pid, None)

    out.sort(key=lambda x: x['cpu'], reverse=True)
    return out[:limit]


def prime_cpu_measurement():
    """CPU 표본의 기준점을 잡는다. 첫 표본은 판정하지 않으므로(None) 미리 한 번 재 둔다."""
    for p in psutil.process_iter(['pid']):
        try:
            sample_cpu(p)
        except Exception:
            pass
