# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('dist_react', 'dist_react')],
    hiddenimports=[
        'backend.uninstaller', 'backend.optimizer', 'backend.system_repair', 
        'backend.system_monitor', 'backend.file_finder', 'backend.debloater', 
        'backend.game_booster', 'backend.config_manager', 'backend.api',
        'backend.process_guard',
        'ctypes', 'ctypes.wintypes', 'threading', 'psutil', 'subprocess',
        'shutil', 'concurrent.futures', 'winreg', 'json', 'logging', 'os', 'sys', 'stat', 'uuid', 'struct', 'time',
        'win32pdh', 'pythoncom', 'win32com'
    ],
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
    name='APEX CARE Payload',
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
    icon=['public\\icon.ico'],
)
