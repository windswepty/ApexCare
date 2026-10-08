"""영어 화면: 사전이 화면의 모든 문장을 담는지, 값 자리가 맞는지, 화면 밖 문장(보고서·안내 창)도 바뀌는지."""
import json
import os
import re

from backend import report, ui_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(ROOT, 'src', 'locales')
HAN = re.compile('[가-힣]')
_TR = re.compile(r"""\btr\(\s*("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')""")


def _load(name):
    with open(os.path.join(LOCALES, name), encoding='utf-8') as f:
        return json.load(f)


def _js_string(lit):
    if lit[0] == "'":
        lit = '"' + lit[1:-1].replace("\\'", "'").replace('"', '\\"') + '"'
    return json.loads(lit)


def _used_keys():
    keys = {}
    for base, _dirs, files in os.walk(os.path.join(ROOT, 'src')):
        for name in files:
            if name.endswith(('.js', '.jsx')) and name != 'i18n.js':      # i18n.js 는 설명 주석의 예만 있다
                path = os.path.join(base, name)
                with open(path, encoding='utf-8') as f:
                    for m in _TR.finditer(f.read()):
                        keys.setdefault(_js_string(m.group(1)), name)
    return keys


def _holes(text):
    return sorted(re.findall(r'(?<!\{)\{\d+\}(?!\})', text))


def test_every_screen_sentence_has_an_english_entry():
    en = _load('en.json')
    keys = _used_keys()
    assert len(keys) > 700
    missing = sorted(f'{f}: {k}' for k, f in keys.items() if k not in en)
    assert not missing, missing[:20]


def test_english_entries_keep_the_value_slots():
    en = _load('en.json')
    back = _load('en-backend.json')
    pairs = list(en.items()) + list(back['exact'].items()) + [tuple(p) for p in back['patterns']]
    bad = [(k, v) for k, v in pairs if _holes(k) != _holes(v)]
    assert not bad, bad[:10]
    assert all(not _holes(k) for k in back['exact'])
    assert all(_holes(k) for k, _v in back['patterns'])


def test_english_text_is_english():
    en = _load('en.json')
    back = _load('en-backend.json')
    values = list(en.values()) + list(back['exact'].values()) + [v for _k, v in back['patterns']]
    korean = [v for v in values if HAN.search(v) and v != '언어 · Language']
    assert not korean, korean[:10]


def test_translate_matches_sentences_patterns_and_parts():
    t = ui_text.translate
    assert t('대기 메모리를 비웠습니다.', 'en') == 'Standby memory cleared.'
    assert t('대기 메모리를 비웠습니다.', 'ko') == '대기 메모리를 비웠습니다.'
    # 문형의 값도 사전에 있으면 함께 바뀐다
    assert t("'메모장' 을 껐습니다. 다음 로그인부터 적용됩니다.", 'en') == "Turned off '메모장'. Takes effect from the next sign-in."
    assert t('게이밍 모드를 적용했지만 2개 항목이 실패했습니다.', 'en') == 'Gaming mode applied, but 2 items failed.'
    # 이어 붙인 문장은 구분자로 나눠 바꾼다
    assert t('시간 초과 — 실패', 'en') == 'Timed out — Failed'
    # 사전에 없는 문장은 그대로(빈칸·키 이름을 만들지 않는다)
    assert t('사전에 없는 문장', 'en') == '사전에 없는 문장'
    assert t('  정상  ', 'en') == '  Healthy  '
    assert t(None, 'en') is None


def test_language_follows_the_saved_choice(monkeypatch):
    from backend import config_manager
    monkeypatch.setattr(config_manager, 'get_ui_language', lambda: 'en')
    assert ui_text.language() == 'en'
    monkeypatch.setattr(config_manager, 'get_ui_language', lambda: None)
    assert ui_text.language() in ('ko', 'en')            # 고른 적이 없으면 Windows 표시 언어(가짜 Windows 에서는 읽지 못해 한국어)


