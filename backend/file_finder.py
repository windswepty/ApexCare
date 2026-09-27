import sys
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
}


def _system_roots():
    return [os.environ.get(k) for k in _SYSTEM_ENV_ROOTS if os.environ.get(k)]


def _blocked_reason(path):
    """이 파일을 스캔·삭제 대상으로 삼으면 안 되는 이유. 괜찮으면 None.

    예전에는 경로 문자열에 'program files' 같은 조각이 들어 있는지만 봤다.
    C:\\PROGRA~1 같은 짧은 이름이나 정션을 거친 경로는 통과했고, 반대로 파일 이름에
    'epic games' 가 들어간 사용자 동영상은 막혔다. 이제 실경로로 풀어서 판단한다.
    """
    real = safe_delete.norm(path)
    for root in _system_roots():
        if safe_delete.is_inside(real, root):
            return "보호된 시스템·프로그램 폴더"
    parts = {c.lower() for c in re.split(r'[\\/]+', real) if c}
    if parts & _BLOCKED_COMPONENTS:
        return "게임 라이브러리·시스템 폴더"
    # safe_delete.is_protected 는 쓰지 않는다. 그건 '폴더를 통째로 지워도 되나' 판정이라
    # 문서·다운로드·사용자 폴더 자체를 막는다(스캔이 그 안으로 못 들어간다).
    # 파일 하나를 휴지통으로 보내는 단계(to_recycle_bin)가 그 검사를 따로 한다.
    return None


def _walk_user_files(top, exclude_dirs):
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
            if _is_link_like(full) or _blocked_reason(full):
                continue
            kept.append(d)
        dirs[:] = kept
        yield root, files

def get_local_drives():
    import psutil
    drives = []
    for p in psutil.disk_partitions(all=False):
        if p.fstype and 'cdrom' not in p.opts:
            drives.append(p.mountpoint)
    return drives if drives else ['C:\\']

def scan_large_files(min_mb=500):
    """Scan all local drives for files larger than min_mb."""
    drives = get_local_drives()
    min_bytes = min_mb * 1024 * 1024
    large_files = []
    
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
            
        for root, files in _walk_user_files(target_dir, exclude_dirs):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in DANGER_EXTS:
                    continue
                    
                try:
                    full_path = os.path.join(root, file)
                    if not _is_link_like(full_path):
                        size = os.path.getsize(full_path)
                        if size >= min_bytes:
                            try:
                                with open(full_path, 'ab'):
                                    pass
                                large_files.append({
                                    "path": full_path,
                                    "name": file,
                                    "sizeMB": round(size / (1024*1024), 2),
                                    "modified": os.path.getmtime(full_path)
                                })
                            except (OSError, PermissionError) as e:
                                print(f"[SCAN_SKIP] locked file: {full_path}")
                                sys.stdout.flush()
                except (OSError, PermissionError):
                    pass
                    
    # Sort descending by size
    large_files.sort(key=lambda x: x["sizeMB"], reverse=True)
    return large_files

def _hash_file(filepath, chunk_size=8192):
    """Hash the entire file."""
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
    
    # First pass: group files by size
    for target_dir in drives:
        if not os.path.exists(target_dir):
            continue
            
        for root, files in _walk_user_files(target_dir, exclude_dirs):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in DANGER_EXTS:
                    continue
                # For duplicate scanning, we don't necessarily only allow SAFE_EXTS, but we strictly block DANGER_EXTS.
                
                try:
                    full_path = os.path.join(root, file)
                    if not _is_link_like(full_path):
                        size = os.path.getsize(full_path)
                        # Only consider files > 10MB to speed up duplicate scanning
                        if size > 10 * 1024 * 1024:
                            try:
                                with open(full_path, 'ab'):
                                    pass
                                real = safe_delete.norm(full_path)
                                if real in seen_real:
                                    continue      # 같은 파일을 다른 경로로 또 만났다. 중복이 아니다.
                                seen_real.add(real)
                                if size not in file_sizes:
                                    file_sizes[size] = []
                                file_sizes[size].append({
                                    "path": full_path,
                                    "name": file,
                                    "size": size,
                                    "modified": os.path.getmtime(full_path)
                                })
                            except (OSError, PermissionError):
                                pass
                except (OSError, PermissionError):
                    pass
                    
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
    for p in paths:
        if not isinstance(p, str) or not os.path.exists(p):
            rejected.append({"path": p, "reason": "파일이 존재하지 않습니다"})
            continue
        # 이 화면은 파일만 다룬다. 폴더 경로가 넘어오면 폴더째 휴지통으로 가지 않게 거부한다.
        if not os.path.isfile(p) or _is_link_like(p):
            rejected.append({"path": p, "reason": "일반 파일이 아닙니다(폴더·링크)"})
            continue
        reason = _blocked_reason(p)
        if reason:
            rejected.append({"path": p, "reason": reason})
            continue
        if os.path.splitext(p)[1].lower() in DANGER_EXTS:
            rejected.append({"path": p, "reason": "시스템에 필요한 파일 형식"})
            continue
        targets.append(p)

    res = safe_delete.to_recycle_bin(targets)
    failed = rejected + res['failed']

    return {
        "success": bool(res['ok']) or not targets,
        "freedMB": round(res['bytes'] / (1024 ** 2), 2),
        "deleted": len(res['ok']),
        "failed": failed,
        "message": (f"{len(res['ok'])}개 파일을 휴지통으로 보냈습니다."
                    + (f" {len(failed)}개는 건너뛰었습니다." if failed else "")
                    + " 휴지통에서 복구할 수 있습니다."),
    }
