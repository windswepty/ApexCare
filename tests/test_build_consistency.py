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


def test_python_sources_compile_without_warnings():
    # 문서 문자열 속 '\S' 같은 잘못된 이스케이프는 경고로만 드러나고, 앞으로 오류가 된다
    import warnings
    files = [os.path.join('backend', f) for f in os.listdir(os.path.join(ROOT, 'backend')) if f.endswith('.py')]
    files += ['main.py', os.path.join('tools', 'uninstall.py'), os.path.join('tools', 'setup_wizard.py')]
    for rel in files:
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            compile(_read(rel), rel, 'exec')


def test_sources_have_no_stray_control_characters():
    # '\a' 가 벨 문자(0x07)로 바뀌는 식의 실수는 문법상 문제가 없어 컴파일로는 안 잡힌다
    bad = []
    for top in ('backend', 'tests', 'tools', os.path.join('tools', 'sandbox'), os.path.join('src', 'components')):
        for f in os.listdir(os.path.join(ROOT, top)):
            if f.endswith(('.py', '.js', '.jsx', '.ps1', '.cmd')):
                text = _read(os.path.join(top, f))
                if any(ord(c) < 32 and c not in '\r\n\t' for c in text):
                    bad.append(os.path.join(top, f))
    assert bad == [], bad


def test_command_output_is_read_without_crashing_on_codepage():
    # 콘솔 도구(ipconfig·defrag 등)는 OEM 코드 페이지로 출력한다. text=True 에 errors 가 없으면 UTF-8 로
    # 읽다가 출력 읽기 스레드가 죽는다(샌드박스 점검에서 실제로 났다).
    import ast
    bad = []
    for f in os.listdir(os.path.join(ROOT, 'backend')):
        if not f.endswith('.py'):
            continue
        tree = ast.parse(_read(os.path.join('backend', f)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                kw = {k.arg for k in node.keywords}
                text = any(k.arg == 'text' and getattr(k.value, 'value', None) is True for k in node.keywords)
                if text and 'errors' not in kw and 'encoding' not in kw:
                    bad.append(f'{f}:{node.lineno}')
    assert bad == [], bad
