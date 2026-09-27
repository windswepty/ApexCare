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
    assert src.index(call) < src.index('_revert_system_changes(install_dir)')
