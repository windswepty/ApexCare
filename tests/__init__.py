"""
'tests' 패키지를 import 하는 순간 문지기를 세운다.

conftest 를 읽지 않는 실행(pytest --noconftest, 테스트 모듈을 python 으로 직접 import)에서도 가짜 Windows 없이
backend 가 import 되지 않게 한다. 예전에는 문지기가 conftest 에서만 세워져, 그런 실행에서는 테스트가 개발 PC 의
진짜 레지스트리·전원 플랜·서비스와 진짜 저널을 바꿀 수 있었다.
"""

from tests import import_guard as _import_guard

_import_guard.install()
