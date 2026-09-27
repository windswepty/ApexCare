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

4. PID 는 재사용된다. 원래 프로세스가 끝나고 같은 번호를 받은 다른 프로세스를
   '복구'하면 전혀 관계없는 프로세스의 우선순위가 바뀐다.
   → 생성 시각과 이름으로 같은 프로세스인지 확인한 뒤에만 되돌린다.

5. 게임 부스터 스레드와 UI 호출(pywebview 는 호출마다 스레드를 만든다)이 동시에 온다.
   복구가 기록을 지운 직후 다른 스레드가 '우리가 바꾼 값'을 원본으로 기록할 수 있었다.
   → 기록·변경·복구를 잠금 하나로 직렬화한다.

6. 효율 모드(EcoQoS)를 걸고 풀지 않았다. 게임이 끝나도 앱이 재시작될 때까지 E 코어에 묶였다.
   → 바꾸기 전 상태를 읽어 기록하고, 복구 때 그 상태로 되돌린다. 원래 상태를 못 읽으면 걸지 않는다.

7. 원래 값이 메모리에만 있어서 앱이 비정상 종료되면 되돌릴 방법이 없었다.
   → 디스크에도 남기고, 다음 실행 때 같은 프로세스가 살아 있으면 되돌린다.
"""

import ctypes
import ctypes.wintypes
import json
import logging
import os
import threading

import psutil

from backend import process_guard

log = logging.getLogger('ProcessBoost')

# 이름만으로는 process_guard 가 막지 않지만, 우선순위를 낮추면
# 사용자가 바로 불편을 겪는 부류. 자동 양보(게임 부스트) 대상에서 제외한다.
# 사용자가 게이밍 탭에서 직접 바꾸는 것은 막지 않는다.
NEVER_THROTTLE = {
    # 보안 — 실시간 검사가 느려지면 보호 수준이 떨어진다
    'avp.exe', 'avgnt.exe', 'avguard.exe', 'ashdisp.exe', 'avastsvc.exe',
    'mbam.exe', 'mbamservice.exe', 'nortonsecurity.exe', 'ns.exe',
    'bdagent.exe', 'vsserv.exe', 'ekrn.exe', 'egui.exe',
    'v3svc.exe', 'v3main.exe', 'ahnsd.exe',          # 국내 백신(V3)
    'alyac.exe', 'ayagent.aye', 'ayrtsrv.aye',       # 알약
    # 소리·음악 — 우선순위를 낮추면 끊긴다
    'audiodg.exe', 'rtkngui64.exe', 'ravcpl64.exe', 'nahimicservice.exe',
    'voicemeeter.exe', 'equalizerapo.exe',
    'spotify.exe', 'vlc.exe', 'foobar2000.exe', 'aimp.exe', 'musicbee.exe',
    'potplayer*', 'melon*',
    # 통화·메신저·화면공유 — 끊기면 즉시 체감된다
    'discord.exe', 'zoom.exe', 'teams.exe', 'ms-teams.exe', 'skype.exe',
    'kakaotalk.exe', 'kakao.exe', 'slack.exe', 'line.exe', 'telegram.exe',
    'whatsapp.exe', 'mumble.exe', 'teamspeak.exe', 'ts3client_win64.exe',
    'webex*', 'ciscocollabhost.exe',
    # 방송·녹화·인코딩 — 느려지면 녹화가 끊기거나 작업 시간이 몇 배로 늘어난다
    'obs64.exe', 'obs32.exe', 'streamlabs obs.exe', 'xsplit*',
    'bandicam.exe', 'bdcam.exe', 'nvidia share.exe', 'nvidia broadcast.exe',
    'ffmpeg.exe', 'handbrake.exe', 'handbrakecli.exe', 'handbrake.worker.exe',
    'adobe premiere pro.exe', 'afterfx.exe', 'adobe media encoder.exe',
    'blender.exe', 'resolve.exe', 'vegas*',
    # 백업·동기화 — 중단되면 데이터 정합성 문제가 생길 수 있다
    'onedrive.exe', 'dropbox.exe', 'googledrivesync.exe', 'googledrivefs.exe',
    'megasync.exe', 'nextcloud.exe', 'backupexec.exe', 'acronis*',
    'reflect.exe', 'icloud*', 'syncthing.exe', 'resilio-sync.exe', 'veeam*',
    'synology*', 'cloud-drive-ui.exe',
    # 게임 런처 — 친구 목록·음성·오버레이·다운로드를 맡는다
    'steam.exe', 'steamwebhelper.exe', 'steamservice.exe',
    'epicgameslauncher.exe', 'epicwebhelper.exe', 'battle.net.exe', 'battlenet.exe',
    'riotclientservices.exe', 'riotclientux.exe', 'eadesktop.exe', 'origin.exe',
    'upc.exe', 'ubisoftconnect.exe', 'galaxyclient.exe',
    'easyanticheat.exe', 'easyanticheat_eos.exe',
    # 원격 제어 — 느려지면 원격 화면·입력이 끊긴다
    'anydesk.exe', 'teamviewer.exe', 'rustdesk.exe', 'mstsc.exe', 'parsecd.exe',
    'sunshine.exe',
    # 입력기·접근성 — 끊기면 아무것도 못 한다
    'imekrmig.exe', 'chsime.exe', 'tsf3g.exe',
    'nvda.exe', 'narrator.exe', 'magnify.exe',
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

# pid -> {'priority': 원래 우선순위, 'name': 프로세스명, 'create_time': 생성 시각,
#         'owner': 'user'|'booster', 'eco': 원래 EcoQoS [control, state] 또는 None,
#         'eco_set': APEX 가 EcoQoS 를 걸었는지}
_original = {}
_lock = threading.RLock()

STATE_DIR = os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA')
STATE_PATH = os.path.join(STATE_DIR, 'process_boost.json')


def _never_throttle(name):
    n = (name or '').lower()
    if n in NEVER_THROTTLE:
        return True
    # acronis* 같은 접두사 항목
    return any(p.endswith('*') and n.startswith(p[:-1]) for p in NEVER_THROTTLE)


# ─────────────────────────────────────────────
# EcoQoS (작업 관리자의 '효율 모드')
# ─────────────────────────────────────────────

_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ProcessPowerThrottling = 4
_THROTTLE_VERSION = 1
_THROTTLE_EXECUTION_SPEED = 0x1


class _PowerThrottlingState(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong)]


_k32 = None


def _kernel32():
    """핸들을 올바른 폭으로 받도록 원형을 선언해 둔다(기본 int 반환은 64비트 핸들을 자를 수 있다)."""
    global _k32
    if _k32 is None:
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.restype = ctypes.wintypes.HANDLE
        k.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
        k.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        k.CloseHandle.restype = ctypes.wintypes.BOOL
        k.GetProcessInformation.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_int,
                                            ctypes.c_void_p, ctypes.wintypes.DWORD]
        k.GetProcessInformation.restype = ctypes.wintypes.BOOL
        k.SetProcessInformation.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_int,
                                            ctypes.c_void_p, ctypes.wintypes.DWORD]
        k.SetProcessInformation.restype = ctypes.wintypes.BOOL
        _k32 = k
    return _k32


def _read_ecoqos(pid):
    """(ControlMask, StateMask) 를 돌려준다. 읽지 못하면 None."""
    try:
        k = _kernel32()
        h = k.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            s = _PowerThrottlingState()
            s.Version = _THROTTLE_VERSION
            if not k.GetProcessInformation(h, _ProcessPowerThrottling,
                                           ctypes.byref(s), ctypes.sizeof(s)):
                return None
            # 다른 정책 비트(타이머 해상도 무시 등)도 그대로 기록한다. 복구 때 통째로 되돌린다.
            return (int(s.ControlMask), int(s.StateMask))
        finally:
            k.CloseHandle(h)
    except Exception as e:
        log.debug(f"EcoQoS 읽기 실패 PID {pid}: {e}")
        return None


def _write_ecoqos(pid, control, state):
    """EcoQoS 를 쓰고 되읽어 확인한다."""
    try:
        k = _kernel32()
        h = k.OpenProcess(_PROCESS_SET_INFORMATION | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            s = _PowerThrottlingState()
            s.Version = _THROTTLE_VERSION
            s.ControlMask = control
            s.StateMask = state
            if not k.SetProcessInformation(h, _ProcessPowerThrottling,
                                           ctypes.byref(s), ctypes.sizeof(s)):
                return False
        finally:
            k.CloseHandle(h)
    except Exception as e:
        log.debug(f"EcoQoS 쓰기 실패 PID {pid}: {e}")
        return False
    return _read_ecoqos(pid) == (control, state)


# ─────────────────────────────────────────────
# 원래 값 기록 (메모리 + 디스크)
# ─────────────────────────────────────────────

def _same_process(entry, create_time, name):
    """기록 당시의 그 프로세스인가. 생성 시각을 못 읽었으면 같다고 보지 않는다(fail-safe)."""
    ct = entry.get('create_time')
    if ct is None or create_time is None:
        return False
    return (abs(ct - create_time) < 0.001
            and (entry.get('name') or '').lower() == (name or '').lower())


def _own_create_time():
    try:
        return psutil.Process(os.getpid()).create_time()
    except Exception:
        return None


def _persist():
    """원래 값을 디스크에도 남긴다. 앱이 비정상 종료돼도 다음 실행 때 되돌릴 수 있게."""
    data = {
        'version': 1,
        'owner': {'pid': os.getpid(), 'create_time': _own_create_time()},
        'entries': [dict(e, pid=pid) for pid, e in _original.items()],
    }
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_PATH)
        return True
    except Exception as e:
        # 우선순위는 프로세스가 끝나면 사라지는 세션 한정 변경이라 변경 자체는 막지 않는다.
        # 메모리 기록은 남아 있으므로 이번 실행 안에서는 그대로 되돌릴 수 있다.
        log.warning(f"우선순위 기록 저장 실패: {e}")
        return False


def snapshot(pid, name=None):
    """바꾸기 전 원래 우선순위를 기록한다. 같은 프로세스의 기록이 있으면 덮어쓰지 않는다.

    덮어쓰면 우리가 설정한 IDLE 이 '원래 값'으로 굳어 영영 복구할 수 없다.
    system_state 가 레지스트리에 대해 하는 것과 같은 원칙이다.
    같은 PID 라도 다른 프로세스(재사용)의 낡은 기록이면 버리고 새로 기록한다.
    기록했으면 True.
    """
    with _lock:
        try:
            p = psutil.Process(pid)
            ct, pname, prio = p.create_time(), p.name(), p.nice()
        except Exception:
            return False
        entry = _original.get(pid)
        if entry and _same_process(entry, ct, pname):
            return False
        _original[pid] = {'priority': prio, 'name': name or pname, 'create_time': ct,
                          'owner': 'user', 'eco': None, 'eco_set': False}
        _persist()
        return True


def set_priority(pid, priority_name, reason='', ecoqos=False, owner='user'):
    """우선순위를 바꾼다. process_guard 를 반드시 통과해야 한다.

    ecoqos=True 면 효율 모드(EcoQoS)도 켠다. 원래 상태를 읽지 못하면 켜지 않는다.
    owner 는 누가 바꿨는지다('user' | 'booster'). 게임 부스터는 자기가 바꾼 것만 되돌린다.
    """
    if priority_name not in PRIORITY_BY_NAME:
        return {'ok': False, 'reason': f'알 수 없는 우선순위: {priority_name}'}

    ok, safe_pid, proc_name, err = process_guard.check_controllable(pid, action='priority')
    if not ok:
        return {'ok': False, 'reason': err, 'name': proc_name}

    target = PRIORITY_BY_NAME[priority_name]
    with _lock:
        try:
            p = psutil.Process(safe_pid)
            ct, current = p.create_time(), p.nice()
        except psutil.NoSuchProcess:
            return {'ok': False, 'name': proc_name, 'reason': '프로세스가 이미 종료되었습니다.'}
        except Exception:
            # 생성 시각을 모르면 나중에 같은 프로세스인지 확인할 수 없다. 바꾸지 않는다.
            return {'ok': False, 'name': proc_name,
                    'reason': f"'{proc_name}' 의 정보를 읽지 못해 우선순위를 바꾸지 않았습니다."}

        entry = _original.get(safe_pid)
        if entry and not _same_process(entry, ct, proc_name):
            _original.pop(safe_pid, None)      # 끝난 프로세스의 낡은 기록
            entry = None
        created = entry is None
        if created:
            entry = {'priority': current, 'name': proc_name, 'create_time': ct,
                     'owner': owner, 'eco': None, 'eco_set': False}
            _original[safe_pid] = entry
            _persist()

        def _undo_record():
            # 아무것도 바꾸지 못했으면 '조정됨' 으로 세지 않는다
            if created:
                _original.pop(safe_pid, None)
                _persist()

        try:
            p.nice(target)
        except psutil.AccessDenied:
            _undo_record()
            return {'ok': False, 'name': proc_name,
                    'reason': f"'{proc_name}' 의 우선순위를 바꿀 권한이 없습니다. "
                              "보호된 프로세스일 수 있습니다."}
        except psutil.NoSuchProcess:
            _original.pop(safe_pid, None)
            _persist()
            return {'ok': False, 'name': proc_name, 'reason': '프로세스가 이미 종료되었습니다.'}
        except Exception as e:
            _undo_record()
            return {'ok': False, 'name': proc_name, 'reason': str(e)}

        # 반환값을 믿지 않고 되읽어 확인한다
        try:
            after = p.nice()
        except Exception:
            after = None
        if after != target:
            if after == entry['priority']:
                _undo_record()
            return {'ok': False, 'name': proc_name,
                    'reason': f'설정 후 확인에 실패했습니다 (현재 {NAME_BY_PRIORITY.get(after, after)})'}

        eco_applied = _apply_ecoqos(safe_pid, entry) if ecoqos else False
        if eco_applied:
            _persist()

    log.info(f"우선순위 변경: {proc_name}({safe_pid}) -> {priority_name}"
             f"{' + 효율 모드' if eco_applied else ''} {reason}")
    return {'ok': True, 'name': proc_name, 'priority': priority_name, 'ecoqos': eco_applied}


def _apply_ecoqos(pid, entry):
    """EcoQoS 를 켠다. 원래 상태를 기록할 수 있을 때만. 켰으면 True."""
    if entry.get('eco_set'):
        return True
    orig = _read_ecoqos(pid)
    if orig is None:
        return False                       # 원래 상태를 모르면 건드리지 않는다
    control, state = orig
    if control & state & _THROTTLE_EXECUTION_SPEED:
        return False                       # 이미 앱 스스로 켜 둔 상태. 우리 것이 아니다
    # 실행 속도 비트만 켜고 나머지 정책 비트는 원래대로 둔다
    if _write_ecoqos(pid, control | _THROTTLE_EXECUTION_SPEED, state | _THROTTLE_EXECUTION_SPEED):
        entry['eco'] = list(orig)
        entry['eco_set'] = True
        return True
    # 되읽기가 다르면 원래 상태로 돌려 둔다
    _write_ecoqos(pid, *orig)
    return False


def restore(pid):
    """기록해둔 원래 우선순위(와 EcoQoS)로 되돌린다.

    지금 그 PID 를 가진 프로세스가 기록 당시와 다르면(재사용) 아무것도 바꾸지 않고
    기록만 버린다.
    """
    with _lock:
        entry = _original.get(pid)
        if not entry:
            return {'ok': False, 'reason': '기록된 원래 값이 없습니다.'}
        name = entry.get('name')
        try:
            p = psutil.Process(pid)
            ct, pname = p.create_time(), p.name()
        except psutil.NoSuchProcess:
            _original.pop(pid, None)
            _persist()
            return {'ok': True, 'name': name, 'ended': True, 'reason': '프로세스가 이미 종료됨'}
        except Exception as e:
            # 확인할 수 없으면 건드리지 않고 기록을 남겨 다시 시도할 수 있게 한다
            return {'ok': False, 'name': name, 'reason': f'프로세스를 확인하지 못했습니다: {e}'}

        if not _same_process(entry, ct, pname):
            _original.pop(pid, None)
            _persist()
            return {'ok': True, 'name': name, 'ended': True,
                    'reason': '원래 프로세스는 종료됐고 같은 번호를 다른 프로세스가 쓰고 있어 건드리지 않았습니다.'}

        errors = []
        try:
            p.nice(entry['priority'])
            if p.nice() != entry['priority']:
                errors.append('우선순위 복구 후 확인 실패')
        except psutil.NoSuchProcess:
            _original.pop(pid, None)
            _persist()
            return {'ok': True, 'name': name, 'ended': True, 'reason': '프로세스가 이미 종료됨'}
        except Exception as e:
            errors.append(f'우선순위 복구 실패: {e}')

        if entry.get('eco_set'):
            eco = entry.get('eco') or [0, 0]
            if _write_ecoqos(pid, eco[0], eco[1]):
                entry['eco_set'] = False
            else:
                errors.append('효율 모드 해제 실패')

        if errors:
            # 복구에 실패하면 기록을 남겨 다음에 다시 시도할 수 있게 한다
            _persist()
            return {'ok': False, 'name': name, 'reason': '; '.join(errors)}

        _original.pop(pid, None)
        _persist()
        return {'ok': True, 'name': name,
                'priority': NAME_BY_PRIORITY.get(entry['priority'], entry['priority'])}


def restore_all(owner=None):
    """조정했던 프로세스를 원래 우선순위로 되돌린다. owner 를 주면 그 주체가 바꾼 것만."""
    with _lock:
        pids = [pid for pid, e in _original.items()
                if owner is None or e.get('owner') == owner]
        results = [dict(restore(pid), pid=pid) for pid in pids]
    ok = [r for r in results if r['ok']]
    failed = [r for r in results if not r['ok']]
    return {'ok': not failed, 'restored': len(ok),
            'ended': sum(1 for r in ok if r.get('ended')), 'failed': failed}


def prune_dead():
    """이미 끝났거나 PID 가 재사용된 기록을 버린다. 버린 개수."""
    removed = 0
    with _lock:
        for pid, entry in list(_original.items()):
            try:
                p = psutil.Process(pid)
                alive = _same_process(entry, p.create_time(), p.name())
            except psutil.NoSuchProcess:
                alive = False
            except Exception:
                alive = True               # 확인할 수 없으면 남겨 둔다
            if not alive:
                _original.pop(pid, None)
                removed += 1
        if removed:
            _persist()
    return removed


def adjusted_count():
    prune_dead()
    with _lock:
        return len(_original)


def is_adjusted(pid, create_time=None):
    """이 PID 의 원래 값이 기록돼 있는가(누군가 이미 바꿨는가)."""
    with _lock:
        entry = _original.get(pid)
        if not entry:
            return False
        if create_time is not None and abs((entry.get('create_time') or -1) - create_time) >= 0.001:
            return False
        return True


def recover_previous_session():
    """지난 실행이 되돌리지 못하고 끝난 우선순위를 되돌린다.

    앱이 강제 종료되면 메모리의 원래 값이 사라진다. 디스크 기록을 읽어,
    같은 프로세스(생성 시각·이름 일치)가 아직 살아 있으면 원래 값으로 돌린다.
    기록을 남긴 인스턴스가 아직 살아 있으면 그쪽 몫이므로 건드리지 않는다.
    """
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return {'ok': True, 'restored': 0, 'failed': []}
    except Exception as e:
        log.warning(f"지난 우선순위 기록을 읽지 못했습니다: {e}")
        return {'ok': False, 'restored': 0,
                'failed': [{'reason': f'지난 기록을 읽지 못했습니다: {e}'}]}

    owner = data.get('owner') or {}
    opid = owner.get('pid')
    if opid and opid != os.getpid():
        try:
            op = psutil.Process(opid)
            if owner.get('create_time') is not None and \
                    abs(op.create_time() - owner['create_time']) < 0.001:
                log.info("기록을 남긴 APEX CARE 가 아직 실행 중이라 건드리지 않습니다")
                return {'ok': True, 'restored': 0, 'failed': [], 'otherInstance': True}
        except Exception:
            pass

    adopted = []
    with _lock:
        for e in data.get('entries') or []:
            pid = e.get('pid')
            if not isinstance(pid, int) or pid in _original:
                continue
            try:
                p = psutil.Process(pid)
                if not _same_process(e, p.create_time(), p.name()):
                    continue
            except Exception:
                continue
            e = {k: v for k, v in e.items() if k != 'pid'}
            if e.get('priority') not in NAME_BY_PRIORITY:
                continue
            _original[pid] = e
            adopted.append(pid)
        _persist()                         # 살아 있지 않은 항목은 여기서 정리된다
        results = [dict(restore(pid), pid=pid) for pid in adopted]

    failed = [r for r in results if not r['ok']]
    restored = sum(1 for r in results if r['ok'] and not r.get('ended'))
    if adopted:
        log.info(f"지난 실행의 우선순위 {restored}개 복구, {len(failed)}개 실패")
    return {'ok': not failed, 'restored': restored, 'failed': failed}


# ─────────────────────────────────────────────
# 자동 양보 후보
# ─────────────────────────────────────────────

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


def process_tree(pid):
    """pid 와 그 자식 전부. 읽지 못하면 pid 만."""
    out = {pid} if pid else set()
    if not pid:
        return out
    try:
        for c in psutil.Process(pid).children(recursive=True):
            out.add(c.pid)
    except Exception:
        pass
    return out


def find_throttle_candidates(foreground_pid, cpu_threshold=3.0, limit=40, exclude_pids=None):
    """게임 중 우선순위를 낮출 만한 백그라운드 프로세스를 고른다.

    예전에는 포그라운드가 아닌 모든 사용자 프로세스를 대상으로 삼았다.
    여기서는 '실제로 CPU 를 쓰고 있는' 것만 고른다. 유휴 상태인 앱의
    우선순위를 낮춰봐야 얻는 것은 없고, 그 앱이 깨어날 때 느려지기만 한다.

    cpu_threshold 는 전체 CPU 대비 % 다(게이밍 탭 프로세스 목록의 CPU 표시와 같은 단위).
    지금 보고 있는 창과 그 자식, 그와 같은 이름의 프로세스, exclude_pids 는 제외한다.
    """
    exclude = set(exclude_pids or ())
    exclude |= process_tree(foreground_pid)
    fg_name = None
    if foreground_pid:
        try:
            fg_name = psutil.Process(foreground_pid).name().lower()
        except Exception:
            pass
    cores = psutil.cpu_count(logical=True) or 1

    out = []
    for p in psutil.process_iter(['pid', 'name']):
        try:
            pid = p.info['pid']
            name = (p.info['name'] or '').lower()
            if not name or pid in exclude or name == fg_name:
                continue
            if _never_throttle(name) or _is_game(name):
                continue
            cpu = p.cpu_percent(None) / cores     # 직전 호출 이후 평균
            if cpu < cpu_threshold:
                continue
            # process_guard 가 막는 것(시스템·서비스·다른 세션·APEX 자신)은 후보가 아니다
            ok, _, _, _ = process_guard.check_controllable(pid, action='priority')
            if not ok:
                continue
            out.append({'pid': pid, 'name': p.info['name'], 'cpu': round(cpu, 1),
                        'create_time': p.create_time()})
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
