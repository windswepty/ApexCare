import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import system_monitor, file_finder

print("=== RAM Standby Test ===")
# Wait a moment for poller to run
time.sleep(2)
stats = system_monitor.get_system_stats()
print(f"Stats keys: {stats.keys() if stats else 'None'}")
if stats:
    print(f"Standby RAM: {stats.get('ramStandbyGB')} GB")

print("\n=== Large File Finder Test ===")
files = file_finder.scan_large_files(500)
print(f"Large files found: {len(files)}")
for f in files[:5]:
    print(f" - {f['name']} ({f['sizeMB']} MB) at {f['path']}")
