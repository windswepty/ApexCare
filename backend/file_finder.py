import os
import hashlib
import concurrent.futures

def scan_large_files(min_mb=500):
    """Scan user folders for files larger than min_mb."""
    # To be safe and fast, we scan the User profile directory
    target_dir = os.environ.get('USERPROFILE', '')
    if not target_dir or not os.path.exists(target_dir):
        return []
        
    min_bytes = min_mb * 1024 * 1024
    large_files = []
    
    # Exclude system or hidden AppData folders to prevent breaking things
    exclude_dirs = ['AppData', 'Application Data', 'Local Settings']
    
    for root, dirs, files in os.walk(target_dir):
        # Filter excluded dirs in place
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
        
        for file in files:
            try:
                full_path = os.path.join(root, file)
                if not os.path.islink(full_path):
                    size = os.path.getsize(full_path)
                    if size >= min_bytes:
                        large_files.append({
                            "path": full_path,
                            "name": file,
                            "sizeMB": round(size / (1024*1024), 2),
                            "modified": os.path.getmtime(full_path)
                        })
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
    """Scan user documents and downloads for duplicate files."""
    target_dirs = [
        os.path.join(os.environ.get('USERPROFILE', ''), 'Downloads'),
        os.path.join(os.environ.get('USERPROFILE', ''), 'Documents'),
        os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
    ]
    
    # First pass: map sizes to files
    size_map = {}
    for target in target_dirs:
        if not os.path.exists(target): continue
        for root, dirs, files in os.walk(target):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                try:
                    full_path = os.path.join(root, file)
                    if not os.path.islink(full_path):
                        size = os.path.getsize(full_path)
                        # Only consider files > 10MB to save time
                        if size > 10 * 1024 * 1024:
                            if size not in size_map:
                                size_map[size] = []
                            size_map[size].append(full_path)
                except (OSError, PermissionError):
                    pass

    # Second pass: only hash files that share the same size
    potential_dupes = {k: v for k, v in size_map.items() if len(v) > 1}
    
    hash_map = {}
    
    # We can parallelize the hashing
    files_to_hash = [filepath for group in potential_dupes.values() for filepath in group]
    
    def process_file(filepath):
        h = _hash_file(filepath)
        return filepath, h

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(process_file, files_to_hash)
        for filepath, h in results:
            if h:
                if h not in hash_map:
                    hash_map[h] = []
                hash_map[h].append(filepath)
                
    # Filter only those with actual duplicates
    duplicates = []
    group_id = 1
    for h, paths in hash_map.items():
        if len(paths) > 1:
            for p in paths:
                try:
                    size = os.path.getsize(p)
                    duplicates.append({
                        "groupId": group_id,
                        "path": p,
                        "name": os.path.basename(p),
                        "sizeMB": round(size / (1024*1024), 2),
                        "hash": h
                    })
                except Exception:
                    pass
            group_id += 1
            
    # Sort by size descending (first item in group)
    duplicates.sort(key=lambda x: (x["sizeMB"], x["groupId"]), reverse=True)
    return duplicates

def delete_files(paths):
    """Delete multiple files safely."""
    deleted_mb = 0
    failed = 0
    for p in paths:
        if os.path.exists(p) and os.path.isfile(p):
            try:
                size = os.path.getsize(p)
                os.unlink(p)
                deleted_mb += (size / (1024*1024))
            except Exception:
                failed += 1
                
    return {"success": True, "freedMB": round(deleted_mb, 2), "failed": failed}
