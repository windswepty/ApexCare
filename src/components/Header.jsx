import React, { useState, useEffect } from 'react';
import { Monitor, Clock, ShieldCheck, Flame, Moon, Sun, Thermometer } from 'lucide-react';

export default function Header({ currentMode, setCurrentMode, isDarkMode, setIsDarkMode }) {
  const [uptime, setUptime] = useState({ hours: 0, minutes: 0, seconds: 0 });
  const [osLabel, setOsLabel] = useState('Windows');
  const [cpuLabel, setCpuLabel] = useState('Loading...');

  useEffect(() => {
    // Fetch real system info
    const fetchInfo = async () => {
      if (window.pywebview?.api && window.pywebview?.api.getSystemStats) {
        try {
          const stats = await window.pywebview?.api.getSystemStats();
          if (stats) {
            // OS Info
            if (stats.osInfo) setOsLabel(stats.osInfo);
            // CPU Info
            if (stats.cpuModel) setCpuLabel(stats.cpuModel);
            // OS Info
            // Uptime from OS
            if (stats.uptimeSec) {
              const totalSec = stats.uptimeSec;
              setUptime({
                hours: Math.floor(totalSec / 3600),
                minutes: Math.floor((totalSec % 3600) / 60),
                seconds: totalSec % 60
              });
            }
          }
        } catch (e) {}
      }
    };
    
    // Initial fetch, retry if pywebview is missing initially
    const initialFetch = setInterval(() => {
      if (window.pywebview?.api) {
        fetchInfo();
        clearInterval(initialFetch);
      }
    }, 100);

    // Tick uptime every second & refresh temp periodically
    let tickCount = 0;
    const timer = setInterval(() => {
      tickCount++;
      // 창이 최소화·가려져 있으면 백엔드를 부르지 않는다(가동 시간 숫자만 센다).
      if (tickCount >= 5 && !document.hidden) {
        fetchInfo();
        tickCount = 0;
      }
      
      setUptime(prev => {
        let sec = prev.seconds + 1;
        let min = prev.minutes;
        let hr = prev.hours;
        if (sec >= 60) { sec = 0; min += 1; }
        if (min >= 60) { min = 0; hr += 1; }
        return { hours: hr, minutes: min, seconds: sec };
      });
    }, 1000);

    return () => {
      clearInterval(timer);
    };
  }, []);

  return (
    <header className="glass-panel p-4 flex flex-wrap items-center justify-between gap-4 mb-6">
      {/* OS & Device Info */}
      <div className="flex items-center gap-4">
        <div className="w-11 h-11 rounded-xl bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 flex items-center justify-center text-black dark:text-white transition-colors duration-300">
          <Monitor className="w-6 h-6" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-bold text-black dark:text-white text-sm tracking-wide truncate max-w-[200px] transition-colors duration-300">{osLabel}</h2>
            <span className="bg-gray-100 dark:bg-zinc-900 text-gray-600 dark:text-gray-300 border border-black/10 dark:border-white/10 text-[10px] font-mono px-2 py-0.5 rounded transition-colors duration-300">
              NATIVE
            </span>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-3 mt-1 font-mono transition-colors duration-300">
            <span className="truncate max-w-[200px]">{cpuLabel}</span>
          </p>
        </div>
      </div>

      {/* Quick Status Pill Monitors */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* System Uptime */}
        <div className="bg-white dark:bg-black border border-black/10 dark:border-white/10 px-3.5 py-2 rounded-xl flex items-center gap-2 text-xs font-mono text-black dark:text-white shadow-sm transition-colors duration-300">
          <Clock className="w-4 h-4 text-gray-600 dark:text-gray-400" />
          <div>
            <div className="text-[10px] text-gray-500 dark:text-gray-400 font-sans">시스템 가동시간</div>
            <div className="font-bold">{uptime.hours}h {uptime.minutes}m {uptime.seconds}s</div>
          </div>
        </div>

        {/* Mode 3-Way Toggle Switch */}
        <div className="bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 p-1 rounded-full flex items-center relative shadow-inner overflow-hidden w-[260px] h-9 transition-colors duration-300">
          {/* Moving background indicator */}
          <div 
            className={`absolute top-1 bottom-1 w-[32%] rounded-full bg-white dark:bg-black border border-black/10 dark:border-white/10 shadow-sm transition-all duration-500 ease-out z-0 ${
              currentMode === 'standard' ? 'left-[2%]' :
              currentMode === 'gaming' ? 'left-[34%]' :
              'left-[66%] w-[32%]'
            }`}
          ></div>
          
          {/* Switch Labels */}
          {['standard', 'gaming', 'eco'].map((mode) => (
            <button
              key={mode}
              onClick={() => {
                setCurrentMode(mode);
              }}
              className={`flex-1 relative z-10 text-[11px] font-bold transition-colors duration-300 h-full flex items-center justify-center ${
                currentMode === mode ? 'text-black dark:text-white' : 'text-gray-500 dark:text-gray-400 hover:text-black dark:hover:text-black dark:text-white'
              }`}
            >
              {mode === 'standard' && '표준'}
              {mode === 'gaming' && '⚡ 게이밍'}
              {mode === 'eco' && '🌱 에코'}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
