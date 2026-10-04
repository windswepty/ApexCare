"""
APEX CARE — 작업 표시줄에 고정한 단추의 아이콘을 화면 설정의 '앱 아이콘 색' 으로 바꾼다.

고정한 단추는 창 아이콘(window_icon)이 아니라 바로 가기(.lnk)의 아이콘을 보여 준다. 그래서 이 계정이 고정한
바로 가기 중 대상이 실행 중인 APEX CARE.exe 인 것만 아이콘 위치를 바꾼다. 대상·이름 등 다른 내용은 건드리지 않는다.

- 바꾸기 전의 아이콘 위치를 설정 파일(ui_icon_shortcuts)에 한 번만 기록한다. 기록하지 못하면 바꾸지 않는다.
- '기본' 으로 돌리면 기록한 원래 위치로 되돌리고, 다시 읽어 확인된 것만 기록에서 지운다.
- 바탕 화면·시작 메뉴 바로 가기는 이 PC 의 모든 계정이 함께 쓰는 것이라 바꾸지 않는다.
- 개발 실행(python.exe)에서는 대상이 없다. 다른 프로그램의 바로 가기를 고칠 일이 없다.
"""

import hashlib
import logging
import os
import struct
import sys

from backend import config_manager

log = logging.getLogger('ShortcutIcon')

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
_PREFIX = 'apex_icon_'
CONFIG_KEY = 'ui_icon_shortcuts'


def _data_dir():
    return os.path.join(os.environ.get('APPDATA', ''), 'APEX_CARE_DATA', 'icons')


def pinned_dir():
    return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Internet Explorer', 'Quick Launch',
                        'User Pinned', 'TaskBar')


def _own_exe():
    """설치된 앱이면 그 exe 경로. 개발 실행이면 None(파이썬의 바로 가기를 고치지 않게)."""
    if not getattr(sys, 'frozen', False):
        return None
    return sys.executable


def _same_file(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, ValueError, TypeError):
        return False


# ── ICO 만들기 ─────────────────────────────────────────

def png_size(png):
    """PNG 의 (가로, 세로). PNG 가 아니면 None."""
    if not isinstance(png, (bytes, bytearray)) or len(png) < 24 or not png.startswith(PNG_MAGIC) \
            or png[12:16] != b'IHDR':
        return None
    return struct.unpack('>II', png[16:24])


def build_ico(pngs):
    """정사각형 PNG 여러 장(크기가 ICON_SIZES 중 하나, 서로 다름)으로 ICO 파일 내용을 만든다. 틀리면 None."""
    items = []
    for png in pngs or []:
        size = png_size(png)
        if not size or size[0] != size[1] or size[0] not in ICON_SIZES:
            return None
        items.append((size[0], bytes(png)))
    sizes = [s for s, _ in items]
    if not items or len(set(sizes)) != len(sizes):
        return None
    items.sort()
    head = struct.pack('<HHH', 0, 1, len(items))
    offset = 6 + 16 * len(items)
    entries, blobs = b'', b''
    for size, png in items:
        dim = 0 if size == 256 else size            # 256 은 0 으로 적는다(ICO 형식)
        entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return head + entries + blobs


def _write_ico(data):
    """내용 해시로 이름을 지어 저장한다(이름이 바뀌어야 Windows 아이콘 캐시가 새로 읽는다). 경로 또는 None."""
    folder = _data_dir()
    path = os.path.join(folder, _PREFIX + hashlib.sha1(data).hexdigest()[:16] + '.ico')
    try:
        os.makedirs(folder, exist_ok=True)
        if not os.path.exists(path):
            tmp = path + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)
        with open(path, 'rb') as f:
            if f.read() != data:
                return None
        return path
    except OSError as e:
        log.warning(f'아이콘 파일을 저장하지 못했습니다: {e}')
        return None


def _drop_unused_icons(keep):
    """이 모듈이 만든 아이콘 파일(apex_icon_*.ico) 중 지금 쓰지 않는 것을 지운다. 앱이 만든 캐시 파일이다."""
    folder = _data_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return
    keep = {os.path.normcase(p) for p in keep if p}
    for name in names:
        path = os.path.join(folder, name)
        if name.startswith(_PREFIX) and name.endswith('.ico') and os.path.normcase(path) not in keep:
            try:
                os.remove(path)
            except OSError:
                pass


# ── 바로 가기 읽기·쓰기 (IShellLink) ───────────────────

class _Com:
    def __enter__(self):
        import pythoncom
        pythoncom.CoInitialize()
        return self

    def __exit__(self, *exc):
        import pythoncom
        pythoncom.CoUninitialize()


def _open_link(path):
    import pythoncom
    from win32com.shell import shell
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    pf = link.QueryInterface(pythoncom.IID_IPersistFile)
    pf.Load(path, 2)                                # STGM_READWRITE
    return link, pf


def read_link(path):
    """(대상 경로, (아이콘 경로, 번호)). 읽지 못하면 None."""
    try:
        link, _ = _open_link(path)
        target = link.GetPath(0)[0]
        icon_path, index = link.GetIconLocation()
        return target, (icon_path or '', int(index))
    except Exception as e:
        log.info(f'바로 가기를 읽지 못했습니다({os.path.basename(path)}): {e}')
        return None


def write_icon(path, icon):
    """바로 가기의 아이콘 위치만 바꾼다. 다시 읽어 확인한다."""
    try:
        link, pf = _open_link(path)
        link.SetIconLocation(icon[0], int(icon[1]))
        pf.Save(None, True)
    except Exception as e:
        log.warning(f'바로 가기 아이콘을 바꾸지 못했습니다({os.path.basename(path)}): {e}')
        return False
    now = read_link(path)
    return bool(now) and _same_icon(now[1], icon)


