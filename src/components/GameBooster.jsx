import React, { useState, useEffect } from 'react';
import { 
  Crosshair, 
  Gamepad2, 
  Activity, 
  ToggleLeft, 
  ToggleRight,
  ShieldCheck,
  Cpu,
  X
} from 'lucide-react';
import { playSound } from '../utils/audio';

export default function GameBooster() {
  const [status, setStatus] = useState({
    enabled: false,
    active: false,
    detected_game: null,
    boost_count: 0
  });

  const [isModalOpen, setIsModalOpen] = useState(false);

  const gameCategories = [
    {
      category: "FPS & 슈팅",
      icon: "🎯",
      games: [
        { name: "PUBG (배틀그라운드)", icon: "🪂" },
        { name: "Valorant (발로란트)", icon: "🔫" },
        { name: "Overwatch (오버워치)", icon: "⚔️" },
        { name: "CS:GO / CS2", icon: "💣" },
        { name: "Apex Legends", icon: "🏃" },
        { name: "Call of Duty", icon: "🎖️" },
        { name: "Fortnite (포트나이트)", icon: "🎪" },
        { name: "Escape from Tarkov", icon: "🎒" },
        { name: "The Finals", icon: "💰" },
        { name: "Destiny 2", icon: "🌌" },
        { name: "Helldivers 2", icon: "🚀" }
      ]
    },
    {
      category: "RPG & MMORPG",
      icon: "🗡️",
      games: [
        { name: "World of Warcraft", icon: "🐲" },
        { name: "Diablo IV", icon: "👿" },
        { name: "Lost Ark (로스트아크)", icon: "⛵" },
        { name: "MapleStory", icon: "🍁" },
        { name: "Elden Ring", icon: "⚔️" },
        { name: "Cyberpunk 2077", icon: "🤖" },
        { name: "Genshin Impact", icon: "🌟" },
        { name: "Honkai: Star Rail", icon: "🚂" }
      ]
    },
    {
      category: "AOS & MOBA",
      icon: "🛡️",
      games: [
        { name: "League of Legends", icon: "⚔️" },
        { name: "Dota 2", icon: "🔥" }
      ]
    },
    {
      category: "오픈월드 & 샌드박스",
      icon: "🌍",
      games: [
        { name: "GTA V", icon: "🚗" },
        { name: "Minecraft", icon: "⛏️" },
        { name: "Roblox", icon: "🧱" },
        { name: "Palworld (팰월드)", icon: "🦕" },
        { name: "Rust (러스트)", icon: "⛺" }
      ]
    },
    {
      category: "스포츠 (Sports)",
      icon: "⚽",
      games: [
        { name: "FC 24 (피파)", icon: "⚽" }
      ]
    }
  ];

  useEffect(() => {
    const checkAndFetch = () => {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getGameBoosterStatus === 'function') {
        fetchStatus();
      }
    };
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getGameBoosterStatus === 'function') {
      checkAndFetch();
    } else {
      window.addEventListener('pywebviewready', checkAndFetch);
    }
    const interval = setInterval(fetchStatus, 3000);
    return () => {
      clearInterval(interval);
      window.removeEventListener('pywebviewready', checkAndFetch);
    };
  }, []);

  const fetchStatus = async () => {
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getGameBoosterStatus === 'function') {
        const st = await window.pywebview.api.getGameBoosterStatus();
        if (st) setStatus(st);
      }
    } catch (e) {
      console.error('Error fetching game booster status:', e);
    }
  };

  const toggleBooster = async () => {
    playSound('click');
    const newState = !status.enabled;
    setStatus(prev => ({ ...prev, enabled: newState }));
    
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.toggleGameBooster === 'function') {
        await window.pywebview.api.toggleGameBooster(newState);
        fetchStatus();
      }
    } catch (e) {
      console.error('Error toggling game booster:', e);
      setStatus(prev => ({ ...prev, enabled: !newState }));
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
          
          <div className="glass-panel p-5 bg-purple-500/5 border-purple-500/20 flex flex-col justify-center items-center">
            <h4 className="font-bold text-purple-500 mb-3 text-sm flex items-center gap-2">
              <Gamepad2 className="w-4 h-4" />
              자동 감지 엔진 가동 중
            </h4>
            <button
              onClick={() => {
                playSound('click');
                setIsModalOpen(true);
              }}
              className="bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold py-2.5 px-6 rounded-xl transition-all shadow-lg shadow-purple-500/30 w-full sm:w-auto"
            >
              지원되는 게임목록 보기
            </button>
          </div>
        </div>
      </div>

      {/* Supported Games Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white dark:bg-slate-900 border border-black/10 dark:border-slate-800 rounded-3xl p-6 w-full max-w-2xl shadow-2xl relative flex flex-col max-h-[85vh]">
            <div className="flex items-center justify-between mb-6 shrink-0">
              <h3 className="text-lg font-black text-black dark:text-white flex items-center gap-2">
                <Gamepad2 className="w-5 h-5 text-purple-500" />
                스마트 부스터 지원 게임 목록
              </h3>
              <button
                onClick={() => {
                  playSound('toggle');
                  setIsModalOpen(false);
                }}
                className="p-2 bg-gray-100 hover:bg-gray-200 dark:bg-slate-800 dark:hover:bg-slate-700 rounded-full transition-colors"
              >
                <X className="w-5 h-5 text-gray-500 dark:text-slate-400" />
              </button>
            </div>
            
            <div className="overflow-y-auto custom-scrollbar pr-4 pb-2 space-y-6" data-lenis-prevent>
              {gameCategories.map((cat, catIdx) => (
                <div key={catIdx}>
                  <h4 className="text-sm font-bold text-gray-800 dark:text-slate-300 mb-3 flex items-center gap-2">
                    <span>{cat.icon}</span> {cat.category}
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {cat.games.map((game, idx) => (
                      <div key={idx} className="bg-gray-50 dark:bg-slate-800/50 hover:bg-purple-50 dark:hover:bg-purple-500/10 border border-black/5 dark:border-slate-700 p-3 rounded-xl flex items-center gap-3 transition-colors cursor-default shadow-sm">
                        <span className="text-xl">{game.icon}</span>
                        <span className="font-semibold text-gray-800 dark:text-slate-200 text-xs truncate">
                          {game.name}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            
            <div className="mt-6 pt-4 border-t border-black/5 dark:border-slate-800 text-center shrink-0">
              <p className="text-xs text-gray-500 dark:text-slate-400 font-mono">
                이 외에도 수십 종의 글로벌 인기 게임 프로세스를 백그라운드에서 실시간 모니터링합니다.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
