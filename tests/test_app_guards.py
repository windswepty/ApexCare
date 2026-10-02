"""창 닫기·자기 보호·제거 안내 같은 작은 안전장치."""

import os

from backend import debloater, process_guard
from backend.api import Api
from tests.conftest import ROOT


def _api():
    # Api() 생성자는 게임 부스트를 켜고 저장된 모드를 적용한다. 여기서는 필요 없어 건너뛴다.
    return object.__new__(Api)


def test_closing_is_blocked_while_apps_are_removed_or_restored():
    api = _api()
    assert api._busy_reason() is None
    assert debloater._op_lock.acquire(blocking=False)
    try:
        assert api._busy_reason() == '기본 앱 제거·되살리기'
        assert api.closeWindow()['busy'] is True
    finally:
        debloater._op_lock.release()
    assert api._busy_reason() is None


def test_installed_exe_name_is_self_protected():
    # 설치 마법사가 Payload 를 'APEX CARE.exe' 로 복사한다. 이름으로도 자신을 지킨다.
    assert process_guard.is_protected_name('APEX CARE.exe')
    assert process_guard.is_protected_name('APEX CARE Payload.exe')


def test_uninstaller_mentions_removed_apps_it_will_not_reinstall():
    with open(os.path.join(ROOT, 'tools', 'uninstall.py'), encoding='utf-8') as f:
        src = f.read()
    assert debloater.REMOVED_NAME in src                      # 기록 파일 이름이 앱과 같다
    call = 'removed_apps = _removed_app_count()'
    assert call in src and '+ removed_note' in src          # 확인 창 문구에 붙는다
    assert src.index(call) < src.index('reverted, why = _revert_system_changes(install_dir)')


def test_maximize_fills_the_work_area_not_the_whole_screen():
    # 테두리 없는 창을 Windows 최대화하면 작업 표시줄까지 덮었다(실측 1920×1080, 작업 영역 1920×1032).
    from backend import window_frame
    moves = []
    rect = {'now': (130, 130, 1224, 801)}

    def move(hwnd, r):
        moves.append(r)
        rect['now'] = r
        return True
    kw = dict(get_rect=lambda h: rect['now'], get_work=lambda h: (0, 0, 1920, 1032), move=move)

    saved = window_frame.toggle(1, None, **kw)
    assert rect['now'] == (0, 0, 1920, 1032) and saved == (130, 130, 1224, 801)
    saved = window_frame.toggle(1, saved, **kw)
    assert rect['now'] == (130, 130, 1224, 801) and saved is None
    # 옮기지 못하면 상태를 바꾸지 않는다(다음 클릭이 엉뚱한 쪽으로 가지 않게)
    kw['move'] = lambda h, r: False
    assert window_frame.toggle(1, None, **kw) is None
    assert window_frame.toggle(1, (5, 5, 10, 10), **kw) == (5, 5, 10, 10)
    api_src = open(os.path.join(ROOT, 'backend', 'api.py'), encoding='utf-8').read()
    assert 'window_frame.toggle(' in api_src and 'toggle_fullscreen' not in api_src


def test_second_instance_exits_before_touching_anything():
    # 두 번째 인스턴스는 첫 인스턴스가 낮춘 우선순위를 '원래 값' 으로 기록하고, 게임 중인 세션을 비정상 종료
    # 잔여물로 보고 되돌렸다. Api(모드 재적용·부스터 시작)를 만들기 전에 끝나야 한다.
    with open(os.path.join(ROOT, 'main.py'), encoding='utf-8') as f:
        src = f.read()
    body = src[src.index("if __name__ == '__main__':\n    #"):]
    assert body.index('single_instance.acquire()') < body.index('Api(None)')
    assert 'sys.exit(0)' in body[:body.index('Api(None)')]


def test_single_instance_check_failure_does_not_block_start(monkeypatch):
    # 확인하지 못했다고 앱을 못 켜게 하지 않는다(fakewin 이 ctypes 를 막아 둔 상태가 그 경우다)
    from backend import single_instance
    assert single_instance.acquire('Local\\apex-test') is True
