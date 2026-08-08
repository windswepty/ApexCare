import React, { useState, useEffect, useRef, useCallback } from 'react';
import Lenis from 'lenis';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';
import TitleBar from './components/TitleBar';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import Dashboard from './components/Dashboard';
import JunkCleaner from './components/JunkCleaner';
import RamBooster from './components/RamBooster';
import StartupManager from './components/StartupManager';
import DiskDefrag from './components/DiskDefrag';
import PerformanceModes from './components/PerformanceModes';
import DriverUpdater from './components/DriverUpdater';
import Uninstaller from './components/Uninstaller';
import FileFinder from './components/FileFinder';
import Debloater from './components/Debloater';
import GameBooster from './components/GameBooster';
import LoadingScreen from './components/LoadingScreen';
import InitialSetupWizard from './components/InitialSetupWizard';
import { JunkProvider } from './context/JunkContext';
import ErrorBoundary from './components/ErrorBoundary';

export default function App() {
  const scrollWrapperRef = useRef(null);
  const scrollContentRef = useRef(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [currentMode, setCurrentMode] = useState('standard');
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [showLoading, setShowLoading] = useState(true);
  const [isBackendReady, setIsBackendReady] = useState(false);
  const [showInitialWizard, setShowInitialWizard] = useState(() => localStorage.getItem('isFirstRunComplete') !== 'true');
  const [systemStats, setSystemStats] = useState(null);
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'success') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 10000);
  }, []);

  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

  useEffect(() => {
    let checkInterval = setInterval(async () => {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getSystemStats === 'function') {
        try {
          const stats = await window.pywebview.api.getSystemStats();
          if (stats && stats.cpuModel !== 'Error') {
            setSystemStats(stats);
            setIsBackendReady(true);
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

  const modeInitialized = useRef(false);
  useEffect(() => {
    if (!modeInitialized.current) {
      modeInitialized.current = true;
      return; // Skip first render - initial mode is loaded from backend
    }
    const applyMode = async () => {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.setOptimizationMode === 'function') {
        try {
          await window.pywebview.api.setOptimizationMode(currentMode);
        } catch (e) {
          console.error('Error setting optimization mode:', e);
        }
      }
    };
    applyMode();
  }, [currentMode]);

  useEffect(() => {
    if (!scrollWrapperRef.current || !scrollContentRef.current) return;

    const lenis = new Lenis({
      wrapper: scrollWrapperRef.current,
      content: scrollContentRef.current,
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
  return (
    <ErrorBoundary>
      <JunkProvider addToast={addToast}>
        <div className="h-screen w-screen bg-white dark:bg-black text-black dark:text-white flex flex-col selection:bg-black selection:text-white dark:selection:bg-white dark:selection:text-black relative overflow-hidden">
          
          {showInitialWizard ? (
            <InitialSetupWizard 
              stats={systemStats} 
              isDarkMode={isDarkMode} 
              onComplete={(selectedMode) => {
                setCurrentMode(selectedMode);
                localStorage.setItem('isFirstRunComplete', 'true');
                setShowInitialWizard(false);
              }} 
            />
          ) : showLoading ? (
            <LoadingScreen 
              isAppReady={isBackendReady} 
              onComplete={() => setShowLoading(false)} 
              isDarkMode={isDarkMode}
            />
          ) : null}

          {/* Desktop Native TitleBar */}
          <div className="relative z-20 flex-shrink-0">
            <TitleBar />
          </div>

          {/* Main Desktop Window Body */}
      <div className="flex flex-1 min-h-0">
        {/* Left Sidebar */}
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} isDarkMode={isDarkMode} />

        {/* Main Content Area Wrapper */}
        <div className="flex-1 flex flex-col relative z-20 min-w-0">
          
          {/* Fixed Header */}
          <div className="pt-6 px-6 flex-shrink-0 z-30">
            <Header 
              currentMode={currentMode} 
              setCurrentMode={setCurrentMode} 
              isDarkMode={isDarkMode}
              setIsDarkMode={setIsDarkMode}
            />
          </div>

          {/* Scrollable Content */}
          <main ref={scrollWrapperRef} className="flex-1 overflow-y-auto px-6 pb-6 flex flex-col">
            <div ref={scrollContentRef} className="flex flex-col flex-1">
              <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none', height: '100%' }}>
                <Dashboard onNavigate={(tab) => setActiveTab(tab)} isDarkMode={isDarkMode} setIsDarkMode={setIsDarkMode} addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'cleaner' ? 'block' : 'none', height: '100%' }}>
                <JunkCleaner addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'ram' ? 'block' : 'none', height: '100%' }}>
                <RamBooster addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'startup' ? 'block' : 'none', height: '100%' }}>
                <StartupManager addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'defrag' ? 'block' : 'none', height: '100%' }}>
                <DiskDefrag addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'modes' ? 'block' : 'none', height: '100%' }}>
                <PerformanceModes currentMode={currentMode} setCurrentMode={setCurrentMode} addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'drivers' ? 'block' : 'none', height: '100%' }}>
                <DriverUpdater addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'uninstaller' ? 'block' : 'none', height: '100%' }}>
                <Uninstaller addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'fileFinder' ? 'block' : 'none', height: '100%' }}>
                <FileFinder addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'debloater' ? 'block' : 'none', height: '100%' }}>
                <Debloater addToast={addToast} />
              </div>
              <div style={{ display: activeTab === 'gamebooster' ? 'block' : 'none', height: '100%' }}>
                <GameBooster addToast={addToast} />
              </div>
            </div>
          </main>
        </div>
      </div>

      {/* Global Toast Container */}
      <div className="fixed top-20 right-6 z-[100] flex flex-col gap-3 pointer-events-none w-80">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto bg-white dark:bg-slate-900 border border-black/10 dark:border-slate-800 shadow-2xl rounded-2xl p-4 flex items-start gap-3 animate-in slide-in-from-right-8 fade-in duration-300">
            {toast.type === 'success' && <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />}
            {toast.type === 'error' && <AlertCircle className="w-5 h-5 text-rose-500 shrink-0 mt-0.5" />}
            {toast.type === 'info' && <Info className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" />}
            <div className="flex-1">
              <p className="text-sm font-semibold text-gray-800 dark:text-slate-200">
                {toast.message}
              </p>
            </div>
            <button onClick={() => removeToast(toast.id)} className="shrink-0 p-1 bg-gray-100 hover:bg-gray-200 dark:bg-slate-800 dark:hover:bg-slate-700 rounded-full transition-colors text-gray-500">
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
      
    </div>
    </JunkProvider>
    </ErrorBoundary>
  );
}
