import sys
import os
import hashlib
import concurrent.futures

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
    
    # Exclude system folders to prevent breaking things
    exclude_dirs = ['Windows', 'Program Files', 'Program Files (x86)', 'ProgramData', 'System Volume Information', '$Recycle.Bin', 'AppData']
    
    for target_dir in drives:
        if not os.path.exists(target_dir):
            continue
            
        for root, dirs, files in os.walk(target_dir):
            # Filter excluded dirs in place
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
            
            for file in files:
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
    except Exception:
        return None

def scan_duplicates():
    """Scan all local drives for duplicate files."""
    drives = get_local_drives()
    
    # Exclude system folders
    exclude_dirs = ['Windows', 'Program Files', 'Program Files (x86)', 'ProgramData', 'System Volume Information', '$Recycle.Bin', 'AppData']
    
    file_sizes = {}
    
    # First pass: group files by size
    for target_dir in drives:
        if not os.path.exists(target_dir):
            continue
            
        for root, dirs, files in os.walk(target_dir):
            # Filter excluded dirs in place
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
            
            for file in files:
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
                except Exception:
                    pass
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
    """Delete multiple files safely with strict system folder protection."""
    deleted_mb = 0
    failed = 0
    
    # Critical system paths that should NEVER be touched
    protected_roots = [
        os.environ.get('WINDIR', 'C:\\Windows').lower(),
        os.environ.get('PROGRAMFILES', 'C:\\Program Files').lower(),
        os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)').lower(),
        os.environ.get('PROGRAMDATA', 'C:\\ProgramData').lower()
    ]
    
    for p in paths:
        if not os.path.exists(p) or not os.path.isfile(p):
            failed += 1
            continue
            
        # Security check: prevent deletion if path is inside protected roots
        p_lower = p.lower()
        is_protected = any(p_lower.startswith(pr) for pr in protected_roots)
        if is_protected:
            failed += 1
            continue
            
        try:
            size = os.path.getsize(p)
            os.unlink(p)
            deleted_mb += (size / (1024*1024))
        except Exception:
            failed += 1
                
    return {"success": True, "freedMB": round(deleted_mb, 2), "failed": failed}
