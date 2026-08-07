import React, { useState, useEffect } from 'react';
import { 
  Rocket, 
  Zap, 
  Power
} from 'lucide-react';
import { playSound } from '../utils/audio';

export default function StartupManager({ addToast }) {
  const [startupApps, setStartupApps] = useState([]);

  useEffect(() => {
    const fetchStartup = async () => {
      if (window.pywebview?.api && window.pywebview?.api.getStartupApps) {
        try {
          const raw_data = await window.pywebview?.api.getStartupApps();
          const apps = typeof raw_data === 'string' ? JSON.parse(raw_data) : raw_data;
          if (apps && apps.length > 0) {
            setStartupApps(apps);
          }
        } catch (e) {}
      }
    };
    fetchStartup();
  }, []);

  const toggleApp = async (id, appName) => {
    playSound('toggle');
    const app = startupApps.find(a => a.id === id);
    if (!app) return;
    const newEnabled = !app.enabled;
    
    // Optimistically update UI
    setStartupApps(startupApps.map(a => 
      a.id === id ? { ...a, enabled: newEnabled } : a
    ));

    if (window.pywebview?.api && window.pywebview?.api.toggleStartupApp) {
      try {
        const res = await window.pywebview?.api.toggleStartupApp(appName, newEnabled);
        if (!res?.success) {
          throw new Error('Failed to toggle');
        }
        if (addToast) addToast(`[${appName}] 시작 프로그램 상태가 변경되었습니다.`, 'success');
      } catch (e) {
        // Revert on failure
        alert(`시작 프로그램(${appName}) 상태 변경에 실패했습니다. 권한을 확인해주세요.`);
        setStartupApps(startupApps.map(a => 
          a.id === id ? { ...a, enabled: !newEnabled } : a
        ));
      }
    }
  };

  const disableAllHighImpact = async () => {
    playSound('boost');
    
    const appsToDisable = startupApps.filter(app => app.impact === 'High' && app.enabled);
    
    // Optimistically update UI
    setStartupApps(startupApps.map(app => 
      app.impact === 'High' ? { ...app, enabled: false } : app
    ));

    for (const app of appsToDisable) {
      if (window.pywebview?.api && window.pywebview?.api.toggleStartupApp) {
        try {
          const res = await window.pywebview?.api.toggleStartupApp(app.name, false);
          if (!res?.success) {
            allSuccess = false;
          }
        } catch (e) {
          allSuccess = false;
        }
      }
    }

    if (!allSuccess) {
      // Revert on failure
      setStartupApps(prev => prev.map(app => 
        appsToDisable.some(a => a.id === app.id) ? { ...app, enabled: true } : app
      ));
      if (addToast) addToast('높은 영향도의 시작 프로그램 비활성화에 실패했습니다.', 'error');
    } else {
      if (addToast) addToast('모든 무거운 시작 프로그램이 비활성화되었습니다!', 'success');
    }
  };

  // Calculate total enabled boot time impact
  const enabledApps = startupApps.filter(a => a.enabled);
  const currentBootSec = (8.5 + enabledApps.length * 1.4).toFixed(1);

  return (
    <div className="space-y-6">
      {/* Header Overview Card */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold mb-1">
            <Rocket className="w-4 h-4" />
            WINDOWS BOOT TIME ACCELERATOR
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">시작 프로그램 관리</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
            윈도우 부팅 시 불필요하게 자동 실행되는 프로그램을 차단하여 부팅 속도를 획기적으로 개선합니다.
          </p>
        </div>

        <button
          onClick={disableAllHighImpact}
          className="btn-secondary text-xs border-amber-500/40 hover:bg-amber-500/10 text-amber-300 px-5 py-3"
        >
          <Zap className="w-4 h-4 text-amber-400" />
          <span>고부하 시작 프로그램 일괄 비활성화</span>
        </button>
      </div>

      {/* Boot Speed Comparison Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="glass-panel p-4 text-center">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">현재 예상 부팅 시간</span>
          <div className="text-3xl font-black font-mono text-amber-400 my-1">{currentBootSec} 초</div>
          <span className="text-[10px] text-slate-500 font-mono">활성 앱 {enabledApps.length}개</span>
        </div>

        <div className="glass-panel p-4 text-center">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">최적화 목표 부팅 시간</span>
          <div className="text-3xl font-black font-mono text-emerald-400 my-1">8.5 초</div>
          <span className="text-[10px] text-emerald-300 font-mono">52% 속도 향상 가용한 상태</span>
        </div>

        <div className="glass-panel p-4 text-center">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">단축 가능 시간</span>
          <div className="text-3xl font-black font-mono text-cyan-400 my-1">
            +{(currentBootSec - 8.5).toFixed(1)} 초
          </div>
          <span className="text-[10px] text-slate-500 font-mono">High Impact 차단 시</span>
        </div>
      </div>

      {/* Startup Applications List */}
      <div className="glass-panel p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-gray-900 dark:text-slate-100 text-sm">
            등록된 부팅 시작 프로그램 목록 ({startupApps.length})
          </h3>
          <span className="text-xs text-gray-500 dark:text-slate-400 font-mono">영향도 순</span>
        </div>

        <div className="space-y-2">
          {startupApps.map((app) => (
            <div
              key={app.id}
              className={`p-4 rounded-xl border transition-all duration-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 ${
                app.enabled
                  ? 'bg-white dark:bg-slate-900/60 border-black/10 dark:border-slate-800'
                  : 'bg-gray-100 dark:bg-slate-950/40 border-black/10 dark:border-slate-900 opacity-60'
              }`}
            >
              <div className="flex items-center gap-3.5 min-w-0 flex-1">
                <div className={`p-2.5 rounded-lg flex-shrink-0 font-mono text-xs ${
                  app.enabled ? 'bg-cyan-500/10 text-cyan-400' : 'bg-gray-50 dark:bg-slate-800 text-slate-500'
                }`}>
                  <Power className="w-4 h-4" />
                </div>

                <div className="min-w-0 flex-1 pr-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-900 dark:text-slate-100 text-sm truncate">{app.name}</span>
                    <span className={`badge flex-shrink-0 ${
                      app.impact === 'High' ? 'badge-high' : app.impact === 'Medium' ? 'badge-medium' : 'badge-low'
                    }`}>
                      {app.impact} Impact
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5 truncate w-full" title={app.publisher}>
                    제조사: {app.publisher} • 부팅 영향: <span className="font-mono text-gray-700 dark:text-slate-300">{app.bootTimeImpact}</span>
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-4 self-end sm:self-center">
                {/* Enable/Disable Toggle */}
                <div 
                  onClick={() => toggleApp(app.id, app.name)} 
                  className={`toggle-switch ${app.enabled ? 'active' : ''}`}
                >
                  <div className="toggle-thumb"></div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
