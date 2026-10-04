import os
import re
import hashlib
import concurrent.futures
import logging

log = logging.getLogger('FileFinder')

from backend.optimizer import DANGER_EXTS, _is_link_like
from backend import safe_delete

# 스캔·삭제 대상에서 빼는 시스템·앱 영역. 실경로(safe_delete.norm)가 이 안이면 건드리지 않는다.
_SYSTEM_ENV_ROOTS = ('SystemRoot', 'windir', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432',
                     'ProgramData', 'APPDATA', 'LOCALAPPDATA')

# 경로 '구성 요소' 가 정확히 이 이름이면 건드리지 않는다(대소문자 무시). 부분 일치가 아니다.
# 게임 라이브러리의 대용량 파일은 게임 데이터라, 지우면 게임이 깨진다.
_BLOCKED_COMPONENTS = {
    'system volume information', '$recycle.bin', 'windowsapps',
    'steamlibrary', 'steamapps', 'origin games', 'riot games', 'epic games',
    'battle.net', 'ubisoft game launcher',
    # 드라이브 루트에 기본으로 설치하는 런처들. Xbox 앱(게임 패스)은 XboxGames, GOG 단독 설치는 GOG Games,
    # 아마존은 Amazon Games, 넥슨은 Nexon. 다른 드라이브에 옮겨 설치한 EA·Rockstar 도 같은 이름을 쓴다.
    'xboxgames', 'gog games', 'amazon games', 'nexon', 'ea games', 'rockstar games',
}


def _read_gaming_root(drive_root):
    """Xbox 앱이 드라이브 루트에 남기는 .GamingRoot 에 적힌 게임 폴더(절대 경로) 목록.

    사용자가 Xbox 앱에서 설치 폴더 이름을 바꿀 수 있어서 이름 목록만으로는 못 거른다.
    형식: b'RGBX' + 개수(uint32 LE) + 드라이브 루트 기준 상대 경로(UTF-16LE, 널 종료)들.
    """
    marker = os.path.join(drive_root, '.GamingRoot')
    if not os.path.isfile(marker) or _is_cloud_only(marker):
        return []
    try:
        with open(marker, 'rb') as f:
            raw = f.read(4096)
    except OSError:
        return []
    if len(raw) < 8 or raw[:4] != b'RGBX':
        return []
    count = int.from_bytes(raw[4:8], 'little')
    names = raw[8:].decode('utf-16-le', errors='ignore').split('\x00')
    out = []
    for n in names[:max(count, 0)]:
        n = n.strip().strip('\\/')
        if n:
            out.append(os.path.join(drive_root, n))
    return out


def _gaming_roots():
    roots = []
    for d in get_local_drives():
        roots.extend(_read_gaming_root(d))
    return roots


# OneDrive 같은 클라우드 동기화의 '온라인 전용' 파일 표시. 이 파일은 내용을 읽거나(해시) 쓰기로 열면
# 내려받는다. 대용량·중복 검사 한 번에 수십 GB 가 내려받아질 수 있고, 로컬 공간도 쓰지 않으므로
# 검사·삭제 대상이 아니다. 속성은 디렉터리 정보에서 읽으므로 확인해도 내려받지 않는다.
_FILE_ATTRIBUTE_OFFLINE = 0x1000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
_CLOUD_ONLY_ATTRS = (_FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_OPEN
                     | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)


def _is_cloud_only(path):
    """내용이 로컬에 없는 파일(온라인 전용)이면 True. 확인하지 못하면 True(읽지 않는 쪽이 안전하다)."""
    try:
        attrs = getattr(os.lstat(path), 'st_file_attributes', 0)   # Windows 가 아니면 속성이 없다
    except OSError:
        return True
    return bool(attrs & _CLOUD_ONLY_ATTRS)


def _local_file_stat(path):
    """검사해도 되는 로컬 파일이면 os.stat 결과, 아니면 None.

    링크·정션·온라인 전용 파일은 None. 파일을 열지 않는다. 예전에는 잠김 여부를 보려고 모든 후보를
    쓰기 모드('ab')로 열었다. 온라인 전용 파일은 그것만으로 내려받아질 수 있다.
    """
    if _is_link_like(path) or _is_cloud_only(path):
        return None
    try:
        return os.stat(path)
    except OSError:
        return None


def _system_roots():
    return [os.environ.get(k) for k in _SYSTEM_ENV_ROOTS if os.environ.get(k)]


# 드라이브 루트 바로 아래의 Windows 관리 폴더(이름 정확 일치). '이 PC 초기화' 용 복구 이미지·제조사 패키지,
# 업그레이드 임시 폴더 등이다. 숨김·시스템 폴더라 사용자가 만든 파일이 아니다.
_OS_ROOT_DIRS = {'recovery', '$windows.~bt', '$windows.~ws', '$winreagent', '$sysreset', 'windows.old',
                 'msocache', 'config.msi', 'boot', 'efi', 'perflogs', '$getcurrent'}


