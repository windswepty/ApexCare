import React, { useState, useEffect } from 'react';
import { 
  Crosshair, 
  Gamepad2, 
  Activity, 
  ToggleLeft, 
  ToggleRight,
  ShieldCheck,
  Cpu
} from 'lucide-react';
import { playSound } from '../utils/audio';

export default function GameBooster() {
  const [status, setStatus] = useState({
    enabled: false,
    active: false,
    detected_game: null,
    boost_count: 0
  });

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const fetchStatus = async () => {
    if (window.pywebview?.api?.getGameBoosterStatus) {
      const st = await window.pywebview.api.getGameBoosterStatus();
      if (st) setStatus(st);
    }
  };

  const toggleBooster = async () => {
    playSound('click');
    const newState = !status.enabled;
    // Optimistic update
    setStatus(prev => ({ ...prev, enabled: newState }));
    
    if (window.pywebview?.api?.toggleGameBooster) {
      await window.pywebview.api.toggleGameBooster(newState);
      fetchStatus();
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
        <div className="space-y-1 z-10">
          <div className="flex items-center gap-2 text-purple-400 font-mono text-xs font-semibold">
            <Crosshair className="w-4 h-4" />
            AUTO GAME BOOSTER & PROCESS TAMER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white tracking-tight">스마트 게임 부스터</h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm max-w-xl">
            백그라운드에서 게임 실행을 자동으로 감지하고, 브라우저와 디스코드 등 렉을 유발하는 프로세스의 자원 점유율을 강제로 억제합니다.
          </p>
        </div>
        <div className="z-10 shrink-0">
          <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-purple-500/10 border border-purple-500/20">
            <Gamepad2 className="w-8 h-8 text-purple-500" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-panel p-8 flex flex-col items-center justify-center text-center relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-purple-500/5 to-transparent pointer-events-none" />
          
          <div className="mb-6 relative">
            <div className={`absolute inset-0 rounded-full blur-xl transition-all duration-700 ${
              status.enabled ? 'bg-purple-500/30' : 'bg-gray-500/10'
            }`} />
            <div className={`relative w-24 h-24 rounded-full flex items-center justify-center border-4 transition-all duration-500 ${
              status.enabled ? 'border-purple-500 text-purple-500' : 'border-gray-300 dark:border-gray-700 text-gray-400'
            }`}>
              <ShieldCheck className="w-10 h-10" />
            </div>
          </div>
          
          <h3 className="text-xl font-bold text-black dark:text-white mb-2">
            자동 부스터 {status.enabled ? '작동 중' : '꺼짐'}
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-8 max-w-xs mx-auto">
            {status.enabled 
              ? "백그라운드 감시 프로세스가 안전하게 동작하고 있습니다." 
              : "기능을 활성화하면 게임 실행 시 렉을 유발하는 앱들을 억제합니다."}
          </p>
          
          <button 
            onClick={toggleBooster}
            className={`flex items-center gap-2 px-8 py-4 rounded-xl font-bold transition-all ${
              status.enabled 
                ? 'bg-purple-500/10 text-purple-500 hover:bg-purple-500/20' 
                : 'bg-black text-white dark:bg-white dark:text-black'
            }`}
          >
            {status.enabled ? <ToggleRight className="w-6 h-6" /> : <ToggleLeft className="w-6 h-6" />}
            {status.enabled ? '기능 끄기' : '기능 켜기'}
          </button>
        </div>

        <div className="space-y-6">
          <div className="glass-panel p-6">
            <h3 className="font-bold text-gray-500 dark:text-gray-400 text-sm mb-4">현재 상태</h3>
            
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-black/5 dark:border-white/5 pb-4">
                <div className="flex items-center gap-3">
                  <Activity className={`w-5 h-5 ${status.active ? 'text-green-500' : 'text-gray-400'}`} />
                  <div>
                    <div className="font-bold text-black dark:text-white">부스트 모드 (Boost)</div>
                    <div className="text-xs text-gray-500">우선순위 억제 엔진</div>
                  </div>
                </div>
                <div className={`font-mono font-bold ${status.active ? 'text-green-500' : 'text-gray-400'}`}>
                  {status.active ? 'ENGAGED' : 'STANDBY'}
                </div>
              </div>
              
              <div className="flex items-center justify-between border-b border-black/5 dark:border-white/5 pb-4">
                <div className="flex items-center gap-3">
                  <Gamepad2 className={`w-5 h-5 ${status.detected_game ? 'text-purple-500' : 'text-gray-400'}`} />
                  <div>
                    <div className="font-bold text-black dark:text-white">감지된 게임</div>
                    <div className="text-xs text-gray-500">실행 중인 대상</div>
                  </div>
                </div>
                <div className="font-mono font-bold text-black dark:text-white">
                  {status.detected_game ? status.detected_game : 'NONE'}
                </div>
              </div>

              <div className="flex items-center justify-between pb-2">
                <div className="flex items-center gap-3">
                  <Cpu className="w-5 h-5 text-blue-500" />
                  <div>
                    <div className="font-bold text-black dark:text-white">누적 억제 횟수</div>
                    <div className="text-xs text-gray-500">게임 렉 방지 기록</div>
                  </div>
                </div>
                <div className="font-mono font-bold text-black dark:text-white">
                  {status.boost_count} 회
                </div>
              </div>
            </div>
          </div>
          
          <div className="glass-panel p-5 bg-purple-500/5 border-purple-500/20">
            <h4 className="font-bold text-purple-500 mb-2 text-sm">지원되는 게임 목록</h4>
            <p className="text-xs text-black/70 dark:text-white/70 leading-relaxed font-mono">
              PUBG(배틀그라운드), Valorant(발로란트), League of Legends(롤), Overwatch, CS:GO, CS2, Apex Legends, GTA V, Dota 2, Rainbow Six Siege, Cyberpunk 2077
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
