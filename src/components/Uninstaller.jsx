import React, { useState, useEffect } from 'react';
import { Trash2, Search, AlertTriangle, CheckCircle, Loader2 } from 'lucide-react';

export default function Uninstaller({ addToast }) {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [leftovers, setLeftovers] = useState([]);
  const [isCleaning, setIsCleaning] = useState(false);
  const [activeApp, setActiveApp] = useState(null);
  const [step, setStep] = useState('list'); // 'list' -> 'wait_uninstall' -> 'leftovers'

  const [cleanElapsed, setCleanElapsed] = useState(0);

  // 잔여물 찾기·정리는 진행률을 알 수 없다. 예전에는 1초마다 33%씩 올려 지어낸 진행률을 보였다. 경과 시간만 센다.
  useEffect(() => {
    let interval;
    if (isCleaning) {
      interval = setInterval(() => setCleanElapsed(t => t + 1), 1000);
    } else {
      setCleanElapsed(0);
    }
    return () => clearInterval(interval);
  }, [isCleaning]);

  useEffect(() => {
    const checkAndFetch = () => {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getUninstallerApps === 'function') {
        fetchApps();
      }
    };

    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getUninstallerApps === 'function') {
      checkAndFetch();
    } else {
      window.addEventListener('pywebviewready', checkAndFetch);
      return () => window.removeEventListener('pywebviewready', checkAndFetch);
    }
  }, []);

  const fetchApps = async () => {
    setLoading(true);
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getUninstallerApps === 'function') {
        const data = await window.pywebview.api.getUninstallerApps();
        if (Array.isArray(data)) {
          setApps(data);
        } else {
          setApps([]);
        }
      } else {
        console.warn('PyWebView API getUninstallerApps is not available yet.');
        setApps([]);
      }
    } catch (e) {
      console.error('Error fetching uninstaller apps:', e);
      setApps([]);
    } finally {
      setLoading(false);
    }
  };

  const handleUninstall = async (app) => {
    if (!window.pywebview?.api || typeof window.pywebview.api.uninstallApp !== 'function') {
      if (addToast) addToast("언인스톨러 API가 준비되지 않았습니다.", "error");
      return;
    }
    
    try {
      // Launch standard uninstaller
      const res = await window.pywebview.api.uninstallApp(app.uninstallString);
      if (res && res.success === false) {
          if (addToast) addToast(res.error || "언인스톨러 실행 실패", "error");
          return;
      }
      
      // Show alert and transition to waiting for user to finish
      setActiveApp(app);
      setStep('wait_uninstall');
    } catch (e) {
      console.error('IPC Error launching uninstaller:', e);
      if (addToast) addToast("언인스톨러 실행 중 시스템 오류가 발생했습니다.", "error");
    }
  };

  const handleScanLeftovers = async () => {
    if (!window.pywebview?.api || typeof window.pywebview.api.findAppLeftovers !== 'function' || !activeApp) return;
    setIsCleaning(true);
    setStep('leftovers');
    
    try {
      const leftoverData = await window.pywebview.api.findAppLeftovers(activeApp.name);
      setLeftovers(Array.isArray(leftoverData) ? leftoverData : []);
    } catch (e) {
      console.error('IPC Error scanning leftovers:', e);
      setLeftovers([]);
      if (addToast) addToast("찌꺼기 스캔 중 시스템 오류가 발생했습니다.", "error");
    } finally {
      setIsCleaning(false);
    }
  };

  const handleCleanLeftovers = async () => {
    if (!window.pywebview?.api || typeof window.pywebview.api.cleanAppLeftovers !== 'function') return;
    setIsCleaning(true);
    
    try {
      const paths = leftovers.map(l => l.path);
      const res = await window.pywebview.api.cleanAppLeftovers(paths);
      
      // 결과 그대로 알린다. 일부를 건너뛰었는데 '완벽 삭제' 라고 하지 않는다.
      const failedCount = Array.isArray(res?.failed) ? res.failed.length : 0;
      if (!res || res.success === false) {
          if (addToast) addToast(res?.message || res?.error || "잔여 폴더를 정리하지 못했습니다.", "error");
      } else if (failedCount > 0) {
          if (addToast) addToast(`[${activeApp.name}] ${res.message}`, 'error');
      } else {
          if (addToast) addToast(`[${activeApp.name}] ${res.message || '잔여 폴더를 휴지통으로 보냈습니다.'}`, 'success');
      }
    } catch (e) {
      console.error('IPC Error cleaning leftovers:', e);
      if (addToast) addToast("잔여 파일 삭제 중 시스템 오류가 발생했습니다.", "error");
    } finally {
      setIsCleaning(false);
      setStep('list');
      setActiveApp(null);
      setLeftovers([]);
      fetchApps(); // refresh list
    }
  };

  const skipLeftovers = () => {
    setStep('list');
    setActiveApp(null);
    setLeftovers([]);
    fetchApps();
  };

  const filteredApps = apps.filter(app => 
    app.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="h-full flex flex-col glass-panel rounded-2xl p-6 relative overflow-hidden">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-black dark:text-white flex items-center gap-2">
            <Trash2 className="w-6 h-6 text-rose-400" />
            프로그램 완전 삭제 (Advanced Uninstaller)
          </h2>
          <p className="text-gray-500 dark:text-slate-400 mt-1">
            프로그램을 삭제하고 숨어있는 레지스트리 및 찌꺼기 파일까지 완벽하게 제거합니다.
          </p>
        </div>
      </div>

      {step === 'list' && (
        <>
          <div className="relative mb-6">
            <Search className="w-5 h-5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 dark:text-slate-400" />
            <input
              type="text"
              placeholder="설치된 프로그램 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-white dark:bg-slate-900/50 border border-black/10 dark:border-slate-700/50 rounded-xl py-3 pl-10 pr-4 text-gray-800 dark:text-slate-200 focus:outline-none focus:border-rose-500/50 transition-colors"
            />
          </div>

          <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
            {loading ? (
              <div className="flex flex-col items-center justify-center h-full text-gray-500 dark:text-slate-400">
                <Loader2 className="w-8 h-8 animate-spin text-rose-500 mb-4" />
                <p>설치된 프로그램을 스캔 중입니다...</p>
              </div>
            ) : filteredApps.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-slate-500">
                <Trash2 className="w-12 h-12 mb-4 opacity-20" />
                <p>검색된 프로그램이 없습니다.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredApps.map((app) => (
                  <div key={app.id} className="flex items-center justify-between p-4 bg-white dark:bg-slate-900/40 hover:bg-gray-50 dark:bg-slate-800/60 border border-black/10 dark:border-slate-700/30 rounded-xl transition-colors group">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-gray-800 dark:text-slate-200 font-medium truncate">{app.name}</h3>
                      <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                        <span>{app.publisher || '게시자 알 수 없음'}</span>
                        {app.sizeMB > 0 && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-slate-600"></span>
                            <span className="text-rose-400/80">{app.sizeMB} MB</span>
                          </>
                        )}
                        {app.installDate && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-slate-600"></span>
                            <span>설치일: {app.installDate}</span>
                          </>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={() => handleUninstall(app)}
                      className="ml-4 px-4 py-2 bg-rose-500/10 text-rose-400 border border-rose-500/20 hover:bg-rose-500 hover:text-black dark:text-white rounded-lg transition-all duration-300 font-medium text-sm flex-shrink-0 flex items-center gap-2 opacity-0 group-hover:opacity-100 focus:opacity-100"
                    >
                      <Trash2 className="w-4 h-4" />
                      삭제
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {step === 'wait_uninstall' && (
        <div className="flex-1 flex flex-col items-center justify-center text-center max-w-lg mx-auto">
          <div className="w-20 h-20 rounded-full bg-amber-500/10 flex items-center justify-center mb-6 border border-amber-500/20">
            <Trash2 className="w-10 h-10 text-amber-500" />
          </div>
          <h3 className="text-xl font-bold text-black dark:text-white mb-2">
            [{activeApp?.name}] 언인스톨러 실행 중...
          </h3>
          <p className="text-gray-500 dark:text-slate-400 mb-8">
            화면에 표시된 윈도우 기본 제거 프로그램의 안내에 따라 삭제를 완전히 완료해주세요. 삭제가 끝나면 아래 버튼을 눌러 찌꺼기 파일을 스캔합니다.
          </p>
          
          <div className="flex gap-4">
            <button
              onClick={skipLeftovers}
              className="px-6 py-3 bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-300 rounded-xl hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors font-medium text-sm"
            >
              건너뛰기
            </button>
            <button
              onClick={handleScanLeftovers}
              className="px-6 py-3 bg-rose-500 text-white rounded-xl hover:bg-rose-600 shadow-lg shadow-rose-500/20 transition-all font-medium text-sm flex items-center gap-2"
            >
              <Search className="w-4 h-4" />
              삭제 완료! 찌꺼기 스캔하기
            </button>
          </div>
        </div>
      )}

      {step === 'leftovers' && (
        <div className="flex-1 flex flex-col items-center justify-center bg-white dark:bg-slate-900/30 rounded-xl border border-black/10 dark:border-slate-700/30 p-8 text-center">
          {isCleaning ? (
            <div className="flex flex-col items-center w-full max-w-md mx-auto">
              <div className="relative mb-6">
                <div className="absolute inset-0 border-4 border-rose-500/20 rounded-full animate-ping"></div>
                <Loader2 className="w-16 h-16 text-rose-500 animate-spin relative z-10" />
              </div>
              <h3 className="text-xl font-bold text-black dark:text-white mb-2">잔여 파일 스캔/제거 중...</h3>
              <p className="text-gray-500 dark:text-slate-400 mb-6">
                {activeApp?.name} 프로그램의 찌꺼기를 추적하고 있습니다. (언인스톨러 창이 떴다면 먼저 삭제를 진행해주세요)
              </p>
              
              <div className="w-full bg-black/5 dark:bg-black/40 border border-black/10 dark:border-white/5 rounded-xl p-4 flex flex-col gap-3">
                <div className="flex items-center justify-between text-rose-500 dark:text-rose-400 font-mono text-sm">
                  <span>진행 중</span>
                  <div className="text-right">
                    <span className="font-bold">경과 {cleanElapsed}초</span>
                  </div>
                </div>
                <div className="relative w-full bg-slate-200 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
                  <div className="absolute inset-y-0 w-1/3 bg-rose-400 rounded-full animate-indeterminate motion-reduce:w-full motion-reduce:opacity-40"></div>
                </div>
              </div>
            </div>
          ) : (
            <div className="w-full max-w-2xl text-left">
              <div className="flex items-center justify-center gap-3 mb-6">
                {leftovers.length > 0 ? (
                  <AlertTriangle className="w-10 h-10 text-amber-500" />
                ) : (
                  <CheckCircle className="w-10 h-10 text-emerald-500" />
                )}
                <h3 className="text-2xl font-bold text-black dark:text-white">
                  {leftovers.length > 0 ? '잔여 파일이 발견되었습니다!' : '잔여 파일이 없습니다.'}
                </h3>
              </div>
              
              {leftovers.length > 0 && (
                <div className="bg-gray-100 dark:bg-slate-950/50 rounded-xl border border-amber-500/30 p-4 mb-6 max-h-[300px] overflow-y-auto custom-scrollbar">
                  <p className="text-amber-400/80 text-sm mb-3">발견된 찌꺼기 폴더 및 레지스트리 추정 목록:</p>
                  <ul className="space-y-2">
                    {leftovers.map((l, i) => (
                      <li key={i} className="text-xs font-mono text-gray-700 dark:text-slate-300 bg-white dark:bg-slate-900 p-2 rounded border border-black/10 dark:border-slate-800 flex justify-between">
                        <span className="truncate mr-4">{l.path}</span>
                        <span className="text-rose-400 flex-shrink-0">{l.sizeMB} MB</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              
              <div className="flex justify-center gap-4">
                <button
                  onClick={skipLeftovers}
                  className="px-6 py-2.5 bg-gray-50 dark:bg-slate-800 hover:bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300 rounded-xl transition-colors font-medium"
                >
                  돌아가기
                </button>
                {leftovers.length > 0 && (
                  <button
                    onClick={handleCleanLeftovers}
                    className="px-6 py-2.5 bg-gradient-to-r from-rose-600 to-rose-500 hover:from-rose-500 hover:to-rose-400 text-black dark:text-white rounded-xl transition-all shadow-lg shadow-rose-500/25 font-medium flex items-center gap-2"
                  >
                    <Trash2 className="w-4 h-4" />
                    찌꺼기 완전 삭제
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
