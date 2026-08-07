import React, { useState, useEffect } from 'react';
import { 
  Zap, 
  Gamepad2, 
  Leaf, 
  Briefcase, 
  CheckCircle2, 
  Flame,
  Target,
  Maximize2,
  Minimize2,
  Layers,
  Sparkles,
  Activity,
  Cpu,
  Gauge
} from 'lucide-react';
import { playSound } from '../utils/audio';

export default function PerformanceModes({ currentMode, setCurrentMode, addToast }) {
  const [isBoosterEnabled, setIsBoosterEnabled] = useState(true);
  const [activeAppId, setActiveAppId] = useState(null);
  const [runningApps, setRunningApps] = useState([]);

  useEffect(() => {
    const fetchProcesses = async () => {
      if (window.pywebview?.api && window.pywebview?.api.getProcesses) {
        try {
          const procs = await window.pywebview?.api.getProcesses();
          if (procs && procs.length > 0) {
            setRunningApps(procs);
            if (!activeAppId) setActiveAppId(procs[0].pid);
          }
        } catch (e) {}
      }
    };
    if (isBoosterEnabled) {
      fetchProcesses();
      const interval = setInterval(fetchProcesses, 5000);
      return () => clearInterval(interval);
    }
  }, [isBoosterEnabled, activeAppId]);

  const activeApp = runningApps.find(app => app.pid === activeAppId) || runningApps[0] || { name: '로딩 중...', memoryMB: 0, cpuPct: '0%' };

  const handleSetPriority = async (pid, priority) => {
    playSound('click');
    setActiveAppId(pid);
    if (window.pywebview?.api && window.pywebview?.api.setProcessPriority) {
      try {
        await window.pywebview?.api.setProcessPriority(pid, priority);
        if (addToast) addToast('우선순위가 성공적으로 변경되었습니다.', 'success');
      } catch (e) {
        alert('우선순위 변경 권한이 없습니다.');
        if (addToast) addToast('우선순위 변경에 실패했습니다.', 'error');
      }
    }
  };

  const modes = [
    {
      id: 'gaming',
      title: '게이밍 울트라 모드 (Gaming Ultra)',
      subtitle: '프레임 극대화 & 최고 우선순위 부스트',
      icon: Gamepad2,
      badge: 'HIGH FPS ENGINE',
      gradient: 'from-purple-600 to-pink-600',
      borderColor: 'border-purple-500/50 shadow-purple-500/20',
      activeColor: 'text-purple-400',
      tweaks: [
        '🎯 [스마트 포커스 엔진] 선택된 프로세스 우선순위를 실시간 상승',
        '백그라운드 유휴 리소스(Standby RAM) 반환 정책 강화',
        '그래픽카드 고성능 전원 관리 (High Performance Plan)',
        '마우스/키보드 인풋렉을 최소화하는 전원 프로필 적용'
      ]
    },
    {
      id: 'standard',
      title: '생산성 균형 모드 (Work & Balanced)',
      subtitle: '일상적인 멀티태스킹 최적화',
      icon: Briefcase,
      badge: 'RECOMMENDED',
      gradient: 'from-cyan-500 to-blue-600',
      borderColor: 'border-cyan-500/50 shadow-cyan-500/20',
      activeColor: 'text-cyan-400',
      tweaks: [
        '🎯 균형 잡힌 CPU 스케줄링 (Balanced Plan)',
        '작업용 프로그램 및 브라우저 성능 최적화',
        '발열 및 팬 소음을 적정 수준으로 관리'
      ]
    },
    {
      id: 'eco',
      title: '에코 & 절전 모드 (Eco Battery Saver)',
      subtitle: '소음 최소화 & 전력 소비 절감',
      icon: Leaf,
      badge: 'LOW POWER',
      gradient: 'from-emerald-500 to-teal-600',
      borderColor: 'border-emerald-500/50 shadow-emerald-500/20',
      activeColor: 'text-emerald-400',
      tweaks: [
        '최대 프로세서 상태 제한 (전력 제한 모드)',
        '미사용 앱 및 백그라운드 우선순위 낮춤',
        '쿨링팬 저소음 로테이션 유도'
      ]
    }
  ];

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col lg:flex-row lg:items-center justify-between gap-6 relative overflow-hidden">
        <div className="space-y-1 z-10">
          <div className="flex items-center gap-2 text-fuchsia-400 font-mono text-xs font-semibold mb-1">
            <Zap className="w-4 h-4" />
            AI OPTIMIZATION PROFILES & SMART BOOSTER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">성능 부스트 모드 설정</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
            사용 목적에 따라 시스템 자원 할당 정책(Power Plan) 및 실시간 프로세스 우선순위를 제어합니다.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-white dark:bg-slate-900/80 px-4 py-2 rounded-xl border border-black/10 dark:border-slate-800 font-mono text-xs text-gray-700 dark:text-slate-300">
          <Flame className="w-4 h-4 text-amber-400" />
          <span>현재 적용 중인 모드: </span>
          <span className="font-bold text-cyan-400 uppercase">{currentMode}</span>
          <span className="text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full ml-1 font-sans font-semibold">
            ✓ OS 전원 프로필 적용됨
          </span>
        </div>
      </div>

      {/* SMART FOCUS BOOSTER CARD - TAILORED FOR GAMING & PRODUCTIVITY */}
      <div className={`glass-panel p-6 border-l-4 transition-all duration-300 shadow-2xl relative overflow-hidden ${
        currentMode === 'gaming'
          ? 'border-l-purple-500 bg-gradient-to-r from-purple-950/30 via-slate-900/90 to-slate-900/90'
          : 'border-l-cyan-400 bg-gradient-to-r from-cyan-950/20 via-slate-900/80 to-slate-900/90'
      }`}>
        {/* Top Header Row with Toggle */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-5 border-b border-black/10 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className={`p-3 rounded-2xl border ${
              currentMode === 'gaming' ? 'bg-purple-500/20 text-purple-400 border-purple-500/40' : 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
            }`}>
              <Target className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-black text-black dark:text-white">스마트 포커스 부스터 (Smart Focus Booster)</h3>
                <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                  currentMode === 'gaming' ? 'bg-purple-500/20 text-purple-300 border-purple-500/40' : 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                }`}>
                  {currentMode === 'gaming' ? '🎮 GAMING PRIORITY ENGINE' : '⚡ WORK PRIORITY ENGINE'}
                </span>
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
                모니터 화면 전면(Foreground) 게임 및 앱에 CPU/GPU 자원을 집중하고 백그라운드 프로세스를 자동으로 절전 억제합니다.
              </p>
            </div>
          </div>

          {/* Engine Toggle Switch */}
          <div className="flex items-center gap-3 bg-white dark:bg-slate-900/90 px-4 py-2 rounded-2xl border border-black/10 dark:border-slate-800 shrink-0 w-max">
            <span className="text-xs font-mono text-gray-700 dark:text-slate-300 font-medium whitespace-nowrap">부스터 엔진:</span>
            <button
              onClick={() => {
                playSound('toggle');
                setIsBoosterEnabled(!isBoosterEnabled);
              }}
              className={`w-12 h-6 shrink-0 rounded-full p-1 transition-all duration-300 ${
                isBoosterEnabled ? (currentMode === 'gaming' ? 'bg-purple-500' : 'bg-cyan-500') : 'bg-gray-100 dark:bg-slate-700'
              }`}
            >
              <div
                className={`w-4 h-4 rounded-full bg-white transition-all duration-300 transform ${
                  isBoosterEnabled ? 'translate-x-6' : 'translate-x-0'
                }`}
              />
            </button>
            <span className={`text-xs font-mono font-bold whitespace-nowrap ${isBoosterEnabled ? (currentMode === 'gaming' ? 'text-purple-400' : 'text-cyan-400') : 'text-slate-500'}`}>
              {isBoosterEnabled ? 'ON' : 'OFF'}
            </span>
          </div>
        </div>

        {/* Live Status Content */}
        {isBoosterEnabled ? (
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Col: Current Active App Showcase */}
            <div className="lg:col-span-7 bg-gray-100 dark:bg-slate-950/60 p-5 rounded-2xl border border-black/10 dark:border-slate-800 space-y-4">
              <div className="flex items-center justify-between">
                <span className={`text-xs font-mono font-semibold flex items-center gap-1.5 ${currentMode === 'gaming' ? 'text-purple-400' : 'text-cyan-400'}`}>
                  <Maximize2 className="w-3.5 h-3.5" />
                  🎯 실시간 프로세스 우선순위 상승
                </span>
                <span className={`text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full border ${
                  currentMode === 'gaming' ? 'bg-purple-500/20 border-purple-500/40 text-purple-300' : 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300'
                }`}>
                  {currentMode === 'gaming' ? '🎮 MAX FPS BOOST ACTIVE' : 'HIGH PRIORITY BOOSTED'}
                </span>
              </div>

              {/* App Info Box */}
              <div className={`flex items-center gap-4 bg-white dark:bg-slate-900/90 p-4 rounded-xl border ${
                currentMode === 'gaming' ? 'border-purple-500/40 shadow-lg shadow-purple-500/10' : 'border-black/10 dark:border-slate-800'
              }`}>
                <div className={`p-3 rounded-xl border ${
                  currentMode === 'gaming' ? 'bg-purple-500/15 text-purple-400 border-purple-500/30' : 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30'
                }`}>
                  <Target className="w-7 h-7" />
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="font-bold text-black dark:text-white text-base truncate">{activeApp.name}</h4>
                  <p className="text-xs text-gray-500 dark:text-slate-400 font-mono">PID: {activeApp.pid} | 우선순위: {activeApp.priority || 'High'}</p>
                </div>
              </div>

              {/* Resource Allocation Breakdown */}
              <div className="grid grid-cols-3 gap-3 font-mono text-xs">
                <div className="bg-white dark:bg-slate-900/60 p-3 rounded-xl border border-black/10 dark:border-slate-800">
                  <span className="text-[10px] text-slate-500 block mb-1">CPU 점유</span>
                  <span className="text-cyan-300 font-bold text-[11px] block truncate">{activeApp.cpuPct || '0%'}</span>
                </div>
                <div className="bg-white dark:bg-slate-900/60 p-3 rounded-xl border border-black/10 dark:border-slate-800">
                  <span className="text-[10px] text-slate-500 block mb-1">메모리 할당</span>
                  <span className="text-purple-300 font-bold text-[11px] block truncate">{activeApp.memoryMB || 0} MB</span>
                </div>
                <div className="bg-white dark:bg-slate-900/60 p-3 rounded-xl border border-black/10 dark:border-slate-800">
                  <span className="text-[10px] text-slate-500 block mb-1">상태</span>
                  <span className="text-emerald-300 font-bold text-[11px] block truncate">{activeApp.status || 'Running'}</span>
                </div>
              </div>
            </div>

            {/* Right Col: Process List */}
            <div className="lg:col-span-5 bg-gray-100 dark:bg-slate-950/60 p-5 rounded-2xl border border-black/10 dark:border-slate-800 flex flex-col justify-between space-y-4">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-mono text-gray-500 dark:text-slate-400 font-semibold flex items-center gap-1.5">
                    <Activity className="w-3.5 h-3.5 text-amber-400" />
                    실행 중인 프로세스 목록
                  </span>
                </div>

                <div className="space-y-2 h-48 overflow-y-auto pr-2 custom-scrollbar" data-lenis-prevent>
                  {runningApps.slice(0, 8).map((app, idx) => (
                    <button 
                      key={app.pid} 
                      onClick={() => handleSetPriority(app.pid, 'High')}
                      className={`w-full flex items-center justify-between p-2.5 rounded-xl border text-xs transition-all ${
                        activeAppId === app.pid ? 'bg-gray-50 dark:bg-slate-800 border-black/20 dark:border-slate-600' : 'bg-white dark:bg-slate-900/70 border-black/10 dark:border-slate-800 hover:bg-gray-50 dark:bg-slate-800'
                      }`}
                    >
                      <div className="min-w-0 pr-2 text-left">
                        <div className="font-semibold text-gray-800 dark:text-slate-200 text-[11px] truncate">{app.name}</div>
                        <div className="text-[9px] font-mono text-gray-500 dark:text-slate-400 truncate">PID: {app.pid}</div>
                      </div>
                      <div className="text-[10px] font-mono px-2 py-0.5 rounded bg-gray-50 dark:bg-slate-800 text-gray-700 dark:text-slate-300 font-bold flex items-center gap-1 shrink-0" title="프로세스 CPU 점유율 (멀티코어 사용 시 100% 초과 가능)">
                        <Cpu className="w-3 h-3 text-amber-500/80 dark:text-amber-400/80" />
                        {app.cpuPct}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Bottom Summary Bar */}
              <div className="p-3 rounded-xl bg-white dark:bg-slate-900 border border-black/10 dark:border-slate-800 flex items-center justify-between text-xs font-mono">
                <span className="text-gray-500 dark:text-slate-400 text-[11px]">프로세스 우선순위 효과:</span>
                <span className={`font-bold flex items-center gap-1 ${currentMode === 'gaming' ? 'text-purple-400' : 'text-cyan-400'}`}>
                  <Sparkles className="w-3.5 h-3.5" />
                  CPU 스케줄링 자원 집중
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-6 p-8 rounded-2xl bg-gray-100 dark:bg-slate-950/40 border border-black/10 dark:border-slate-800 text-center">
            <Target className="w-10 h-10 text-slate-600 mx-auto mb-2 opacity-50" />
            <h4 className="text-sm font-bold text-gray-500 dark:text-slate-400">스마트 포커스 부스터 엔진이 비활성화되어 있습니다.</h4>
            <p className="text-xs text-slate-500 mt-1">상단 스위치를 켜면 화면 전면 앱 자동 자원 집중 기능이 가동됩니다.</p>
          </div>
        )}
      </div>

      {/* Mode Cards Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {modes.map((mode) => {
          const Icon = mode.icon;
          const isActive = currentMode === mode.id;

          return (
            <div
              key={mode.id}
              onClick={() => {
                playSound('success');
                setCurrentMode(mode.id);
                if (addToast) addToast(`[${mode.title.split('(')[0].trim()}] 프로필이 적용되었습니다!`, 'success');
              }}
              className={`relative flex-1 glass-panel text-left p-6 group cursor-pointer transition-all duration-300 ${
                isActive
                  ? `border-2 ${mode.borderColor} bg-white dark:bg-slate-900/90 shadow-xl scale-[1.02]` : 'hover:border-black/10 dark:border-slate-700 opacity-85'
              }`}
            >
              {/* Active Badge indicator top right */}
              {isActive && (
                <div className="absolute top-4 right-4 flex items-center gap-1 text-[10px] font-mono font-bold px-2.5 py-1 rounded-full bg-gray-50 dark:bg-slate-800 text-black dark:text-white border border-black/10 dark:border-slate-700">
                  <CheckCircle2 className={`w-3.5 h-3.5 ${mode.activeColor}`} />
                  ACTIVE
                </div>
              )}

              <div>
                <div className="flex items-center gap-3 mb-4">
                  <div className={`p-3 rounded-2xl bg-gradient-to-tr ${mode.gradient} text-slate-950 shadow-md`}>
                    <Icon className="w-6 h-6" />
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-gray-500 dark:text-slate-400 tracking-wider uppercase">{mode.badge}</span>
                    <h3 className="font-bold text-gray-900 dark:text-slate-100 text-base">{mode.title}</h3>
                  </div>
                </div>

                <p className="text-xs text-gray-500 dark:text-slate-400 mb-4">{mode.subtitle}</p>

                {/* Tweaks list */}
                <div className="space-y-2 border-t border-black/10 dark:border-slate-800/80 pt-4">
                  <span className="text-[11px] font-mono text-gray-500 dark:text-slate-400 font-semibold block">적용되는 주요 최적화 옵션:</span>
                  {mode.tweaks.map((tweak, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-xs text-gray-700 dark:text-slate-300">
                      <span className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${isActive ? mode.activeColor : 'bg-slate-600'}`}></span>
                      <span>{tweak}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-6 pt-4 border-t border-black/10 dark:border-slate-800/60">
                <button
                  className={`w-full py-2.5 rounded-xl font-bold text-xs transition-all ${
                    isActive
                      ? `bg-gradient-to-r ${mode.gradient} text-black dark:text-white shadow-lg`
                      : 'bg-gray-50 dark:bg-slate-800 text-gray-700 dark:text-slate-300 hover:bg-gray-100 dark:bg-slate-700'
                  }`}
                >
                  {isActive ? '현재 적용 중' : '이 프로필로 전환'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
