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
                  setCleanedSuccess(true);
                  // Empty selected items size
                  setItems(prevItems => prevItems.map(item => item.selected ? { ...item, sizeMB: 0, selected: false } : item));
                  
                  if (addToast) {
                    const mb = state.freed_mb || 0;
                    addToast(`정크 파일 세척이 완료되었습니다! (확보된 용량: ${mb >= 1024 ? (mb/1024).toFixed(2) + ' GB' : mb + ' MB'})`, 'success');
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

  const rescanJunk = async () => {
    setCleanedSuccess(false);
    setFreedMB(0);
    setScanProgress(0);
    setScanEta(0);
    setIsScanning(true);
    
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.scanJunk === 'function') {
        await window.pywebview.api.scanJunk();
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
        await window.pywebview.api.cleanJunk(selectedIds);
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
      cleanedSuccess, freedMB, rescanJunk, startClean, toggleItem, selectAll, deselectAll,
      setCleanedSuccess
    }}>
      {children}
    </JunkContext.Provider>
  );
}
