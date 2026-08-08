import React, { useState, useEffect } from 'react';
import { Cpu, HardDrive, Monitor, Zap, CheckCircle2, ChevronRight, Loader2, Sparkles, Sliders, MemoryStick } from 'lucide-react';

export default function InitialSetupWizard({ stats, onComplete, isDarkMode }) {
  const [step, setStep] = useState('scanning'); // 'scanning' | 'result' | 'applying'
  const [scanProgress, setScanProgress] = useState(0);
  const [tuningTier, setTuningTier] = useState('HighEnd');

  useEffect(() => {
    // Determine tuning tier for UI text
    if (stats) {
      const ram = stats.ramTotalGB || 0;
      const cores = stats.cpuCores || 0;
      if (cores <= 4 || ram < 8) {
        setTuningTier('LowEnd');
      } else {
        setTuningTier('HighEnd');
      }
    }

    // Fake scanning animation for premium feel
    const interval = setInterval(() => {
      setScanProgress(prev => {
        if (prev >= 100) {
          clearInterval(interval);
          setTimeout(() => setStep('result'), 500);
          return 100;
        }
        return prev + 2;
      });
    }, 30);

    return () => clearInterval(interval);
  }, [stats]);

  const handleApply = async () => {
    setStep('applying');
    
    // Call the actual backend tailored tuning API
    if (window.pywebview?.api?.applyHardwareTuning) {
      try {
        await window.pywebview.api.applyHardwareTuning(stats.cpuCores, stats.ramTotalGB);
      } catch (e) {
        console.error("Failed to apply hardware tuning:", e);
      }
    }
    
    // Briefly show applying animation before complete
    setTimeout(() => {
      onComplete('standard'); // Return to standard mode as base for dashboard
    }, 1500);
  };

  const getTuningInfo = (tier) => {
    if (tier === 'LowEnd') {
      return {
        title: '저사양 맞춤형 다이내믹 튜닝',
        desc: '백그라운드 서비스(SysMain, WSearch 등)를 억제하여 제한된 자원을 영끌하고 CPU/RAM 점유율을 대폭 낮춥니다.',
        icon: Sliders,
        color: 'text-amber-400',
        bg: 'bg-amber-500/20',
        border: 'border-amber-500/50'
      };
    } else {
      return {
        title: '고성능 맞춤형 한계 돌파 튜닝',
        desc: '넉넉한 하드웨어 자원을 100% 활용합니다. 시스템 캐시를 넉넉하게 유지하고 CPU 최대 클럭 다운을 방지하여 잠재력을 폭발시킵니다.',
        icon: Sparkles,
        color: 'text-cyan-400',
        bg: 'bg-cyan-500/20',
        border: 'border-cyan-500/50'
      };
    }
  };

  const TierInfo = getTuningInfo(tuningTier);
  const InfoIcon = TierInfo.icon;

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center p-6 ${isDarkMode ? 'bg-black/95 text-white' : 'bg-gray-100/95 text-black'}`}>
      
      {/* Background Decor */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-cyan-500/10 blur-[120px] rounded-full pointer-events-none"></div>

      <div className={`relative w-full max-w-2xl rounded-3xl border shadow-2xl overflow-hidden transition-all duration-700 ${isDarkMode ? 'bg-zinc-950/80 border-white/10' : 'bg-white/90 border-black/10'}`}>
        
        {step === 'scanning' ? (
          <div className="flex flex-col items-center justify-center py-32 px-10">
            <Loader2 className="w-16 h-16 text-cyan-400 animate-spin mb-6" />
            <h2 className="text-2xl font-black mb-2 tracking-tight">하드웨어 스펙 분석 중</h2>
            <p className={`text-sm mb-10 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              내 PC 환경을 분석하여 최적의 튜닝 파라미터를 계산하고 있습니다...
            </p>
            
            <div className="w-full max-w-md h-2 rounded-full overflow-hidden bg-black/10 dark:bg-white/10">
              <div 
                className="h-full bg-cyan-400 transition-all duration-75 ease-out shadow-[0_0_10px_rgba(34,211,238,0.5)]"
                style={{ width: `${scanProgress}%` }}
              ></div>
            </div>
            <div className="mt-3 font-mono text-xs text-cyan-400 font-bold">{scanProgress}%</div>
          </div>
        ) : step === 'applying' ? (
          <div className="flex flex-col items-center justify-center py-32 px-10">
            <Zap className="w-16 h-16 text-yellow-400 animate-pulse mb-6" />
            <h2 className="text-2xl font-black mb-2 tracking-tight">AI 커스텀 튜닝 적용 중...</h2>
            <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              레지스트리 및 OS 서비스 레벨에 맞춤형 설정을 영구적으로 적용합니다.
            </p>
          </div>
        ) : (
          <div className="flex flex-col h-full animate-fade-in-up">
            {/* Header */}
            <div className={`p-8 pb-6 border-b ${isDarkMode ? 'border-white/10 bg-white/5' : 'border-black/10 bg-black/5'}`}>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-xl bg-black dark:bg-white flex items-center justify-center">
                  <img src="/icon.png" alt="logo" className="w-6 h-6 invert dark:invert-0" />
                </div>
                <div>
                  <h1 className="text-2xl font-black tracking-tight flex items-center gap-2">
                    <span className="text-cyan-400">APEX CARE</span> 다이내믹 엔진
                  </h1>
                </div>
              </div>
              <p className={`text-sm mt-2 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                PC 사양 분석 완료. 이 PC의 체급에 완벽하게 맞춰진 베이스 최적화 프로필이 준비되었습니다.
              </p>
            </div>

            {/* Body */}
            <div className="p-8 grid grid-cols-1 md:grid-cols-2 gap-8">
              
              {/* Left: Specs */}
              <div>
                <h3 className={`text-xs font-mono font-bold mb-4 uppercase tracking-widest ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}>
                  분석된 시스템 스펙
                </h3>
                
                <div className="grid grid-cols-2 gap-3">
                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <Cpu className={`w-4 h-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`} />
                      <div className={`text-[10px] font-mono ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>프로세서</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate" title={stats?.cpuModel}>{stats?.cpuModel || '알 수 없음'}</div>
                      <div className={`text-[10px] font-mono mt-0.5 ${isDarkMode ? 'text-cyan-400/70' : 'text-cyan-600'}`}>
                        {stats?.cpuCores} Cores / {stats?.cpuThreads} Threads
                      </div>
                    </div>
                  </div>

                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <Monitor className={`w-4 h-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`} />
                      <div className={`text-[10px] font-mono ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>그래픽 (GPU)</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate" title={stats?.gpuModel || '3D Engine (WMI)'}>{stats?.gpuModel || '3D Engine (WMI)'}</div>
                      <div className={`text-[10px] font-mono mt-0.5 ${isDarkMode ? 'text-cyan-400/70' : 'text-cyan-600'}`}>
                        Hardware Accelerated
                      </div>
                    </div>
                  </div>

                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <MemoryStick className={`w-4 h-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`} />
                      <div className={`text-[10px] font-mono ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>메모리 (RAM)</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate">{stats?.ramTotalGB || 0} GB 탑재</div>
                    </div>
                  </div>

                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <HardDrive className={`w-4 h-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`} />
                      <div className={`text-[10px] font-mono ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>로컬 드라이브 (SSD)</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate">{stats?.diskTotalGB || 0} GB 공간</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right: Custom Tuning Info */}
              <div className="flex flex-col justify-center">
                <h3 className={`text-xs font-mono font-bold mb-4 uppercase tracking-widest ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}>
                  AI 스펙 맞춤형 튜닝 솔루션
                </h3>
                
                <div className={`relative p-6 rounded-2xl border-2 ${TierInfo.border} ${TierInfo.bg} overflow-hidden shadow-lg`}>
                  <div className="absolute top-0 right-0 bg-black/20 px-3 py-1 rounded-bl-xl text-[10px] font-bold font-mono text-white flex items-center gap-1 backdrop-blur-sm">
                    <CheckCircle2 className="w-3 h-3" /> CUSTOMIZED
                  </div>
                  
                  <InfoIcon className={`w-10 h-10 mb-4 ${TierInfo.color}`} />
                  
                  <h4 className="text-lg font-black mb-2">{TierInfo.title}</h4>
                  <p className={`text-xs leading-relaxed ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                    {TierInfo.desc}
                  </p>
                </div>
              </div>
              
            </div>

            {/* Footer Buttons */}
            <div className={`p-6 border-t flex justify-end gap-3 ${isDarkMode ? 'border-white/10 bg-white/5' : 'border-black/10 bg-black/5'}`}>
              <button 
                onClick={() => onComplete('standard')}
                className={`px-5 py-2.5 rounded-xl text-sm font-semibold transition-all ${isDarkMode ? 'hover:bg-white/10 text-gray-400' : 'hover:bg-black/5 text-gray-600'}`}
              >
                건너뛰기 (적용 안함)
              </button>
              
              <button 
                onClick={handleApply}
                className={`px-6 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-lg active:scale-95 ${
                  isDarkMode 
                    ? 'bg-white text-black hover:bg-gray-200 shadow-white/10' 
                    : 'bg-black text-white hover:bg-gray-800 shadow-black/10'
                }`}
              >
                내 PC 맞춤형 최적화 즉시 적용
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}
