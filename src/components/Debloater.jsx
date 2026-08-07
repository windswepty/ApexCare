import React, { useState, useEffect } from 'react';
import { 
  Trash2, 
  CheckCircle2, 
  AlertTriangle,
  RotateCw,
  ShieldAlert,
  ServerCrash
} from 'lucide-react';
import { playSound } from '../utils/audio';

export default function Debloater({ addToast }) {
  const [items, setItems] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  const [status, setStatus] = useState({ running: false, progress_pct: 0, current_task: '' });

  useEffect(() => {
    fetchItems();
  }, []);

  const fetchItems = async () => {
    if (window.pywebview?.api?.getDebloatList) {
      const list = await window.pywebview.api.getDebloatList();
      if (list) setItems(list);
    }
  };

  const toggleItem = (id) => {
    setSelectedIds(prev => 
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
    playSound('hover');
  };

  const selectAll = () => {
    if (selectedIds.length === items.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(items.map(x => x.id));
    }
    playSound('hover');
  };

  const startDebloat = async () => {
    if (selectedIds.length === 0) return;
    
    if (!window.confirm("선택한 항목들을 정말로 윈도우에서 완전히 삭제하시겠습니까?\n(삭제 후에는 Microsoft Store를 통해 다시 설치해야 할 수 있습니다.)")) {
      return;
    }

    playSound('scan');
    setIsScanning(true);
    
    if (window.pywebview?.api?.startDebloater) {
      const res = await window.pywebview.api.startDebloater(selectedIds);
      if (!res.success) {
        alert(res.message);
        setIsScanning(false);
        return;
      }
      
      const poll = setInterval(async () => {
        const st = await window.pywebview.api.getDebloatStatus();
        if (st) {
          setStatus(st);
          if (!st.running) {
            clearInterval(poll);
            setIsScanning(false);
            if (st.error) {
              alert("오류 발생: " + st.error);
              if (addToast) addToast("오류 발생: " + st.error, 'error');
            } else {
              playSound('success');
              if (addToast) addToast("선택한 항목들의 순정화(제거)가 완료되었습니다!", 'success');
              setSelectedIds([]);
            }
          }
        }
      }, 500);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
        <div className="space-y-1 z-10">
          <div className="flex items-center gap-2 text-red-400 font-mono text-xs font-semibold">
            <ServerCrash className="w-4 h-4" />
            WINDOWS DEEP DEBLOATER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white tracking-tight">윈도우 하드코어 적출</h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm max-w-xl">
            지워지지 않는 기본 앱, 백그라운드 텔레메트리(데이터 수집) 등을 파워쉘 단에서 강제로 적출하여 윈도우를 가장 가벼운 상태로 만듭니다.
          </p>
        </div>
        <div className="z-10 shrink-0">
          <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20">
            <Trash2 className="w-8 h-8 text-red-500" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="flex justify-between items-center px-2">
            <h3 className="font-bold text-black dark:text-white">적출 가능 항목 ({items.length})</h3>
            <button 
              onClick={selectAll}
              className="text-xs font-bold text-cyan-500 hover:text-cyan-400 transition-colors"
            >
              {selectedIds.length === items.length ? '전체 해제' : '전체 선택'}
            </button>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[500px] overflow-y-auto pr-2 custom-scrollbar">
            {items.map(item => (
              <div 
                key={item.id}
                onClick={() => !isScanning && toggleItem(item.id)}
                className={`glass-panel p-4 flex items-center gap-3 cursor-pointer transition-all duration-300 border-2 ${
                  selectedIds.includes(item.id) 
                    ? 'border-red-500/50 bg-red-500/5' 
                    : 'border-transparent hover:border-black/10 dark:hover:border-white/10'
                } ${isScanning ? 'opacity-50 pointer-events-none' : ''}`}
              >
                <div className={`w-5 h-5 rounded flex items-center justify-center shrink-0 border transition-colors ${
                  selectedIds.includes(item.id)
                    ? 'bg-red-500 border-red-500'
                    : 'border-gray-300 dark:border-gray-600'
                }`}>
                  {selectedIds.includes(item.id) && <CheckCircle2 className="w-3.5 h-3.5 text-white" />}
                </div>
                <div>
                  <div className="font-bold text-sm text-black dark:text-white">{item.name}</div>
                  <div className="text-xs text-gray-500 font-mono mt-0.5">{item.pattern}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-6">
          <div className="glass-panel p-5 bg-red-500/5 border-red-500/20">
            <h3 className="font-bold text-red-500 mb-2 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4" />
              주의사항
            </h3>
            <p className="text-xs text-black/70 dark:text-white/70 leading-relaxed mb-4">
              이 기능은 일반적인 방법으로 삭제할 수 없는 윈도우 코어 구성요소를 강제로 제거합니다. 나열된 항목은 대부분 삭제해도 안전하지만, 사용 중인 기능(예: Xbox 로그인 등)이 있다면 선택 해제해 주세요.
            </p>
          </div>

          <div className="glass-panel p-5 text-center">
            <h3 className="font-bold text-black dark:text-white mb-2">선택된 항목: {selectedIds.length}개</h3>
            <button
              onClick={startDebloat}
              disabled={selectedIds.length === 0 || isScanning}
              className={`w-full py-4 rounded-xl font-bold flex items-center justify-center gap-2 transition-all ${
                selectedIds.length === 0
                  ? 'bg-gray-200 dark:bg-zinc-800 text-gray-400 cursor-not-allowed'
                  : 'bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/20'
              }`}
            >
              {isScanning ? (
                <>
                  <RotateCw className="w-5 h-5 animate-spin" />
                  <span>적출 진행 중...</span>
                </>
              ) : (
                <>
                  <Trash2 className="w-5 h-5" />
                  <span>선택 항목 강제 적출</span>
                </>
              )}
            </button>
          </div>

          {isScanning && (
            <div className="glass-panel p-5">
              <div className="flex justify-between text-xs font-mono mb-2">
                <span className="text-gray-500 truncate max-w-[200px]">{status.current_task}</span>
                <span className="text-black dark:text-white font-bold">{status.progress_pct}%</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-zinc-800 h-2 rounded-full overflow-hidden">
                <div 
                  className="bg-red-500 h-full rounded-full transition-all duration-300"
                  style={{ width: `${status.progress_pct}%` }}
                ></div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
