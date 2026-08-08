import React, { createContext, useContext, useState, useEffect } from 'react';
import { playSound } from '../utils/audio';

const JunkContext = createContext();

export function useJunk() {
  return useContext(JunkContext);
}

export function JunkProvider({ children, addToast }) {
  const [items, setItems] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  
  const [isCleaning, setIsCleaning] = useState(false);
  const [cleanProgress, setCleanProgress] = useState(0);
  const [cleanEta, setCleanEta] = useState(5);
  const [cleanedSuccess, setCleanedSuccess] = useState(false);
  const [freedMB, setFreedMB] = useState(0);
  
  const [hasScannedOnce, setHasScannedOnce] = useState(false);

  // Poll scan status
  useEffect(() => {
    let interval;
    if (isScanning) {
      interval = setInterval(async () => {
        if (window.pywebview?.api?.getJunkScanStatus) {
          try {
            const state = await window.pywebview.api.getJunkScanStatus();
            if (state && state.status !== 'running' && state.status !== 'idle') {
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
          } catch (e) {}
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
        setCleanProgress(p => (p < 99 ? p + 20 : 99));
        setCleanEta(e => (e > 0 ? e - 1 : 0));
        
        if (window.pywebview?.api?.getJunkCleanStatus) {
          try {
            const state = await window.pywebview.api.getJunkCleanStatus();
            if (state && state.status !== 'running' && state.status !== 'idle') {
              setIsCleaning(false);
              if (state.status === 'success') {
                setFreedMB(state.freedMB || 0);
                setCleanedSuccess(true);
                playSound('success');
                // Empty selected items size
                setItems(prevItems => prevItems.map(item => item.selected ? { ...item, sizeMB: 0, selected: false } : item));
                
                if (addToast) {
                  const mb = state.freedMB || 0;
                  addToast(`정크 파일 세척이 완료되었습니다! (확보된 용량: ${mb >= 1024 ? (mb/1024).toFixed(2) + ' GB' : mb + ' MB'})`, 'success');
                }
              } else {
                if (addToast) addToast("정크 파일 삭제 중 에러 발생: " + (state.error || ""), "error");
              }
            }
          } catch (e) {}
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isCleaning, addToast]);

  const rescanJunk = async () => {
    playSound('scan');
    setCleanedSuccess(false);
    setFreedMB(0);
    setIsScanning(true);
    if (window.pywebview?.api?.scanJunk) {
      try {
        await window.pywebview.api.scanJunk();
      } catch (e) {
        setIsScanning(false);
      }
    } else {
      setIsScanning(false);
    }
  };

  const startClean = async (selectedIds) => {
    playSound('scan');
    setIsCleaning(true);
    setCleanProgress(0);
    setCleanEta(5);
    setCleanedSuccess(false);
    
    if (window.pywebview?.api?.cleanJunk) {
      try {
        await window.pywebview.api.cleanJunk(selectedIds);
      } catch (e) {
        setIsCleaning(false);
      }
    } else {
      setIsCleaning(false);
    }
  };

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

  return (
    <JunkContext.Provider value={{
      items, isScanning, isCleaning, cleanProgress, cleanEta, hasScannedOnce,
      cleanedSuccess, freedMB, rescanJunk, startClean, toggleItem, selectAll, deselectAll,
      setCleanedSuccess
    }}>
      {children}
    </JunkContext.Provider>
  );
}
