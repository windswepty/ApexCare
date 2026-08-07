import os
from backend import system_monitor
from backend import optimizer
from backend import system_repair
from backend import uninstaller
from backend import file_finder
from backend import debloater
from backend import game_booster
import json

class Api:
    def __init__(self, window):
        self._window = window

    def getSystemStats(self):
        stats = system_monitor.get_system_stats()
        if not stats:
            return {
                'cpuUsage': 0, 'ramPct': 0, 'diskPct': 0,
                'cpuModel': 'Error', 'cpuCores': 0, 'cpuThreads': 0,
                'ramTotalGB': '0', 'ramUsedGB': '0',
                'diskTotalGB': '0', 'diskUsedGB': '0'
            }
        return stats

    def startDeepOptimization(self):
        return optimizer.start_deep_optimization()

    def cancelDeepOptimization(self):
        return optimizer.cancel_deep_optimization()

    def getDeepOptimizationStatus(self):
        return optimizer.get_deep_optimization_status()

    def scanJunk(self):
        return optimizer.scan_junk()

    def cleanJunk(self, selectedIds):
        return optimizer.clean_junk(selectedIds)

    def cleanTempFiles(self):
        # 1번 항목(Temp) 정리 호출
        res = optimizer.clean_junk([1])
        freed = res.get("freedMB", 0)
        return {"success": True, "message": f"임시 파일 정리 완료 (약 {freed}MB 확보)", "freedMB": freed}
        
    def purgeRam(self):
        res = optimizer.purge_ram()
        if res.get("success"):
            return {"success": True, "message": f"RAM 메모리 최적화 완료 (프로세스 {res.get('purgedProcesses')}개 최적화)", "freedMB": 0}
        return {"success": False, "message": "RAM 메모리 최적화 실패", "error": res.get("error")}

    def runTrim(self):
        return system_repair.run_trim()

    def optimizeNetwork(self):
        return system_repair.optimize_network()

    def runSfc(self):
        return system_repair.run_sfc()
        
    def runDism(self):
        return system_repair.run_dism()

    def getStartupApps(self):
        try:
            return json.dumps(optimizer.get_startup_apps())
        except Exception as e:
            return json.dumps([])

    def toggleStartupApp(self, name, enabled):
        return optimizer.toggle_startup_app(name, enabled)

    def getProcesses(self):
        return system_monitor.get_processes()

    def killProcess(self, pid):
        return system_monitor.kill_process(pid)

    def setProcessPriority(self, pid, priority):
        return system_monitor.set_process_priority(pid, priority)

    def getOptimizationMode(self):
        return optimizer.get_optimization_mode()

    def setOptimizationMode(self, mode):
        return optimizer.set_optimization_mode(mode)
        
    def applyHardwareTuning(self, cpu_cores, ram_gb):
        return optimizer.apply_hardware_tailored_tuning(cpu_cores, ram_gb)

    # --- Uninstaller Features ---
    def getUninstallerApps(self):
        try:
            return json.dumps(uninstaller.get_installed_apps())
        except Exception:
            return json.dumps([])

    def uninstallApp(self, uninstall_string):
        return uninstaller.run_uninstall(uninstall_string)

    def findAppLeftovers(self, app_name):
        return uninstaller.find_leftovers(app_name)

    def cleanAppLeftovers(self, paths):
        return uninstaller.clean_leftovers(paths)

    # --- File Finder Features ---
    def findLargeFiles(self, min_mb=500):
        return file_finder.scan_large_files(min_mb)

    def findDuplicateFiles(self):
        return file_finder.scan_duplicates()

    def deleteFiles(self, paths):
        return file_finder.delete_files(paths)

    # === Debloater API ===
    def getDebloatList(self):
        return debloater.get_debloat_list()
        
    def getDebloatStatus(self):
        return debloater.get_debloat_status()
        
    def startDebloater(self, selectedIds):
        return debloater.start_debloater(selectedIds)

    # === Game Booster API ===
    def getGameBoosterStatus(self):
        return game_booster.get_booster_status()
        
    def toggleGameBooster(self, enabled):
        return game_booster.toggle_booster(enabled)


    def closeWindow(self):
        if self._window:
            self._window.destroy()

    def minimizeWindow(self):
        if self._window:
            self._window.minimize()

    def maximizeWindow(self):
        if self._window:
            self._window.toggle_fullscreen()
