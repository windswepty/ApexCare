"""
APEX CARE - 성능 모드 비교용 짧은 CPU 측정.

모드를 바꿔도 가벼운 작업에서는 차이가 잘 느껴지지 않는다. 같은 계산을 몇 초 돌려 점수와 그때의 실제 클럭을
모드별로 남겨, 모드의 효과를 숫자로 비교할 수 있게 한다. 계산만 하고 시스템은 바꾸지 않는다.

점수는 한 코어로 SHA-256 을 계산한 양(MB/s)이다. 부스트 클럭의 차이가 그대로 드러난다.
"""
import hashlib
import logging
import os
import threading
import time

log = logging.getLogger('PerfBench')

BENCH_SECONDS = 3.0
_BLOCK = os.urandom(1 << 20)      # 1MB. 해시는 큰 데이터에서 GIL 을 놓아 다른 API 호출을 막지 않는다
_lock = threading.Lock()
_SETTINGS_KEY = 'bench_results'


def _measure(seconds):
    done = 0
    start = time.perf_counter()
    deadline = start + seconds
    while time.perf_counter() < deadline:
        hashlib.sha256(_BLOCK).digest()
        done += 1
    elapsed = time.perf_counter() - start
    return done / elapsed if elapsed > 0 else 0.0     # MB/s


def _current_mode():
    """지금 실제로 걸려 있는 모드. (모드, 모를 때의 이유) — 이유가 있으면 측정 결과를 어느 모드에도 두지 않는다.

    저장된 모드만 보면 틀린다. 게임 부스트가 게임 동안 게이밍 모드를 임시로 쓰는 중이면 실제는 게이밍이고,
    앱 밖에서 전원 플랜이 바뀌었으면(inSync=False) 어느 모드의 결과인지 알 수 없다.
    예전에는 이런 때에도 저장된 모드 이름으로 결과를 남겨 비교표가 틀렸다.
    """
    try:
        from backend import perf_modes
        info = perf_modes.get_mode()
    except Exception as e:
        return None, f'지금 모드를 읽지 못했습니다: {e}'
    if info.get('boostOverride'):
        return 'gaming', None
    if not info.get('inSync', True):
        return None, ("지금 전원 설정이 선택한 모드와 달라 어느 모드의 결과인지 알 수 없습니다. "
                      "성능 모드를 다시 눌러 맞춘 뒤 측정해 주세요.")
    return info.get('mode') or 'standard', None


def get_results():
    """모드별 마지막 측정 결과. {mode: {score, clockMHz, at}}"""
    try:
        from backend import config_manager
        data = config_manager.load_config().get(_SETTINGS_KEY)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def run(seconds=BENCH_SECONDS):
    """지금 모드에서 측정하고 결과를 모드별로 남긴다. 이미 측정 중이면 기다리지 않고 알린다."""
    if not _lock.acquire(blocking=False):
        return {'success': False, 'busy': True, 'message': '이미 측정 중입니다.'}
    try:
        from backend import system_monitor
        mode, why = _current_mode()
        if why:
            return {'success': False, 'message': why}
        system_monitor.note_demand()                 # 측정 동안 클럭 수집기가 깨어 있게 한다
        _measure(0.3)                                # 부스트가 올라올 시간을 준다
        score = _measure(seconds)
        clock = system_monitor.get_system_stats() or {}
        result = {'score': round(score), 'clockMHz': clock.get('cpuClockMHz'),
                  'at': time.strftime('%Y-%m-%d %H:%M')}
        results = get_results()
        results[mode] = result
        try:
            from backend import config_manager
            cfg = config_manager.load_config()
            cfg[_SETTINGS_KEY] = results
            config_manager.save_config(cfg)
        except Exception as e:
            log.warning(f'측정 결과를 저장하지 못했습니다: {e}')
        return {'success': True, 'mode': mode, 'result': result, 'results': results,
                'message': f"{result['score']} MB/s"}
    except Exception as e:
        log.warning(f'CPU 측정 실패: {e}')
        return {'success': False, 'message': f'측정하지 못했습니다: {e}'}
    finally:
        _lock.release()
