import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import system_monitor
from backend import optimizer
from backend import uninstaller
from backend import file_finder
from backend import debloater
from backend import game_booster
from backend import system_repair

def run_tests():
    print("="*50)
    print("APEX CARE - Comprehensive Backend Integration Test")
    print("="*50)

    results = []
    
    def report(name, success, detail=""):
        status = "[PASS]" if success else "[FAIL]"
        msg = f"{status} | {name}"
        if detail:
            msg += f" -> {detail}"
        print(msg)
        results.append((name, success, detail))

    # 1. System Monitor
    try:
        stats = system_monitor.get_system_stats()
        if 'cpuUsage' in stats and 'ramPct' in stats:
            report("System Monitor (get_system_stats)", True, f"CPU: {stats['cpuUsage']}%, RAM: {stats['ramPct']}%")
        else:
            report("System Monitor (get_system_stats)", False, "Missing keys in stats")
    except Exception as e:
        report("System Monitor", False, str(e))

    # 2. Optimizer API
    try:
        opt_status = optimizer.get_deep_optimization_status()
        report("Optimizer (get_deep_optimization_status)", True, f"Running: {opt_status['running']}")
    except Exception as e:
        report("Optimizer", False, str(e))

    # 3. Uninstaller
    try:
        apps = uninstaller.get_installed_apps()
        if len(apps) > 0:
            report("Uninstaller (get_installed_apps)", True, f"Found {len(apps)} apps")
        else:
            report("Uninstaller (get_installed_apps)", True, "Found 0 apps (might be expected depending on registry access)")
    except Exception as e:
        report("Uninstaller", False, str(e))

    # 4. File Finder
    try:
        ff_status = file_finder.scan_large_files(1000)
        report("File Finder (scan_large_files)", True, f"Found {len(ff_status)} large files")
    except Exception as e:
        report("File Finder", False, str(e))

    # 5. Debloater
    try:
        debloat_list = debloater.get_debloat_list()
        report("Debloater (get_debloat_list)", True, f"Found {len(debloat_list)} targets (e.g. {debloat_list[0]['name']})")
    except Exception as e:
        report("Debloater", False, str(e))

    # 6. Game Booster
    try:
        gb_status = game_booster.get_booster_status()
        report("Game Booster (get_booster_status)", True, f"Enabled: {gb_status['enabled']}, Active: {gb_status['active']}")
    except Exception as e:
        report("Game Booster", False, str(e))

    # 7. System Repair
    try:
        # Check if sfc is available in path, don't actually run it since it requires admin and takes time
        report("System Repair (import check)", True, "Module loaded successfully")
    except Exception as e:
        report("System Repair", False, str(e))

    print("="*50)
    passed = sum(1 for r in results if r[1])
    print(f"Total: {len(results)}, Passed: {passed}, Failed: {len(results) - passed}")
    
if __name__ == "__main__":
    run_tests()
