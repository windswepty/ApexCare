"""
APEX CARE — 대용량·중복 파일 찾기.

검색 결과는 대부분 사용자가 만든 영상·사진·VM 디스크다. 그래서 지우는 쪽을 좁게 잡는다.
  - 직전 검색 결과에 있는 파일만 지운다. 검색 뒤 바뀐 파일(크기·수정 시각·파일 ID)은 거부한다.
  - 중복 그룹은 그룹마다 최소 1개가 남아야 한다. UI 가 아니라 여기서 확인한다.
  - 정션·심볼릭 링크 안으로 들어가지 않고, 같은 물리 파일(st_dev, st_ino)은 하나로 친다.
    같은 파일을 두 경로로 찾아 '중복' 이라고 보여 주면, 사용자가 '사본' 을 지우는 순간
    유일한 원본이 사라진다.
  - 온라인 전용 클라우드 파일은 읽지 않는다. 읽으면 내려받기가 시작된다.
  - 고정 디스크만 검색한다. 이동식·네트워크 드라이브에는 휴지통이 없다.

삭제는 safe_delete.to_recycle_bin 으로 휴지통을 거친다. 휴지통에 못 넣는 파일은 건드리지 않는다.
"""

import concurrent.futures
import hashlib
import logging
import os
import shutil
import threading

from backend import safe_delete

log = logging.getLogger('FileFinder')

MB = 1024 * 1024
MIN_DUP_BYTES = 10 * MB          # 중복 검색은 10MB 이상만 본다
MAX_LARGE_RESULTS = 1000
MAX_DUP_GROUPS = 500
_QUICK_BYTES = 1 * MB            # 앞·뒤 1MB 로 먼저 거르고, 겹치는 것만 전체를 읽는다

# 시스템이 쓰는 파일 형식. 사용자 폴더에 있어도 목록에 올리지 않는다.
DANGER_EXTS = frozenset({
    '.dll', '.exe', '.sys', '.ini', '.ocx', '.drv', '.cpl',
    '.cat', '.mum', '.manifest', '.msi', '.msp', '.mst',
    '.inf', '.nls', '.tlb', '.ax', '.acm', '.scr', '.com',
    '.efi', '.mui', '.pnf',
})
# 사용자 레지스트리 하이브(NTUSER.DAT, UsrClass.dat 과 그 로그)
_HIVE_PREFIXES = ('ntuser.', 'usrclass.')

# 이름이 이것이면 그 폴더 안으로 들어가지 않는다 (대소문자 무시)
EXCLUDE_DIR_NAMES = frozenset({
    'windows', 'program files', 'program files (x86)', 'programdata',
    'system volume information', '$recycle.bin', 'appdata', 'recovery',
    'boot', 'efi', 'config.msi', '$windows.~bt', '$windows.~ws', '$winreagent',
    '$sysreset', 'windowsapps', 'msocache',
    'steamlibrary', 'steamapps', 'origin games', 'riot games', 'epic games',
    'battle.net', 'ubisoft game launcher', 'xboxgames',
})

_EXCLUDED_REASON = {
    'removable': '이동식 드라이브',
    'network': '네트워크 드라이브',
    'cdrom': 'CD/DVD 드라이브',
    'ramdisk': '램디스크',
    'unknown': '종류를 확인할 수 없는 드라이브',
}

# ── 직전 검색 결과 (삭제는 여기 있는 파일만 받는다) ─────────────
_state_lock = threading.Lock()
_scan_guard = threading.Lock()      # 검색은 한 번에 하나
_delete_lock = threading.Lock()
_state = {'id': 0, 'kind': None, 'entries': {}, 'groups': {}}


def _store(kind, entries, groups):
    with _state_lock:
        _state['id'] += 1
        _state['kind'] = kind
        _state['entries'] = entries
        _state['groups'] = groups


def _new_stats():
    return {'links': 0, 'cloud': 0, 'unreadableDirs': 0, 'unreadableFiles': 0,
            'sameFile': 0, 'changed': 0}


def _busy_result(kind):
    return {'success': False, 'kind': kind, 'files': [], 'groups': [],
            'excludedDrives': [], 'scannedDrives': [],
            'message': '이미 검색 중입니다. 끝난 뒤 다시 시도하세요.'}


# ── 드라이브 ──────────────────────────────────────────────────
def _ready(root):
    try:
        shutil.disk_usage(root)
        return True
    except Exception:
        return False