def test_report_in_english_has_no_korean_for_known_values():
    data = {
        'stats': {'osInfo': 'Windows 11', 'cpuModel': 'CPU', 'cpuCores': 8, 'cpuThreads': 16, 'gpuModel': None,
                  'ramInstalledGB': 16, 'ramTotalGB': 15.8,
                  'drives': [{'label': 'C:', 'system': True, 'usedGB': 10, 'totalGB': 100, 'freeGB': 90, 'percent': 10}]},
        'disks': {'ok': True, 'disks': [{'name': 'SSD', 'health': '주의', 'media': 'SSD', 'bus': 'NVMe', 'letters': ['C:'],
                                         'wearPct': 3, 'temperatureC': 40, 'powerOnHours': 1200, 'mediaErrors': 0,
                                         'warnings': ['온도가 기준을 벗어났습니다'], 'nvme': {'dataWrittenBytes': 2e12}}]},
        'boots': {'boots': [{'at': '2026-10-01T09:00:00', 'seconds': 20}], 'stale': None},
        'battery': {'batteries': [{'name': 'BAT', 'healthPct': 90, 'cycles': 100}]},
        'changes': {'k': {'why': '정책: <x>'}},
    }
    html_en = report.build_html(data, lang='en')
    assert '<html lang="en">' in html_en and 'PC status report' in html_en
    assert not HAN.search(html_en), HAN.findall(html_en)[:20]
    assert 'class="warn">Warning<' in html_en                  # 상태 색은 한국어 값으로 정하고 글자만 바꾼다
    assert 'Policy: &lt;x&gt;' in html_en                     # 바꾼 뒤에도 이스케이프한다
    html_ko = report.build_html(data)
    assert '<html lang="ko">' in html_ko and '온도가 기준을 벗어났습니다' in html_ko and 'Policy' not in html_ko


def test_out_of_screen_text_is_bundled_and_used():
    with open(os.path.join(ROOT, 'APEX CARE Payload.spec'), encoding='utf-8') as f:
        spec = f.read()
    assert "'backend.ui_text'" in spec
    assert "('src/locales/en.json', 'locales')" in spec and "('src/locales/en-backend.json', 'locales')" in spec
    with open(os.path.join(ROOT, 'backend', 'single_instance.py'), encoding='utf-8') as f:
        assert 'ui_text.translate(OTHER_SESSION_MESSAGE' in f.read()
    assert ui_text.translate(__import__('backend.single_instance', fromlist=['x']).OTHER_SESSION_MESSAGE, 'en').startswith(
        'APEX CARE is running')


def test_uninstall_result_is_written_in_the_screen_language(monkeypatch):
    from backend import uninstall_prep
    res = {'success': False, 'steps': [], 'remaining': None,
           'failed': [{'name': '시스템 설정 되돌리기', 'ok': False, 'detail': '관리자 권한이 필요합니다.'}]}
    monkeypatch.setattr(ui_text, 'language', lambda: 'en')
    out = uninstall_prep._in_ui_language(res)
    assert out['failed'][0]['name'] == 'Undo system settings'
    assert out['failed'][0]['detail'] == 'Administrator rights are required.'
    assert out['success'] is False and res['failed'][0]['name'] == '시스템 설정 되돌리기'   # 원본·성패는 그대로
    monkeypatch.setattr(ui_text, 'language', lambda: 'ko')
    assert uninstall_prep._in_ui_language(res) is res
    with open(os.path.join(ROOT, 'backend', 'uninstall_prep.py'), encoding='utf-8') as f:
        assert '_write_result(_in_ui_language(res))' in f.read()


def test_installer_and_uninstaller_speak_both_languages():
    # 두 프로그램은 앱 사전을 싣지 않고 문장마다 두 언어를 함께 적는다. 고르는 규칙은 앱과 같다(고른 언어 → Windows 표시 언어).
    for name in ('setup_wizard.py', 'uninstall.py'):
        with open(os.path.join(ROOT, 'tools', name), encoding='utf-8') as f:
            src = f.read()
        assert 'def _english():' in src and '"ui_language"' in src and 'GetUserDefaultUILanguage' in src
        calls = re.findall(r'(?:setTitle|setSubTitle|QLabel|QCheckBox|QRadioButton|setWindowTitle|setText)\(\s*"', src)
        assert not calls, f'{name}: 한 언어로만 적힌 화면 문장 {calls}'
    with open(os.path.join(ROOT, 'tools', 'sandbox', 'real_checks.py'), encoding='utf-8') as f:
        checks = f.read()
    assert 'Uninstall APEX CARE' in checks and 'APEX CARE Setup' in checks
