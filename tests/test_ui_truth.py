"""화면은 사실만 말한다: 실제로 바뀌지 않은 것을 바뀐 것처럼 보여 주지 않는다."""

import os
import re

from tests.conftest import ROOT


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_mode_is_switched_only_where_it_is_really_applied():
    # 헤더의 표준·게이밍·에코 스위치는 화면의 선택만 바꿔, '게이밍' 으로 보이는데 PC 는 에코로 돌았다.
    # 모드 표시를 바꾸는 곳은 실제로 적용(setOptimizationMode)하거나 백엔드에서 읽는(getOptimizationMode) 곳뿐이어야 한다.
    comp_dir = os.path.join(ROOT, 'src', 'components')
    for f in os.listdir(comp_dir):
        if not f.endswith('.jsx'):
            continue
        src = _read(os.path.join('src', 'components', f))
        if re.search(r'\bsetCurrentMode\(', src):
            assert 'setOptimizationMode' in src and 'getOptimizationMode' in src, f
    header = _read('src/components/Header.jsx')
    assert 'setCurrentMode' not in header and "'gaming'" not in header
    assert 'setCurrentMode=' not in re.search(r'<Header[^>]*>', _read('src/App.jsx'), re.S).group(0)


def test_no_invented_progress_or_remaining_time():
    # SFC·DISM·잔여물 정리는 진행률을 알려 주지 않는다. 예전에는 타이머로 %를 올리고 '예상 남은 시간' 을 셌다.
    comp_dir = os.path.join(ROOT, 'src', 'components')
    for f in os.listdir(comp_dir):
        if f.endswith('.jsx'):
            src = _read(os.path.join('src', 'components', f))
            assert not re.search(r'set\w*Progress\(\s*\w+\s*=>\s*\(\s*\w+\s*<\s*99', src), f
            assert '예상 남은 시간' not in src, f


def test_result_toasts_follow_the_result():
    storage = _read('src/components/StorageCenter.jsx')
    assert "st?.status === 'success'" in storage              # TRIM: 실패·진행 중을 '마쳤습니다' 로 보이지 않는다
    uninst = _read('src/components/Uninstaller.jsx')
    assert '완벽 삭제 및 잔여 파일 정리가 완료' not in uninst and 'failedCount > 0' in uninst


def test_descriptions_do_not_promise_what_the_code_does_not_do():
    # 잔여물 정리는 고른 폴더만 휴지통으로 보낸다(레지스트리는 건드리지 않는다).
    # SFC·DISM 은 시스템 파일 손상만 고친다. 블루스크린을 '원천 방지' 하지 않는다.
    assert '레지스트리 및 찌꺼기 파일까지 완벽하게' not in _read('src/components/Uninstaller.jsx')
    assert '원천 방지' not in _read('src/components/DriverUpdater.jsx')


def test_uninstall_button_asks_first():
    # Squirrel 계열(Update.exe --uninstall)은 확인 창 없이 바로 지운다. 마우스를 올리면 나오는 버튼이라 잘못 누르기 쉽다.
    src = _read('src/components/Uninstaller.jsx')
    body = src[src.index('const handleUninstall'):]
    body = body[:body.index('\n  };\n')]
    assert body.index('window.confirm(') < body.index('a.uninstallApp(')
    assert 'launchingRef.current) return;' in body


def test_restore_center_shows_failure_reasons_not_a_false_admin_hint():
    src = _read('src/components/RestoreCenter.jsx')
    assert '관리자 권한으로 실행하면 해결됩니다' not in src      # 이 앱은 늘 관리자 권한으로 돈다
    assert 'f.reason' in src


def test_dashboard_keeps_live_values_updating_during_one_click():
    src = _read('src/components/Dashboard.jsx')
    assert 'usePolling(fetchRealStats, 3000, active);' in src
    assert '!isScanning);' not in src


def test_tabs_reread_state_when_opened_again():
    app = _read('src/App.jsx')
    assert "<StartupManager active={activeTab === 'startup'}" in app
    assert 'if (active) refresh();' in _read('src/components/PerformanceModes.jsx')
    assert 'wasActive.current' in _read('src/components/StartupManager.jsx')


