"""game_booster: 적용한 것만 정확히 되돌리고, 끝나면 게임 전 상태로."""

import pytest

from backend import config_manager, game_booster, perf_modes
from backend import system_state as ss
from tests import fakewin
from tests.fakewin import POWER, REGISTRY

NAGLE = game_booster._NAGLE_BASE
A = '{aaaaaaaa-0000-0000-0000-000000000001}'
B = '{bbbbbbbb-0000-0000-0000-000000000002}'


def _settings(**kw):
    cfg = config_manager.load_config()
    cfg.update({'boost_timer_resolution': False, 'boost_tame_background': False,
                'boost_disable_nagle': False, 'boost_auto_power_mode': False})
    cfg.update(kw)
    assert config_manager.save_config(cfg)


def _adapters():
    REGISTRY.seed('HKLM', f'{NAGLE}\\{A}', 'TcpAckFrequency', 2)     # 사용자가 넣어 둔 값
    REGISTRY.seed_key('HKLM', f'{NAGLE}\\{B}')                       # 값 없음


def test_nagle_is_restored_to_original_values():
    _adapters()
    _settings(boost_disable_nagle=True)

    game_booster._enter_boost_mode()
    for iface in (A, B):
        assert REGISTRY.value('HKLM', f'{NAGLE}\\{iface}', 'TcpAckFrequency') == 1
        assert REGISTRY.value('HKLM', f'{NAGLE}\\{iface}', 'TCPNoDelay') == 1

    game_booster._exit_boost_mode()

    assert REGISTRY.value('HKLM', f'{NAGLE}\\{A}', 'TcpAckFrequency') == 2
    assert REGISTRY.get('HKLM', f'{NAGLE}\\{A}', 'TCPNoDelay') is None
    assert REGISTRY.get('HKLM', f'{NAGLE}\\{B}', 'TcpAckFrequency') is None
    assert REGISTRY.get('HKLM', f'{NAGLE}\\{B}', 'TCPNoDelay') is None
    assert ss.pending_changes() == {}


@pytest.mark.usefixtures('as_admin')      # 관리자가 아니면 모드 되돌리기가 조용히 건너뛰어 회귀를 못 잡는다
def test_things_not_applied_are_not_touched_at_teardown():
    _adapters()
    REGISTRY.seed('HKLM', f'{NAGLE}\\{A}', 'TCPNoDelay', 1)            # 사용자가 직접 끈 Nagle
    ss.set_registry('HKLM', r'SOFTWARE\Other', 'X', 1, group='perf_mode')   # 다른 기능의 기록
    _settings()                                                     # 게임 시작 때는 전부 꺼짐
    game_booster._booster_state['active'] = True
    game_booster._enter_boost_mode()
    writes_before = list(REGISTRY.writes)

    # 게임 도중 사용자가 Nagle 끄기·전원 모드를 켰다. 적용한 적 없으니 되돌릴 것도 없다.
    _settings(boost_disable_nagle=True, boost_auto_power_mode=True)
    game_booster._teardown()

    assert REGISTRY.writes == writes_before
    assert REGISTRY.value('HKLM', f'{NAGLE}\\{A}', 'TCPNoDelay') == 1
    assert set(ss.pending_changes()) == {r'reg:HKLM\SOFTWARE\Other\X'}
    assert POWER.activations == []


