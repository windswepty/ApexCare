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
    assert cm.set_optimization_mode('eco') is True and cm.get_optimization_mode() == 'eco'
    monkeypatch.setattr(cm, 'save_config', lambda c: False)
    assert cm.set_optimization_mode('gaming') is False
    assert cm.set_booster_state(True) is False
    assert cm.set_boost_setting('boost_disable_nagle', True)['success'] is False
