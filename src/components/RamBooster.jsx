import React, { useState, useEffect } from 'react';
import { 
  Cpu, 
  Zap, 
  RotateCcw, 
  Activity, 
  CheckCircle2, 
  XCircle 
} from 'lucide-react';
import { playSound } from '../utils/audio';

export default function RamBooster({ addToast }) {
  const [ramData, setRamData] = useState({
    activeGB: 14.2,
    standbyGB: 7.8,
    freeGB: 8.8,
    totalGB: 32.0,
  });

  const [processes, setProcesses] = useState([]);

  useEffect(() => {
    const fetchRealData = async () => {
      if (window.pywebview?.api && window.pywebview?.api.getSystemStats) {
        try {
          const stats = await window.pywebview?.api.getSystemStats();
          if (stats) {
            // psutil's ramUsedGB on Windows is (Total - Free), so it ALREADY includes Standby Cache.
            const totalGB = parseFloat(stats.ramTotalGB ?? 32.0);
            const usedGB = parseFloat(stats.ramUsedGB ?? 14.2);
            const standbyGB = parseFloat(stats.ramStandbyGB ?? 2.4);
            
            // True Active RAM = (Used - Standby)
            const activeGB = Math.max(0.1, usedGB - standbyGB);
            // Free RAM = (Total - Used)
            const freeGB = Math.max(0.1, totalGB - usedGB);

            setRamData({
              activeGB: activeGB,
              standbyGB: standbyGB,
              freeGB: freeGB,
              totalGB: totalGB,
            });
          }
        } catch (e) {}
      }

      if (window.pywebview?.api && window.pywebview?.api.getProcesses) {
        try {
          const realProcs = await window.pywebview?.api.getProcesses();
          if (realProcs && realProcs.length > 0) {
            setProcesses(realProcs);
          }
        } catch (e) {}
      }
    };

    fetchRealData();
    const interval = setInterval(fetchRealData, 2000);
    return () => clearInterval(interval);
  }, []);

  const [isPurging, setIsPurging] = useState(false);
  const [purgedSuccess, setPurgedSuccess] = useState(false);

  const handlePurgeStandby = async () => {
    if (isPurging) return;
    playSound('boost');
    setIsPurging(true);

    let success = false;
    if (window.pywebview?.api && window.pywebview?.api.purgeRam) {
      try {
        const res = await window.pywebview?.api.purgeRam();
        success = res?.success;
      } catch (e) {
        success = false;
      }
    } else {
      // Fake delay for web view
      await new Promise(r => setTimeout(r, 1500));
      success = true;
    }

    setIsPurging(false);
    
    if (success) {
      setPurgedSuccess(true);
      playSound('success');
      if (addToast) addToast('대기 메모리(Standby Cache)가 성공적으로 최적화되었습니다!', 'success');
    } else {
      alert("RAM 최적화에 실패했습니다. 관리자 권한을 확인해주세요.");
      if (addToast) addToast('RAM 최적화에 실패했습니다.', 'error');
    }
  };

  const killProcess = async (id, pid) => {
    playSound('click');
    // Optimistically remove
    const processToRemove = processes.find(p => (p.id || p.pid) === id && p.pid === pid);
    setProcesses(prev => prev.filter(p => (p.id || p.pid) !== id && p.pid !== pid));

    if (window.pywebview?.api && window.pywebview?.api.killProcess && pid) {
      try {
        const res = await window.pywebview?.api.killProcess(pid);
        if (!res?.success) {
          throw new Error('Failed to kill');
        }
        if (addToast) addToast('프로세스가 성공적으로 종료되었습니다.', 'success');
      } catch (e) {
        alert("프로세스 종료에 실패했습니다. (액세스 거부됨)");
        if (addToast) addToast('프로세스 종료에 실패했습니다.', 'error');
        if (processToRemove) {
          setProcesses(prev => [...prev, processToRemove]);
        }
      }
    }
  };

  const totalRamPct = (((ramData.activeGB + ramData.standbyGB) / ramData.totalGB) * 100).toFixed(0);

  return (
    <div className="space-y-6">
      {/* Header Panel */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 text-purple-400 font-mono text-xs font-semibold mb-1">
            <Cpu className="w-4 h-4" />
            STANDBY MEMORY PURGER & WORKING SET OPTIMIZER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">RAM 메모리 최적화</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
            윈도우가 캐시해둔 미사용 Standby 메모리를 즉시 해제하여 게임 및 무거운 작업 시 메모리 스왑 지연 현상을 방지합니다.
          </p>
        </div>

        <button
          onClick={handlePurgeStandby}
          disabled={isPurging || ramData.standbyGB < 0.5}
          className={`btn-primary bg-gradient-to-r from-purple-600 to-pink-600 shadow-purple-500/30 px-6 py-3.5 ${
            isPurging || ramData.standbyGB < 0.5 ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {isPurging ? (
            <>
              <RotateCcw className="w-5 h-5 animate-spin text-black dark:text-white" />
              <span>Standby 메모리 퍼지 중...</span>
            </>
          ) : (
            <>
              <Zap className="w-5 h-5 text-black dark:text-white fill-current" />
              <span>대기 메모리 ({ramData.standbyGB.toFixed(1)} GB) 즉시 해제</span>
            </>
          )}
        </button>
      </div>

      {/* Success Notification */}
      {purgedSuccess && (
        <div className="glass-panel border-purple-500/40 bg-purple-950/20 p-4 rounded-xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-6 h-6 text-purple-400" />
            <div>
              <h4 className="font-bold text-purple-300 text-sm">Standby RAM 퍼지가 성공적으로 실행되었습니다!</h4>
              <p className="text-xs text-gray-700 dark:text-slate-300">여유 가용 메모리가 즉시 확보되어 최상의 시스템 응답속도를 유지합니다.</p>
            </div>
          </div>
          <button onClick={() => setPurgedSuccess(false)} className="text-xs text-gray-500 dark:text-slate-400 hover:text-black dark:text-white underline">
            닫기
          </button>
        </div>
      )}

      {/* RAM Allocation Breakdown Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="glass-panel p-4 border-l-4 border-l-cyan-400">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">활성 앱 점유 (Active)</span>
          <div className="text-2xl font-black font-mono text-black dark:text-white mt-1">{ramData.activeGB.toFixed(1)} GB</div>
          <span className="text-[10px] text-slate-500 font-mono">작업 중인 필수 프로세스</span>
        </div>

        <div className="glass-panel p-4 border-l-4 border-l-purple-500">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">대기 캐시 (Standby)</span>
          <div className="text-2xl font-black font-mono text-purple-400 mt-1">{ramData.standbyGB.toFixed(1)} GB</div>
          <span className="text-[10px] text-purple-300 font-mono">해제 가능한 캐시 영역</span>
        </div>

        <div className="glass-panel p-4 border-l-4 border-l-emerald-400">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">순수 여유 RAM (Free)</span>
          <div className="text-2xl font-black font-mono text-emerald-400 mt-1">{ramData.freeGB.toFixed(1)} GB</div>
          <span className="text-[10px] text-slate-500 font-mono">즉시 할당 가능 메모리</span>
        </div>

        <div className="glass-panel p-4 border-l-4 border-l-slate-500">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">전체 메모리 점유율</span>
          <div className="text-2xl font-black font-mono text-gray-800 dark:text-slate-200 mt-1">{totalRamPct}%</div>
          <span className="text-[10px] text-slate-500 font-mono">Total {ramData.totalGB.toFixed(1)} GB</span>
        </div>
      </div>

      {/* Visual Memory Stack Segment Bar */}
      <div className="glass-panel p-5 space-y-3">
        <div className="flex justify-between items-center text-xs font-mono">
          <span className="text-gray-700 dark:text-slate-300 font-bold">메모리 할당 분포도</span>
          <span className="text-gray-500 dark:text-slate-400">{ramData.totalGB.toFixed(1)} GB 중 {(ramData.activeGB + ramData.standbyGB).toFixed(1)} GB 활성화</span>
        </div>
        <div className="w-full h-4 bg-white dark:bg-slate-900 rounded-full overflow-hidden flex">
          <div 
            className="bg-cyan-500 h-full transition-all duration-500" 
            style={{ width: `${(ramData.activeGB / ramData.totalGB) * 100}%` }}
            title="Active Memory"
          ></div>
          <div 
            className="bg-purple-500 h-full transition-all duration-500" 
            style={{ width: `${(ramData.standbyGB / ramData.totalGB) * 100}%` }}
            title="Standby Memory"
          ></div>
          <div 
            className="bg-gray-50 dark:bg-slate-800 h-full transition-all duration-500" 
            style={{ width: `${(ramData.freeGB / ramData.totalGB) * 100}%` }}
            title="Free Memory"
          ></div>
        </div>
        <div className="flex items-center justify-center gap-6 text-xs font-mono pt-1">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded bg-cyan-500"></span>
            <span className="text-gray-700 dark:text-slate-300">활성 앱 (Active)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded bg-purple-500"></span>
            <span className="text-gray-700 dark:text-slate-300">대기 캐시 (Standby)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded bg-gray-50 dark:bg-slate-800"></span>
            <span className="text-gray-500 dark:text-slate-400">여유 메모리 (Free)</span>
          </div>
        </div>
      </div>

      {/* Active Process Management Table */}
      <div className="glass-panel p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-gray-900 dark:text-slate-100 text-sm flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            고점유 프로세스 실시간 관리 ({processes.length})
          </h3>
          <span className="text-xs text-gray-500 dark:text-slate-400 font-mono">RAM 사용량 순 정렬</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-black/10 dark:border-slate-800 text-gray-500 dark:text-slate-400 uppercase">
                <th className="pb-3 px-2">프로세스명</th>
                <th className="pb-3 px-2">PID</th>
                <th className="pb-3 px-2">RAM 사용량</th>
                <th className="pb-3 px-2">CPU 점유</th>
                <th className="pb-3 px-2">우선순위</th>
                <th className="pb-3 px-2 text-right">작업</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {processes.map((proc) => (
                <tr key={proc.id} className="hover:bg-gray-50 dark:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-2 font-bold text-gray-800 dark:text-slate-200">{proc.name}</td>
                  <td className="py-3 px-2 text-gray-500 dark:text-slate-400">{proc.pid}</td>
                  <td className="py-3 px-2 text-purple-400 font-bold">{proc.memoryMB} MB</td>
                  <td className="py-3 px-2 text-cyan-400">{proc.cpuPct}</td>
                  <td className="py-3 px-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] ${
                      proc.priority === 'High' ? 'bg-amber-500/20 text-amber-300' : 'bg-gray-50 dark:bg-slate-800 text-gray-700 dark:text-slate-300'
                    }`}>
                      {proc.priority}
                    </span>
                  </td>
                  <td className="py-3 px-2 text-right">
                    <button
                      onClick={() => killProcess(proc.id, proc.pid)}
                      className="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 px-2 py-1 rounded transition-all flex items-center gap-1 ml-auto"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      프로세스 종료
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
