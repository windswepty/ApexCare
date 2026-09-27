# -*- mode: python ; coding: utf-8 -*-
import json
import os
import re

# 버전은 tools/setup_wizard.py 의 APP_VERSION 한 곳에서 정한다.
# 설치 파일 이름과 '앱 및 기능' 의 DisplayVersion 이 서로 어긋나지 않게 여기서 읽어 쓰고,
# package.json 의 version 과 다르면 빌드를 멈춘다(앱 화면의 버전과도 맞아야 한다).
with open(os.path.join(SPECPATH, 'tools', 'setup_wizard.py'), encoding='utf-8') as _f:
    _m = re.search(r"^APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", _f.read(), re.M)
if not _m:
    raise SystemExit('tools/setup_wizard.py 에서 APP_VERSION 을 찾지 못했습니다.')
APP_VERSION = _m.group(1)
with open(os.path.join(SPECPATH, 'package.json'), encoding='utf-8') as _f:
    _pkg_version = json.load(_f).get('version')
if _pkg_version != APP_VERSION:
    raise SystemExit(f'버전이 다릅니다: setup_wizard.py={APP_VERSION}, package.json={_pkg_version}')


a = Analysis(
    ['tools\\setup_wizard.py'],
    pathex=[],
    binaries=[],
    datas=[('dist/APEX CARE Payload.exe', '.'), ('dist/APEX CARE Uninstaller.exe', '.'), ('public/eula.txt', '.'), ('public/setup_icon.ico', '.')],
    hiddenimports=['pythoncom', 'win32com.client'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'APEX CARE Setup {APP_VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # %ProgramFiles% 에 설치하고 HKLM 에 제거 정보를 등록하므로 관리자 권한이 필요하다
    uac_admin=True,
    icon=['public\\setup_icon.ico'],
)
