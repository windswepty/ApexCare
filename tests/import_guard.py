"""
fakewin 없이 backend 를 import 하지 못하게 막는 문지기.

fakewin 과 따로 둔다. fakewin 설치가 빠지거나 실패해도(누가 conftest 를 고쳤거나,
테스트 파일을 python 으로 직접 돌렸거나) 이 문지기는 그대로 남아 backend import 를 막는다.
윈도우 개발 PC 에서 진짜 winreg·전원 API 를 쥔 backend 가 테스트에 쓰이는 일이 없게 한다.
"""

import importlib.abc
import sys

GUARDED = 'backend'


class BackendImportBlocked(ImportError):
    pass


def fakewin_ready():
    fw = sys.modules.get('tests.fakewin')
    return bool(fw is not None and getattr(fw, 'INSTALLED', False)
                and sys.modules.get('winreg') is getattr(fw, 'winreg', None))


class _Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == GUARDED or fullname.startswith(GUARDED + '.'):
            if not fakewin_ready():
                raise BackendImportBlocked(
                    f"'{fullname}' 를 가짜 Windows(tests/fakewin.py) 없이 import 하려 했습니다. "
                    "테스트가 실제 레지스트리·전원 설정·서비스를 바꿀 수 있어 막았습니다. "
                    "python -m pytest tests 로 실행하세요.")
        return None                       # 통과시키면 나머지 finder 가 평소대로 찾는다


def install():
    if not any(isinstance(f, _Guard) for f in sys.meta_path):
        sys.meta_path.insert(0, _Guard())
    loaded = [m for m in sys.modules if m == GUARDED or m.startswith(GUARDED + '.')]
    if loaded and not fakewin_ready():
        raise BackendImportBlocked(f'가짜 Windows 설치 전에 backend 가 이미 import 됐습니다: {loaded}')
