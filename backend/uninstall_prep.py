"""
APEX CARE — 제거하기 전에 이 앱이 바꾼 것을 되돌린다.

제거 프로그램(tools/uninstall.py)이 설치 폴더를 지우기 전에 `APEX CARE.exe --revert-for-uninstall` 로 부른다.
창을 띄우지 않고 되돌리기만 한 뒤, 결과를 %APPDATA%\\APEX_CARE_DATA\\uninstall_revert.json 에 남기고
종료 코드(0 = 전부 되돌림, 1 = 실패 있음)로 알린다.

왜 필요한가:
  예전 제거 프로그램은 설치 폴더·바로가기·제거 등록만 지웠다. 성능 모드·디블로터·게임 부스트가 바꾼
  전원 설정과 레지스트리, 이 앱으로 꺼 둔 시작 프로그램이 그대로 남았고, 되돌릴 앱이 사라져 방법도 없었다.

되돌리는 것:
  1. 복구 센터의 '전부 원래대로'(perf_modes.revert_everything): system_state 저널 전부와 구버전 백업.
     이 앱으로 끈 시작 프로그램(StartupApproved 표시)도 저널에 있어 여기서 되켜진다
  2. 예전 버전이 Run 에서 지우고 HKCU\\Software\\APEXCARE 에 숨겨 둔 시작 프로그램을 원래 자리로 되살려 켠다
  3. 게임 부스트의 '게임 전 모드' 기록을 지운다. 남겨 두면 다시 설치했을 때 그 모드가 적용된다
실패한 항목은 저널·백업에 그대로 남는다(다시 시도할 수 있게). 제거 여부는 제거 프로그램이 사용자에게 묻는다.
"""

import json
import logging
import os

log = logging.getLogger('UninstallPrep')

RESULT_NAME = 'uninstall_revert.json'
_STARTUP_BACKUP = r"Software\APEXCARE\DisabledStartup"
_STARTUP_ORIGIN = _STARTUP_BACKUP + r"\_origin"
_APEX_KEY = r"Software\APEXCARE"


def result_path():
    from backend import config_manager
    return os.path.join(config_manager.APPDATA_DIR, RESULT_NAME)


def _disabled_startup_names():
    import winreg
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_BACKUP, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    names.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    break
                i += 1
    except FileNotFoundError:
        pass
    return names


def _delete_key_if_empty(path):
    """값도 하위 키도 없을 때만 지운다. 무언가 남아 있으면 그대로 둔다."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as k:
            subkeys, values, _ = winreg.QueryInfoKey(k)
        if subkeys or values:
            return
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def _restore_disabled_startup():
    """예전 버전이 숨겨 둔 시작 프로그램을 원래 자리로 되살려 켠다. 항목별 step 목록."""
    from backend import optimizer
    steps = []
    for name in _disabled_startup_names():
        r = optimizer.toggle_startup_app(f'LEGACY:{name}', True)
        ok = bool(r.get('success'))
        steps.append({'name': f"시작 프로그램 '{name}' 다시 켜기", 'ok': ok,
                      'detail': '' if ok else r.get('message', '실패')})
    # 이 앱이 만든 키는 비었을 때만 지운다(깊은 것부터)
    for path in (_STARTUP_ORIGIN, _STARTUP_BACKUP, _APEX_KEY):
        _delete_key_if_empty(path)
    return steps


def revert_for_uninstall():
    """제거 전 되돌리기. {'success', 'steps', 'failed', 'remaining'}"""
    from backend import config_manager, perf_modes, system_state

    steps = []
    r = perf_modes.revert_everything()
    if r.get('error') == 'UAC_REQUIRED':
        steps.append({'name': '시스템 설정 되돌리기', 'ok': False,
                      'detail': r.get('message') or '관리자 권한이 필요합니다.'})
    else:
        for p in r.get('parts', []):
            detail = p.get('detail', '')
            reasons = [f.get('reason') for f in p.get('failed') or [] if f.get('reason')]
            if reasons:
                detail = f"{detail} — {'; '.join(reasons[:5])}"
            steps.append({'name': p['name'], 'ok': bool(p['ok']), 'detail': detail})

    steps.extend(_restore_disabled_startup())

    # 복귀할 '게임 전 모드' 는 더 없다. revert_everything 이 모드를 표준으로 기록했다.
    if config_manager.get_boost_restore_mode() is not None:
        saved = config_manager.set_boost_restore_mode(None)
        steps.append({'name': '게임 부스트 복귀 기록 지우기', 'ok': bool(saved),
                      'detail': '' if saved else '설정 파일에 저장하지 못했습니다'})

    failed = [s for s in steps if not s['ok']]
    return {'success': not failed, 'steps': steps, 'failed': failed,
            'remaining': len(system_state.pending_changes())}


def _write_result(res):
    path = result_path()
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main_cli():
    """`APEX CARE.exe --revert-for-uninstall` 진입점. 종료 코드: 0 전부 되돌림, 1 실패 있음."""
    try:
        res = revert_for_uninstall()
    except Exception as e:                    # 무엇이 잘못됐는지 제거 프로그램이 보여줄 수 있게 남긴다
        log.exception('제거 전 되돌리기 실패')
        res = {'success': False, 'steps': [],
               'failed': [{'name': '제거 전 되돌리기', 'ok': False, 'detail': str(e) or type(e).__name__}],
               'remaining': None}
    try:
        _write_result(res)
    except Exception as e:
        log.error(f'결과 파일을 쓰지 못했습니다: {e}')
        return 1                              # 결과를 전하지 못하면 성공이라고 할 수 없다
    return 0 if res['success'] else 1
