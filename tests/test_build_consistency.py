"""빌드가 설치 파일에서만 깨지는 실수를 미리 잡는다. 파일을 읽기만 한다(빌드하지 않는다)."""

import json
import os
import re

from tests.conftest import ROOT


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_every_backend_module_is_in_payload_hiddenimports():
    # 함수 안에서 import 하는 모듈은 PyInstaller 가 못 찾는다. 빠지면 개발 실행은 멀쩡하고 설치 파일에서만 실패한다.
    spec = _read('APEX CARE Payload.spec')
    modules = sorted(f[:-3] for f in os.listdir(os.path.join(ROOT, 'backend'))
                     if f.endswith('.py') and f != '__init__.py')
    missing = [m for m in modules if f"'backend.{m}'" not in spec]
    assert missing == [], f'APEX CARE Payload.spec 의 hiddenimports 에 없습니다: {missing}'


def test_setup_version_matches_package_json():
    # Setup spec(.gitignore 대상이라 CI 에는 없다)이 이 값을 읽어 설치 파일 이름을 짓고 package.json 과 비교한다
    m = re.search(r"^APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", _read('tools/setup_wizard.py'), re.M)
    assert m, 'tools/setup_wizard.py 에 APP_VERSION 이 없습니다'
    assert m.group(1) == json.loads(_read('package.json'))['version']
