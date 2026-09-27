# -*- mode: python ; coding: utf-8 -*-


# 진입점은 tools/uninstall.py 다. tools/uninstaller_src.py 는 어떤 빌드에도 쓰이지 않는다.
a = Analysis(
    ['tools\\uninstall.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # 바로 가기 대상 확인에 함수 안에서 import 한다
    hiddenimports=['win32com.client'],
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
    name='APEX CARE Uninstaller',
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
    uac_admin=True,
    icon=['public\\setup_icon.ico'],
)
