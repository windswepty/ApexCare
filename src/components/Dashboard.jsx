import React, { useState, useEffect, useRef, useCallback } from 'react';
import { usePolling } from '../usePolling';
import {
  Zap,
  CheckCircle2,
  AlertTriangle,
  Cpu,
  HardDrive,
  MemoryStick,
  XCircle,
  Monitor
} from 'lucide-react';
import confetti from 'canvas-confetti';

// 탭을 바꿔도 그래프를 이어 가려고 모듈 변수에 둔다. 칸은 null(아직 재지 않음)로 시작한다.
// 예전에는 0 으로 채워, 앱을 켜자마자 '지난 75초 동안 0%' 인 그래프가 그려졌다(재지 않은 과거를 지어냄).
const HISTORY_POINTS = 25;
let globalCpuHistory = Array(HISTORY_POINTS).fill(null);
let globalGpuHistory = Array(HISTORY_POINTS).fill(null);

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const pctText = (v, state) => (isNum(v) ? `${v}%` : state === 'unavailable' ? '측정 불가' : '측정 중');
const barWidth = (v) => `${isNum(v) ? Math.max(0, Math.min(100, v)) : 0}%`;

const renderLineGraph = (history) => {
  const height = 64; // h-16
  const width = 200;

  // 잰 칸만 잇는다. 재지 않은 칸(null)은 그리지 않는다.
  const measured = history.map((val, i) => ({ val, i })).filter((p) => isNum(p.val));
  if (measured.length < 2) {
    return <p className="text-[11px] text-gray-500 font-mono">기록을 모으는 중…</p>;
  }
  const points = measured.map(({ val, i }) => {
    const x = (i / (HISTORY_POINTS - 1)) * width;
    const y = height - (Math.min(100, Math.max(0, val)) / 100) * height;
    return `${x},${y}`;
  });
  const firstX = (measured[0].i / (HISTORY_POINTS - 1)) * width;

  const linePath = `M ${points.join(' L ')}`;
  const areaPath = `${linePath} L ${width},${height} L ${firstX},${height} Z`;

  const currentVal = measured[measured.length - 1].val;
  let strokeColor = "stroke-emerald-500";
  let fillColor = "fill-emerald-500/20";
  
  if (currentVal >= 85) {
    strokeColor = "stroke-rose-500";
    fillColor = "fill-rose-500/20";
  } else if (currentVal >= 60) {
    strokeColor = "stroke-amber-500";
    fillColor = "fill-amber-500/20";
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-16 overflow-visible preserve-3d" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`grad-${strokeColor}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.4" className={fillColor.replace('fill-', 'text-').replace('/20', '')} />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.0" className={fillColor.replace('fill-', 'text-').replace('/20', '')} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#grad-${strokeColor})`} className="transition-all duration-300" />
      <path d={linePath} fill="none" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={`${strokeColor} transition-all duration-300 drop-shadow-md`} />
    </svg>
  );
};

// 원클릭 최적화가 실제로 하는 일 (backend/optimizer.py _run_deep_optimization 과 같은 순서)
// backend/optimizer.get_deep_optimization_plan 의 단계 이름과 같다(백엔드가 없을 때 보여 줄 목록)
const OPTIMIZATION_STEPS = ['임시 파일·브라우저 캐시 정리', '대기 메모리 비우기', 'DNS 캐시 초기화', '디스크 최적화(TRIM)'];

// 설치 용량과 Windows 가 쓸 수 있는 용량이 다르면(내장 그래픽 예약 등) 둘 다 보여 준다.
// 예전에는 쓸 수 있는 용량만 'Total' 로 보여 16GB PC 가 15.4GB 로 보였다.
function ramTotalLabel(info) {
  const usable = Number(info.ramTotalGB);
  const installed = Number(info.ramInstalledGB);
  if (!(usable > 0)) return '…';
  if (installed > 0 && installed - usable >= 0.1) {
    return `설치 ${installed.toFixed(1)} GB · 사용 가능 ${usable.toFixed(1)} GB`;
  }
  return `${usable.toFixed(1)} GB`;
}