def notify(paths):
    """탐색기·작업 표시줄에 바뀐 바로 가기를 알린다(아이콘을 다시 읽게)."""
    try:
        from win32com.shell import shell, shellcon
        for p in paths:
            shell.SHChangeNotify(shellcon.SHCNE_UPDATEITEM, shellcon.SHCNF_PATHW, p, None)
        shell.SHChangeNotify(shellcon.SHCNE_ASSOCCHANGED, shellcon.SHCNF_IDLIST, None, None)
    except Exception as e:
        log.info(f'아이콘 변경 알림 실패: {e}')


def _is_ours(icon_path):
    """이 모듈이 만든 아이콘 파일(아이콘 폴더의 apex_icon_*.ico)인가"""
    if not icon_path:
        return False
    name = os.path.basename(icon_path)
    return name.startswith(_PREFIX) and name.lower().endswith('.ico') and _same_file(os.path.dirname(icon_path), _data_dir())


def _same_icon(a, b):
    return os.path.normcase(a[0] or '') == os.path.normcase(b[0] or '') and int(a[1]) == int(b[1])


# ── 적용·되돌리기 ──────────────────────────────────────

def _records():
    rec = config_manager.load_config().get(CONFIG_KEY)
    if not isinstance(rec, dict):
        return {}
    out = {}
    for k, v in rec.items():
        if isinstance(k, str) and isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) \
                and isinstance(v[1], int):
            out[k] = (v[0], v[1])
    return out


def _save_records(change):
    def apply(c):
        rec = c.get(CONFIG_KEY)
        rec = dict(rec) if isinstance(rec, dict) else {}
        change(rec)
        if rec:
            c[CONFIG_KEY] = rec
        else:
            c.pop(CONFIG_KEY, None)
    return config_manager.update_config(apply)


def _own_pins(exe):
    """이 계정이 작업 표시줄에 고정한 바로 가기 중 대상이 exe 인 것: [(경로, 지금 아이콘)]"""
    folder = pinned_dir()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.lower().endswith('.lnk'):
            continue
        path = os.path.join(folder, name)
        info = read_link(path)
        if info and info[0] and _same_file(info[0], exe):
            out.append((path, info[1]))
    return out


def apply_pngs(pngs):
    """고정한 단추 아이콘을 pngs(PNG bytes 목록)로 만든 ICO 로 바꾼다. {'success', 'changed', 'failed', 'message'}"""
    exe = _own_exe()
    if not exe:
        return {'success': True, 'changed': 0, 'failed': [], 'message': '개발 실행에서는 바꾸지 않습니다.'}
    data = build_ico(pngs)
    if data is None:
        return {'success': False, 'changed': 0, 'failed': [], 'message': '아이콘 그림 형식이 올바르지 않습니다.'}
    with _Com():
        pins = _own_pins(exe)
        if not pins:
            return {'success': True, 'changed': 0, 'failed': [], 'message': '작업 표시줄에 고정한 APEX CARE 가 없습니다.'}
        ico = _write_ico(data)
        if not ico:
            return {'success': False, 'changed': 0, 'failed': [], 'message': '아이콘 파일을 저장하지 못했습니다.'}
        new = (ico, 0)
        records = _records()
        # 원래 아이콘 위치를 먼저 기록한다(이미 이 모듈이 바꾼 것이면 처음 기록을 그대로 둔다)
        fresh = {p: icon for p, icon in pins if p not in records}
        if fresh:
            if not _save_records(lambda r: r.update({p: list(i) for p, i in fresh.items()})):
                return {'success': False, 'changed': 0, 'failed': [],
                        'message': '원래 아이콘을 기록하지 못해 바꾸지 않았습니다.'}
        changed, failed = [], []
        for path, icon in pins:
            if _same_icon(icon, new):
                continue
            if write_icon(path, new):
                changed.append(path)
            else:
                failed.append(os.path.basename(path))
        if changed:
            notify(changed)
        # 지금 바로 가기들이 가리키는 아이콘 파일은 남긴다(바꾸지 못해 예전 파일을 가리키는 단추가 있을 수 있다)
        keep = [ico] + [info[1][0] for info in (read_link(p) for p, _ in pins) if info]
    _drop_unused_icons(keep)
    return {'success': not failed, 'changed': len(changed), 'failed': failed,
            'message': '' if not failed else f"바꾸지 못한 단추: {', '.join(failed)}"}


def restore():
    """기록한 원래 아이콘 위치로 되돌린다. {'success', 'restored', 'failed', 'message'}"""
    records = _records()
    if not records:
        return {'success': True, 'restored': 0, 'failed': [], 'message': ''}
    done, failed = [], []
    with _Com():
        for path, icon in records.items():
            if not os.path.exists(path):          # 고정을 풀었다. 되돌릴 대상이 없다
                done.append(path)
                continue
            now = read_link(path)
            if now and not _is_ours(now[1][0]):     # 지금은 이 모듈이 만든 아이콘이 아니다(사용자가 바꿨거나 다른 바로 가기)
                done.append(path)
                continue
            if write_icon(path, icon):
                done.append(path)
            else:
                failed.append(path)
        if done:
            notify([p for p in done if os.path.exists(p)])
    if done and not _save_records(lambda r: [r.pop(p, None) for p in done]):
        return {'success': False, 'restored': len(done), 'failed': [os.path.basename(p) for p in failed],
                'message': '되돌렸지만 기록을 지우지 못했습니다.'}
    if not failed:
        _drop_unused_icons([])
    return {'success': not failed, 'restored': len(done), 'failed': [os.path.basename(p) for p in failed],
            'message': '' if not failed else f"되돌리지 못한 단추: {', '.join(os.path.basename(p) for p in failed)}"}
