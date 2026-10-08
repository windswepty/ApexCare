"""
화면 밖으로 나가는 문장(저장하는 보고서, 앱이 뜨기 전에 띄우는 안내 창)의 영어 번역.

화면 문장은 src/i18n.js 가 바꾼다. 이 모듈은 같은 사전(src/locales/en.json·en-backend.json)과 같은 방식
(문장 그대로 → 문형 → 구분자로 나눠서)으로 바꾼다. 사전에 없는 문장은 한국어 그대로 둔다.
exe 에서는 사전이 locales/ 에 함께 묶인다(APEX CARE Payload.spec 의 datas).
"""

import json
import logging
import os
import re
import sys

log = logging.getLogger('UiText')

_HAN = re.compile('[가-힣]')
_SEPARATORS = ['\n', ' — ', '; ', ' / ', ': ', ' · ', ', ']
_dict = None


def _locales_dir():
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return os.path.join(base, 'locales')
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'locales')


def _load():
    global _dict
    if _dict is not None:
        return _dict
    exact, patterns = {}, []
    try:
        d = _locales_dir()
        with open(os.path.join(d, 'en.json'), encoding='utf-8') as f:
            exact.update(json.load(f))
        with open(os.path.join(d, 'en-backend.json'), encoding='utf-8') as f:
            back = json.load(f)
        exact.update(back.get('exact') or {})
        for ko, out in back.get('patterns') or []:
            parts = re.split(r'(\{\d+\})', ko)
            order, rx = [], []
            for p in parts:
                m = re.fullmatch(r'\{(\d+)\}', p)
                if m:
                    order.append(int(m.group(1)))
                    rx.append(r'([\s\S]*?)')
                else:
                    rx.append(re.escape(p))
            weight = sum(len(p) for p in parts if not re.fullmatch(r'\{\d+\}', p))
            patterns.append((re.compile('^' + ''.join(rx) + '$'), order, out, weight))
        patterns.sort(key=lambda p: -p[3])
    except (OSError, ValueError) as e:
        log.warning(f"번역 사전을 읽지 못해 한국어로 둡니다: {e}")
    _dict = (exact, patterns)
    return _dict


def _fill(text, args):
    def rep(m):
        s = m.group(0)
        if s == '{{':
            return '{'
        if s == '}}':
            return '}'
        i = int(m.group(1))
        v = args.get(i)
        return '' if v is None else str(v)
    return re.sub(r'\{\{|\}\}|\{(\d+)\}', rep, text)


def translate(text, lang='en', _depth=0):
    """lang 이 'en' 이면 사전으로 바꾼 문장, 아니면 그대로."""
    if lang != 'en' or not isinstance(text, str) or not _HAN.search(text) or _depth > 6:
        return text
    exact, patterns = _load()
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    core = text.strip()
    if core in exact:
        return lead + exact[core] + trail
    for rx, order, out, _w in patterns:
        m = rx.match(core)
        if not m:
            continue
        args = {idx: translate(m.group(k + 1), lang, _depth + 1) for k, idx in enumerate(order)}
        return lead + _fill(out, args) + trail
    for sep in _SEPARATORS:
        if sep in core:
            joined = sep.join(translate(s, lang, _depth + 1) for s in core.split(sep))
            if joined != core:
                return lead + joined + trail
    return text


def language():
    """화면 언어: 고른 값이 있으면 그것, 없으면 Windows 표시 언어(한국어가 아니면 영어). 화면(App.jsx)과 같은 규칙."""
    try:
        from backend import config_manager
        chosen = config_manager.get_ui_language()
        if chosen:
            return chosen
    except Exception as e:
        log.debug(f"화면 언어 설정을 읽지 못했습니다: {e}")
    try:
        import ctypes
        lang_id = ctypes.WinDLL('kernel32').GetUserDefaultUILanguage()
        return 'ko' if (lang_id & 0x3FF) == 0x12 else 'en'       # LANG_KOREAN
    except Exception:
        return 'ko'
