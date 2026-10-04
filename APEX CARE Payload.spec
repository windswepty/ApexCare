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
        # 아래 모듈들은 순환 참조를 피하려고 함수 안에서 지연 import 한다.
        # hiddenimports 에 없으면 exe 로 묶였을 때만 import 에 실패한다
        # (개발 중에는 드러나지 않는다).
        'backend.safe_delete', 'backend.system_state', 'backend.perf_modes',
        'backend.process_boost', 'backend.storage', 'backend.perf_bench', 'backend.window_frame',
        'backend.single_instance', 'backend.machine_store', 'backend.window_icon', 'backend.health',
        'backend.shortcut_icon',
        # main.py 가 --revert-for-uninstall 일 때만 import 한다(제거 프로그램이 부른다)
        'backend.uninstall_prep',
        'ctypes', 'ctypes.wintypes', 'threading', 'psutil', 'subprocess',
        'shutil', 'concurrent.futures', 'winreg', 'json', 'logging', 'os', 'sys', 'stat', 'uuid', 'struct', 'time',
        'win32pdh', 'pythoncom', 'win32com',
        # 고정한 작업 표시줄 단추의 아이콘(IShellLink·SHChangeNotify, backend/shortcut_icon.py)
        'win32com.shell', 'win32com.shell.shell', 'win32com.shell.shellcon'
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
