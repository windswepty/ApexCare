import React, { useRef, useEffect } from 'react';
import Lenis from 'lenis';
import { 
  LayoutDashboard, 
  Trash2, 
  Cpu, 
  Rocket, 
  HardDrive, 
  Zap, 
  ShieldCheck, 
  Sparkles,
  PackageMinus,
  SearchCode,
  ServerCrash,
  Crosshair
} from 'lucide-react';

export default function Sidebar({ activeTab, setActiveTab }) {
  const sidebarWrapperRef = useRef(null);

  useEffect(() => {
    if (!sidebarWrapperRef.current) return;

    const lenis = new Lenis({
      wrapper: sidebarWrapperRef.current,
      content: sidebarWrapperRef.current.firstElementChild,
      lerp: 0.05,
      smoothWheel: true,
      wheelMultiplier: 1.0,
    });

    let animationFrameId;
    function raf(time) {
      lenis.raf(time);
      animationFrameId = requestAnimationFrame(raf);
    }
    animationFrameId = requestAnimationFrame(raf);

    return () => {
      cancelAnimationFrame(animationFrameId);
      lenis.destroy();
    };
  }, []);

  const menuItems = [
    { id: 'dashboard', label: '대시보드 (Dashboard)', icon: LayoutDashboard },
    { id: 'cleaner', label: '정크 파일 세척 (Junk Clean)', icon: Trash2 },
    { id: 'ram', label: 'RAM 메모리 최적화', icon: Cpu },
    { id: 'startup', label: '시작 프로그램 관리', icon: Rocket },
    { id: 'uninstaller', label: '프로그램 완전 삭제', icon: PackageMinus },
    { id: 'fileFinder', label: '대용량/중복 탐색기', icon: SearchCode },
    { id: 'defrag', label: '디스크 조각모음 & TRIM', icon: HardDrive },
    { id: 'modes', label: '성능 부스트 모드', icon: Zap },
    { id: 'gamebooster', label: '스마트 게임 부스터', icon: Crosshair },
    { id: 'drivers', label: 'OS 코어 복구 (SFC/DISM)', icon: ShieldCheck },
    { id: 'debloater', label: '윈도우 하드코어 적출', icon: ServerCrash },
  ];

  return (
    <aside ref={sidebarWrapperRef} className="w-64 glass-panel p-5 flex flex-col h-full overflow-y-auto flex-shrink-0 hide-scrollbar">
      <div className="flex flex-col flex-1 justify-between min-h-max">
        <div>
          {/* Brand Header */}
        <div className="flex items-center gap-3 mb-8 px-2">
          <div className="w-10 h-10 rounded-xl border border-black/10 flex items-center justify-center bg-white shadow-sm overflow-hidden transition-colors duration-300">
            <img src="/icon.png" alt="logo" className="w-7 h-7" />
          </div>
          <div>
            <h1 className="font-extrabold text-lg tracking-tight text-black dark:text-white flex items-center gap-1.5 transition-colors duration-300">
              APEX <span className="text-gray-500 dark:text-gray-400">CARE</span>
            </h1>
            <p className="text-xs text-gray-500 dark:text-gray-400 font-mono transition-colors duration-300">v1.0.4</p>
          </div>
        </div>

        {/* Navigation List */}
        <nav className="space-y-1.5">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  setActiveTab(item.id);
                }}
                className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl transition-all duration-300 text-sm font-medium ${
                  isActive
                    ? 'bg-black dark:bg-white text-white dark:text-black shadow-md'
                    : 'text-gray-600 dark:text-gray-400 hover:text-black dark:hover:text-black dark:text-white hover:bg-gray-100 dark:hover:bg-zinc-800 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <Icon className={`w-4 h-4 flex-shrink-0 ${isActive ? 'text-white dark:text-black' : 'text-gray-400 dark:text-gray-500'}`} />
                  <span className="whitespace-nowrap truncate text-left">{item.label}</span>
                </div>
              </button>
            );
          })}
        </nav>
      </div>

        {/* System Status Summary Footer */}
        <div className="p-3.5 mt-6 rounded-xl bg-white dark:bg-black border border-black/10 dark:border-white/10 shadow-sm transition-colors duration-300">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="text-gray-600 dark:text-gray-400">실시간 엔진 상태</span>
            <span className="flex items-center gap-1.5 text-black dark:text-white font-semibold">
              <span className="w-2 h-2 rounded-full bg-black dark:bg-white animate-pulse"></span>
              ACTIVE
            </span>
          </div>
          <div className="w-full bg-gray-100 dark:bg-zinc-900 h-1.5 rounded-full overflow-hidden">
            <div className="bg-black dark:bg-white h-full w-[88%] rounded-full"></div>
          </div>
          <div className="flex justify-between text-[10px] font-mono text-gray-500 dark:text-gray-400 mt-2">
            <span>AI 최적화 엔진 ON</span>
            <span>99.4% 정상</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
