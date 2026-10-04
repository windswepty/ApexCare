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
    assert body.index('single_instance.acquire_both()') < body.index('Api(None)')
    assert body.index('tell_other_session()') < body.index('Api(None)')
    assert body[:body.index('Api(None)')].count('sys.exit(0)') == 2


def test_single_instance_check_failure_does_not_block_start(monkeypatch):
    # 확인하지 못했다고 앱을 못 켜게 하지 않는다(fakewin 이 ctypes 를 막아 둔 상태가 그 경우다)
    from backend import single_instance
    assert single_instance.acquire('Local\\apex-test') is True
    assert single_instance.acquire_both() is None


def test_instance_in_another_windows_account_is_told_apart(monkeypatch):
    # PC 전체 상태(저널·성능 모드)는 하나라서 다른 계정(빠른 사용자 전환)의 실행도 막는다
    from backend import single_instance
    held = set()
    monkeypatch.setattr(single_instance, 'acquire', lambda name: name not in held)
    assert single_instance.acquire_both() is None
    held.add(single_instance.GLOBAL_MUTEX_NAME)                       # 다른 세션에서 실행 중
    assert single_instance.acquire_both() == 'other'
    held.add(single_instance.MUTEX_NAME)                              # 이 세션에서 실행 중
    assert single_instance.acquire_both() == 'same'
    assert single_instance.GLOBAL_MUTEX_NAME.startswith('Global\\')


def test_kill_refuses_a_process_that_took_over_the_listed_number(procs):
    # 목록을 본 뒤 그 프로세스가 끝나고 다른 프로그램이 같은 PID 를 받으면, 예전에는 그 프로그램을 끝냈다
    from backend import system_monitor
    procs.add(4321, 'notepad.exe', created=1000.0)
    procs.remove(4321)
    procs.add(4321, 'WINWORD.EXE', created=2000.0)

    r = system_monitor.kill_process(4321, created=1000.0)
    assert r['success'] is False and '같은 번호' in r['message']
    assert procs.killed == []

    r = system_monitor.kill_process(4321, created=2000.0)
    assert r['success'] and procs.killed == [(4321, 'WINWORD.EXE')]


def test_uninstall_command_without_a_folder_runs_only_from_the_windows_folder(monkeypatch, tmp_path):
    # 'MsiExec.exe /X{…}' 처럼 이름만 적힌 명령은 CreateProcess 가 현재 폴더부터 찾는다(관리자 권한 실행)
    import types
    from backend import uninstaller
    started = []
    monkeypatch.setattr(uninstaller.subprocess, 'Popen',
                        lambda args, shell=None: started.append((list(args), shell)) or types.SimpleNamespace(pid=7))
    monkeypatch.setattr(uninstaller, '_split_command', lambda s: s.split())   # CommandLineToArgvW 대신
    system32 = tmp_path / 'Windows' / 'System32'
    system32.mkdir(parents=True)
    (system32 / 'MsiExec.exe').write_bytes(b'')
    (system32 / 'rundll32.exe').write_bytes(b'')
    monkeypatch.setenv('SystemRoot', str(tmp_path / 'Windows'))

    assert uninstaller.run_uninstall('MsiExec.exe /I{1234}')['success']
    assert started.pop() == ([str(system32 / 'MsiExec.exe'), '/x{1234}'], False)
    assert uninstaller.run_uninstall('rundll32 app.dll,Uninstall')['success']
    assert started.pop() == ([str(system32 / 'rundll32.exe'), 'app.dll,Uninstall'], False)

    # Windows 폴더에 없는 이름은 실행하지 않는다
    r = uninstaller.run_uninstall('setup.exe /uninstall')
    assert r['success'] is False and '설정 → 앱' in r['message'] and started == []


def test_user_installed_uninstaller_is_not_run_with_admin_rights(monkeypatch, tmp_path):
    # 사용자 폴더의 제거 프로그램(Discord 의 Update.exe 등)이나 이 계정에만 등록된 프로그램은 일반 권한 프로그램이
    # 바꿔 넣을 수 있다. 관리자 권한인 이 앱이 실행하면 그 권한을 넘겨준다. Windows 설정 → 앱으로 안내한다
    import types
    from backend import uninstaller
    started, opened = [], []
    monkeypatch.setattr(uninstaller.subprocess, 'Popen',
                        lambda args, shell=None: started.append(list(args)) or types.SimpleNamespace(pid=7))
    monkeypatch.setattr(uninstaller, '_split_command', lambda s: s.split('|'))
    monkeypatch.setattr(uninstaller, '_open_apps_settings', lambda: opened.append(1))
    pf = tmp_path / 'Program Files'
    user = tmp_path / 'Users' / 'me' / 'AppData' / 'Local' / 'Discord'
    for d in (pf / 'Foo', user):
        d.mkdir(parents=True)
    (pf / 'Foo' / 'uninst.exe').write_bytes(b'')
    (user / 'Update.exe').write_bytes(b'')
    monkeypatch.setenv('ProgramFiles', str(pf))

    r = uninstaller.run_uninstall(str(user / 'Update.exe') + '|--uninstall')
    assert r['success'] is False and r['needsSettings'] and started == [] and opened == [1]
    r = uninstaller.run_uninstall(str(pf / 'Foo' / 'uninst.exe') + '|/S', user_scope=True)   # HKCU 에 등록된 항목
    assert r['success'] is False and started == []
    assert uninstaller.run_uninstall(str(pf / 'Foo' / 'uninst.exe') + '|/S')['success']
    assert started == [[str(pf / 'Foo' / 'uninst.exe'), '/S']]


def test_installer_and_uninstaller_windows_all_carry_the_app_icon():
    # 마법사 창에만 아이콘을 걸어, 중간에 뜨는 확인·경고 창과 제거 프로그램 창은 Windows 기본 아이콘으로 보였다
    setup = open(os.path.join(ROOT, 'tools', 'setup_wizard.py'), encoding='utf-8').read()
    un = open(os.path.join(ROOT, 'tools', 'uninstall.py'), encoding='utf-8').read()
    assert 'app.setWindowIcon(_app_icon())' in setup and 'app.setWindowIcon(_app_icon())' in un
    # *.spec 은 .gitignore 대상이라 새 클론·푸시 전 검사에는 없다(build_all.bat 도 그렇게 안내한다). 있을 때만 본다
    spec_path = os.path.join(ROOT, 'APEX CARE Uninstaller.spec')
    if os.path.exists(spec_path):
        spec = open(spec_path, encoding='utf-8').read()
        assert "('public/setup_icon.ico', '.')" in spec              # 제거 프로그램 exe 안에 아이콘 파일이 있어야 한다