def _blocked_reason(path, gaming_roots=()):
    """이 파일을 스캔·삭제 대상으로 삼으면 안 되는 이유. 괜찮으면 None.

    예전에는 경로 문자열에 'program files' 같은 조각이 들어 있는지만 봤다.
    C:\\PROGRA~1 같은 짧은 이름이나 정션을 거친 경로는 통과했고, 반대로 파일 이름에
    'epic games' 가 들어간 사용자 동영상은 막혔다. 이제 실경로로 풀어서 판단한다.
    """
    real = safe_delete.norm(path)
    for root in _system_roots():
        if safe_delete.is_inside(real, root):
            return "보호된 시스템·프로그램 폴더"
    comps = [c for c in re.split(r'[\\/]+', real) if c]
    if len(comps) >= 2 and comps[1].lower() in _OS_ROOT_DIRS:      # comps[0] 은 드라이브('c:')
        return "Windows 복구·업그레이드 폴더"
    parts = {c.lower() for c in comps}
    if parts & _BLOCKED_COMPONENTS:
        return "게임 라이브러리·시스템 폴더"
    for g in gaming_roots:                     # Xbox 앱이 .GamingRoot 에 적어 둔 설치 폴더(이름을 바꿨어도)
        if safe_delete.is_inside(real, g):
            return "게임 라이브러리·시스템 폴더"
    # safe_delete.is_protected 는 쓰지 않는다. 그건 '폴더를 통째로 지워도 되나' 판정이라
    # 문서·다운로드·사용자 폴더 자체를 막는다(스캔이 그 안으로 못 들어간다).
    # 파일 하나를 휴지통으로 보내는 단계(to_recycle_bin)가 그 검사를 따로 한다.
    return None


def _walk_user_files(top, exclude_dirs, gaming_roots=()):
    """드라이브를 돈다. 링크·정션인 폴더와 시스템 영역에는 들어가지 않는다.

    os.walk 는 정션을 따라간다. 'Documents and Settings' 같은 정션을 따라가면 같은 파일이
    두 경로로 잡혀 '중복 파일' 로 오인되고, 사용자가 사본이라 믿고 지운 것이 유일한 원본이 된다.
    """
    for root, dirs, files in os.walk(top, topdown=True, followlinks=False):
        kept = []
        for d in dirs:
            if d in exclude_dirs or d.startswith('.'):
                continue
            full = os.path.join(root, d)
            if _is_link_like(full) or _blocked_reason(full, gaming_roots):
                continue
            kept.append(d)
        dirs[:] = kept
        yield root, files

def get_local_drives():
    import psutil
    drives = []
    for p in psutil.disk_partitions(all=False):
        # 고정 디스크만. USB 메모리·네트워크 드라이브는 휴지통이 없어 이 화면에서 지울 수 없다
        # (safe_delete 가 영구 삭제를 막는다). 지울 수 없는 파일을 목록에 올리지 않는다.
        if p.fstype and 'fixed' in (p.opts or '').split(','):
            drives.append(p.mountpoint)
    return drives if drives else ['C:\\']

def scan_large_files(min_mb=500):
    """Scan all local drives for files larger than min_mb."""
    # 화면에서 온 값이다. 문자열이 오면 '500' * 1048576 처럼 거대한 문자열을 만들고, 0·음수면 모든 파일이 잡힌다.
    if isinstance(min_mb, bool) or not isinstance(min_mb, (int, float)) or not (1 <= min_mb <= 1024 * 1024):
        min_mb = 500
    drives = get_local_drives()
    min_bytes = min_mb * 1024 * 1024
    large_files = []
    gaming = _gaming_roots()
    
    # Exclude system folders AND game platforms to prevent breaking things
    exclude_dirs = [
        'Windows', 'Program Files', 'Program Files (x86)', 'ProgramData',
        'System Volume Information', '$Recycle.Bin', 'AppData',
        'SteamLibrary', 'steamapps', 'Origin Games', 'Riot Games',
        'Epic Games', 'Battle.net', 'Ubisoft Game Launcher',
    ]
    
    
    for target_dir in drives:
        if not os.path.exists(target_dir):
            continue
            
        for root, files in _walk_user_files(target_dir, exclude_dirs, gaming):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in DANGER_EXTS:
                    continue
                    
                full_path = os.path.join(root, file)
                st = _local_file_stat(full_path)
                if st is None or st.st_size < min_bytes:
                    continue
                large_files.append({
                    "path": full_path,
                    "name": file,
                    "sizeMB": round(st.st_size / (1024*1024), 2),
                    "modified": st.st_mtime,
                })
                    
    # Sort descending by size
    large_files.sort(key=lambda x: x["sizeMB"], reverse=True)
    return large_files

def _hash_file(filepath, chunk_size=8192):
    """파일 전체의 해시. 읽지 못하면(잠김 등) None.

    읽기 직전에 온라인 전용인지 다시 본다. 첫 번째 순회 뒤에 OneDrive 가 '공간 확보' 로
    파일을 온라인 전용으로 바꿨을 수 있다. 그 파일을 읽으면 통째로 내려받는다.
    """
    if _is_cloud_only(filepath):
        return None
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        log.debug(f"Hash error {filepath}: {e}")
        return None