def get_scan_drives():
    """(검색할 드라이브, 제외한 드라이브 [{drive, type, reason}]). 고정 디스크만 검색한다."""
    included, excluded, seen = [], [], set()
    for root in safe_delete.logical_drives():
        letter = root[:2]
        dtype = safe_delete.letter_drive_type(root)
        if dtype != 'fixed':
            # 매체가 없는 카드 리더·광학 드라이브 슬롯은 알릴 필요가 없다
            if dtype in ('removable', 'cdrom', 'unknown') and not _ready(root):
                continue
            excluded.append({'drive': letter, 'type': dtype,
                             'reason': _EXCLUDED_REASON.get(dtype, _EXCLUDED_REASON['unknown'])})
            continue
        if safe_delete.is_subst_drive(root):
            excluded.append({'drive': letter, 'type': 'subst',
                             'reason': '가상 드라이브(subst) — 원래 드라이브에서 검색합니다'})
            continue
        guid = safe_delete.volume_guid(root)
        if guid and guid in seen:
            excluded.append({'drive': letter, 'type': 'duplicate', 'reason': '같은 볼륨'})
            continue
        if guid:
            seen.add(guid)
        if not os.path.isdir(root):
            continue
        included.append(root)
    return included, excluded


def get_local_drives():
    """호환용. 검색 대상 드라이브(고정 디스크)만 돌려준다."""
    return get_scan_drives()[0] or ['C:\\']


