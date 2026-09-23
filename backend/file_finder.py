import sys
import os
import hashlib
import concurrent.futures
import logging

log = logging.getLogger('FileFinder')

# Import shared protection constants from optimizer
from backend.optimizer import PROTECTED_ROOTS, DANGER_EXTS
from backend import safe_delete

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
            
        for root, dirs, files in os.walk(target_dir):
            # Filter excluded dirs in place
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
            
            # Security check: absolute block on core folders
            root_lower = root.lower()
            if any(blk in root_lower for blk in ['\\windows\\system32', '\\windows\\syswow64', '\\windows\\winsxs']):
                continue
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in DANGER_EXTS:
                    continue
                    
                try:
                    full_path = os.path.join(root, file)
                    if not os.path.islink(full_path):
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
    
    # First pass: group files by size
    for target_dir in drives:
        if not os.path.exists(target_dir):
            continue
            
        for root, dirs, files in os.walk(target_dir):
            # Filter excluded dirs in place
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
            
            # Security check: absolute block on core folders
            root_lower = root.lower()
            if any(blk in root_lower for blk in ['\\windows\\system32', '\\windows\\syswow64', '\\windows\\winsxs']):
                continue
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in DANGER_EXTS:
                    continue
                # For duplicate scanning, we don't necessarily only allow SAFE_EXTS, but we strictly block DANGER_EXTS.
                
                try:
                    full_path = os.path.join(root, file)
                    if not os.path.islink(full_path):
                        size = os.path.getsize(full_path)
                        # Only consider files > 10MB to speed up duplicate scanning
                        if size > 10 * 1024 * 1024:
                            try:
                                with open(full_path, 'ab'):
                                    pass
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
        # 시스템 보호 구역과 위험 확장자는 그대로 유지한다
        if any(pr in p.lower() for pr in PROTECTED_ROOTS):
            rejected.append({"path": p, "reason": "보호된 시스템 폴더"})
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
