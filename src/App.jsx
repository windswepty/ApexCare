import React, { useState, useEffect, useRef } from 'react';
import Lenis from 'lenis';
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

  useEffect(() => {
    let checkInterval = setInterval(async () => {
      if (window.pywebview?.api && window.pywebview?.api.getSystemStats) {
        try {
          const stats = await window.pywebview?.api.getSystemStats();
          if (stats && stats.cpuModel !== 'Error') {
            setSystemStats(stats);
            setIsBackendReady(true);
            // Sync current active power plan mode from backend
            if (window.pywebview?.api.getOptimizationMode) {
              const res = await window.pywebview.api.getOptimizationMode();
              if (res && res.mode) {
                setCurrentMode(res.mode);
              }
            }
            clearInterval(checkInterval);
          }
        } catch (e) {}
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
      if (window.pywebview?.api && window.pywebview?.api.setOptimizationMode) {
        try {
          await window.pywebview?.api.setOptimizationMode(currentMode);
        } catch (e) {}
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
              {activeTab === 'dashboard' && (
                <Dashboard onNavigate={(tab) => setActiveTab(tab)} isDarkMode={isDarkMode} setIsDarkMode={setIsDarkMode} />
              )}
              {activeTab === 'cleaner' && <JunkCleaner />}
              {activeTab === 'ram' && <RamBooster />}
              {activeTab === 'startup' && <StartupManager />}
              {activeTab === 'defrag' && <DiskDefrag />}
              {activeTab === 'modes' && <PerformanceModes currentMode={currentMode} setCurrentMode={setCurrentMode} />}
              {activeTab === 'drivers' && <DriverUpdater />}
              {activeTab === 'uninstaller' && <Uninstaller />}
              {activeTab === 'fileFinder' && <FileFinder />}
              {activeTab === 'debloater' && <Debloater />}
              {activeTab === 'gamebooster' && <GameBooster />}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
