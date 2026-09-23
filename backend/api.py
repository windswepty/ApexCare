import os
import logging
import json

from backend import system_monitor
from backend import optimizer
from backend import system_repair
from backend import uninstaller
from backend import file_finder
from backend import debloater
from backend import game_booster
from backend import config_manager
from backend import perf_modes
from backend import system_state

log = logging.getLogger('API')

class Api:
    def __init__(self, window):
        self._window = window
        try:
            game_booster.init_booster()
            optimizer.init_optimization_mode()
        except Exception as e:
            print(f"[Api] Initialization error: {e}")

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

    def getJunkScanStatus(self):
        return optimizer.get_junk_scan_status()

    def scanJunk(self):
        return optimizer.scan_junk()
        
    def getJunkCleanStatus(self):
        return optimizer.get_junk_clean_status()

    def cleanJunk(self, selectedIds):
        return optimizer.clean_junk(selectedIds)

    def cancelJunkClean(self):
        return optimizer.cancel_junk_clean()

    def cleanTempFiles(self):
        """Synchronous temp file clean for dashboard one-click optimization."""
        try:
            optimizer.clean_junk_background([1], cancel_event=None)
            freed = optimizer._junk_clean_state.get("freed_mb", 0)
            return {"success": True, "message": f"임시 파일 정리 완료 (약 {freed}MB 확보)", "freed_mb": freed}
        except Exception as e:
            return {"success": False, "message": "임시 파일 정리 실패", "error": str(e)}
        
    def purgeRam(self):
        res = optimizer.purge_ram()
        if res.get("success"):
            return {"success": True, "message": f"RAM 메모리 최적화 완료 (프로세스 {res.get('purgedProcesses')}개 최적화)", "freedMB": 0}
        return {"success": False, "message": "RAM 메모리 최적화 실패", "error": res.get("error")}

    def runTrim(self):
        return system_repair.run_trim()

    def getTrimStatus(self):
        return system_repair.get_trim_status()

    def optimizeNetwork(self, consent=False):
        # consent=False 는 미리보기(변경 예정 항목만 반환, 시스템 변경 없음).
        # 기본값이 False 라 프론트가 옛 버전이어도 영구 변경이 들어가지 않는다.
        return system_repair.apply_network_tweaks(consent=consent)

    def restoreNetworkTweaks(self):
        return system_repair.restore_network_tweaks()

    def getNetworkStatus(self):
        return system_repair.get_network_status()

    def runSfc(self):
        return system_repair.run_sfc()
        
    def runDism(self):
        return system_repair.run_dism()

    def getStartupApps(self):
        try:
            return optimizer.get_startup_apps()
        except Exception as e:
            log.warning(f"Error getting startup apps: {e}")
            return []

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
        """성능 모드 적용.

        반환값의 steps 에 항목별 성패가 들어 있다. 프론트는 이것을 반드시 확인해야 한다.
        예전에는 버튼을 누른 즉시 성공 토스트를 띄워, 실제로는 아무것도 적용되지 않아도
        사용자가 알 수 없었다.
        """
        return perf_modes.apply_mode(mode)

    def listOptimizationModes(self):
        """모드 카드에 표시할 정보. 무엇이 바뀌는지 미리 보여주기 위한 것."""
        return perf_modes.list_modes()

    def revertAllSystemChanges(self):
        """이 앱이 바꾼 모든 시스템 설정을 원래대로 되돌린다."""
        return perf_modes.revert_everything()

    def getPendingSystemChanges(self):
        """아직 되돌리지 않은 변경 목록. UI 가 '되돌리기' 버튼 노출 여부를 판단한다."""
        changes = system_state.pending_changes()
        by_group = {}
        for key, e in changes.items():
            by_group.setdefault(e.get('group', '기타'), []).append({
                'what': e.get('why') or key,
                'kind': e.get('kind'),
            })
        return {'count': len(changes), 'groups': by_group}
        
    def applyHardwareTuning(self, cpu_cores, ram_gb, consent=False):
        # consent=False 는 미리보기(변경 예정 항목만 반환, 시스템 변경 없음).
        # 기본값이 False 라 프론트가 옛 버전이어도 영구 변경이 들어가지 않는다.
        return optimizer.apply_hardware_tailored_tuning(cpu_cores, ram_gb, consent=consent)

    def restoreTailoredServiceConfig(self):
        return optimizer.restore_tailored_service_config()

    # --- Uninstaller Features ---
    def getUninstallerApps(self):
        try:
            return uninstaller.get_installed_apps()
        except Exception as e:
            log.warning(f"Error getting uninstaller apps: {e}")
            return []

    def uninstallApp(self, uninstall_string):
        return uninstaller.run_uninstall(uninstall_string)
        
    def getSfcStatus(self):
        return system_repair.get_sfc_status()
        
    def getDismStatus(self):
        return system_repair.get_dism_status()

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
        import os
        os._exit(0)
            
    def quitApplication(self):
        import os
        os._exit(0)

    def minimizeWindow(self):
        if self._window:
            self._window.minimize()

    def maximizeWindow(self):
        if self._window:
            self._window.toggle_fullscreen()