def test_same_name_data_folders_are_not_preselected_and_failures_stay_on_screen():
    # AppData·ProgramData 의 같은 이름 폴더는 설정·저장 데이터일 수 있다(OBS 장면·프로필). 미리 고르지 않는다.
    src = _read('src/components/Uninstaller.jsx')
    assert "items.filter((l) => l.confidence === 'certain')" in src
    assert 'AppData·ProgramData 의 같은 이름 폴더' in src and '설정·저장 데이터일 수 있습니다' in src
    # 정리에 실패하면 화면에 남아 다시 시도할 수 있다(제거가 끝난 프로그램은 목록에서 사라져 돌아갈 길이 없었다)
    body = src[src.index('const handleCleanLeftovers'):]
    body = body[:body.index('\n  };\n')]
    assert 'failed.length === 0' in body and 'failReason' in body


def test_nested_lists_scroll_with_the_mouse_wheel():
    # Lenis 가 휠을 막아 프로그램 목록·남은 폴더 확인 목록·대용량 파일 결과를 휠로 내려 볼 수 없었다
    assert 'allowNestedScroll: true' in _read('src/smoothScroll.js')


def test_results_and_dialogs_reach_screen_readers_and_keyboard():
    app = _read('src/App.jsx')
    assert 'aria-live="polite"' in app and "role={toast.type === 'error' ? 'alert' : undefined}" in app
    assert 'aria-label="알림 닫기"' in app
    modal = _read('src/components/SettingsModal.jsx')
    assert 'role="dialog" aria-modal="true"' in modal and "e.key === 'Escape'" in modal
    assert 'role="switch"' in _read('src/components/GameBooster.jsx')
    storage = _read('src/components/StorageCenter.jsx')
    assert storage.count('aria-pressed=') >= 4
    dash = _read('src/components/Dashboard.jsx')
    assert 'aria-label="성공"' in dash and 'aria-label="실패"' in dash and 'aria-label="중지됨"' in dash


def test_window_can_always_be_closed():
    # 창 테두리가 없다. 제목 표시줄이 로딩·설정 화면에 가려지거나 오류 화면에 없으면 닫을 방법이 없었다
    assert 'relative z-[60] flex-shrink-0' in _read('src/App.jsx')
    eb = _read('src/components/ErrorBoundary.jsx')
    assert '앱 닫기' in eb and 'closeWindow' in eb and 'pywebview-drag-region' in eb


def test_dashboard_says_what_it_knows():
    dash = _read('src/components/Dashboard.jsx')
    assert "state === 'unavailable'" in dash and 'renderLineGraph(gpuHistory, gpuState)' in dash
    assert '하드웨어 예약' in dash and '· 사용 가능 ${usable' not in dash
    assert "current_task: ''" in dash                      # 새 실행이 지난 실행의 '완료 100%' 로 시작하지 않는다
    assert 'followPendingStep' in dash and 'getTrimStatus' in dash


def test_nagle_option_says_when_it_applies():
    gb = _read('src/components/GameBooster.jsx')
    assert '레지스트리 영구 변경' not in gb and '게임 동안만 레지스트리에 기록' in gb
    assert '재부팅하거나 네트워크를 다시 연결할 때' in gb


def test_settings_dialog_keeps_tab_inside():
    # Tab·Shift+Tab 이 설정 창 안에서만 돈다(가려진 창 닫기 버튼으로 가지 않는다)
    modal = _read('src/components/SettingsModal.jsx')
    assert "e.key !== 'Tab'" in modal and 'dialogRef.current.querySelectorAll(FOCUSABLE)' in modal
    assert '(e.shiftKey ? last : first).focus()' in modal and 'ref={dialogRef}' in modal


def test_dashboard_does_not_wait_forever_for_values_it_could_not_read():
    # 첫 응답 뒤에도 값이 없으면 '측정 중'·'…' 가 아니라 읽지 못했다고 보여준다
    dash = _read('src/components/Dashboard.jsx')
    assert "pctText(diskUsage, loaded ? 'unavailable' : undefined)" in dash
    assert "pctText(ramUsage, loaded ? 'unavailable' : undefined)" in dash
    assert "return info.cpuModel !== '확인 중…' ? '?' : '…';" in dash
    assert "sysInfo.cpuModel !== '확인 중…' ? '?' : '…'" in dash
    assert "if (stats && stats.error)" in dash and "cpuModel: '읽지 못함'" in dash


