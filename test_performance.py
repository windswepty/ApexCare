import time
import psutil
from backend.api import Api

def measure_system():
    # psutil CPU usage can take a little time to be accurate if interval=None,
    # but we can do a blocking call.
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    return cpu, mem.percent, mem.used / (1024**3)

def run_test():
    print("=== APEX CARE Performance & Overload Test ===")
    api = Api(None)
    
    # Baseline
    cpu, ram_pct, ram_used = measure_system()
    print(f"Baseline: CPU {cpu}% | RAM {ram_pct}% ({ram_used:.2f} GB)")
    
    # 1. API: getSystemStats
    start = time.time()
    stats = api.getSystemStats()
    dur = time.time() - start
    cpu, ram_pct, ram_used = measure_system()
    print(f"getSystemStats: took {dur:.2f}s | CPU {cpu}% | RAM {ram_pct}%")

    # 2. API: scanJunk
    print("Running scanJunk...")
    start = time.time()
    junk = api.scanJunk()
    dur = time.time() - start
    cpu, ram_pct, ram_used = measure_system()
    print(f"scanJunk: took {dur:.2f}s | CPU {cpu}% | RAM {ram_pct}% | Found: {len(junk)} items")

    # 3. API: getProcesses
    print("Running getProcesses...")
    start = time.time()
    procs = api.getProcesses()
    dur = time.time() - start
    cpu, ram_pct, ram_used = measure_system()
    print(f"getProcesses: took {dur:.2f}s | CPU {cpu}% | RAM {ram_pct}% | Found: {len(procs)} processes")

    # 4. API: setOptimizationMode (Gaming)
    print("Running setOptimizationMode('gaming')...")
    start = time.time()
    api.setOptimizationMode('gaming')
    dur = time.time() - start
    cpu, ram_pct, ram_used = measure_system()
    print(f"setOptimizationMode(gaming): took {dur:.2f}s | CPU {cpu}% | RAM {ram_pct}%")
    
    # 5. API: setOptimizationMode (Eco)
    print("Running setOptimizationMode('eco')...")
    start = time.time()
    api.setOptimizationMode('eco')
    dur = time.time() - start
    cpu, ram_pct, ram_used = measure_system()
    print(f"setOptimizationMode(eco): took {dur:.2f}s | CPU {cpu}% | RAM {ram_pct}%")

    # Restore standard
    api.setOptimizationMode('standard')
    print("Test Completed Successfully.")

if __name__ == '__main__':
    run_test()