def _excluded_roots():
    env = os.environ.get
    out = set()
    for v in ('SystemRoot', 'windir', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432',
              'ProgramData', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        p = env(v)
        if p:
            out.add(os.path.normcase(os.path.abspath(p)).rstrip('\\'))
    return out


def _walk_files(root, stats, excluded_roots):
    """root 아래 일반 파일을 (경로, 이름, lstat) 로 내놓는다.

    os.walk 는 정션을 링크로 보지 않고 따라 들어간다. 그래서 scandir 로 직접 돌면서
    재분석 지점(정션·심볼릭 링크·마운트 지점)은 들어가지도, 목록에 올리지도 않는다.
    """
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            stats['unreadableDirs'] += 1
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if safe_delete.is_link_like(st):
                    stats['links'] += 1
                    continue
                attrs = getattr(st, 'st_file_attributes', 0) or 0
                name = e.name
                if attrs & safe_delete.FILE_ATTRIBUTE_DIRECTORY:
                    low = name.lower()
                    if name.startswith('.') or low in EXCLUDE_DIR_NAMES:
                        continue
                    if attrs & (safe_delete.FILE_ATTRIBUTE_RECALL_ON_OPEN
                                | safe_delete.FILE_ATTRIBUTE_OFFLINE):
                        stats['cloud'] += 1     # 열기만 해도 목록을 내려받는 온라인 폴더
                        continue
                    full = os.path.join(d, name)
                    if os.path.normcase(full).rstrip('\\') in excluded_roots:
                        continue
                    stack.append(full)
                else:
                    if safe_delete.is_cloud_placeholder(st):
                        stats['cloud'] += 1
                        continue
                    yield os.path.join(d, name), name, st


def _blocked_name(name):
    low = name.lower()
    return os.path.splitext(low)[1] in DANGER_EXTS or low.startswith(_HIVE_PREFIXES)


def _make_entry(path):
    """삭제 전 대조용으로 파일 정체(크기·수정 시각·파일 ID)를 기록한다."""
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    attrs = getattr(st, 'st_file_attributes', 0) or 0
    if (safe_delete.is_link_like(st) or safe_delete.is_cloud_placeholder(st)
            or attrs & safe_delete.FILE_ATTRIBUTE_DIRECTORY):
        return None
    return {'path': path, 'name': os.path.basename(path), 'size': st.st_size,
            'mtime_ns': st.st_mtime_ns, 'mtime': st.st_mtime,
            'dev': st.st_dev, 'ino': st.st_ino, 'groupId': None}


def _changed_since_scan(ent):
    """검색 때와 다른 파일이면 그 이유, 같으면 None."""
    try:
        st = os.stat(ent['path'], follow_symlinks=False)
    except FileNotFoundError:
        return '파일이 없습니다'
    except OSError:
        return '파일을 확인할 수 없습니다'
    attrs = getattr(st, 'st_file_attributes', 0) or 0
    if safe_delete.is_link_like(st) or attrs & safe_delete.FILE_ATTRIBUTE_DIRECTORY:
        return '검색 이후 파일이 아닌 것으로 바뀌었습니다'
    same_id = (not ent['ino'] or (st.st_dev, st.st_ino) == (ent['dev'], ent['ino']))
    if not same_id or st.st_size != ent['size'] or st.st_mtime_ns != ent['mtime_ns']:
        return '검색 이후 바뀌었습니다. 다시 검색하세요'
    return None


def _recycle_note(path, size, limits):
    """(휴지통에 들어가는가, 안 들어가면 이유). 볼륨마다 한 번만 조회한다."""
    root = safe_delete.volume_root(path) or ''
    if root not in limits:
        limits[root] = safe_delete.recycle_bin_limit(path)
    limit, why = limits[root]
    if why:
        return False, why
    if size > limit:
        return False, f"휴지통 최대 크기({safe_delete.fmt_bytes(limit)})보다 커서 휴지통에 들어가지 않습니다"
    return True, None


def _public(ent, limits):
    ok, note = _recycle_note(ent['path'], ent['size'], limits)
    return {
        'path': ent['path'], 'name': ent['name'], 'size': ent['size'],
        'sizeMB': round(ent['size'] / MB, 2), 'modified': ent['mtime'],
        'groupId': ent['groupId'], 'recyclable': ok, 'note': note,
    }


# ── 대용량 파일 ───────────────────────────────────────────────
def scan_large_files(min_mb=500):
    """고정 디스크에서 min_mb 이상인 파일을 찾는다. 결과는 삭제 대조용으로 보관한다."""
    try:
        min_mb = int(float(min_mb))
    except (TypeError, ValueError):
        min_mb = 500
    min_mb = max(10, min(min_mb, 10 * 1024 * 1024))
    min_bytes = min_mb * MB

    if not _scan_guard.acquire(blocking=False):
        return _busy_result('large')
    try:
        drives, excluded = get_scan_drives()
        stats = _new_stats()
        if not drives:
            _store('large', {}, {})
            return {'success': False, 'kind': 'large', 'files': [], 'groups': [],
                    'excludedDrives': excluded, 'scannedDrives': [], 'skipped': stats,
                    'message': '검색할 고정 디스크가 없습니다.'}
        ex_roots = _excluded_roots()
        found = []
        for root in drives:
            for path, name, st in _walk_files(root, stats, ex_roots):
                if st.st_size >= min_bytes and not _blocked_name(name):
                    found.append((st.st_size, path))
        found.sort(key=lambda x: -x[0])
        truncated = max(0, len(found) - MAX_LARGE_RESULTS)

        entries, files, limits = {}, [], {}
        for _, path in found[:MAX_LARGE_RESULTS]:
            ent = _make_entry(path)
            if not ent or ent['size'] < min_bytes:
                continue
            key = safe_delete.norm(path)
            if key in entries:
                continue
            entries[key] = ent
            files.append(_public(ent, limits))
        _store('large', entries, {})
        return {'success': True, 'kind': 'large', 'files': files, 'groups': [],
                'excludedDrives': excluded, 'scannedDrives': [d[:2] for d in drives],
                'truncated': truncated, 'skipped': stats,
                'message': f"{len(files)}개를 찾았습니다."}
    except Exception as e:
        log.warning(f"대용량 파일 검색 실패: {e}")
        return {'success': False, 'kind': 'large', 'files': [], 'groups': [],
                'excludedDrives': [], 'scannedDrives': [], 'message': f"검색 실패: {e}"}
    finally:
        _scan_guard.release()


# ── 중복 파일 ─────────────────────────────────────────────────
def _hash_file(filepath, quick=False):
    """파일 내용의 해시. quick 이면 앞·뒤 1MB 만 읽는다. 읽기 전용으로만 연다."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            if quick:
                hasher.update(f.read(_QUICK_BYTES))
                size = os.fstat(f.fileno()).st_size
                if size > 2 * _QUICK_BYTES:
                    f.seek(size - _QUICK_BYTES)
                    hasher.update(f.read(_QUICK_BYTES))
            else:
                while chunk := f.read(MB):
                    hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        log.debug(f"Hash error {filepath}: {e}")
        return None


def _bucket(executor, ents, quick, stats):
    """해시가 같은 것끼리 묶는다. 읽지 못한 파일은 뺀다."""
    futures = {executor.submit(_hash_file, ent['path'], quick): ent for ent in ents}
    out = {}
    for fut in concurrent.futures.as_completed(futures):
        ent = futures[fut]
        try:
            h = fut.result()
        except Exception:
            h = None
        if not h:
            stats['unreadableFiles'] += 1
            continue
        out.setdefault(h, []).append(ent)
    return list(out.values())


def scan_duplicates():
    """고정 디스크에서 내용이 같은 파일(10MB 이상)을 그룹으로 찾는다."""
    if not _scan_guard.acquire(blocking=False):
        return _busy_result('dup')
    try:
        drives, excluded = get_scan_drives()
        stats = _new_stats()
        if not drives:
            _store('dup', {}, {})
            return {'success': False, 'kind': 'dup', 'files': [], 'groups': [],
                    'excludedDrives': excluded, 'scannedDrives': [], 'skipped': stats,
                    'message': '검색할 고정 디스크가 없습니다.'}
        ex_roots = _excluded_roots()

        # 1단계: 크기로 묶는다
        by_size = {}
        for root in drives:
            for path, name, st in _walk_files(root, stats, ex_roots):
                if st.st_size >= MIN_DUP_BYTES and not _blocked_name(name):
                    by_size.setdefault(st.st_size, []).append(path)

        # 2단계: 같은 물리 파일(하드 링크, 다른 경로로 보이는 같은 파일)은 하나로 친다
        candidates = []
        for size, paths in by_size.items():
            if len(paths) < 2:
                continue
            ids = {}
            for path in paths:
                ent = _make_entry(path)
                if not ent or ent['size'] != size:
                    continue
                fid = (ent['dev'], ent['ino']) if ent['ino'] else ('path', safe_delete.norm(path))
                if fid in ids:
                    stats['sameFile'] += 1
                    continue
                ids[fid] = ent
            if len(ids) > 1:
                candidates.append(list(ids.values()))

        # 3단계: 앞·뒤 일부 해시 → 겹치는 것만 전체 해시
        found = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            for ents in candidates:
                for q in _bucket(ex, ents, True, stats):
                    if len(q) < 2:
                        continue
                    for full in _bucket(ex, q, False, stats):
                        # 해시를 읽는 동안 바뀐 파일은 뺀다
                        same = [e for e in full if _changed_since_scan(e) is None]
                        stats['changed'] += len(full) - len(same)
                        if len(same) >= 2:
                            found.append(same)

        found.sort(key=lambda g: -(g[0]['size'] * (len(g) - 1)))
        truncated = max(0, len(found) - MAX_DUP_GROUPS)

        entries, groups, out_groups, flat, limits = {}, {}, [], [], {}
        for i, members in enumerate(found[:MAX_DUP_GROUPS]):
            gid = f"g{i + 1}"
            # 가장 오래된 파일을 '남길 후보' 로 맨 앞에 둔다(보통 원본이다)
            members.sort(key=lambda e: (e['mtime_ns'], len(e['path']), e['path'].lower()))
            keys, files = [], []
            for j, ent in enumerate(members):
                key = safe_delete.norm(ent['path'])
                if key in entries:
                    continue
                ent['groupId'] = gid
                entries[key] = ent
                keys.append(key)
                pub = _public(ent, limits)
                pub['keepSuggested'] = (j == 0)
                files.append(pub)
            if len(keys) < 2:
                for k in keys:
                    entries.pop(k, None)
                continue
            groups[gid] = keys
            size = members[0]['size']
            out_groups.append({'groupId': gid, 'size': size, 'sizeMB': round(size / MB, 2),
                               'count': len(files), 'files': files})
            flat.extend(files)
        _store('dup', entries, groups)
        return {'success': True, 'kind': 'dup', 'groups': out_groups, 'files': flat,
                'excludedDrives': excluded, 'scannedDrives': [d[:2] for d in drives],
                'truncated': truncated, 'skipped': stats,
                'message': f"중복 그룹 {len(out_groups)}개를 찾았습니다."}
    except Exception as e:
        log.warning(f"중복 파일 검색 실패: {e}")
        return {'success': False, 'kind': 'dup', 'files': [], 'groups': [],
                'excludedDrives': [], 'scannedDrives': [], 'message': f"검색 실패: {e}"}
    finally:
        _scan_guard.release()


# ── 삭제 ──────────────────────────────────────────────────────
def _delete_result(moved, moved_bytes, failed, not_recyclable, message=None):
    n = len(moved)
    if message is None:
        if n:
            message = (f"{n}개 파일({round(moved_bytes / MB, 1)}MB)을 휴지통으로 옮겼습니다. "
                       "휴지통에서 복구할 수 있습니다.")
        else:
            message = "휴지통으로 옮긴 파일이 없습니다."
        if not_recyclable:
            message += f" {len(not_recyclable)}개는 휴지통에 넣을 수 없어 지우지 않았습니다."
        if failed:
            message += f" {len(failed)}개는 옮기지 못했습니다."
    moved_mb = round(moved_bytes / MB, 2)
    return {
        # 하나라도 실패하거나 남았으면 성공이 아니다
        "success": n > 0 and not failed and not not_recyclable,
        "partial": n > 0 and bool(failed or not_recyclable),
        "deleted": n,
        "deletedPaths": list(moved),
        "movedMB": moved_mb,
        "freedMB": moved_mb,   # 호환용. 휴지통을 비우기 전까지 디스크 공간은 그대로다.
        "failed": list(failed),
        "not_recyclable": list(not_recyclable),
        "message": message,
    }


def delete_files(paths):
    """직전 검색 결과에 있는 파일만 휴지통으로 보낸다.

    - 검색 결과에 없거나, 검색 뒤 바뀐 파일은 거부한다.
    - 중복 검색이면 그룹마다 1개는 남아야 한다. 그룹 전체를 고르면 그 그룹은 거부한다.
    - 휴지통에 들어가지 않는 파일은 건드리지 않고 not_recyclable 로 돌려준다.
    """
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, (list, tuple)) or not paths:
        return _delete_result([], 0, [], [], "선택된 항목이 없습니다.")
    if _scan_guard.locked():
        return _delete_result([], 0, [], [], "검색 중에는 지울 수 없습니다. 검색이 끝난 뒤 다시 시도하세요.")

    with _delete_lock:
        with _state_lock:
            scan_id = _state['id']
            kind = _state['kind']
            entries = dict(_state['entries'])
            groups = {g: list(v) for g, v in _state['groups'].items()}
        if not entries:
            return _delete_result([], 0, [], [],
                                  "먼저 검색하세요. 직전 검색 결과에 있는 파일만 지울 수 있습니다.")

        rejected, chosen, seen = [], [], set()
        for p in paths:
            if not isinstance(p, str) or not p:
                rejected.append({"path": p, "reason": "잘못된 경로"})
                continue
            try:
                key = safe_delete.norm(p)
            except Exception:
                rejected.append({"path": p, "reason": "잘못된 경로"})
                continue
            if key in seen:
                continue
            seen.add(key)
            ent = entries.get(key)
            if not ent:
                rejected.append({"path": p, "reason": "직전 검색 결과에 없는 파일입니다"})
                continue
            if _blocked_name(ent['name']):
                rejected.append({"path": p, "reason": "시스템에 필요한 파일 형식"})
                continue
            why = _changed_since_scan(ent)
            if why:
                rejected.append({"path": p, "reason": why})
                continue
            chosen.append(key)

        if kind == 'dup':
            by_group = {}
            for key in chosen:
                by_group.setdefault(entries[key]['groupId'], []).append(key)
            drop = set()
            for gid, keys in by_group.items():
                members = groups.get(gid, [])
                keep = [m for m in members if m not in keys]
                if not keep:
                    reason = "같은 내용의 파일을 모두 지우려 했습니다. 그룹마다 1개는 남겨야 합니다"
                elif not any(m in entries and _changed_since_scan(entries[m]) is None for m in keep):
                    reason = "남길 파일이 검색 이후 바뀌었거나 없어졌습니다. 다시 검색하세요"
                else:
                    continue
                for k in keys:
                    rejected.append({"path": entries[k]['path'], "reason": reason})
                    drop.add(k)
            chosen = [k for k in chosen if k not in drop]

        targets = [entries[k]['path'] for k in chosen]
        if targets:
            res = safe_delete.to_recycle_bin(targets)
        else:
            res = {'ok': [], 'failed': [], 'bytes': 0, 'not_recyclable': []}

        # 옮긴 파일은 검색 결과에서 뺀다. 그룹의 나머지는 남겨서 '마지막 1개' 규칙이 계속 지켜지게 한다.
        path_to_key = {entries[k]['path']: k for k in chosen}
        with _state_lock:
            if _state['id'] == scan_id:
                for p in res.get('ok', []):
                    k = path_to_key.get(p)
                    if not k:
                        continue
                    ent = _state['entries'].pop(k, None)
                    gid = ent and ent.get('groupId')
                    if gid and gid in _state['groups']:
                        _state['groups'][gid] = [m for m in _state['groups'][gid] if m != k]

        return _delete_result(res.get('ok', []), res.get('bytes', 0),
                              rejected + res.get('failed', []),
                              res.get('not_recyclable', []))
