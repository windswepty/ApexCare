"""APEX CARE 진입점.

일반 실행        : pywebview 창을 띄우고 backend.api.Api 를 JS API 로 노출한다.
--revert-all     : 창 없이 이 앱이 바꾼 설정을 전부 되돌리고 끝낸다. 제거 프로그램이 제거 전에 부른다.
  --result <json> : 결과를 이 파일에 쓴다. 종료 코드 0=성공, 1=일부 실패, 2=오류.
--dev            : dist_react 가 없을 때 개발 서버(localhost:5173)를 띄운다. 설치본에서는 무시한다.

실행 파일은 관리자 권한으로 돈다. 창을 어떻게 닫든(X 버튼, Alt+F4, 작업 표시줄, 로그오프)
우선순위·게임 부스트를 되돌리도록 closing 이벤트와 atexit 양쪽에서 같은 정리를 한 번만 실행한다.
"""

import sys
import os

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import argparse
import atexit
import ctypes
import json
import logging
import threading
from ctypes import wintypes

log = logging.getLogger('Main')

APP_TITLE = 'APEX CARE'

# Global\ 이름이라 다른 사용자 세션에서 띄운 인스턴스와도 겹치지 않게 막는다.
# 전원 옵션·서비스처럼 PC 전체에 걸리는 설정을 두 인스턴스가 동시에 바꾸면 원래 값 기록이 꼬인다.
MUTEX_NAME = 'APEX_CARE_SingleInstance_5E2A9C71'

EXIT_OK, EXIT_PARTIAL, EXIT_ERROR = 0, 1, 2

ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_DEFBUTTON2 = 0x100
MB_TASKMODAL = 0x2000
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000
IDYES = 6

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
_user32.MessageBoxW.restype = ctypes.c_int

_instance_mutex = None     # 프로세스가 끝날 때까지 들고 있어야 한다


def _message(text, flags=MB_OK | MB_ICONINFORMATION):
    try:
        return _user32.MessageBoxW(None, text, APP_TITLE,
                                   flags | MB_TASKMODAL | MB_SETFOREGROUND | MB_TOPMOST)
    except Exception:
        return 0


# ─────────────────────────────────────────────
# 단일 인스턴스
# ─────────────────────────────────────────────

def acquire_single_instance():
    """이 프로세스가 유일한 인스턴스면 True.

    두 인스턴스가 함께 돌면 서로 바꾼 우선순위를 '원래 값' 으로 기록해
    되돌린 뒤에도 값이 틀어진다. 그래서 창 모드와 --revert-all 모두 이 검사를 거친다.
    """
    global _instance_mutex
    for prefix in ('Global\\', 'Local\\'):
        handle = _kernel32.CreateMutexW(None, False, prefix + MUTEX_NAME)
        err = ctypes.get_last_error()
        if handle:
            if err == ERROR_ALREADY_EXISTS:
                _kernel32.CloseHandle(handle)
                return False
            _instance_mutex = handle
            return True
        if err == ERROR_ACCESS_DENIED:
            # 다른 권한으로 만든 같은 이름의 뮤텍스가 있다 = 이미 돌고 있다
            return False
        # Global 이름을 쓸 수 없는 환경이면 세션 범위로 다시 시도한다
    log.warning('단일 인스턴스 뮤텍스를 만들지 못해 중복 실행 검사를 건너뜁니다')
    return True


def _activate_existing_window():
    """이미 떠 있는 APEX CARE 창을 앞으로 가져온다. 못 찾으면 아무것도 하지 않는다."""
    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        _user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        _user32.IsWindowVisible.argtypes = [wintypes.HWND]
        _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        found = []

        def _cb(hwnd, _lparam):
            if not _user32.IsWindowVisible(hwnd):
                return True
            title = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, title, 256)
            if title.value != APP_TITLE:
                return True
            cls = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(hwnd, cls, 256)
            if not cls.value.startswith('WindowsForms10.'):   # pywebview(WinForms) 창만
                return True
            found.append(hwnd)
            return False

        _user32.EnumWindows(WNDENUMPROC(_cb), 0)
        if found:
            SW_RESTORE = 9
            _user32.ShowWindow(found[0], SW_RESTORE)
            _user32.SetForegroundWindow(found[0])
    except Exception as e:
        log.debug(f'기존 창 활성화 실패: {e}')


# ─────────────────────────────────────────────
# --revert-all (창 없이 되돌리기)
# ─────────────────────────────────────────────

def _norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _check_result_path(path):
    """결과 파일 경로를 검사한다. 문제가 없으면 None, 있으면 이유."""
    if not path:
        return None
    if not os.path.isabs(path):
        return '결과 파일 경로는 절대 경로여야 합니다.'
    if not path.lower().endswith('.json'):
        return '결과 파일은 .json 이어야 합니다.'
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        return '결과 파일을 둘 폴더가 없습니다.'
    if os.path.lexists(path):
        # 미리 만들어 둔 파일·링크를 관리자 권한으로 덮어쓰지 않는다
        return '결과 파일이 이미 있습니다.'
    if getattr(sys, 'frozen', False):
        # 설치본은 관리자 권한으로 돈다. 아무 곳에나 파일을 만들게 두지 않고,
        # 제거 프로그램이 쓰는 설치 폴더(관리자만 쓸 수 있는 곳)로 한정한다.
        if _norm(parent) != _norm(os.path.dirname(sys.executable)):
            return '결과 파일은 설치 폴더 안에만 만들 수 있습니다.'
    return None


