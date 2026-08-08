import React, { useEffect } from 'react';
import { 
  Trash2, 
  CheckSquare, 
  Square, 
  RefreshCw, 
  Sparkles, 
  CheckCircle2 
} from 'lucide-react';
import { useJunk } from '../context/JunkContext';

export default function JunkCleaner() {
  const {
    items, isScanning, isCleaning, cleanProgress, cleanEta, hasScannedOnce,
    cleanedSuccess, freedMB, rescanJunk, startClean, toggleItem, selectAll, deselectAll,
    setCleanedSuccess
  } = useJunk();

  useEffect(() => {
    const checkAndScan = () => {
      if (!hasScannedOnce && window.pywebview && window.pywebview.api && typeof window.pywebview.api.scanJunk === 'function') {
        rescanJunk();
      }
    };

    if (!hasScannedOnce && window.pywebview && window.pywebview.api && typeof window.pywebview.api.scanJunk === 'function') {
      checkAndScan();
    } else if (!hasScannedOnce) {
      window.addEventListener('pywebviewready', checkAndScan);
      return () => window.removeEventListener('pywebviewready', checkAndScan);
    }
  }, [hasScannedOnce, rescanJunk]);

  const totalSelectedMB = items
    .filter(i => i.selected)
    .reduce((acc, i) => acc + i.sizeMB, 0);

  const handleClean = () => {
    if (totalSelectedMB === 0 || isCleaning) return;
    const selectedIds = items.filter(i => i.selected).map(i => i.id);
    startClean(selectedIds);
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold mb-1">
            <Trash2 className="w-4 h-4" />
            DEEP JUNK FILE PURGER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">정크 및 임시 파일 세척</h2>
          <p className="text-sm text-gray-700 dark:text-slate-300 mt-2">
            시스템 구석에 쌓인 불필요한 캐시, 찌꺼기 파일들을 완벽하게 제거합니다.
          </p>
        </div>
        
        <div className="flex flex-col items-end gap-2 w-full sm:w-auto mt-4 sm:mt-0">
          <div className="text-right">
            <div className="text-xs text-gray-500 dark:text-slate-400 mb-1">정리 가능 용량</div>
            <div className="text-3xl font-black text-cyan-400 font-mono">
              {totalSelectedMB >= 1024 
                ? (totalSelectedMB / 1024).toFixed(2) + ' GB'
                : totalSelectedMB + ' MB'
              }
            </div>
          </div>

          {freedMB > 0 ? (
            <button
              onClick={rescanJunk}
              disabled={isScanning}
              className={`btn-secondary px-5 py-3 text-xs flex items-center gap-2 ${isScanning ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <RefreshCw className={`w-4 h-4 text-cyan-400 ${isScanning ? 'animate-spin' : ''}`} />
              <span>{isScanning ? '스캔 중...' : '시스템 다시 스캔'}</span>
            </button>
          ) : (
            <button
              onClick={handleClean}
              disabled={isCleaning || totalSelectedMB === 0 || isScanning}
              className={`btn-primary px-6 py-3 ${isCleaning || totalSelectedMB === 0 || isScanning ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {isCleaning ? (
                <>
                  <RefreshCw className="w-5 h-5 animate-spin" />
                  <span>세척 중...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-5 h-5" />
                  <span>선택 항목 지금 정리</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Cleaning Progress Indicator */}
      {isCleaning && (
        <div className="glass-panel p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between text-cyan-400 font-mono text-sm">
            <div className="flex items-center gap-2">
              <RefreshCw className="w-5 h-5 animate-spin" />
              <span>임시 조각파일 및 캐시 데이터 안전 제거 중...</span>
            </div>
            <div className="text-right">
              <span className="font-bold">{Math.floor(cleanProgress)}%</span>
              <span className="text-xs ml-3 text-slate-500">예상 남은 시간: {cleanEta}초</span>
            </div>
          </div>
          <div className="w-full bg-slate-200 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div className="bg-cyan-400 h-1.5 rounded-full transition-all duration-1000 ease-out" style={{ width: `${cleanProgress}%` }}></div>
          </div>
        </div>
      )}

      {/* Success Alert Banner */}
      {cleanedSuccess && (
        <div className="glass-panel border-emerald-500/40 bg-emerald-950/20 p-4 rounded-xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-6 h-6 text-emerald-400" />
            <div>
              <h4 className="font-bold text-emerald-300 text-sm">
                정크 파일 세척 완료! 총 <span className="text-emerald-400 font-mono font-black">{freedMB >= 1024 ? `${(freedMB / 1024).toFixed(2)} GB` : `${freedMB} MB`}</span> 공간이 성공적으로 확보되었습니다!
              </h4>
              <p className="text-xs text-gray-700 dark:text-slate-300">
                실제 비활성 임시 파일이 디스크에서 안전하게 제거되었습니다.
              </p>
            </div>
          </div>
          <button 
            onClick={() => setCleanedSuccess(false)}
            className="text-xs text-gray-500 dark:text-slate-400 hover:text-black dark:text-white underline"
          >
            닫기
          </button>
        </div>
      )}

      {/* Controls Bar */}
      <div className="flex items-center justify-between px-2 text-xs font-mono">
        <div className="flex items-center gap-3">
          <button onClick={selectAll} className="text-cyan-400 hover:underline">전체 선택</button>
          <span className="text-slate-600">|</span>
          <button onClick={deselectAll} className="text-gray-500 dark:text-slate-400 hover:underline">전체 해제</button>
        </div>
        <span className="text-gray-500 dark:text-slate-400">
          {isScanning ? '스캔 중...' : `총 ${items.length}개 정크 카테고리 감지됨`}
        </span>
      </div>

      {/* Items List */}
      <div className="space-y-3">
        {items.map((item) => (
          <div
            key={item.id}
            onClick={() => toggleItem(item.id)}
            className={`glass-panel p-4 cursor-pointer transition-all duration-200 flex items-center justify-between gap-4 ${
              item.selected 
                ? 'border-cyan-500/40 bg-cyan-950/10' 
                : 'hover:border-black/10 dark:border-slate-700 opacity-80'
            }`}
          >
            <div className="flex items-center gap-3.5">
              <button className="text-cyan-400 focus:outline-none">
                {item.selected ? (
                  <CheckSquare className="w-5 h-5" />
                ) : (
                  <Square className="w-5 h-5 text-gray-400 dark:text-slate-600" />
                )}
              </button>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-gray-900 dark:text-slate-100 text-sm">{item.name}</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-gray-50 dark:bg-slate-800 text-gray-700 dark:text-slate-300 border border-black/10 dark:border-slate-700">
                    {item.category}
                  </span>
                </div>
                <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">{item.description}</p>
              </div>
            </div>

            <div className="text-right">
              <span className={`font-mono font-bold text-sm ${item.sizeMB > 0 ? 'text-amber-400' : 'text-slate-500'}`}>
                {item.sizeMB > 0
                  ? (item.sizeMB >= 1024 ? `${(item.sizeMB / 1024).toFixed(2)} GB` : `${item.sizeMB} MB`)
                  : '0 MB Clean'
                }
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
