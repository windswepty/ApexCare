import React, { useState, useEffect } from 'react';
import { Trash2, Search, AlertTriangle, CheckCircle, Loader2 } from 'lucide-react';
import { playSound } from '../utils/audio';

export default function Uninstaller() {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [leftovers, setLeftovers] = useState([]);
  const [isCleaning, setIsCleaning] = useState(false);
  const [activeApp, setActiveApp] = useState(null);
  const [step, setStep] = useState('list'); // 'list' -> 'leftovers'

  useEffect(() => {
    fetchApps();
  }, []);

  const fetchApps = async () => {
    setLoading(true);
    if (window.pywebview?.api) {
      try {
        const data = await window.pywebview.api.getUninstallerApps();
        setApps(data);
      } catch (e) {
        console.error(e);
      }
    }
    setLoading(false);
  };

  const handleUninstall = async (app) => {
    if (!window.pywebview?.api) return;
    playSound('click');
    
    // Launch standard uninstaller
    await window.pywebview.api.uninstallApp(app.uninstallString);
    
    // Show alert and transition to leftovers scan
    setActiveApp(app);
    setStep('leftovers');
    setIsCleaning(true);
    
    // Give user time to finish uninstaller visually
    setTimeout(async () => {
      const leftoverData = await window.pywebview.api.findAppLeftovers(app.name);
      setLeftovers(leftoverData);
      setIsCleaning(false);
    }, 5000); // 5 sec fake/real wait for uninstaller to spawn and run
  };

  const handleCleanLeftovers = async () => {
    if (!window.pywebview?.api) return;
    playSound('success');
    setIsCleaning(true);
    
    const paths = leftovers.map(l => l.path);
    const res = await window.pywebview.api.cleanAppLeftovers(paths);
    
    setIsCleaning(false);
    setStep('list');
    setActiveApp(null);
    setLeftovers([]);
    fetchApps(); // refresh list
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

      {step === 'leftovers' && (
        <div className="flex-1 flex flex-col items-center justify-center bg-white dark:bg-slate-900/30 rounded-xl border border-black/10 dark:border-slate-700/30 p-8 text-center">
          {isCleaning ? (
            <div className="flex flex-col items-center">
              <div className="relative mb-6">
                <div className="absolute inset-0 border-4 border-rose-500/20 rounded-full animate-ping"></div>
                <Loader2 className="w-16 h-16 text-rose-500 animate-spin relative z-10" />
              </div>
              <h3 className="text-xl font-bold text-black dark:text-white mb-2">잔여 파일 스캔 중...</h3>
              <p className="text-gray-500 dark:text-slate-400">
                {activeApp?.name} 프로그램의 찌꺼기를 추적하고 있습니다. (언인스톨러 창이 떴다면 먼저 삭제를 진행해주세요)
              </p>
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
