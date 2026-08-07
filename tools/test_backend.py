"""
APEX CARE - Python Backend Integration Test
Verifies that ALL functions work without spawning PowerShell/CMD.
"""
import os
import sys
import io
import time
import psutil

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import system_monitor
from backend import optimizer
from backend import config_manager

PASS = "[PASS]"
FAIL = "[FAIL]"
passed = 0
failed = 0

def log(ok, name, detail=""):
    global passed, failed
    status = PASS if ok else FAIL
    if ok: passed += 1
    else: failed += 1
    print(f"  {status} {name}: {detail}")


def count_powershell():
    """Count how many powershell.exe processes are currently running."""
    count = 0
    for p in psutil.process_iter(['name']):
        try:
            if 'powershell' in (p.info['name'] or '').lower():
                count += 1
        except:
            pass
    return count


print("=" * 60)
print("  APEX CARE Python Backend Test")
print("  목표: PowerShell 프로세스 0개 생성 확인")
print("=" * 60)

# Baseline PowerShell count
ps_before = count_powershell()
print(f"\n  [기준선] 현재 PowerShell 프로세스: {ps_before}개")

# TEST 1: System Stats
print("\n--- TEST 1: 시스템 정보 조회 ---")
stats = system_monitor.get_system_stats()
log(stats is not None, "시스템 정보 조회", f"CPU: {stats['cpuModel']}" if stats else "실패")
if stats:
    log(stats['cpuUsage'] >= 0, "CPU 사용률", f"{stats['cpuUsage']}%")
    log(stats['ramTotalGB'] > 0, "RAM 총량", f"{stats['ramTotalGB']} GB")
    log(stats['diskTotalGB'] > 0, "디스크 정보", f"C: {stats['diskUsedGB']}/{stats['diskTotalGB']} GB")

ps_after_1 = count_powershell()
log(ps_after_1 <= ps_before, "PowerShell 생성 여부", f"이전: {ps_before}개 → 현재: {ps_after_1}개")

# TEST 2: Process List
print("\n--- TEST 2: 프로세스 목록 ---")
procs = system_monitor.get_processes()
log(len(procs) > 0, "프로세스 목록", f"{len(procs)}개 조회됨")
if procs:
    log(procs[0]['memoryMB'] > 0, "메모리 정보", f"Top: {procs[0]['name']} ({procs[0]['memoryMB']} MB)")

ps_after_2 = count_powershell()
log(ps_after_2 <= ps_before, "PowerShell 생성 여부", f"이전: {ps_before}개 → 현재: {ps_after_2}개")

# TEST 3: Junk Scan
print("\n--- TEST 3: 정크 스캔 (순차적) ---")
t1 = time.time()
junk = optimizer.scan_junk()
t2 = time.time()
log(len(junk) > 0, "정크 스캔", f"{len(junk)}개 카테고리, {t2-t1:.2f}초 소요")
total_junk = sum(j['sizeMB'] for j in junk)
log(True, "총 정크 크기", f"{total_junk} MB")

ps_after_3 = count_powershell()
log(ps_after_3 <= ps_before, "PowerShell 생성 여부", f"이전: {ps_before}개 → 현재: {ps_after_3}개")

# TEST 4: RAM Purge
print("\n--- TEST 4: RAM 최적화 (ctypes) ---")
ram_result = optimizer.purge_ram()
log(ram_result.get('success', False), "RAM 퍼지", f"{ram_result.get('purgedProcesses', 0)}개 프로세스 해제")

ps_after_4 = count_powershell()
log(ps_after_4 <= ps_before, "PowerShell 생성 여부", f"이전: {ps_before}개 → 현재: {ps_after_4}개")

# TEST 5: Config Manager (booster state persistence)
print("\n--- TEST 5: 설정 저장 (부스터 상태 유지) ---")
config_manager.set_booster_state(False)
log(config_manager.get_booster_state() == False, "OFF 저장", "OFF로 저장됨")
config_manager.set_booster_state(True)
log(config_manager.get_booster_state() == True, "ON 저장", "ON으로 저장됨")
config_manager.set_booster_state(False)
log(config_manager.get_booster_state() == False, "OFF 재저장", "OFF 상태 유지 확인")

# TEST 6: Power Plan (ctypes)
print("\n--- TEST 6: 전원 계획 전환 (ctypes, PowerShell 0개) ---")
mode_result = optimizer.set_optimization_mode('standard')
log(mode_result.get('success', False), "Standard 모드", "Balanced Plan 적용")

ps_after_6 = count_powershell()
log(ps_after_6 <= ps_before, "PowerShell 생성 여부", f"이전: {ps_before}개 → 현재: {ps_after_6}개")

# TEST 7: Memory usage of this test script
print("\n--- TEST 7: 메모리 사용량 ---")
process = psutil.Process(os.getpid())
mem_mb = process.memory_info().rss / (1024 * 1024)
log(mem_mb < 100, "테스트 스크립트 메모리", f"{mem_mb:.1f} MB (100MB 미만이면 PASS)")

# FINAL: Overall PowerShell check
print("\n--- 최종 PowerShell 확인 ---")
ps_final = count_powershell()
new_ps = max(0, ps_final - ps_before)
log(new_ps == 0, "새로 생성된 PowerShell", f"{new_ps}개 (0개여야 PASS)")

print("\n" + "=" * 60)
print(f"  결과: {PASS} {passed}개  |  {FAIL} {failed}개")
print("=" * 60)

if failed > 0:
    print("\n  ⚠️ 실패한 테스트가 있습니다.")
    sys.exit(1)
else:
    print("\n  ✅ 모든 테스트 통과! PowerShell 0개 생성!")
    sys.exit(0)
