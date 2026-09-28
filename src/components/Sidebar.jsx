import React, { useRef, useEffect } from 'react';
import { attachSmoothScroll } from '../smoothScroll';
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
  Crosshair,
  History
} from 'lucide-react';

export default function Sidebar({ activeTab, setActiveTab }) {
  const sidebarWrapperRef = useRef(null);

  useEffect(() => {
    if (!sidebarWrapperRef.current) return;
    return attachSmoothScroll(sidebarWrapperRef.current, sidebarWrapperRef.current.firstElementChild);
  }, []);

  const menuItems = [
    { id: 'dashboard', label: '대시보드 (Dashboard)', icon: LayoutDashboard },
    // 정크·대용량 탐색·조각모음을 하나의 '저장공간' 탭으로 합쳤다.
    // 세 곳에 흩어져 있어 사용자가 '지금 디스크 상태가 어떤지' 볼 방법이 없었다.
    { id: 'storage', label: '저장공간 정리', icon: HardDrive },
    { id: 'ram', label: 'RAM 메모리 최적화', icon: Cpu },
    { id: 'startup', label: '시작 프로그램 관리', icon: Rocket },
    { id: 'uninstaller', label: '프로그램 완전 삭제', icon: PackageMinus },
    { id: 'modes', label: '성능 부스트 모드', icon: Zap },
    { id: 'gamebooster', label: '스마트 게임 부스터', icon: Crosshair },
    { id: 'drivers', label: 'OS 코어 복구 (SFC/DISM)', icon: ShieldCheck },
    { id: 'debloater', label: '윈도우 하드코어 적출', icon: ServerCrash },
    // 이 프로그램이 바꾼 모든 것을 확인하고 되돌리는 곳.
    // 복구 기능이 백엔드에만 있고 UI 가 없으면 사실상 되돌릴 수 없는 것과 같다.
    { id: 'restore', label: '변경 내역 · 되돌리기', icon: History },
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
            <p className="text-xs text-gray-500 dark:text-gray-400 font-mono transition-colors duration-300">v1.0.1</p>
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

        {/* 예전에는 여기 '실시간 엔진 상태 ACTIVE · AI 최적화 엔진 ON · 99.4% 정상' 과
            88% 막대가 고정값으로 박혀 있었다. 뒷받침하는 기능이 없어 뺐다. */}
      </div>
    </aside>
  );
}
