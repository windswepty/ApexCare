import { useRef, useEffect } from 'react';
import { attachSmoothScroll } from '../smoothScroll';
import AppLogo from './AppLogo';
import {
  LayoutDashboard,
  Cpu,
  Rocket,
  HardDrive,
  Zap,
  ShieldCheck,
  PackageMinus,
  ServerCrash,
  Crosshair,
  History
} from 'lucide-react';
// 버전은 package.json 한 곳에서 온다(설치 마법사 APP_VERSION 과 테스트가 맞춰 본다).
// 예전에는 여기에 버전 번호를 직접 적어, 버전을 올려도 화면에는 옛 번호가 남을 수 있었다.
import { version as APP_VERSION } from '../../package.json';

export default function Sidebar({ activeTab, setActiveTab }) {
  const sidebarWrapperRef = useRef(null);

  useEffect(() => {
    if (!sidebarWrapperRef.current) return;
    return attachSmoothScroll(sidebarWrapperRef.current, sidebarWrapperRef.current.firstElementChild);
  }, []);

  const menuItems = [
    { id: 'dashboard', label: '대시보드', icon: LayoutDashboard },
    // 정크·대용량 탐색·조각모음을 하나의 '저장공간' 탭으로 합쳤다.
    // 세 곳에 흩어져 있어 사용자가 '지금 디스크 상태가 어떤지' 볼 방법이 없었다.
    { id: 'storage', label: '저장공간 정리', icon: HardDrive },
    { id: 'ram', label: 'RAM 메모리 최적화', icon: Cpu },
    { id: 'startup', label: '시작 프로그램 관리', icon: Rocket },
    // '완전 삭제' 는 사실이 아니었다. 제거 프로그램을 실행하고 남은 폴더를 휴지통으로 보낼 뿐이다.
    { id: 'uninstaller', label: '프로그램 삭제', icon: PackageMinus },
    { id: 'modes', label: '성능 부스트 모드', icon: Zap },
    { id: 'gamebooster', label: '스마트 게임 부스터', icon: Crosshair },
    { id: 'drivers', label: '시스템 파일 복구', icon: ShieldCheck },
    // 예전 이름 '윈도우 하드코어 적출' 은 과장이었다. 기본 앱을 이 계정에서 제거하고 정책 두 개를 바꾼다.
    { id: 'debloater', label: 'Windows 기본 앱 정리', icon: ServerCrash },
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
          <AppLogo className="w-10 h-10" />
          <div>
            <h1 className="font-extrabold text-lg tracking-tight text-black dark:text-white flex items-center gap-1.5 transition-colors duration-300">
              APEX <span className="text-gray-500 dark:text-gray-400">CARE</span>
            </h1>
            <p className="text-xs text-gray-500 dark:text-gray-400 font-mono transition-colors duration-300">v{APP_VERSION}</p>
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
                aria-current={isActive ? 'page' : undefined}
                onClick={() => {
                  setActiveTab(item.id);
                }}
                className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl transition-all duration-300 text-sm font-medium ${
                  isActive
                    ? 'bg-black dark:bg-white text-white dark:text-black shadow-md'
                    : 'text-gray-600 dark:text-gray-400 hover:text-black dark:hover:text-white hover:bg-gray-100 dark:hover:bg-zinc-800 border border-transparent'
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