def test_restore_center_names_what_failed():
    src = _read('src/components/RestoreCenter.jsx')
    assert "{f.what ? `${f.what}: ` : ''}{f.reason || f.key}" in src


def test_debloater_says_which_apps_cannot_be_restored():
    src = _read('src/components/Debloater.jsx')
    assert 'setRestorable(r?.restorable || {})' in src
    assert '제거하면 Windows 가 설치 파일까지 지웁니다' in src            # 확인 창
    assert '제거하면 설치 파일도 지워져 되살릴 수 없음' in src             # 항목 표시
    assert "이 계정에서 제거하고(아래 '제거한 앱' 에서 되살릴 수 있습니다)" not in src


def test_choosing_a_theme_changes_the_whole_ui():
    # 직접 지정한 강조색이 남아 모든 색 조합을 덮어써, 색 조합을 바꿔도 화면이 그대로였다(사용자 보고).
    modal = _read('src/components/SettingsModal.jsx')
    assert "{ id, accent: null, background: null }" in modal
    assert "api.setUiAccent('')" in modal and "api.setUiBackground('')" in modal
    assert '[isOpen, themeId]' in modal                        # 입력 칸도 새 색 조합의 강조색으로
    # 배경·패널(무채색 어두운 단계)도 색 조합마다 물든다. 예전에는 거의 같은 검정·회색이었다
    theme = _read('src/theme.js')
    assert 'tinted(TW.zinc, TW.violet' in theme and 'tinted(TW.slate, TW.blue' in theme
    assert "black: '#000000',\n  },\n  {\n    id: 'graphite'" in theme       # 기본(시안)은 그대로


def test_display_settings_are_applied_everywhere():
    # 배경색·글자 크기·움직임 줄이기: 첫 화면(main.jsx 캐시)과 저장 값(App.jsx) 모두에 적용한다
    main = _read('src/main.jsx')
    app = _read('src/App.jsx')
    assert 'applyTheme(cached.id, cached.accent, cached.background)' in main and 'applyDisplay(cached)' in main
    assert 'getUiAppearance()' in app and 'applyDisplay({ scale: saved?.scale' in app
    # 글자 크기는 rem 으로 바뀐다. 픽셀로 고정한 글자는 크기 설정을 따르지 않는다
    for f in os.listdir(os.path.join(ROOT, 'src', 'components')):
        assert 'text-[10px]' not in _read(os.path.join('src', 'components', f)), f
        assert 'text-[11px]' not in _read(os.path.join('src', 'components', f)), f
    assert '.reduce-motion' in _read('src/index.css')
    assert "classList.contains('reduce-motion')" in _read('src/smoothScroll.js')


def test_one_broken_tab_does_not_take_down_the_app():
    # 예전에는 한 탭의 오류(예: 성능 모드 목록이 null)가 앱 전체를 오류 화면으로 바꿔 '되돌리기' 탭에도 갈 수 없었다
    app = _read('src/App.jsx')
    assert app.count('<ErrorBoundary compact>') == 11
    assert 'this.props.compact' in _read('src/components/ErrorBoundary.jsx')
    assert 'Array.isArray(list) ? list : []' in _read('src/components/PerformanceModes.jsx')


def test_screens_follow_the_theme_and_korean_is_not_in_a_coding_font():
    for f in os.listdir(os.path.join(ROOT, 'src', 'components')):
        src = _read(os.path.join('src', 'components', f))
        # 화면 고유색(보라 그라데이션 등)은 색 조합을 무시했다. 강조색(cyan = 테마 변수)을 쓴다
        assert 'from-purple' not in src and 'to-indigo' not in src and 'to-pink' not in src, f
        assert 'uppercase tracking-widest' not in src, f              # 한글에 영문 대문자용 넓은 자간
    cfg = _read('tailwind.config.cjs')
    assert 'mono:' in cfg and '"Malgun Gothic"' in cfg               # 고정폭 글꼴 안의 한글은 맑은 고딕