def _write_result(path, report):
    if not path:
        return True
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=1, default=str)
        return True
    except Exception as e:
        log.error(f'결과 파일을 쓰지 못했습니다: {e}')
        return False


def run_revert_all(result_path):
    """이 앱이 바꾼 설정을 전부 되돌리고 결과를 JSON 으로 남긴다.

    Api 를 만들지 않는다. Api 를 만들면 저장된 성능 모드를 다시 적용하고
    게임 부스터 루프를 띄우기 때문에, 되돌리러 온 프로세스가 오히려 설정을 바꾼다.
    """
    report = {
        'version': 1,
        'exitCode': EXIT_ERROR,
        'error': None,
        'message': '',
        'revert': None,
        'startupMigration': None,
    }

    path_error = _check_result_path(result_path)
    if path_error:
        # 결과를 알릴 수 없으면 되돌리기도 하지 않는다. 호출한 쪽이 성패를 알 수 없게 된다.
        log.error(path_error)
        return EXIT_ERROR

    if not acquire_single_instance():
        report['error'] = 'ALREADY_RUNNING'
        report['message'] = 'APEX CARE 가 실행 중이라 되돌리지 않았습니다. 창을 닫은 뒤 다시 시도해 주세요.'
        _write_result(result_path, report)
        return EXIT_ERROR

    # 1) 저널·옛 백업 전체 복구
    try:
        from backend import perf_modes
        rev = perf_modes.revert_everything()
        if not isinstance(rev, dict):
            rev = {'success': False, 'error': 'EXCEPTION', 'message': '되돌리기 결과를 알 수 없습니다.'}
    except Exception as e:
        log.exception('되돌리기 실패')
        rev = {'success': False, 'error': 'EXCEPTION', 'message': f'되돌리는 중 오류가 났습니다: {e}'}
    report['revert'] = rev
    revert_ran = rev.get('error') not in ('UAC_REQUIRED', 'EXCEPTION')

    # 2) 구버전이 Run 값을 지우고 숨겨 둔 시작 프로그램을 작업 관리자에서 보이게(꺼진 상태 유지)
    try:
        from backend import optimizer
        migrate = getattr(optimizer, 'migrate_legacy_disabled_startup', None)
        if callable(migrate):
            mig = migrate()
            if not isinstance(mig, dict):
                mig = {'ok': False, 'migrated': [], 'failed': [], 'error': 'EXCEPTION',
                       'message': '시작 프로그램 복원 결과를 알 수 없습니다.'}
        else:
            mig = {'ok': False, 'migrated': [], 'failed': [], 'error': 'NOT_AVAILABLE',
                   'message': '이 버전에는 숨겨진 시작 프로그램 복원 기능이 없습니다.'}
    except Exception as e:
        log.exception('시작 프로그램 복원 실패')
        mig = {'ok': False, 'migrated': [], 'failed': [], 'error': 'EXCEPTION',
               'message': f'시작 프로그램 복원 중 오류가 났습니다: {e}'}
    report['startupMigration'] = mig

    if not revert_ran:
        code = EXIT_ERROR
        report['error'] = rev.get('error')
        report['message'] = rev.get('message') or '설정을 되돌리지 못했습니다.'
    elif rev.get('success') and mig.get('ok'):
        code = EXIT_OK
        report['message'] = rev.get('message') or '설정을 원래대로 되돌렸습니다.'
    else:
        code = EXIT_PARTIAL
        report['message'] = '일부 설정을 되돌리지 못했습니다.'
    report['exitCode'] = code

    if not _write_result(result_path, report):
        return EXIT_ERROR
    return code


# ─────────────────────────────────────────────
# 창 모드
# ─────────────────────────────────────────────

_cleanup_lock = threading.Lock()
_cleanup_result = None


def _fallback_cleanup():
    """Api._cleanup_on_exit 가 없을 때의 정리. 설정(booster_enabled)은 저장하지 않는다."""
    restored, failed = [], []
    try:
        from backend import game_booster
        shutdown = getattr(game_booster, 'shutdown', None)
        if callable(shutdown):
            r = shutdown(timeout=5.0) or {}
            restored.extend(r.get('restored') or [])
            failed.extend(r.get('failed') or [])
    except Exception as e:
        failed.append(f'게임 부스트 정리: {e}')
    try:
        from backend import process_boost
        r = process_boost.restore_all() or {}
        failed.extend(r.get('failed') or [])
    except Exception as e:
        failed.append(f'우선순위 복구: {e}')
    return {'ok': not failed, 'restored': restored, 'failed': failed}