export default function Dashboard({ addToast, active = true }) {
  // 예전에는 CPU·RAM·디스크 사용률로 임의 공식을 만들어 'Health Score' 와
  // '최상 / 최적화 필요' 를 판정했다. 측정한 건강 상태가 아니므로 없앴다.
  const [lastRun, setLastRun] = useState(null);   // 이번 실행의 단계별 결과
  const [isScanning, setIsScanning] = useState(false);
  const [modalMessage, setModalMessage] = useState(null);
  
  const [optStatus, setOptStatus] = useState({
    running: false,
    progress_pct: 0,
    eta_seconds: 0,
    current_task: '',
    freed_mb: 0,
    error: null
  });

  const [lastOptimized, setLastOptimized] = useState(() => localStorage.getItem('apex_last_optimized') || '기록 없음');
  const [totalFreed, setTotalFreed] = useState(() => parseFloat(localStorage.getItem('apex_total_freed')) || 0);

  // 실시간 값. null = 아직 받지 못함('측정 중'). 0 으로 시작하면 받기 전에도 '0%' 로 보였다.
  const [cpuUsage, setCpuUsage] = useState(null);
  const [gpuUsage, setGpuUsage] = useState(null);
  const [gpuState, setGpuState] = useState('measuring');
  const [ramUsage, setRamUsage] = useState(null);
  const [diskUsage, setDiskUsage] = useState(null);

  // 받기 전에는 모든 값이 null 이고 화면은 '…' 을 보여 준다(0 GB 같은 지어낸 값을 그리지 않는다).
  const [sysInfo, setSysInfo] = useState({
    cpuModel: '확인 중…',
    gpuModel: '확인 중…',
    cpuCores: null,
    cpuThreads: null,
    ramTotalGB: null,
    ramInstalledGB: null,
    ramInUseGB: null,
    ramAvailableGB: null,
    diskTotalGB: null,
    diskUsedGB: null,
    diskFreeGB: null
  });
  const gb = (v) => (isNum(Number(v)) && v !== null && v !== '' ? `${v} GB` : '…');
  // 받기 전에는 '…', 받았는데 Windows 가 알려 주지 않은 값은 '?' (0 으로 지어내지 않는다)
  const loaded = sysInfo.cpuModel !== '확인 중…';
  const count = (v) => (isNum(v) && v > 0 ? v : loaded ? '?' : '…');
  const coresText = `${count(sysInfo.cpuCores)}코어 / ${count(sysInfo.cpuThreads)}스레드`;

  // Live sparkline histories
  const [cpuHistory, setCpuHistory] = useState(globalCpuHistory);
  const [gpuHistory, setGpuHistory] = useState(globalGpuHistory);

  const optPollInterval = useRef(null);

  const fetchRealStats = useCallback(async () => {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getSystemStats === 'function') {
        try {
          const stats = await window.pywebview.api.getSystemStats();
          // 읽기에 실패하면(error) 이전 값을 그대로 둔다. 0 으로 바꾸지 않는다.
          if (stats && !stats.error) {
            const cpu = isNum(stats.cpuUsage) ? stats.cpuUsage : null;
            const gpu = isNum(stats.gpuUsage) ? stats.gpuUsage : null;
            setCpuUsage(cpu);
            setGpuUsage(gpu);
            setGpuState(stats.gpuUsageState || 'measuring');
            setRamUsage(isNum(stats.ramPct) ? stats.ramPct : null);
            setDiskUsage(isNum(stats.diskPct) ? stats.diskPct : null);
            // 잰 값만 그래프에 넣는다. 아직 재지 못한 순간(null)을 0% 로 넣지 않는다.
            setCpuHistory(prev => {
              const next = [...prev.slice(1), cpu];
              globalCpuHistory = next;
              return next;
            });
            setGpuHistory(prev => {
              const next = [...prev.slice(1), gpu];
              globalGpuHistory = next;
              return next;
            });

            setSysInfo({
              cpuModel: stats.cpuModel || '알 수 없음',
              cpuCores: stats.cpuCores ?? null,
              cpuThreads: stats.cpuThreads ?? null,
              gpuModel: stats.gpuModel || '알 수 없음',
              ramTotalGB: stats.ramTotalGB ?? null,
              ramInstalledGB: stats.ramInstalledGB ?? null,
              // '사용 중' 은 작업 관리자·RAM 화면과 같은 값(수정됨 목록 제외)을 쓴다. 성능 카운터를 못 읽었으면
              // 전체 − 사용 가능. 예전에는 두 화면의 '사용 중' 이 서로 달랐다.
              ramInUseGB: stats.ramInUseGB ?? stats.ramUsedGB ?? null,
              ramAvailableGB: stats.ramAvailableGB ?? null,
              diskTotalGB: stats.diskTotalGB ?? null,
              diskUsedGB: stats.diskUsedGB ?? null,
              // 백엔드가 직접 잰 남은 용량. 반올림한 전체 − 반올림한 사용량으로 계산하면 1GB 씩 어긋났다.
              diskFreeGB: stats.diskFreeGB ?? null
            });
          }
        } catch {
          // 받지 못하면 이전 값을 그대로 둔다
        }
      }
  }, []);
  // 대시보드가 보일 때만 3초마다 갱신한다. 원클릭 최적화 중에는 멈춘다(예전 동작과 같다).
  usePolling(fetchRealStats, 3000, active && !isScanning);
  useEffect(() => () => {
    if (optPollInterval.current) clearInterval(optPollInterval.current);
  }, []);

  const runMasterOptimization = async () => {
    if (isScanning) return;

    // 되돌릴 수 없는 삭제(임시 파일·캐시)가 들어 있다. 무엇을 할지 먼저 보여 주고 확인을 받는다.
    let plan = null;
    try {
      if (window.pywebview?.api?.getDeepOptimizationPlan) plan = await window.pywebview.api.getDeepOptimizationPlan();
    } catch {
      plan = null;
    }
    const planLines = (plan?.steps || []).map((s, i) => `${i + 1}. ${s.name}\n    ${s.detail}`);
    const body = planLines.length ? planLines.join('\n') : OPTIMIZATION_STEPS.map((n, i) => `${i + 1}. ${n}`).join('\n');
    const excluded = plan?.excluded?.length
      ? `\n\n하지 않는 것: ${plan.excluded.join(', ')} (저장공간 화면에서 직접 고를 수 있습니다)`
      : '';
    if (!window.confirm(`원클릭 최적화를 시작합니다.\n\n${body}${excluded}\n\n계속할까요?`)) return;

    setIsScanning(true);
    
    try {
      if (window.pywebview?.api && window.pywebview?.api.startDeepOptimization) {
        const res = await window.pywebview.api.startDeepOptimization();
        if (!res || !res.success) {
          setModalMessage({ title: '시작 실패', text: res?.message || '최적화 시작에 실패했습니다.', isError: true });
          setIsScanning(false);
          return;
        }

        optPollInterval.current = setInterval(async () => {
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getDeepOptimizationStatus === 'function') {
            try {
              const status = await window.pywebview.api.getDeepOptimizationStatus();
              if (status) {
                setOptStatus(status);
                
                if (!status.running) {
                  clearInterval(optPollInterval.current);
                  if (status.error) {
                    if (status.error.includes("취소")) {
                      setModalMessage({ title: '작업 취소', text: '사용자에 의해 최적화가 중단되었습니다.', isError: false });
                    } else {
                      setModalMessage({ title: '오류 발생', text: status.error, isError: true });
                    }
                    setIsScanning(false);
                  } else {
                    finishOptimization(status);
                  }
                }
              }
            } catch (err) {
              console.error('Error polling optimization status:', err);
              clearInterval(optPollInterval.current);
              setIsScanning(false);
              setModalMessage({ title: '오류 발생', text: '최적화 상태 확인 중 시스템 오류가 발생했습니다.', isError: true });
            }
          }
        }, 1000);
      } else {
        // Fallback or missing API
        setIsScanning(false);
      }
    } catch (e) {
      console.error(e);
      setModalMessage({ title: '오류 발생', text: '통합 최적화 도중 오류가 발생했습니다. 관리자 권한을 확인해주세요.', isError: true });
      setIsScanning(false);
    }
  };

  // 백엔드가 돌려준 단계별 성패를 그대로 보여준다. 부분 실패는 성공이 아니다.
  const finishOptimization = (status) => {
    const steps = Array.isArray(status.steps) ? status.steps : [];
    const failedCount = steps.filter(st => !st.ok).length;
    setLastRun({ steps, failedCount });

    const freedMB = Number(status.freed_mb) || 0;
    const now = new Date().toLocaleDateString('ko-KR');
    localStorage.setItem('apex_last_optimized', now);
    setLastOptimized(now);

    const newTotalFreed = totalFreed + freedMB;
    localStorage.setItem('apex_total_freed', newTotalFreed);
    setTotalFreed(newTotalFreed);

    if (failedCount === 0 && steps.length > 0) {
      try {
        confetti({ particleCount: 150, spread: 100, origin: { y: 0.6 } });
      } catch {
        // 장식일 뿐이다. 실패해도 결과 표시는 이어 간다
      }
      if (addToast) addToast(`원클릭 최적화를 마쳤습니다 (${steps.length}단계 모두 성공).`, 'success');
    } else if (addToast) {
      addToast(steps.length
        ? `원클릭 최적화: ${steps.length}단계 중 ${failedCount}단계 실패. 결과를 확인하세요.`
        : '원클릭 최적화 결과를 받지 못했습니다.', 'error');
    }
    setIsScanning(false);
  };

  const getUsageColor = (val) => {
    if (!isNum(val)) return 'bg-gray-400';
    if (val < 60) return 'bg-emerald-500';
    if (val < 85) return 'bg-amber-500';
    return 'bg-rose-500';
  };

  return (
    <div className="space-y-6">
      {/* Custom Modal Overlay */}
      {modalMessage && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setModalMessage(null)}></div>
          <div className="relative glass-panel p-6 w-full max-w-sm rounded-2xl shadow-2xl border border-white/20 dark:border-black/20 transform animate-in fade-in zoom-in duration-200">
            <div className="flex flex-col items-center text-center space-y-4">
              <div className={`w-12 h-12 rounded-full flex items-center justify-center ${modalMessage.isError ? 'bg-red-500/10 text-red-500' : 'bg-blue-500/10 text-blue-500'}`}>
                <AlertTriangle className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-black dark:text-white">{modalMessage.title}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">{modalMessage.text}</p>
              </div>
              <button
                onClick={() => setModalMessage(null)}
                className={`w-full py-2.5 rounded-xl font-bold transition-colors ${
                  modalMessage.isError ? 'bg-red-500 hover:bg-red-600 text-white' : 'bg-black hover:bg-black/80 dark:bg-white dark:hover:bg-gray-200 text-white dark:text-black'
                }`}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Grid Layout */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        {/* Top Banner: Master Optimization Gauge Card */}
        <div className="md:col-span-12 glass-panel p-8 relative overflow-hidden flex flex-col justify-center">

        <div className="flex flex-col md:flex-row items-center justify-between gap-8 relative z-10 px-4 md:px-8">
          {/* Left info & call to action */}
          <div className="space-y-4 max-w-xl text-center md:text-left">
            <div className="flex items-center gap-2">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 text-xs font-mono text-gray-600 dark:text-gray-300">
                <Zap className="w-3.5 h-3.5 text-black dark:text-white" />
                ONE-CLICK
              </div>
            </div>

            <h2 className="text-3xl font-black tracking-tight text-black dark:text-white transition-colors duration-300">
              원클릭 최적화
            </h2>

            <div className="text-gray-600 dark:text-gray-400 text-sm leading-relaxed transition-colors duration-300">
              아래 네 가지를 차례로 실행하고 단계별 결과를 보여줍니다.
              <ol className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs font-mono">
                {OPTIMIZATION_STEPS.map((name, i) => (
                  <li key={name}>{i + 1}. {name}</li>
                ))}
              </ol>
            </div>

            <div className="flex flex-wrap items-center justify-center md:justify-start gap-4 pt-2">
              <button
                onClick={runMasterOptimization}
                disabled={isScanning}
                className={`btn-primary text-base px-8 py-4 ${isScanning ? 'opacity-75 cursor-not-allowed hidden' : ''}`}
              >
                <>
                  <Zap className="w-5 h-5 fill-current" />
                  <span>원클릭 최적화 시작</span>
                </>
              </button>

              {isScanning && (
                <button
                  onClick={async () => {
                    if (window.pywebview?.api?.cancelDeepOptimization) {
                      await window.pywebview.api.cancelDeepOptimization();
                    }
                  }}
                  className="bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20 px-8 py-4 rounded-xl flex items-center gap-2 transition-all"
                >
                  <span className="w-5 h-5 flex items-center justify-center font-bold text-xl leading-none">&times;</span>
                  <span className="font-bold">최적화 중지</span>
                </button>
              )}

            </div>
          </div>

          {/* Right: 이번 실행의 단계별 결과 (실행 전에는 비워 둔다) */}
          {lastRun && !isScanning && (
            <div className="w-full md:w-72 space-y-2">
              <div className="text-xs font-mono font-bold text-gray-500 dark:text-gray-400">
                최근 실행 결과 — {lastRun.steps.length - lastRun.failedCount}/{lastRun.steps.length} 단계 성공
              </div>
              {lastRun.steps.map((st, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  {st.ok
                    ? <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                    : <XCircle className="w-4 h-4 text-rose-500 flex-shrink-0" />}
                  <div className="min-w-0">
                    <div className="font-semibold text-black dark:text-white">{st.name}</div>
                    {st.detail && <div className="text-gray-500 dark:text-gray-400 break-words">{st.detail}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Scan Step Progress Bar if active */}
        {isScanning && (
          <div className="mt-6 pt-4 border-t border-black/10 dark:border-white/10 space-y-2">
            <div className="flex justify-between text-xs font-mono">
              <span className="text-gray-700 dark:text-gray-300">
                {optStatus.current_task || '시작하는 중...'}
              </span>
              <div className="flex gap-4">
                <span className="text-gray-500 dark:text-gray-400">
                  {Math.round(optStatus.progress_pct)}%
                </span>
              </div>
            </div>
            <div className="w-full bg-gray-200 dark:bg-zinc-800 h-2 rounded-full overflow-hidden">
              <div 
                className="bg-black dark:bg-white h-full rounded-full transition-all duration-700"
                style={{ width: `${Math.round(optStatus.progress_pct)}%` }}
              ></div>
            </div>
          </div>
        )}
      </div>

      {/* NEW SECTION: Lutimize-style Info Blocks */}
      <div className="md:col-span-12 grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="glass-panel p-5 flex items-center justify-between">
          <div>
            <h4 className="text-xs font-mono font-bold text-gray-500 dark:text-gray-400 uppercase tracking-widest mb-1">마지막 원클릭 최적화</h4>
            <div className="text-2xl font-black text-black dark:text-white">{lastOptimized}</div>
          </div>
          <div className="w-12 h-12 rounded-full bg-amber-500/10 flex items-center justify-center">
            <CheckCircle2 className="w-6 h-6 text-amber-500" />
          </div>
        </div>
        
        <div className="glass-panel p-5 flex items-center justify-between">
          <div>
            <h4 className="text-xs font-mono font-bold text-gray-500 dark:text-gray-400 uppercase tracking-widest mb-1">원클릭 최적화로 확보한 공간 (누적)</h4>
            <div className="text-2xl font-black text-black dark:text-white">{totalFreed.toFixed(1)} <span className="text-lg">MB</span></div>
          </div>
          <div className="w-12 h-12 rounded-full bg-blue-500/10 flex items-center justify-center">
            <HardDrive className="w-6 h-6 text-blue-500" />
          </div>
        </div>
      </div>

      {/* NEW SECTION: System Info Block */}
      <div className="md:col-span-12 glass-panel p-6">
        <h3 className="text-sm font-bold text-black dark:text-white mb-4 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-cyan-500" /> 시스템 정보
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-y-4 gap-x-8 text-sm">
          <div className="flex justify-between border-b border-black/5 dark:border-white/5 pb-2">
            <span className="text-gray-500 dark:text-gray-400">프로세서</span>
            <span className="text-black dark:text-white font-medium text-right truncate max-w-[300px]" title={sysInfo.cpuModel}>{sysInfo.cpuModel}</span>
          </div>
          <div className="flex justify-between border-b border-black/5 dark:border-white/5 pb-2">
            <span className="text-gray-500 dark:text-gray-400">그래픽 (GPU)</span>
            <span className="text-black dark:text-white font-medium text-right truncate max-w-[300px]" title={sysInfo.gpuModel}>{sysInfo.gpuModel}</span>
          </div>
          <div className="flex justify-between border-b border-black/5 dark:border-white/5 pb-2">
            <span className="text-gray-500 dark:text-gray-400">메모리 (RAM)</span>
            <span className="text-black dark:text-white font-medium text-right">{ramTotalLabel(sysInfo)}</span>
          </div>
          <div className="flex justify-between border-b border-black/5 dark:border-white/5 pb-2">
            {/* C: 드라이브만 잰 값이다. 예전에는 'Storage' 라고 써서 전체 저장 장치 용량처럼 보였다. */}
            <span className="text-gray-500 dark:text-gray-400">C: 드라이브</span>
            <span className="text-black dark:text-white font-medium text-right">{gb(sysInfo.diskTotalGB)}</span>
          </div>
          <div className="flex justify-between border-b border-black/5 dark:border-white/5 pb-2">
            <span className="text-gray-500 dark:text-gray-400">코어 / 스레드</span>
            <span className="text-black dark:text-white font-medium text-right">{coresText}</span>
          </div>
        </div>
      </div>

      {/* 2x2 Metric Grid (CPU, GPU, RAM, Storage) */}
      
      {/* 1. CPU Monitor */}
      <div className="md:col-span-6 glass-panel p-6 relative overflow-hidden flex flex-col justify-between hover:border-black/20 dark:hover:border-white/20 transition-all duration-300">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-2xl bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 text-black dark:text-white">
              <Cpu className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-base text-black dark:text-white truncate max-w-[280px]" title={sysInfo.cpuModel}>{sysInfo.cpuModel}</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 font-mono">{coresText} · CPU 사용률</p>
            </div>
          </div>
          <span className="text-3xl font-black font-mono text-black dark:text-white shrink-0">{pctText(cpuUsage)}</span>
        </div>

        <div className="w-full bg-gray-200 dark:bg-zinc-800 h-3 rounded-full overflow-hidden mb-5">
          <div 
            className={`${getUsageColor(cpuUsage)} h-full rounded-full transition-all duration-500`}
            style={{ width: barWidth(cpuUsage) }}
          ></div>
        </div>

        {/* Sparkline Canvas Simulation */}
        <div className="h-16 flex items-end justify-between gap-1 pt-2 relative">
          {renderLineGraph(cpuHistory)}
        </div>
      </div>

      {/* 2. GPU Monitor */}
      <div className="md:col-span-6 glass-panel p-6 relative overflow-hidden flex flex-col justify-between hover:border-black/20 dark:hover:border-white/20 transition-all duration-300">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-2xl bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 text-black dark:text-white">
              <Monitor className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-base text-black dark:text-white truncate max-w-[280px]" title={sysInfo.gpuModel}>{sysInfo.gpuModel}</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 font-mono">3D 엔진 사용률</p>
            </div>
          </div>
          <span className="text-3xl font-black font-mono text-black dark:text-white shrink-0">{pctText(gpuUsage, gpuState)}</span>
        </div>

        <div className="w-full bg-gray-200 dark:bg-zinc-800 h-3 rounded-full overflow-hidden mb-5">
          <div 
            className={`${getUsageColor(gpuUsage)} h-full rounded-full transition-all duration-500`}
            style={{ width: barWidth(gpuUsage) }}
          ></div>
        </div>

        {/* Sparkline Canvas Simulation */}
        <div className="h-16 flex items-end justify-between gap-1 pt-2 relative">
          {renderLineGraph(gpuHistory)}
        </div>
      </div>

      {/* 3. RAM Monitor */}
      <div className="md:col-span-6 glass-panel p-6 relative overflow-hidden flex flex-col justify-between hover:border-black/20 dark:hover:border-white/20 transition-all duration-300">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-2xl bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 text-black dark:text-white">
              <MemoryStick className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-base text-black dark:text-white">시스템 메모리 (RAM)</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 font-mono">{ramTotalLabel(sysInfo)}</p>
            </div>
          </div>
          <span className="text-3xl font-black font-mono text-black dark:text-white shrink-0">{pctText(ramUsage)}</span>
        </div>

        <div className="w-full bg-gray-200 dark:bg-zinc-800 h-3 rounded-full overflow-hidden mb-4">
          <div 
            className={`${getUsageColor(ramUsage)} h-full rounded-full transition-all duration-500`}
            style={{ width: barWidth(ramUsage) }}
          ></div>
        </div>

        <div className="flex justify-between text-sm font-mono text-gray-500 dark:text-gray-400 mt-2">
          <span title="작업 관리자의 '사용 중' 과 같은 값(디스크 기록을 기다리는 '수정됨' 메모리 제외)">사용 중: {gb(sysInfo.ramInUseGB)}</span>
          <span>사용 가능: {gb(sysInfo.ramAvailableGB)}</span>
        </div>
      </div>

      {/* 4. Disk Storage */}
      <div className="md:col-span-6 glass-panel p-6 relative overflow-hidden flex flex-col justify-between hover:border-black/20 dark:hover:border-white/20 transition-all duration-300">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-2xl bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 text-black dark:text-white">
              <HardDrive className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-base text-black dark:text-white">로컬 드라이브 (C:\)</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 font-mono">전체 {gb(sysInfo.diskTotalGB)}</p>
            </div>
          </div>
          <span className="text-3xl font-black font-mono text-black dark:text-white shrink-0">{pctText(diskUsage)}</span>
        </div>

        <div className="w-full bg-gray-200 dark:bg-zinc-800 h-3 rounded-full overflow-hidden mb-4">
          <div 
            className={`${getUsageColor(diskUsage)} h-full rounded-full transition-all duration-500`}
            style={{ width: barWidth(diskUsage) }}
          ></div>
        </div>

        <div className="flex justify-between text-sm font-mono text-gray-500 dark:text-gray-400 mt-2">
          <span>사용 중: {gb(sysInfo.diskUsedGB)}</span>
          <span>남은 용량: {gb(sysInfo.diskFreeGB)}</span>
        </div>
      </div>

      </div>
    </div>
  );
}
