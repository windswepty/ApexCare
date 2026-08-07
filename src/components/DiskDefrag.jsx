import React, { useState, useRef, useEffect } from 'react';
import { 
  HardDrive, 
  RotateCw, 
  CheckCircle2, 
  Zap, 
  Layers 
} from 'lucide-react';
import confetti from 'canvas-confetti';
import { playSound } from '../utils/audio';

export default function DiskDefrag({ addToast }) {
  const [blocks, setBlocks] = useState(() => {
    const saved = localStorage.getItem('apex_disk_defrag_state');
    const savedTime = localStorage.getItem('apex_disk_defrag_time');
    
    if (saved && savedTime) {
      try {
        let parsedBlocks = JSON.parse(saved);
        
        // Time decay simulation: increase fragmentation over time
        const daysPassed = (Date.now() - parseInt(savedTime)) / (1000 * 60 * 60 * 24);
        if (daysPassed > 1) { // After 1 day, start fragmenting
          const blocksToFragment = Math.min(Math.floor(daysPassed * 2), 20); // Max 20 blocks
          let fragmentedAdded = 0;
          for (let i = 15; i < 95; i++) {
            if (parsedBlocks[i] === 'contiguous' && Math.random() > 0.8) {
              parsedBlocks[i] = 'fragmented';
              fragmentedAdded++;
              if (fragmentedAdded >= blocksToFragment) break;
            }
          }
          // Also reset 'done' status if it's too fragmented
          if (fragmentedAdded > 5) {
            localStorage.removeItem('apex_disk_defrag_done');
          }
        }
        return parsedBlocks;
      } catch (e) {}
    }
    // 100 blocks grid representation
    // Types: 'contiguous' (cyan), 'fragmented' (rose), 'system' (purple), 'free' (slate)
    return Array.from({ length: 120 }, (_, idx) => {
      if (idx < 15) return 'system';
      if (idx % 7 === 0 || idx % 11 === 0) return 'fragmented';
      if (idx > 95) return 'free';
      return 'contiguous';
    });
  });

  const [cmdOutput, setCmdOutput] = useState("");
  const terminalRef = useRef(null);
  const [isDefragging, setIsDefragging] = useState(false);
  const [defragDone, setDefragDone] = useState(() => localStorage.getItem('apex_disk_defrag_done') === 'true');

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [cmdOutput]);

  const startDefragAndTrim = async () => {
    if (isDefragging) return;
    playSound('scan');
    setIsDefragging(true);
    setDefragDone(false);
    setCmdOutput("C:\\Windows\\System32> defrag.exe /C /O\n\n[APEX Engine] 윈도우 네이티브 시스템에 모든 드라이브(C:, D: 등 전체)의 최적화 및 TRIM(빈 블록 데이터 폐기) 명령을 요청합니다...\n[APEX Engine] 저장 장치 타입(NVMe, SATA SSD 등)에 따라 작업이 수 초 내외로 빠르게 완료될 수 있습니다. 대기 중...\n\n");

    let success = false;
    let outputText = "";
    if (window.pywebview?.api && window.pywebview?.api.runTrim) {
      try {
        const res = await window.pywebview?.api.runTrim();
        success = res?.success;
        outputText = res?.output || (success ? "성공적으로 완료되었습니다." : "출력 내용이 없습니다.");
      } catch (e) {
        success = false;
        outputText = String(e);
      }
    } else {
      await new Promise(r => setTimeout(r, 2000));
      success = true;
      outputText = "개발 모드: 가상 출력 완료.\n\n볼륨 C: 최적화 완료.\n모든 볼륨 최적화 완료.";
    }

    setIsDefragging(false);
    setCmdOutput(prev => prev + outputText + "\n\n[APEX Engine] 모든 작업이 종료되었습니다.");

    if (success) {
      setDefragDone(true);
      localStorage.setItem('apex_disk_defrag_done', 'true');
      localStorage.setItem('apex_disk_defrag_time', Date.now().toString());
      playSound('success');
      setBlocks(prev => {
        const next = prev.map(b => b === 'fragmented' ? 'contiguous' : b);
        localStorage.setItem('apex_disk_defrag_state', JSON.stringify(next));
        return next;
      });
      try {
        confetti({ particleCount: 70, spread: 70, origin: { y: 0.6 } });
      } catch (e) {}
      if (addToast) addToast('디스크 조각모음 및 TRIM 최적화가 완료되었습니다!', 'success');
    } else {
      alert("최적화에 실패했습니다. 관리자 권한을 확인해주세요.");
      if (addToast) addToast('디스크 최적화에 실패했습니다.', 'error');
    }
  };

  const getBlockColor = (type) => {
    switch (type) {
      case 'system':
        return 'bg-purple-500/80 border-purple-400/50 shadow-purple-500/20';
      case 'fragmented':
        return 'bg-rose-500/90 border-rose-400/60 shadow-rose-500/30 animate-pulse';
      case 'contiguous':
        return 'bg-cyan-500/80 border-cyan-400/50 shadow-cyan-500/20';
      case 'free':
      default:
        return 'bg-gray-50 dark:bg-slate-800/60 border-black/10 dark:border-slate-700/40';
    }
  };

  const fragmentedCount = blocks.filter(b => b === 'fragmented').length;

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs font-semibold mb-1">
            <HardDrive className="w-4 h-4" />
            NVMe SSD TRIM & SMART DISK DEFRAG ENGINE
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">디스크 조각모음 & TRIM 최적화</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
            SSD 최적화(TRIM) 명령 전송 및 파편화된 디스크 클러스터 데이터를 재정렬하여 파일 읽기/쓰기 속도를 극대화합니다.
          </p>
        </div>

        <button
          onClick={startDefragAndTrim}
          disabled={isDefragging}
          className={`btn-primary bg-gradient-to-r from-emerald-500 to-teal-600 shadow-emerald-500/30 px-6 py-3.5 ${
            isDefragging ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {isDefragging ? (
            <>
              <RotateCw className="w-5 h-5 animate-spin" />
              <span>TRIM 최적화 진행 중...</span>
            </>
          ) : (
            <>
              <Zap className="w-5 h-5 fill-current" />
              <span>TRIM & 디스크 재정렬 시작</span>
            </>
          )}
        </button>
      </div>

      {/* Progress Terminal */}
      {(isDefragging || cmdOutput) && (
        <div className="glass-panel p-4 space-y-2">
          <div className="flex justify-between text-xs font-mono mb-2">
            <span className="text-emerald-300">Windows Native CMD Console</span>
            {isDefragging && <span className="text-emerald-400 animate-pulse">Running...</span>}
          </div>
          <div 
            ref={terminalRef}
            className="w-full bg-black/80 dark:bg-black/90 rounded-lg p-4 font-mono text-[11px] leading-relaxed text-gray-300 overflow-y-auto max-h-[300px] border border-white/5"
            style={{ whiteSpace: 'pre-wrap' }}
          >
            {cmdOutput}
          </div>
        </div>
      )}

      {defragDone && !isDefragging && (
        <div className="glass-panel border-emerald-500/40 bg-emerald-950/20 p-4 rounded-xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-6 h-6 text-emerald-400" />
            <div>
              <h4 className="font-bold text-emerald-300 text-sm">SSD TRIM 및 클러스터 최적화가 완료되었습니다!</h4>
              <p className="text-xs text-gray-700 dark:text-slate-300">모든 파일 클러스터가 연속 블록으로 재정렬되었으며 SSD 수명이 보존됩니다.</p>
            </div>
          </div>
          <button onClick={() => setDefragDone(false)} className="text-xs text-gray-500 dark:text-slate-400 hover:text-black dark:text-white underline">
            닫기
          </button>
        </div>
      )}

      {/* Disk Status Specs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="glass-panel p-4 text-center">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">드라이브 종류</span>
          <div className="text-lg font-extrabold text-black dark:text-white mt-1">ALL Connected Drives</div>
          <span className="text-[10px] text-emerald-400 font-mono">전체 드라이브 대상 최적화 지원됨</span>
        </div>

        <div className="glass-panel p-4 text-center">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">조각화 비율 추정 (Fragmented)</span>
          <div className={`text-lg font-extrabold font-mono mt-1 ${fragmentedCount > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
            {((fragmentedCount / blocks.length) * 100).toFixed(1)}%
          </div>
          <span className="text-[10px] text-slate-500 font-mono">시간 경과에 따른 가상 조각화 추정치</span>
        </div>
      </div>

      {/* Detailed Status */}
      <div className="glass-panel p-6 space-y-4">
        <h3 className="font-bold text-gray-900 dark:text-slate-100 text-sm flex items-center gap-2">
          <Layers className="w-4 h-4 text-cyan-400" />
          디스크 파티션 상태
        </h3>
        <p className="text-xs text-gray-500 dark:text-slate-400 leading-relaxed">
          TRIM 명령은 NVMe 및 SATA SSD의 빈 블록 정보를 컨트롤러에 알려주어 쓰기 수명을 연장하고 속도 저하(Write Amplification)를 방지합니다. 
          실제 Windows Optimize-Volume 명령과 연동되어 백그라운드에서 안전하게 수행됩니다.
        </p>
      </div>
    </div>
  );
}
