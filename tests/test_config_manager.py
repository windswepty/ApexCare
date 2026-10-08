"""settings.json: 동시에 써도 깨지거나 값이 사라지지 않고, 잠깐 못 읽었다고 멀쩡한 파일을 덮어쓰지 않는다."""

import json
import os
import threading
import time

import pytest

from backend import config_manager as cm


def _raw():
    with open(cm.CONFIG_FILE, encoding='utf-8') as f:
        return json.load(f)


def _seed(data):
    os.makedirs(cm.APPDATA_DIR, exist_ok=True)
    with open(cm.CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def test_concurrent_updates_are_not_lost():
    # pywebview 는 호출마다 스레드를 새로 쓴다. 읽고-고치고-쓰기가 겹치면 먼저 저장한 값이 사라졌다.
    def slow_set(i):
        def change(c):
            time.sleep(0.005)              # 읽은 뒤 저장 전에 다른 스레드가 끼어들 틈
            c[f'k{i}'] = i
        assert cm.update_config(change)

    threads = [threading.Thread(target=slow_set, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = _raw()
    assert all(data.get(f'k{i}') == i for i in range(20))
    assert not [n for n in os.listdir(cm.APPDATA_DIR) if n.endswith('.tmp')]     # 임시 파일이 남지 않는다


def test_unreadable_file_is_not_overwritten_with_defaults(monkeypatch):
    _seed({'network_tweak_backup': {'autotuning': 'normal'}, 'setup_wizard_done': True})
    before = _raw()

    def locked():
        raise cm._ReadError(PermissionError('다른 프로그램이 사용 중'))
    monkeypatch.setattr(cm, '_read_once', locked)
    monkeypatch.setattr(cm, '_RETRY_WAIT', 0)

    cfg = cm.load_config()
    assert cfg['setup_wizard_done'] is False               # 읽을 때는 기본값으로 대신하지만
    assert cm.save_config(cfg) is False                    # 그 기본값을 저장하지는 않는다
    assert cm.update_config(lambda c: c.__setitem__('ui_theme', 'stone')) is False
    assert cm.set_setup_wizard_done()['success'] is False
    assert cm.set_optimization_mode('gaming') is False

    monkeypatch.undo()
    assert _raw() == before                                # 구버전 복구 백업이 그대로다
    assert not [n for n in os.listdir(cm.APPDATA_DIR) if '.corrupt' in n]


def test_briefly_locked_file_is_read_on_retry(monkeypatch):
    _seed({'setup_wizard_done': True})
    real, calls = cm._read_once, []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise cm._ReadError(PermissionError('백신 검사 중'))
        return real()
    monkeypatch.setattr(cm, '_read_once', flaky)
    monkeypatch.setattr(cm, '_RETRY_WAIT', 0)

    assert cm.get_setup_wizard_done() is True and len(calls) == 2


@pytest.mark.parametrize('content', [b'{"booster_enabled": tr', b'[1, 2]', b'null', b'\xff\xfe\x00broken'])
def test_broken_file_is_moved_aside_not_destroyed(content):
    os.makedirs(cm.APPDATA_DIR, exist_ok=True)
    with open(cm.CONFIG_FILE, 'wb') as f:
        f.write(content)

    assert cm.load_config() == cm.DEFAULT_CONFIG
    kept = [n for n in os.listdir(cm.APPDATA_DIR) if n.startswith('settings.json.corrupt-')]
    assert len(kept) == 1
    with open(os.path.join(cm.APPDATA_DIR, kept[0]), 'rb') as f:
        assert f.read() == content                         # 손으로 살릴 수 있게 원본을 남긴다
    assert cm.set_booster_state(False) and _raw()['booster_enabled'] is False


def test_file_saved_with_bom_is_read():
    # 메모장 등으로 고쳐 저장하면 BOM 이 붙는다. 예전에는 깨진 파일로 보고 기본값으로 돌아갔다.
    os.makedirs(cm.APPDATA_DIR, exist_ok=True)
    with open(cm.CONFIG_FILE, 'w', encoding='utf-8-sig') as f:
        json.dump({'ui_theme': 'violet'}, f)
    assert cm.get_ui_theme() == 'violet'


def test_setters_report_save_result(monkeypatch):
    from backend import machine_store
    assert cm.set_optimization_mode('eco') is True and cm.get_optimization_mode() == 'eco'
    monkeypatch.setattr(cm, 'save_config', lambda c: False)
    assert cm.set_booster_state(True) is False
    assert cm.set_boost_setting('boost_disable_nagle', True)['success'] is False
    monkeypatch.setattr(machine_store, 'write', lambda name, data: False)
    assert cm.set_optimization_mode('gaming') is False
    assert cm.set_boost_restore_mode('eco') is False


# ── PC 전체 설정(성능 모드) ──────────────────────────────────

def test_mode_is_one_per_pc_and_lives_where_only_admins_can_write():
    import json as _json
    from backend import machine_store
    from tests.fakewin import REGISTRY
    assert cm.set_optimization_mode('gaming') is True
    stored = _json.loads(REGISTRY.value('HKLM', machine_store.KEY, 'Settings'))
    assert stored['optimization_mode'] == 'gaming' and stored['optimization_mode_user_set'] is True
    assert 'optimization_mode' not in _raw_json()                 # 계정 파일에는 없다


def test_old_mode_is_taken_from_the_account_file_once_and_not_again_after_uninstall():
    from backend import machine_store
    _seed({'optimization_mode': 'gaming', 'optimization_mode_user_set': True, 'ui_theme': 'stone'})
    assert cm.get_optimization_mode() == 'gaming' and cm.get_optimization_mode_user_set() is True
    assert 'optimization_mode' not in _raw_json() and _raw_json()['ui_theme'] == 'stone'

    assert cm.set_optimization_mode('standard', user_set=False)
    assert machine_store.remove()                                  # 제거 전 되돌리기가 PC 쪽 기록을 지웠다
    # 다시 설치: 옛 '게이밍' 을 다시 가져와 적용하지 않는다
    assert cm.get_optimization_mode() == 'standard' and cm.get_optimization_mode_user_set() is False


def _raw_json():
    try:
        with open(cm.CONFIG_FILE, encoding='utf-8-sig') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _locked_file(monkeypatch):
    def locked():
        raise cm._ReadError(PermissionError('다른 프로그램이 사용 중'))
    monkeypatch.setattr(cm, '_read_once', locked)
    monkeypatch.setattr(cm, '_RETRY_WAIT', 0)


def test_unreadable_settings_do_not_turn_the_booster_on(monkeypatch):
    # 사용자가 부스터를 꺼 두었는데, 앱 시작 때 파일을 잠깐 못 읽으면 기본값 '켜짐' 으로 켜지고 저장됐다
    from backend import game_booster
    _seed({'booster_enabled': False})
    _locked_file(monkeypatch)
    started = []
    monkeypatch.setattr(game_booster, 'toggle_booster', lambda on: started.append(on))
    monkeypatch.setattr(game_booster, '_recover_after_crash', lambda: None)

    assert cm.get_booster_state() is None
    game_booster.init_booster()
    assert started == []


def test_unreadable_settings_do_not_reopen_the_wizard(monkeypatch):
    _seed({'setup_wizard_done': True})
    _locked_file(monkeypatch)
    assert cm.get_setup_wizard_done() is None            # 화면은 false 일 때만 띄운다


def test_unreadable_settings_apply_no_optional_boosts(monkeypatch):
    # 사용자가 끈 '바쁜 앱 양보' 가 기본값(켜짐)으로 적용되면 안 된다
    from backend import game_booster
    _seed({'boost_tame_background': False})
    _locked_file(monkeypatch)
    game_booster._applied.clear()
    game_booster._enter_boost_mode()
    assert game_booster._applied == {} and game_booster.get_booster_status()['appliedBoosts'] == []


# ── 화면 설정(배경색·크기·움직임 줄이기) ─────────────────────

def test_ui_background_scale_and_motion_are_validated_and_saved():
    assert cm.set_ui_background('#2E1065')['success'] and cm.get_ui_background() == '#2e1065'
    assert cm.set_ui_background('red')['success'] is False and cm.get_ui_background() == '#2e1065'
    assert cm.set_ui_background('')['success'] and cm.get_ui_background() is None
    assert cm.set_ui_scale(125)['success'] and cm.get_ui_scale() == 125
    for bad in (300, 0, '110', True, None):                 # 정해 둔 크기만(True 는 1 로 통과하면 안 된다)
        assert cm.set_ui_scale(bad)['success'] is False
    assert cm.get_ui_scale() == 125
    assert cm.set_ui_reduce_motion(True)['success'] and cm.get_ui_reduce_motion() is True
    assert cm.set_ui_reduce_motion('yes')['success'] is False and cm.get_ui_reduce_motion() is True
    # 손으로 고친 이상한 값은 기본값으로 읽는다
    cm.update_config(lambda c: c.update(ui_scale=9999, ui_background='#zzzzzz', ui_reduce_motion='1'))
    assert cm.get_ui_appearance() == {'theme': 'cyan', 'accent': None, 'background': None,
                                      'scale': 100, 'reduceMotion': False, 'icon': '', 'mode': 'dark'}


def test_ui_mode_is_validated_and_reset():
    assert cm.get_ui_mode() == 'dark'                                    # 기본은 어두운 화면
    assert cm.set_ui_mode('light')['success'] and cm.get_ui_appearance()['mode'] == 'light'
    assert cm.set_ui_mode('sepia')['success'] is False and cm.get_ui_mode() == 'light'
    cm.update_config(lambda c: c.__setitem__('ui_mode', 7))
    assert cm.get_ui_mode() == 'dark'                                    # 이상한 값은 기본으로 읽는다
    cm.set_ui_mode('light')
    assert cm.reset_ui_appearance()['success'] and cm.get_ui_mode() == 'dark'


def test_reset_ui_appearance_puts_everything_back_at_once(monkeypatch):
    cm.set_ui_theme('violet')
    cm.set_ui_accent('#22d3ee')
    cm.set_ui_background('#2e1065')
    cm.set_ui_scale(110)
    cm.set_ui_reduce_motion(True)
    cm.set_ui_icon('#FF8800')
    r = cm.reset_ui_appearance()
    assert r['success'] and r['theme'] == 'cyan' and r['accent'] is None and r['background'] is None
    assert r['scale'] == 100 and r['reduceMotion'] is False and r['icon'] == ''
    monkeypatch.setattr(cm, 'save_config', lambda c: False)
    assert cm.reset_ui_appearance()['success'] is False and cm.set_ui_scale(90)['success'] is False


def test_ui_icon_accepts_only_presets_and_colors():
    for ok in ('accent', 'dark', '#FF8800', ''):
        assert cm.set_ui_icon(ok)['success'], ok
    assert cm.set_ui_icon('#ff8800')['success'] and cm.get_ui_icon() == '#ff8800'
    for bad in ('neon', '#ff88', 12, True):
        assert cm.set_ui_icon(bad)['success'] is False, bad
    assert cm.get_ui_icon() == '#ff8800'
    cm.update_config(lambda c: c.__setitem__('ui_icon', 'javascript:alert(1)'))      # 손으로 고친 값
    assert cm.get_ui_icon() == ''
