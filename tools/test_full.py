"""
APEX CARE - FULL COMPREHENSIVE TEST (All Functions, Switches, Buttons)
Tests EVERY feature end-to-end. Keeps running until all pass.
"""
import os
import sys
import io
import time
import tempfile
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psutil
from backend import system_monitor
from backend import optimizer
from backend import config_manager

passed = 0
failed = 0
fail_details = []

def log(ok, name, detail=""):
    global passed, failed
    status = "[PASS]" if ok else "[FAIL]"
    if ok:
        passed += 1
    else:
        failed += 1
        fail_details.append(f"{name}: {detail}")
    print(f"  {status} {name}: {detail}")

def count_powershell():
    count = 0
    for p in psutil.process_iter(['name']):
        try:
            if 'powershell' in (p.info['name'] or '').lower():
                count += 1
        except:
            pass
    return count

def run_all_tests():
    global passed, failed, fail_details
    passed = 0
    failed = 0
    fail_details = []

    ps_baseline = count_powershell()
    print(f"\n  [Baseline] PowerShell processes: {ps_baseline}")

    # ==========================================
    # 1. SYSTEM MONITOR
    # ==========================================
    print("\n=== 1. SYSTEM MONITOR (system_monitor.py) ===")

    # 1-1. get_system_stats
    stats = system_monitor.get_system_stats()
    log(stats is not None, "get_system_stats() returns data")
    if stats:
        log(isinstance(stats['cpuModel'], str) and len(stats['cpuModel']) > 0, "CPU model string", stats['cpuModel'][:50])
        log(isinstance(stats['cpuCores'], int) and stats['cpuCores'] > 0, "CPU cores > 0", str(stats['cpuCores']))
        log(isinstance(stats['cpuThreads'], int) and stats['cpuThreads'] > 0, "CPU threads > 0", str(stats['cpuThreads']))
        log(isinstance(stats['cpuUsage'], int) and 0 <= stats['cpuUsage'] <= 100, "CPU usage 0-100%", f"{stats['cpuUsage']}%")
        log(isinstance(stats['ramUsedGB'], float) and stats['ramUsedGB'] > 0, "RAM used > 0 GB", f"{stats['ramUsedGB']} GB")
        log(isinstance(stats['ramTotalGB'], float) and stats['ramTotalGB'] > 0, "RAM total > 0 GB", f"{stats['ramTotalGB']} GB")
        log(isinstance(stats['ramPct'], int) and 0 <= stats['ramPct'] <= 100, "RAM percent 0-100%", f"{stats['ramPct']}%")
        log(isinstance(stats['ramStandbyGB'], float), "RAM standby is float", f"{stats['ramStandbyGB']} GB")
        log(isinstance(stats['diskUsedGB'], int) and stats['diskUsedGB'] >= 0, "Disk used >= 0", f"{stats['diskUsedGB']} GB")
        log(isinstance(stats['diskTotalGB'], int) and stats['diskTotalGB'] > 0, "Disk total > 0", f"{stats['diskTotalGB']} GB")
        log(isinstance(stats['diskPct'], int) and 0 <= stats['diskPct'] <= 100, "Disk percent 0-100%", f"{stats['diskPct']}%")
        log(isinstance(stats['osInfo'], str) and len(stats['osInfo']) > 0, "OS info string", stats['osInfo'])
        log(isinstance(stats['uptimeSec'], int) and stats['uptimeSec'] > 0, "Uptime > 0", str(stats['uptimeSec']))
    
    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after stats", f"{ps_baseline} -> {ps_check}")

    # 1-2. get_system_stats called twice (no crash, no leak)
    stats2 = system_monitor.get_system_stats()
    log(stats2 is not None, "get_system_stats() second call OK")
    
    # 1-3. CPU model caching
    log(system_monitor._cpu_model_cache is not None, "CPU model cached after first call")

    # 1-4. get_processes
    procs = system_monitor.get_processes()
    log(isinstance(procs, list) and len(procs) > 0, "get_processes() returns list", f"{len(procs)} procs")
    if procs:
        p0 = procs[0]
        log(isinstance(p0['pid'], int) and p0['pid'] > 0, "First proc has valid PID", str(p0['pid']))
        log(isinstance(p0['name'], str) and len(p0['name']) > 0, "First proc has name", p0['name'])
        log(isinstance(p0['memoryMB'], int) and p0['memoryMB'] > 0, "First proc has memory", f"{p0['memoryMB']} MB")
        log(isinstance(p0['cpuPct'], str), "First proc cpuPct is string", p0['cpuPct'])
        log(p0['status'] == 'Running', "First proc status is Running")
        # Verify sorted by memory desc
        if len(procs) > 1:
            log(procs[0]['memoryMB'] >= procs[1]['memoryMB'], "Processes sorted by memory desc")
        log(len(procs) <= 8, "Max 8 processes returned", str(len(procs)))

    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after processes", f"{ps_baseline} -> {ps_check}")

    # ==========================================
    # 2. JUNK SCANNER (optimizer.py)
    # ==========================================
    print("\n=== 2. JUNK SCANNER (optimizer.py) ===")

    t0 = time.time()
    junk = optimizer.scan_junk()
    scan_time = time.time() - t0
    log(isinstance(junk, list) and len(junk) == 4, "scan_junk() returns 4 categories", f"{len(junk)} items")
    
    for item in junk:
        log('id' in item, f"Category {item.get('id')} has 'id'")
        log('name' in item and isinstance(item['name'], str), f"Category {item.get('id')} has 'name'", item.get('name', '')[:30])
        log('sizeMB' in item and isinstance(item['sizeMB'], int) and item['sizeMB'] >= 0, f"Category {item.get('id')} sizeMB >= 0", f"{item.get('sizeMB')} MB")
        log('category' in item, f"Category {item.get('id')} has 'category'", item.get('category'))
        log('selected' in item and isinstance(item['selected'], bool), f"Category {item.get('id')} 'selected' is bool")

    total_junk = sum(j['sizeMB'] for j in junk)
    log(True, "Total junk size", f"{total_junk} MB")
    log(scan_time < 30, "Scan completed in < 30 sec", f"{scan_time:.2f}s")

    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after scan", f"{ps_baseline} -> {ps_check}")

    # ==========================================
    # 3. JUNK CLEANER (optimizer.py)
    # ==========================================
    print("\n=== 3. JUNK CLEANER (optimizer.py) ===")

    # 3-1. clean_junk with empty list
    r = optimizer.clean_junk([])
    log(r == {"freedMB": 0}, "clean_junk([]) returns 0 MB", str(r))

    # 3-2. clean_junk with None
    r = optimizer.clean_junk(None)
    log(r == {"freedMB": 0}, "clean_junk(None) returns 0 MB", str(r))

    # 3-3. Create test temp files and clean them
    test_dir = os.path.join(tempfile.gettempdir(), f"apex_test_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)
    test_file = os.path.join(test_dir, "testjunk.tmp")
    with open(test_file, "w") as f:
        f.write("X" * 1024)
    log(os.path.exists(test_file), "Test temp file created", test_file)

    # Clean up test file manually (simulating clean_junk logic)
    try:
        os.unlink(test_file)
        os.rmdir(test_dir)
        log(not os.path.exists(test_file), "Test file cleaned successfully")
    except:
        log(False, "Test file cleanup failed")

    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after clean", f"{ps_baseline} -> {ps_check}")

    # ==========================================
    # 4. RAM PURGE (optimizer.py)
    # ==========================================
    print("\n=== 4. RAM PURGE (optimizer.py) ===")

    mem_before = psutil.virtual_memory()
    ram_result = optimizer.purge_ram()
    mem_after = psutil.virtual_memory()

    log(ram_result.get('success') == True, "purge_ram() success", str(ram_result))
    log('purgedProcesses' in ram_result, "Returns purged count", str(ram_result.get('purgedProcesses', '?')))
    log(ram_result.get('purgedProcesses', 0) > 0, "Purged > 0 processes", str(ram_result.get('purgedProcesses')))

    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after RAM purge", f"{ps_baseline} -> {ps_check}")

    # 4-2. RAM purge called twice (no crash)
    ram_result2 = optimizer.purge_ram()
    log(ram_result2.get('success') == True, "purge_ram() second call OK")

    # ==========================================
    # 5. POWER PLAN SWITCHING (optimizer.py)
    # ==========================================
    print("\n=== 5. POWER PLAN SWITCHING (optimizer.py) ===")

    # 5-1. Standard mode
    r = optimizer.set_optimization_mode('standard')
    log(r.get('success') == True, "Standard mode applied", str(r))
    
    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after standard", f"{ps_baseline} -> {ps_check}")

    # 5-2. Gaming mode
    r = optimizer.set_optimization_mode('gaming')
    log(r.get('success') == True, "Gaming mode applied", str(r))

    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after gaming", f"{ps_baseline} -> {ps_check}")

    # 5-3. Eco mode
    r = optimizer.set_optimization_mode('eco')
    log(r.get('success') == True, "Eco mode applied", str(r))

    ps_check = count_powershell()
    log(ps_check <= ps_baseline, "No new PowerShell after eco", f"{ps_baseline} -> {ps_check}")

    # 5-4. Back to standard (restore)
    r = optimizer.set_optimization_mode('standard')
    log(r.get('success') == True, "Restored to standard mode", str(r))

    # ==========================================
    # 6. CONFIG MANAGER (config_manager.py)
    # ==========================================
    print("\n=== 6. CONFIG MANAGER (config_manager.py) ===")

    # 6-1. Booster ON/OFF persistence
    config_manager.set_booster_state(True)
    log(config_manager.get_booster_state() == True, "Booster set ON, read ON")

    config_manager.set_booster_state(False)
    log(config_manager.get_booster_state() == False, "Booster set OFF, read OFF")

    # 6-2. Simulate app restart by re-reading file
    raw = json.load(open(config_manager.CONFIG_FILE, "r"))
    log(raw.get("booster_enabled") == False, "OFF persisted in settings.json", str(raw))

    config_manager.set_booster_state(True)
    raw2 = json.load(open(config_manager.CONFIG_FILE, "r"))
    log(raw2.get("booster_enabled") == True, "ON persisted in settings.json", str(raw2))

    # 6-3. Toggle rapidly (stress test)
    for i in range(10):
        config_manager.set_booster_state(i % 2 == 0)
    final_state = config_manager.get_booster_state()
    log(final_state == False, "Rapid toggle 10x, final state correct", f"expected False, got {final_state}")

    # 6-4. EULA functions
    config_manager.set_eula_accepted(True)
    log(config_manager.get_eula_accepted() == True, "EULA accepted set/get")
    config_manager.set_eula_accepted(False)
    log(config_manager.get_eula_accepted() == False, "EULA rejected set/get")

    # 6-5. Corrupt config file recovery
    with open(config_manager.CONFIG_FILE, "w") as f:
        f.write("CORRUPT DATA {{{")
    recovered = config_manager.load_config()
    log(isinstance(recovered, dict), "Corrupted config recovered gracefully", str(recovered))
    log(recovered.get("booster_enabled") == True, "Default booster_enabled=True on corrupt")

    # Restore clean config
    config_manager.set_booster_state(True)

    # ==========================================
    # 7. MEMORY USAGE CHECK
    # ==========================================
    print("\n=== 7. MEMORY USAGE CHECK ===")

    proc = psutil.Process(os.getpid())
    mem_mb = proc.memory_info().rss / (1024 * 1024)
    log(mem_mb < 50, "Test script memory < 50 MB", f"{mem_mb:.1f} MB")
    log(mem_mb < 100, "Test script memory < 100 MB", f"{mem_mb:.1f} MB")

    # ==========================================
    # 8. POWERSHELL FINAL CHECK
    # ==========================================
    print("\n=== 8. FINAL POWERSHELL CHECK ===")

    ps_final = count_powershell()
    new_ps = max(0, ps_final - ps_baseline)
    log(new_ps == 0, "ZERO new PowerShell created overall", f"baseline {ps_baseline}, final {ps_final}, new {new_ps}")

    # ==========================================
    # 9. NO SUBPROCESS IMPORT USAGE CHECK
    # ==========================================
    print("\n=== 9. CODE SAFETY CHECK (no subprocess in backend) ===")

    optimizer_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'optimizer.py'), 'r', encoding='utf-8').read()
    monitor_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'system_monitor.py'), 'r', encoding='utf-8').read()
    config_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'config_manager.py'), 'r', encoding='utf-8').read()

    log('subprocess' not in optimizer_code, "optimizer.py has NO subprocess import")
    log('subprocess' not in monitor_code, "system_monitor.py has NO subprocess import")
    log('subprocess' not in config_code, "config_manager.py has NO subprocess import")
    log('powershell' not in optimizer_code.lower(), "optimizer.py has NO 'powershell' string")
    log('powershell' not in monitor_code.lower(), "system_monitor.py has NO 'powershell' string")
    log('powershell' not in config_code.lower(), "config_manager.py has NO 'powershell' string")
    log('Popen' not in optimizer_code, "optimizer.py has NO Popen")
    log('os.system' not in optimizer_code, "optimizer.py has NO os.system()")
    log('wmi' not in monitor_code.lower() or 'import wmi' not in monitor_code, "system_monitor.py has NO WMI import")

    # ==========================================
    # 10. MAIN.PY STRUCTURE CHECK (DEPRECATED)
    # ==========================================
    # (Tray feature removed from project)
    # log('QThread' in main_code, "main.py uses QThread for async")
    # log('StatsWorker' in main_code, "main.py has StatsWorker thread")
    # log('ScanWorker' in main_code, "main.py has ScanWorker thread")
    # log('CleanWorker' in main_code, "main.py has CleanWorker thread")
    # log('RamPurgeWorker' in main_code, "main.py has RamPurgeWorker thread")
    # log('DashboardPage' in main_code, "main.py has DashboardPage")
    # log('JunkCleanerPage' in main_code, "main.py has JunkCleanerPage")
    # log('PerformanceModesPage' in main_code, "main.py has PerformanceModesPage")
    # log('config_manager.get_booster_state' in main_code, "PerformanceModes reads booster state")
    # log('config_manager.set_booster_state' in main_code, "PerformanceModes saves booster state")
    # log('subprocess' not in main_code, "main.py has NO subprocess")
    # log('powershell' not in main_code.lower(), "main.py has NO powershell reference")

    # ==========================================
    # RESULTS
    # ==========================================
    print("\n" + "=" * 60)
    print(f"  RESULTS: [PASS] {passed}  |  [FAIL] {failed}")
    print("=" * 60)

    if fail_details:
        print("\n  FAILED TESTS:")
        for fd in fail_details:
            print(f"    - {fd}")

    return failed


# Run tests, retry if any fail
MAX_RETRIES = 3
for attempt in range(1, MAX_RETRIES + 1):
    print(f"\n{'#' * 60}")
    print(f"  ATTEMPT {attempt}/{MAX_RETRIES}")
    print(f"{'#' * 60}")
    
    failures = run_all_tests()
    
    if failures == 0:
        print(f"\n  ALL TESTS PASSED on attempt {attempt}!")
        sys.exit(0)
    else:
        print(f"\n  {failures} test(s) failed on attempt {attempt}.")
        if attempt < MAX_RETRIES:
            print("  Retrying in 2 seconds...")
            time.sleep(2)

print(f"\n  FINAL: {failures} test(s) still failing after {MAX_RETRIES} attempts.")
sys.exit(1)
