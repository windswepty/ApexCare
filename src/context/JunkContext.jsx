import React, { createContext, useContext, useState, useEffect } from 'react';

const JunkContext = createContext();

export function useJunk() {
  return useContext(JunkContext);
}

export function JunkProvider({ children, addToast }) {
  const [items, setItems] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  
  const [isCleaning, setIsCleaning] = useState(false);
  const [cleanProgress, setCleanProgress] = useState(0);
  const [cleanEta, setCleanEta] = useState(0);
  const [scanProgress, setScanProgress] = useState(0);
  const [scanEta, setScanEta] = useState(0);
  const [cleanedSuccess, setCleanedSuccess] = useState(false);
  const [freedMB, setFreedMB] = useState(0);
  const [skippedMB, setSkippedMB] = useState(0);
  const [cleanDetails, setCleanDetails] = useState({});
  
  const [hasScannedOnce, setHasScannedOnce] = useState(false);

  // Poll scan status
  useEffect(() => {
    let interval;
    if (isScanning) {
      interval = setInterval(async () => {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getJunkScanStatus === 'function') {
          try {
            const state = await window.pywebview.api.getJunkScanStatus();
            if (state) {
              if (state.progress !== undefined) setScanProgress(state.progress);
              if (state.eta_seconds !== undefined) setScanEta(state.eta_seconds);
              
              if (state.status !== 'running' && state.status !== 'idle') {
                setIsScanning(false);
                setHasScannedOnce(true);
                if (state.status === 'success') {
                  if (Array.isArray(state.data) && state.data.length > 0) {
                    setItems(state.data);
                  }
                } else {
                  if (addToast) addToast("정크 파일 스캔 중 에러가 발생했습니다.", "error");
                }
              }
            }
          } catch (e) {
            console.error('Error polling junk scan status:', e);
            setIsScanning(false);
            if (addToast) addToast("정크 파일 스캔 상태 확인 중 오류가 발생했습니다.", "error");
          }
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isScanning, addToast]);

  // Poll clean status
  useEffect(() => {
    let interval;
    if (isCleaning) {
      interval = setInterval(async () => {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getJunkCleanStatus === 'function') {
          try {
            const state = await window.pywebview.api.getJunkCleanStatus();
            if (state) {
              if (state.progress !== undefined) setCleanProgress(state.progress);
              if (state.eta_seconds !== undefined) setCleanEta(state.eta_seconds);
              
              if (state.status !== 'running' && state.status !== 'idle') {
                setIsCleaning(false);
                if (state.status === 'success') {
                  setFreedMB(state.freed_mb || 0);
                  setSkippedMB(state.skipped_mb || 0);
                  setCleanDetails(state.details || {});
                  setCleanedSuccess(true);
                  // 리스캔을 방지하고 스킵된 용량을 수학적으로 분배하여 UI에 덮어씌움
                  const skippedMBValue = state.skipped_mb || 0;
                  setItems(prevItems => {
                    const totalSelected = prevItems.filter(i => i.selected).reduce((acc, i) => acc + i.sizeMB, 0);
                    return prevItems.map(item => {
                      if (item.selected) {
                        const ratio = totalSelected > 0 ? item.sizeMB / totalSelected : 0;
                        const newSize = skippedMBValue * ratio;
                        return { ...item, sizeMB: Number(newSize.toFixed(2)) };
                      }
                      return item;
                    });
                  });
                  
                  if (addToast) {
                    const mb = state.freed_mb || 0;
                    const skipped = state.skipped_mb || 0;
                    const totalStr = mb >= 1024 ? (mb/1024).toFixed(2) + ' GB' : mb.toFixed(2) + ' MB';
                    const skippedStr = skipped >= 1024 ? (skipped/1024).toFixed(2) + ' GB' : skipped.toFixed(2) + ' MB';
                    
                    let detailsStr = '';
                    if (state.details && Object.keys(state.details).length > 0) {
                      const detailParts = Object.entries(state.details).map(([drv, size]) => {
                         const sizeStr = size >= 1024 ? (size/1024).toFixed(2) + ' GB' : size.toFixed(2) + ' MB';
                         return `${drv} ${sizeStr}`;
                      });
                      detailsStr = ` (${detailParts.join(' / ')})`;
                    }
                    if (skipped > 0) {
                      addToast(`총 ${totalStr} 정리 완료! (${skippedStr}는 시스템 사용 중으로 안전하게 스킵됨)${detailsStr}`, 'success');
                    } else {
                      addToast(`정크 파일 세척이 완료되었습니다! (확보된 용량: ${totalStr}${detailsStr})`, 'success');
                    }
                  }
                } else {
                  if (addToast) addToast("정크 파일 삭제 중 에러 발생: " + (state.error || ""), "error");
                }
              }
            }
          } catch (e) {
            console.error('Error polling junk clean status:', e);
            setIsCleaning(false);
            if (addToast) addToast("정크 파일 삭제 상태 확인 중 오류가 발생했습니다.", "error");
          }
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isCleaning, addToast]);

  const rescanJunk = async (preserveSuccess = false) => {
    if (!preserveSuccess) {
      setCleanedSuccess(false);
      setFreedMB(0);
      setSkippedMB(0);
    }
    setScanProgress(0);
    setScanEta(0);
    setIsScanning(true);
    
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.scanJunk === 'function') {
        const res = await window.pywebview.api.scanJunk();
        if (res && res.success === false) {
           if (addToast && res.error === "UAC_REQUIRED") {
               addToast("관리자 권한이 필요합니다.", "error");
           } else if (res.message) {
               addToast(res.message, "error");
           }
           setIsScanning(false);
        }
      } else {
        setIsScanning(false);
      }
    } catch (e) {
      console.error('Error starting junk scan:', e);
      setIsScanning(false);
    }
  };

  const startClean = async (selectedIds) => {
    setIsCleaning(true);
    setCleanProgress(0);
    setCleanEta(5);
    setCleanedSuccess(false);
    
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.cleanJunk === 'function') {
        const res = await window.pywebview.api.cleanJunk(selectedIds);
        if (res && res.success === false) {
           if (addToast && res.error === "UAC_REQUIRED") {
               addToast("관리자 권한이 필요합니다.", "error");
           } else if (res.message) {
               addToast(res.message, "error");
           }
           setIsCleaning(false);
        }
      } else {
        setIsCleaning(false);
      }
    } catch (e) {
      console.error('Error starting junk clean:', e);
      setIsCleaning(false);
    }
  };

  const toggleItem = (id) => {
    setItems(items.map(item => item.id === id ? { ...item, selected: !item.selected } : item));
  };

  const selectAll = () => {
    setItems(items.map(item => ({ ...item, selected: true })));
  };

  const deselectAll = () => {
    setItems(items.map(item => ({ ...item, selected: false })));
  };

  return (
    <JunkContext.Provider value={{
      items, isScanning, isCleaning, cleanProgress, cleanEta, scanProgress, scanEta, hasScannedOnce,
      cleanedSuccess, freedMB, skippedMB, cleanDetails, rescanJunk, startClean, toggleItem, selectAll, deselectAll,
      setCleanedSuccess
    }}>
      {children}
    </JunkContext.Provider>
  );
}