@pytest.mark.usefixtures('as_admin')
def test_gaming_power_mode_returns_to_pre_game_mode():
    for plan in POWER.plans:
        POWER.seed_value(plan, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN, 7)
        POWER.seed_value(plan, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX, 90)
        POWER.seed_value(plan, ss.SUB_PROCESSOR, ss.CPMINCORES, 30)
        POWER.seed_value(plan, ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND, 1)
    assert perf_modes.apply_mode('eco', user_set=True)['success']
    assert POWER.active == fakewin.PLAN_POWER_SAVER
    _settings(boost_auto_power_mode=True)

    game_booster._enter_boost_mode()
    assert POWER.active == fakewin.PLAN_HIGH_PERF
    assert config_manager.get_optimization_mode() == 'eco'          # 저장된 모드는 그대로
    assert config_manager.get_boost_restore_mode() == 'eco'          # 비정상 종료 대비 기록
    assert game_booster.power_mode_overridden()

    game_booster._exit_boost_mode()

    assert POWER.active == fakewin.PLAN_POWER_SAVER
    assert POWER.get(fakewin.PLAN_HIGH_PERF, ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN) == 7
    assert config_manager.get_optimization_mode() == 'eco'
    assert config_manager.get_boost_restore_mode() is None
    assert not game_booster.power_mode_overridden()


def test_shutdown_keeps_booster_enabled_setting():
    _adapters()
    _settings(boost_disable_nagle=True, booster_enabled=True)
    game_booster._booster_state['enabled'] = True
    game_booster._booster_state['active'] = True
    game_booster._enter_boost_mode()

    game_booster.shutdown(timeout=1)

    assert config_manager.get_booster_state() is True
    assert config_manager.load_config()['booster_enabled'] is True
    # 종료 경로는 적용한 것을 지금 이 자리에서 되돌린다
    assert REGISTRY.value('HKLM', f'{NAGLE}\\{A}', 'TcpAckFrequency') == 2
    assert ss.pending_changes() == {}


@pytest.mark.usefixtures('as_admin')
def test_leftovers_from_crashed_session_are_cleaned_up():
    for plan in POWER.plans:
        for sub, setting in ((ss.SUB_PROCESSOR, ss.PROCTHROTTLEMIN), (ss.SUB_PROCESSOR, ss.PROCTHROTTLEMAX),
                             (ss.SUB_PROCESSOR, ss.CPMINCORES), (ss.SUB_USB, ss.USB_SELECTIVE_SUSPEND)):
            POWER.seed_value(plan, sub, setting, 50)
    _adapters()
    _settings(boost_disable_nagle=True, boost_auto_power_mode=True)
    config_manager.set_optimization_mode('standard', user_set=True)
    # 지난 세션: 게임 중 부스트 적용 → 앱이 죽어서 되돌리지 못했다
    game_booster._enter_boost_mode()
    assert POWER.active == fakewin.PLAN_HIGH_PERF
    game_booster._applied.clear()                                   # 프로세스가 죽으면 메모리 기록도 사라진다

    game_booster._recover_after_crash()

    assert POWER.active == fakewin.PLAN_BALANCED
    assert REGISTRY.value('HKLM', f'{NAGLE}\\{A}', 'TcpAckFrequency') == 2
    assert REGISTRY.get('HKLM', f'{NAGLE}\\{B}', 'TCPNoDelay') is None
    assert ss.pending_changes() == {}
    assert config_manager.get_boost_restore_mode() is None
    assert config_manager.get_optimization_mode() == 'standard'


def test_crash_recovery_with_nothing_left_changes_nothing():
    _adapters()
    game_booster._recover_after_crash()
    assert REGISTRY.writes == [] and POWER.activations == []


def test_uwp_app_in_front_is_recognised_as_the_app_in_use():
    # UWP 앱의 바깥 창은 ApplicationFrameHost 가 가진다. 앱은 그 안의 자식 창을 가진 별도 프로세스다.
    names = {10: 'ApplicationFrameHost.exe', 20: 'Microsoft.Media.Player.exe', 30: 'chrome.exe'}
    pid = game_booster._foreground_app_pid(
        'frame', window_pid=lambda h: 10, child_pids=lambda h: [10, 20], name_of=names.get)
    assert pid == 20                       # 예전에는 10(틀) 이라 보고 있는 앱이 '바쁜 백그라운드 앱' 이 됐다
    assert game_booster._foreground_app_pid(
        'win', window_pid=lambda h: 30, child_pids=lambda h: [31], name_of=names.get) == 30