def run_cleanup(api):
    """종료 정리. 몇 번을 불러도 실제 정리는 한 번만 한다."""
    global _cleanup_result
    with _cleanup_lock:
        if _cleanup_result is not None:
            return _cleanup_result
        try:
            fn = getattr(api, '_cleanup_on_exit', None) if api is not None else None
            res = fn() if callable(fn) else _fallback_cleanup()
        except Exception as e:
            log.exception('종료 정리 실패')
            res = {'ok': False, 'failed': [f'종료 정리 중 오류: {e}']}
        _cleanup_result = res if isinstance(res, dict) else {'ok': True}
        return _cleanup_result


def _describe_failed(item):
    if isinstance(item, dict):
        name = item.get('name') or item.get('label') or item.get('key') or ''
        reason = item.get('reason') or item.get('error') or ''
        return f'{name}: {reason}'.strip(': ') or str(item)
    return str(item)


def _report_cleanup_failure(res):
    """정리가 일부 실패했으면 사실대로 알린다. 조용히 끝내면 다 되돌린 줄 안다."""
    failed = res.get('failed') or []
    if res.get('ok', True) and not failed:
        return
    lines = [f'- {_describe_failed(x)}' for x in failed[:8]]
    if len(failed) > 8:
        lines.append(f'- 외 {len(failed) - 8}개')
    body = '\n'.join(lines) if lines else '- 자세한 내용을 알 수 없습니다.'
    _message('종료하면서 일부 설정을 원래대로 되돌리지 못했습니다.\n\n' + body,
             MB_OK | MB_ICONWARNING)


def _on_closing(api):
    """창이 닫히기 직전(X 버튼·Alt+F4·작업 표시줄·로그오프). False 를 돌려주면 닫기를 취소한다.

    GUI 스레드에서 돈다. 여기서 evaluate_js 를 부르면 교착되므로 네이티브 메시지 상자만 쓴다.
    """
    reason = None
    try:
        # closeWindow 가 이미 사용자 확인을 받고 닫는 중이면 다시 묻지 않는다
        if not getattr(api, '_close_confirmed', False):
            busy = getattr(api, '_busy_reason', None)
            reason = busy() if callable(busy) else None
    except Exception:
        reason = None
    if reason:
        answer = _message(
            f'{reason} 작업이 진행 중입니다.\n\n'
            '지금 닫으면 작업이 중간에 끊기고, 되돌리기 정보가 저장되지 않을 수 있습니다.\n\n'
            '그래도 닫을까요?',
            MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2)
        if answer != IDYES:
            return False
    run_cleanup(api)
    return True


def get_html_path(dev):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, 'dist_react', 'index.html')

    dist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist_react')
    if os.path.exists(os.path.join(dist_path, 'index.html')):
        return os.path.join(dist_path, 'index.html')
    # 관리자 권한 창에 로컬 포트의 페이지를 띄우면, 그 포트를 먼저 잡은 프로세스가
    # js_api(관리자 권한)를 얻는다. 개발자가 명시했을 때만 쓴다.
    if dev and not getattr(sys, 'frozen', False):
        return "http://localhost:5173"
    return None


def run_gui(dev):
    if not acquire_single_instance():
        _message('APEX CARE 가 이미 실행 중입니다.\n열려 있는 창을 사용해 주세요.')
        _activate_existing_window()
        return EXIT_OK

    html_path = get_html_path(dev)
    if not html_path:
        _message('화면 파일(dist_react\\index.html)을 찾을 수 없습니다.\n'
                 "'npm run build' 로 만든 뒤 다시 실행하거나, 개발 서버를 쓰려면 --dev 로 실행하세요.",
                 MB_OK | MB_ICONWARNING)
        return EXIT_ERROR

    import webview
    from backend.api import Api

    api = Api(None)
    # 예외로 끝나거나 창 이벤트 없이 끝나도 정리는 한다
    atexit.register(run_cleanup, api)

    window = webview.create_window(
        title=APP_TITLE,
        url=html_path,
        js_api=api,
        width=1240,
        height=840,
        resizable=False,
        frameless=True,
        easy_drag=False,
        background_color='#080c14'
    )
    api._window = window
    window.events.closing += lambda: _on_closing(api)

    # 버전이 바뀌어도 웹 저장소가 유지되도록 고정 경로를 쓴다
    app_data_path = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'APEX_CARE_DATA')
    os.makedirs(app_data_path, exist_ok=True)

    webview.start(debug=False, private_mode=False, storage_path=app_data_path)

    _report_cleanup_failure(run_cleanup(api))
    return EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(prog='APEX CARE', add_help=False)
    parser.add_argument('--revert-all', action='store_true')
    parser.add_argument('--result', default=None)
    parser.add_argument('--dev', action='store_true')
    args, _unknown = parser.parse_known_args(argv)

    if args.revert_all:
        return run_revert_all(args.result)
    return run_gui(args.dev)


if __name__ == '__main__':
    sys.exit(main())
