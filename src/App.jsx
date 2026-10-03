import { useState, useEffect, useRef, useCallback } from 'react';
import { attachSmoothScroll } from './smoothScroll';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';
import TitleBar from './components/TitleBar';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import Dashboard from './components/Dashboard';
import StorageCenter from './components/StorageCenter';
import RestoreCenter from './components/RestoreCenter';
import RamBooster from './components/RamBooster';
import StartupManager from './components/StartupManager';
import PerformanceModes from './components/PerformanceModes';
import DriverUpdater from './components/DriverUpdater';
import Uninstaller from './components/Uninstaller';
import Debloater from './components/Debloater';
import GameBooster from './components/GameBooster';
import LoadingScreen from './components/LoadingScreen';
import InitialSetupWizard from './components/InitialSetupWizard';
import ErrorBoundary from './components/ErrorBoundary';
import SettingsModal from './components/SettingsModal';
import { applyTheme, applyDisplay, applyIcon, isIconSetting, syncWindowIcon, cachedAppearance } from './theme';

export default function App() {
  const scrollWrapperRef = useRef(null);
  const scrollContentRef = useRef(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  // 탭은 처음 열 때 띄우고, 한 번 연 탭은 상태를 지키려고 숨겨 둔다. 예전에는 열지 않은 탭까지
  // 앱을 켜자마자 전부 띄워 각자 백엔드를 불렀다(프로그램 목록·시작 프로그램·드라이브 조회 등).
  const [visitedTabs, setVisitedTabs] = useState(() => new Set(['dashboard']));
  useEffect(() => {
    setVisitedTabs(prev => (prev.has(activeTab) ? prev : new Set(prev).add(activeTab)));
  }, [activeTab]);
  const isMounted = (tab) => tab === activeTab || visitedTabs.has(tab);
  const [currentMode, setCurrentMode] = useState('standard');
  const [isDarkMode] = useState(true);
  const [showLoading, setShowLoading] = useState(true);
  const [isBackendReady, setIsBackendReady] = useState(false);
  // 초기 설정 마법사는 첫 실행 때만 띄운다. 백엔드에서 기록을 읽기 전에는 띄우지 않는다.
  // 예전에는 useState(true) 라 앱을 켤 때마다 떴다.
  const [showInitialWizard, setShowInitialWizard] = useState(false);
  const [systemStats, setSystemStats] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  // 색 조합과 직접 고른 강조색(저장된 값). main.jsx 가 캐시 값으로 먼저 적용해 둔다.
  const [appearance, setAppearance] = useState(cachedAppearance);

  // 같은 밀리초에 알림이 둘 뜨면 Date.now() 가 같아 하나를 닫을 때 둘 다 사라졌다. 순번을 쓴다.
  const toastSeq = useRef(0);
  const addToast = useCallback((message, type = 'success') => {
    toastSeq.current += 1;
    const id = toastSeq.current;
    setToasts(prev => {
      // Prevent identical messages from stacking up
      if (prev.some(t => t.message === message)) return prev;
      return [...prev, { id, message, type }];
    });
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 10000);
  }, []);

  // 마법사를 닫으면(건너뛰기·적용 후 계속 모두) 다시 띄우지 않도록 기록한다.
  const closeSetupWizard = async () => {
    setShowInitialWizard(false);
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.markSetupWizardDone !== 'function') return;
    try {
      const res = await api.markSetupWizardDone();
      if (!res?.success) addToast(res?.message || '마법사 완료 기록을 저장하지 못했습니다.', 'error');
    } catch (e) {
      addToast(`마법사 완료 기록을 저장하지 못했습니다: ${e}`, 'error');
    }
  };

  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

  useEffect(() => {
    let checkInterval = setInterval(async () => {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getSystemStats === 'function') {
        try {
          const stats = await window.pywebview.api.getSystemStats();
          // 백엔드가 답했으면(통계를 못 읽어 error 여도) 준비된 것이다. 예전에는 error 면 영원히 다시 묻기만 해서,
          // 통계 하나를 못 읽는 PC 에서는 로딩 화면이 걷히지 않아 '되돌리기' 를 포함한 앱 전체를 쓸 수 없었다.
          // 각 화면은 값이 없으면 '측정 중·모름' 으로 보여 준다.
          if (stats) {
            // 대시보드가 잠깐 보였다 마법사로 바뀌지 않도록 준비 완료 전에 먼저 확인한다.
            // 읽지 못하면 띄우지 않는다(마법사의 튜닝은 선택 사항이고, 설정 창에서 다시 열 수 있다).
            if (typeof window.pywebview.api.getSetupWizardDone === 'function') {
              try {
                const done = await window.pywebview.api.getSetupWizardDone();
                if (done === false) setShowInitialWizard(true);
              } catch (e) {
                console.error('Error reading setup wizard state:', e);
              }
            }
            setSystemStats(stats.error ? {} : stats);
            setIsBackendReady(true);
            // 저장된 색 설정을 기준으로 다시 맞춘다(캐시와 다를 수 있다).
            if (typeof window.pywebview.api.getUiAppearance === 'function') {
              try {
                const saved = await window.pywebview.api.getUiAppearance();
                const applied = applyTheme(saved?.theme, saved?.accent, saved?.background);
                const display = applyDisplay({ scale: saved?.scale, reduceMotion: saved?.reduceMotion });
                const icon = isIconSetting(saved?.icon) ? (saved.icon || '') : '';
                const colors = applyIcon(icon, applied.id, saved?.accent, saved?.background);
                if (icon) syncWindowIcon(icon, colors);       // 기본이면 창 아이콘은 원래 것 그대로
                setAppearance({ id: applied.id, accent: saved?.accent || null, background: saved?.background || null, icon, ...display });
              } catch (e) {
                console.error('Error loading UI appearance:', e);
              }
            }
            // Sync current active power plan mode from backend
            if (typeof window.pywebview.api.getOptimizationMode === 'function') {
              const res = await window.pywebview.api.getOptimizationMode();
              if (res && res.mode) {
                setCurrentMode(res.mode);
              }
            }
            clearInterval(checkInterval);
          }
        } catch (e) {
          console.error('Error checking backend readiness:', e);
        }
      }
    }, 200);
    return () => clearInterval(checkInterval);
  }, []);

  // Force dark class on HTML element permanently
  useEffect(() => {
    document.documentElement.classList.add('dark');
    document.body.classList.add('dark');
  }, []);

  // 모드 적용은 PerformanceModes 컴포넌트가 직접 한다.
  //
  // 예전에는 currentMode 가 바뀌면 이 useEffect 가 백엔드를 호출했는데,
  // 반환값을 await 만 하고 버려서 실패를 알 방법이 없었다. 게다가 상태 변경을
  // 부수효과로 시스템을 바꾸는 구조라 어디서 setCurrentMode 를 불러도
  // 의도치 않게 OS 설정이 바뀌었다. 이제 setCurrentMode 는 화면 표시만 담당한다.

  useEffect(() => {
    if (!scrollWrapperRef.current || !scrollContentRef.current) return;
    return attachSmoothScroll(scrollWrapperRef.current, scrollContentRef.current);
  }, []);
  return (
    <ErrorBoundary>
        <div className="h-screen w-screen bg-white dark:bg-black text-black dark:text-white flex flex-col selection:bg-black selection:text-white dark:selection:bg-white dark:selection:text-black relative overflow-hidden">
          
          {showInitialWizard ? (
            <InitialSetupWizard 
              stats={systemStats} 
              isDarkMode={isDarkMode} 
              // 마법사를 닫기만 한다. 예전에는 여기서 setOptimizationMode('standard') 를 불러,
              // '건너뛰기 (적용 안함)' 을 눌러도 앱을 켤 때마다 사용자가 고른 게이밍·에코 모드를
              // 표준으로 되돌리고 전원 플랜을 바꿨다. 마법사에는 이제 모드 선택이 없다.
              onComplete={closeSetupWizard}
            />
          ) : showLoading ? (
            <LoadingScreen 
              isAppReady={isBackendReady} 
              onComplete={() => setShowLoading(false)} 
              isDarkMode={isDarkMode}
            />
          ) : null}

          {/* Desktop Native TitleBar — 로딩 화면·초기 설정·오버레이 위에 둔다. 창 테두리가 없어(frameless) 이것이 가려지면
              창을 닫거나 옮길 방법이 없다. */}
          <div className="relative z-[60] flex-shrink-0">
            <TitleBar onOpenSettings={() => setIsSettingsOpen(true)} />
          </div>

          {/* Settings Modal */}
          <SettingsModal 
            isOpen={isSettingsOpen} 
            onClose={() => setIsSettingsOpen(false)} 
            addToast={addToast}
            onOpenSetupWizard={() => { setIsSettingsOpen(false); setShowInitialWizard(true); }}
            appearance={appearance}
            onAppearanceChange={setAppearance}
          />

          {/* Main Desktop Window Body */}
      <div className="flex flex-1 min-h-0">
        {/* Left Sidebar */}
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} isDarkMode={isDarkMode} />

        {/* Main Content Area Wrapper */}
        <div className="flex-1 flex flex-col relative z-20 min-w-0">
          
          {/* Fixed Header */}
          <div className="pt-6 px-6 flex-shrink-0 z-30">
            <Header />
          </div>

          {/* Scrollable Content */}
          <main ref={scrollWrapperRef} className="flex-1 overflow-y-auto px-6 pb-6 flex flex-col">
            <div ref={scrollContentRef} className="flex flex-col flex-1">
              <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none', height: '100%' }}>
                {isMounted('dashboard') && <ErrorBoundary compact><Dashboard active={activeTab === 'dashboard'} addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'restore' ? 'block' : 'none', height: '100%' }}>
                {isMounted('restore') && <ErrorBoundary compact><RestoreCenter active={activeTab === 'restore'} addToast={addToast} /></ErrorBoundary>}
              </div>

              <div style={{ display: activeTab === 'storage' ? 'block' : 'none', height: '100%' }}>
                {isMounted('storage') && <ErrorBoundary compact><StorageCenter active={activeTab === 'storage'} addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'ram' ? 'block' : 'none', height: '100%' }}>
                {isMounted('ram') && <ErrorBoundary compact><RamBooster active={activeTab === 'ram'} addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'startup' ? 'block' : 'none', height: '100%' }}>
                {isMounted('startup') && <ErrorBoundary compact><StartupManager active={activeTab === 'startup'} addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'modes' ? 'block' : 'none', height: '100%' }}>
                {isMounted('modes') && <ErrorBoundary compact><PerformanceModes active={activeTab === 'modes'} currentMode={currentMode} setCurrentMode={setCurrentMode} addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'drivers' ? 'block' : 'none', height: '100%' }}>
                {isMounted('drivers') && <ErrorBoundary compact><DriverUpdater addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'uninstaller' ? 'block' : 'none', height: '100%' }}>
                {isMounted('uninstaller') && <ErrorBoundary compact><Uninstaller addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'debloater' ? 'block' : 'none', height: '100%' }}>
                {isMounted('debloater') && <ErrorBoundary compact><Debloater addToast={addToast} /></ErrorBoundary>}
              </div>
              <div style={{ display: activeTab === 'gamebooster' ? 'block' : 'none', height: '100%' }}>
                {isMounted('gamebooster') && <ErrorBoundary compact><GameBooster active={activeTab === 'gamebooster'} addToast={addToast} /></ErrorBoundary>}
              </div>
            </div>
          </main>
        </div>
      </div>

      {/* Global Toast Container */}
      {/* 결과 알림을 스크린 리더도 읽는다. 실패는 바로 알린다(alert). */}
      <div className="fixed top-20 right-6 z-[100] flex flex-col gap-3 pointer-events-none w-80" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} role={toast.type === 'error' ? 'alert' : undefined} className="pointer-events-auto bg-white dark:bg-slate-900 border border-black/10 dark:border-slate-800 shadow-2xl rounded-2xl p-4 flex items-start gap-3 animate-in slide-in-from-right-8 fade-in duration-300">
            {toast.type === 'success' && <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />}
            {toast.type === 'error' && <AlertCircle className="w-5 h-5 text-rose-500 shrink-0 mt-0.5" />}
            {toast.type === 'info' && <Info className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />}
            <div className="flex-1">
              <p className="text-sm font-semibold text-gray-800 dark:text-slate-200">
                {toast.message}
              </p>
            </div>
            <button onClick={() => removeToast(toast.id)} aria-label="알림 닫기" className="shrink-0 p-1 bg-gray-100 hover:bg-gray-200 dark:bg-slate-800 dark:hover:bg-slate-700 rounded-full transition-colors text-gray-500">
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>

    </div>
    </ErrorBoundary>
  );
}
