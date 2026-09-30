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
from backend import process_boost
from backend import storage

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
            # 숫자를 0 으로 채워 돌려주지 않는다. 예전에는 읽기에 실패하면 CPU 0%·RAM 0 GB 가
            # 측정값처럼 대시보드에 그려졌다. 화면은 error 를 보고 이전 값을 그대로 둔다.
            return {'error': '시스템 정보를 읽지 못했습니다.'}
        return stats

    def getDeepOptimizationPlan(self):
        """원클릭이 할 일. 대시보드가 실행 전에 보여 주고 확인을 받는다."""
        return optimizer.get_deep_optimization_plan()

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
        """대기 메모리를 비우고, 측정한 전후 크기를 그대로 돌려준다.

        예전에는 실패해도 성공으로 보고할 수 있었고 freedMB 는 늘 0 이었다.
        """
        res = optimizer.purge_ram()
        if not res.get("success"):
            return {"success": False, "error": res.get("error"),
                    "message": res.get("message") or "대기 메모리를 비우지 못했습니다."}

        def gb(b):
            return None if b is None else round(b / (1024 ** 3), 2)

        out = {"success": True,
               "standbyBeforeGB": gb(res.get("standbyBeforeBytes")),
               "standbyAfterGB": gb(res.get("standbyAfterBytes")),
               "freeBeforeGB": gb(res.get("freeBeforeBytes")),
               "freeAfterGB": gb(res.get("freeAfterBytes"))}
        if out["standbyBeforeGB"] is not None and out["standbyAfterGB"] is not None:
            out["message"] = (f"대기 메모리를 비웠습니다: {out['standbyBeforeGB']:.1f} GB → "
                              f"{out['standbyAfterGB']:.1f} GB")
        else:
            out["message"] = "대기 메모리를 비웠습니다. 전후 크기는 측정하지 못했습니다."
        return out

    def runTrim(self):
        return system_repair.run_trim()

    def getTrimStatus(self):
        return system_repair.get_trim_status()

    # 네트워크 '영구 최적화'(Winsock 초기화 등)는 제거했다. 되돌릴 수 없는 변경이 섞여 있었고
    # 프론트 어디에서도 쓰이지 않았다. 구버전이 적용한 것을 되돌리는 경로만 남긴다.
    def restoreNetworkTweaks(self):
        return system_repair.restore_network_tweaks()

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

    def getProcesses(self, limit=8):
        """메모리 순 프로세스 목록. limit=0 이면 전부(게이밍 탭의 우선순위 조정이 이름으로 찾는다)."""
        return system_monitor.get_processes(limit)

    def killProcess(self, pid):
        return system_monitor.kill_process(pid)

    def setProcessPriority(self, pid, priority):
        """프로세스 우선순위 변경 (구 API 이름).

        process_boost 로 위임한다. 예전 경로는 바꾸기 전 원래 값을 기록하지 않아
        되돌릴 수 없었다. 같은 일을 하는 두 경로 중 하나만 안전하면
        어느 쪽이 호출됐는지에 따라 복구 가능 여부가 달라지는 함정이 된다.
        """
        return process_boost.set_priority(pid, priority, reason='(구 API)')

    def getOptimizationMode(self):
        return optimizer.get_optimization_mode()

    def setOptimizationMode(self, mode):
        """성능 모드 적용.

        반환값의 steps 에 항목별 성패가 들어 있다. 프론트는 이것을 반드시 확인해야 한다.
        예전에는 버튼을 누른 즉시 성공 토스트를 띄워, 실제로는 아무것도 적용되지 않아도
        사용자가 알 수 없었다.
        """
        # 사용자가 직접 골랐다. 게임이 끝났다고 게임 전 모드로 되돌리면 이 선택을 덮어쓴다.
        game_booster.forget_power_mode_restore()
        return perf_modes.apply_mode(mode)

    def listOptimizationModes(self):
        """모드 카드에 표시할 정보. 무엇이 바뀌는지 미리 보여주기 위한 것."""
        return perf_modes.list_modes()

    def runCpuBenchmark(self):
        """지금 모드에서 3초 동안 CPU 를 재서 모드별로 남긴다. 계산만 하고 시스템은 바꾸지 않는다."""
        from backend import perf_bench
        return perf_bench.run()

    def getCpuBenchmarks(self):
        from backend import perf_bench
        return perf_bench.get_results()

    def revertAllSystemChanges(self):
        """이 앱이 바꾼 모든 시스템 설정을 원래대로 되돌린다."""
        game_booster.forget_power_mode_restore()
        return perf_modes.revert_everything()

    def getPendingSystemChanges(self):
        """아직 되돌리지 않은 변경 목록. UI 가 '되돌리기' 버튼 노출 여부를 판단한다.

        구버전이 settings.json 에 따로 남긴 백업도 함께 보여준다. 여기서 빠지면
        복구 센터가 '되돌릴 변경이 없습니다' 라고 말하는데 실제로는 남아 있게 된다.
        """
        changes = system_state.pending_changes()
        by_group = {}
        for key, e in changes.items():
            group = e.get('group') or '기타'
            # 시작 프로그램은 항목마다 그룹(startup:위치:이름)을 따로 쓴다. 화면에는 한 묶음으로 보여 준다.
            # 예전에는 'startup:HKCU:Discord' 같은 내부 키가 그대로 제목으로 보였다.
            if group.startswith('startup:'):
                group = 'startup'
            by_group.setdefault(group, []).append({
                'what': e.get('why') or key,
                'kind': e.get('kind'),
            })
        count = len(changes)
        if system_repair.has_legacy_network_backup():
            by_group.setdefault('legacy_network', []).append({
                'what': '이전 버전이 바꾼 TCP 자동 튜닝·Nagle·네트워크 스로틀링', 'kind': 'legacy'})
            count += 1
        if optimizer.has_legacy_service_backup():
            by_group.setdefault('legacy_service', []).append({
                'what': '이전 버전이 바꾼 SysMain·Windows Search 시작 설정', 'kind': 'legacy'})
            count += 1
        return {'count': count, 'groups': by_group}
        
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

    def uninstallApp(self, app_name):
        """프로그램 이름으로 제거 프로그램을 실행한다. 명령줄은 백엔드가 레지스트리에서 읽는다."""
        return uninstaller.uninstall_by_name(app_name)
        
    def getSfcStatus(self):
        return system_repair.get_sfc_status()
        
    def getDismStatus(self):
        return system_repair.get_dism_status()

    def findAppLeftovers(self, app_name):
        """아직 설치돼 있으면 찾지 않는다. {success, stillInstalled, items, message}"""
        return uninstaller.scan_leftovers(app_name)

    def cleanAppLeftovers(self, paths):
        return uninstaller.clean_leftovers(paths)

    # --- 저장공간 현황 ---
    def getStorageOverview(self):
        """드라이브별 용량과 매체 종류(SSD/HDD). 읽기만 한다."""
        return storage.get_overview()

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

    def getRemovedDebloatApps(self):
        """디블로터가 이 계정에서 제거한 앱 목록(되살리기 화면)."""
        return debloater.get_removed_apps()

    def restoreRemovedDebloatApps(self, names=None):
        """제거한 앱을 되살린다. names 가 없으면 전부. 앱마다 성패를 돌려준다."""
        return debloater.restore_removed_apps(names)

    # === Game Booster API ===
    def getGameBoosterStatus(self):
        return game_booster.get_booster_status()
        
    def toggleGameBooster(self, enabled):
        return game_booster.toggle_booster(enabled)

    def getBoostSettings(self):
        """게임 부스트가 무엇을 할지에 대한 설정.

        예전에는 게임이 감지되면 타이머 해상도·Nagle 레지스트리·전원 모드를
        고지 없이 한꺼번에 바꿨다. 이제 각 항목을 사용자가 끄고 켤 수 있다.
        """
        return config_manager.get_boost_settings()

    def setBoostSetting(self, key, value):
        return config_manager.set_boost_setting(key, value)

    # --- UI 색 조합 ---
    def getUiTheme(self):
        return config_manager.get_ui_theme()

    def setUiTheme(self, theme):
        return config_manager.set_ui_theme(theme)

    def getUiAccent(self):
        return config_manager.get_ui_accent()

    def setUiAccent(self, accent):
        return config_manager.set_ui_accent(accent)

    # --- 초기 설정 마법사 (첫 실행 때만) ---
    def getSetupWizardDone(self):
        return config_manager.get_setup_wizard_done()

    def markSetupWizardDone(self):
        return config_manager.set_setup_wizard_done()

    # --- 프로세스 우선순위 (게이밍 탭) ---
    def boostProcess(self, pid, priority):
        """프로세스 우선순위를 바꾼다. 원래 값을 기록하므로 되돌릴 수 있다."""
        return process_boost.set_priority(pid, priority, reason='(사용자 지정)')

    def restoreProcess(self, pid):
        return process_boost.restore(pid)

    def restoreAllProcesses(self):
        return process_boost.restore_all()

    def getAdjustedProcessCount(self):
        return {'count': process_boost.adjusted_count()}


    def _busy_reason(self):
        """지금 끄면 안 되는 작업이 돌고 있는지."""
        try:
            if optimizer.get_deep_optimization_status().get('running'):
                return '원클릭 최적화'
            if optimizer.get_junk_clean_status().get('status') == 'running':
                return '정크 파일 정리'
            if debloater.is_busy():
                return '기본 앱 제거·되살리기'
            for name, getter in (('SFC 검사', system_repair.get_sfc_status),
                                 ('DISM 복구', system_repair.get_dism_status),
                                 ('디스크 최적화', system_repair.get_trim_status)):
                if getter().get('status') == 'running':
                    return name
        except Exception:
            pass
        return None

    def getShutdownBlockers(self):
        """창을 닫기 전에 프론트가 물어볼 수 있게 한다."""
        reason = self._busy_reason()
        return {'busy': bool(reason), 'reason': reason}

    def closeWindow(self, force=False):
        """창을 닫는다.

        os._exit(0) 는 정리 코드를 하나도 실행하지 않고 프로세스를 즉시 죽인다.
        파일을 지우는 중이었다면 그 순간에 끊기고, 시스템 변경 저널이 디스크에
        기록되기 전이었다면 '되돌리기' 정보가 통째로 사라진다.
        진행 중인 작업이 있으면 알리고, 정상 종료 경로를 먼저 시도한다.
        """
        reason = self._busy_reason()
        if reason and not force:
            return {'success': False, 'busy': True, 'reason': reason,
                    'message': f'{reason} 작업이 진행 중입니다. 완료 후 종료하거나 먼저 중단해 주세요.'}

        self._cleanup()

        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
        return {'success': True}

    def _cleanup(self):
        """종료 직전 정리. 여러 번 불러도 안전하다(main.py 도 창이 닫힌 뒤 한 번 더 부른다)."""
        try:
            # 부스트가 바꾼 것을 이 스레드에서 되돌린다. toggle_booster(False) 를 쓰면
            # '부스터 꺼짐' 이 설정에 저장되고, 되돌리기는 곧 죽을 데몬 스레드에 맡겨진다.
            game_booster.shutdown()
        except Exception as e:
            log.warning(f"종료 중 부스터 정리 실패: {e}")
        try:
            process_boost.restore_all()          # 우선순위를 원래대로
        except Exception as e:
            log.warning(f"종료 중 우선순위 복구 실패: {e}")

    def quitApplication(self, force=False):
        return self.closeWindow(force=force)

    def minimizeWindow(self):
        if self._window:
            self._window.minimize()

    def maximizeWindow(self):
        """최대화 ↔ 이전 크기. 예전에는 전체 화면(작업 표시줄까지 덮음)으로 바꿔 버튼 설명과 달랐다."""
        if not self._window:
            return
        if getattr(self, '_maximized', False):
            self._window.restore()
            self._maximized = False
        else:
            self._window.maximize()
            self._maximized = True

    def _on_window_maximized(self, *args):
        self._maximized = True

    def _on_window_restored(self, *args):
        self._maximized = False
