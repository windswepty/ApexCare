"""src/ 가 부르는 window.pywebview.api.X 가 모두 backend/api.py 의 Api 메서드인지.

이름이 어긋나면 개발 중에는 조용히 undefined 가 되고, 사용자는 눌러도 아무 일도 없는 버튼을 본다.
프론트는 세 가지 방식으로 부른다.
  window.pywebview.api.X(...)            직접
  const api = window.pywebview && window.pywebview.api;  api.X(...)
  const api = () => (... window.pywebview.api) || null;  const a = api();  a.X(...)
"""

import inspect
import os
import re

from backend.api import Api
from tests.conftest import ROOT

SRC = os.path.join(ROOT, 'src')

_DIRECT = re.compile(r'pywebview\??\.api\??\.([A-Za-z_]\w*)')
# 오른쪽이 pywebview ... .api 로 '끝나는' 선언: 값 별칭(api) 또는 함수 별칭(api = () => ...)
# .api.X() 의 결과를 받는 변수(const res = await ...api.getX())는 별칭이 아니다.
_ALIAS = re.compile(r'(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*'
                    r'([^;\n]*pywebview[^;\n]*?\.api\b(?!\s*\??\.)[^;\n]*)')
_CALL_ALIAS = r'(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:await\s+)?{fn}\(\)'


def _source_files():
    for dirpath, _, files in os.walk(SRC):
        for f in files:
            if f.endswith(('.js', '.jsx', '.ts', '.tsx')):
                yield os.path.join(dirpath, f)


def frontend_calls():
    """{메서드 이름: [파일, ...]}"""
    found = {}
    for path in _source_files():
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        names = set(_DIRECT.findall(text))

        value_aliases, fn_aliases = set(), set()
        for name, rhs in _ALIAS.findall(text):
            (fn_aliases if '=>' in rhs else value_aliases).add(name)
        for fn in list(fn_aliases):
            value_aliases.update(re.findall(_CALL_ALIAS.format(fn=re.escape(fn)), text))
            names.update(re.findall(rf'\b{re.escape(fn)}\(\)\??\.([A-Za-z_]\w*)', text))
        for alias in value_aliases:
            names.update(re.findall(rf'(?<![\w.]){re.escape(alias)}\??\.([A-Za-z_]\w*)', text))

        for n in names:
            found.setdefault(n, []).append(os.path.relpath(path, ROOT))
    return found


def api_methods():
    return {n for n, _ in inspect.getmembers(Api, inspect.isfunction) if not n.startswith('_')}


def test_frontend_calls_are_found():
    calls = frontend_calls()
    # 세 가지 호출 방식이 모두 잡히는지 (추출기가 망가지면 아래 검사가 빈 목록으로 통과해 버린다)
    for expected in ('getSystemStats', 'markSetupWizardDone', 'setOptimizationMode',
                     'revertAllSystemChanges', 'cleanJunk', 'boostProcess'):
        assert expected in calls, expected
    assert len(calls) >= 30


def test_every_frontend_call_exists_on_api():
    missing = {n: files for n, files in frontend_calls().items() if n not in api_methods()}
    assert missing == {}, '백엔드 Api 에 없는 메서드를 프론트가 부릅니다: ' + ', '.join(
        f'{n} ({", ".join(sorted(set(f)))})' for n, f in sorted(missing.items()))