def scan_duplicates():
    """Scan all local drives for duplicate files."""
    drives = get_local_drives()
    
    # Exclude system folders AND game platforms
    exclude_dirs = [
        'Windows', 'Program Files', 'Program Files (x86)', 'ProgramData',
        'System Volume Information', '$Recycle.Bin', 'AppData',
        'SteamLibrary', 'steamapps', 'Origin Games', 'Riot Games',
        'Epic Games', 'Battle.net', 'Ubisoft Game Launcher',
    ]
    
    # Strict whitelist and blacklist
    
    file_sizes = {}
    seen_real = set()
    gaming = _gaming_roots()
    
    # First pass: group files by size
    for target_dir in drives:
        if not os.path.exists(target_dir):
            continue
            
        for root, files in _walk_user_files(target_dir, exclude_dirs, gaming):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in DANGER_EXTS:
                    continue
                # For duplicate scanning, we don't necessarily only allow SAFE_EXTS, but we strictly block DANGER_EXTS.
                
                full_path = os.path.join(root, file)
                st = _local_file_stat(full_path)
                # Only consider files > 10MB to speed up duplicate scanning
                if st is None or st.st_size <= 10 * 1024 * 1024:
                    continue
                real = safe_delete.norm(full_path)
                if real in seen_real:
                    continue      # 같은 파일을 다른 경로로 또 만났다. 중복이 아니다.
                seen_real.add(real)
                file_sizes.setdefault(st.st_size, []).append({
                    "path": full_path,
                    "name": file,
                    "size": st.st_size,
                    "modified": st.st_mtime,
                })
                    
    # Only keep groups with > 1 file
    potential_dupes = {sz: files for sz, files in file_sizes.items() if len(files) > 1}
    
    # Second pass: hash check
    duplicates = []
    
    for size, files in potential_dupes.items():
        hashes = {}
        # We can use ThreadPoolExecutor to speed up hashing
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_file = {executor.submit(_hash_file, f["path"]): f for f in files}
            for future in concurrent.futures.as_completed(future_to_file):
                file_info = future_to_file[future]
                try:
                    h = future.result()
                    if h:
                        if h not in hashes:
                            hashes[h] = []
                        hashes[h].append(file_info)
                except Exception as e:
                    log.debug(f"Future hash error: {e}")
        # Add to duplicates if still > 1
        for h, group in hashes.items():
            if len(group) > 1:
                group_id = h[:8]
                for f in group:
                    f["groupId"] = group_id
                    f["sizeMB"] = round(f["size"] / (1024*1024), 2)
                    duplicates.append(f)
                    
    # Sort by size descending, then by groupId
    duplicates.sort(key=lambda x: (-x["size"], x["groupId"]))
    return duplicates

def delete_files(paths):
    """선택한 파일을 휴지통으로 보낸다.

    예전에는 os.unlink 로 영구 삭제했다. 스캔 범위에 사용자의 문서·사진·동영상·
    소스코드·VM 디스크가 전부 포함되므로, 잘못 고른 파일 하나가 곧바로
    복구 불가능한 손실이 됐다. 휴지통을 거치면 되돌릴 수 있다.
    """
    if not paths:
        return {"success": True, "freedMB": 0, "deleted": 0, "failed": [],
                "message": "선택된 항목이 없습니다."}

    targets, rejected = [], []
    gaming = _gaming_roots()
    for p in paths:
        if not isinstance(p, str) or not os.path.exists(p):
            rejected.append({"path": p, "reason": "파일이 존재하지 않습니다"})
            continue
        # 이 화면은 파일만 다룬다. 폴더 경로가 넘어오면 폴더째 휴지통으로 가지 않게 거부한다.
        if not os.path.isfile(p) or _is_link_like(p):
            rejected.append({"path": p, "reason": "일반 파일이 아닙니다(폴더·링크)"})
            continue
        if _is_cloud_only(p):
            # 로컬 공간을 쓰지 않는다. 지우면 클라우드(OneDrive 등)의 원본이 지워진다.
            rejected.append({"path": p, "reason": "클라우드에만 있는 파일(이 PC 의 공간을 쓰지 않음)"})
            continue
        reason = _blocked_reason(p, gaming)
        if reason:
            rejected.append({"path": p, "reason": reason})
            continue
        if os.path.splitext(p)[1].lower() in DANGER_EXTS:
            rejected.append({"path": p, "reason": "시스템에 필요한 파일 형식"})
            continue
        targets.append(p)

    res = safe_delete.to_recycle_bin(targets)
    failed = rejected + res['failed']

    # 하나도 보내지 못하고 건너뛴 것만 있으면 실패다. 예전에는 대상이 모두 거부되면(targets 가 비면)
    # '0개 파일을 휴지통으로 보냈습니다' 가 성공으로 떴다.
    return {
        "success": bool(res['ok']) or not failed,
        "freedMB": round(res['bytes'] / (1024 ** 2), 2),
        "deleted": len(res['ok']),
        "failed": failed,
        "message": (f"{len(res['ok'])}개 파일을 휴지통으로 보냈습니다."
                    + (f" {len(failed)}개는 건너뛰었습니다." if failed else "")
                    + " 휴지통에서 복구할 수 있습니다."),
    }
