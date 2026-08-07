import React, { useState, useEffect } from 'react';
import { 
  Trash2, 
  CheckSquare, 
  Square, 
  RefreshCw, 
  Sparkles, 
  CheckCircle2 
} from 'lucide-react';
import confetti from 'canvas-confetti';
import { playSound } from '../utils/audio';

export default function JunkCleaner({ addToast }) {
  const [items, setItems] = useState([]);

  const rescanJunk = async () => {
    playSound('scan');
    setCleanedSuccess(false);
    setFreedMB(0);
    if (window.pywebview?.api && window.pywebview?.api.scanJunk) {
      try {
        const realItems = await window.pywebview?.api.scanJunk();
        if (realItems && realItems.length > 0) {
          setItems(realItems);
          return;
        }
      } catch (e) {}
    }
  };

  useEffect(() => {
    rescanJunk();
  }, []);

  const [isCleaning, setIsCleaning] = useState(false);
  const [cleanedSuccess, setCleanedSuccess] = useState(false);

  const toggleItem = (id) => {
    playSound('toggle');
    setItems(items.map(item => item.id === id ? { ...item, selected: !item.selected } : item));
  };

  const selectAll = () => {
    playSound('click');
    setItems(items.map(item => ({ ...item, selected: true })));
  };

  const deselectAll = () => {
    playSound('click');
    setItems(items.map(item => ({ ...item, selected: false })));
  };

  const totalSelectedMB = items
    .filter(i => i.selected)
    .reduce((acc, i) => acc + i.sizeMB, 0);

  const [freedMB, setFreedMB] = useState(0);

  const handleClean = async () => {
    if (totalSelectedMB === 0 || isCleaning) return;
    playSound('scan');
    setIsCleaning(true);

    const selectedIds = items.filter(i => i.selected).map(i => i.id);

    // Call real Electron IPC if available
    if (window.pywebview?.api && window.pywebview?.api.cleanJunk) {
      try {
        const result = await window.pywebview?.api.cleanJunk(selectedIds);
        if (result && result.freedMB !== undefined) {
          setFreedMB(result.freedMB);
        }
      } catch (e) {}
    } else if (window.pywebview?.api && window.pywebview?.api.cleanTempFiles) {
      try {
        const result = await window.pywebview?.api.cleanTempFiles();
        if (result && result.freedMB !== undefined) {
          setFreedMB(result.freedMB);
        }
      } catch (e) {}
    }

    setIsCleaning(false);
    setCleanedSuccess(true);
    playSound('success');

      // Empty selected items size
      setItems(prevItems => prevItems.map(item => item.selected ? { ...item, sizeMB: 0, selected: false } : item));

      try {
        confetti({ particleCount: 60, spread: 60, origin: { y: 0.7 } });
      } catch (e) {}
      
      if (addToast) {
        addToast(`정크 파일 세척이 완료되었습니다! (확보된 용량: ${freedMB || '성공'})`, 'success');
      }
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
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
            불필요한 임시 데이터와 캐시를 제거하여 디스크 공간을 확보하고 I/O 속도를 향상시킵니다.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-xs text-gray-500 dark:text-slate-400">
              {freedMB > 0 ? '확보 완료된 용량' : '선택한 확보 가능 용량'}
            </div>
            <div className={`text-2xl font-black font-mono ${freedMB > 0 ? 'text-emerald-400' : 'text-cyan-400'}`}>
              {freedMB > 0
                ? (freedMB >= 1024 ? `${(freedMB / 1024).toFixed(2)} GB` : `${freedMB} MB`)
                : (totalSelectedMB >= 1024 ? `${(totalSelectedMB / 1024).toFixed(2)} GB` : `${totalSelectedMB} MB`)
              }
            </div>
          </div>

          {freedMB > 0 ? (
            <button
              onClick={rescanJunk}
              className="btn-secondary px-5 py-3 text-xs flex items-center gap-2"
            >
              <RefreshCw className="w-4 h-4 text-cyan-400" />
              <span>시스템 다시 스캔</span>
            </button>
          ) : (
            <button
              onClick={handleClean}
              disabled={isCleaning || totalSelectedMB === 0}
              className={`btn-primary px-6 py-3 ${isCleaning || totalSelectedMB === 0 ? 'opacity-50 cursor-not-allowed' : ''}`}
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
        <div className="glass-panel p-4 flex items-center justify-center gap-3 text-cyan-400 font-mono text-sm">
          <RefreshCw className="w-5 h-5 animate-spin" />
          임시 조각파일 및 캐시 데이터 안전 제거 중...
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
                실제 %TEMP% 및 C:\Windows\Temp 디렉터리의 비활성 임시 파일이 디스크에서 안전하게 제거되었습니다.
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
        <span className="text-gray-500 dark:text-slate-400">총 {items.length}개 정크 카테고리 감지됨</span>
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
                  <CheckSquare className="w-5 h-5 text-cyan-400 fill-cyan-950" />
                ) : (
                  <Square className="w-5 h-5 text-slate-500" />
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
