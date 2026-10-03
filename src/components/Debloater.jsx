import { useState, useEffect } from 'react';
import {
  Trash2,
  CheckCircle2,
  AlertTriangle,
  RotateCw,
  RotateCcw,
  ShieldAlert,
  ServerCrash,
  Loader2,
  PackageX,
  Undo2
} from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;

export default function Debloater({ addToast }) {
  const [items, setItems] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [isScanning, setIsScanning] = useState(false);
  const [status, setStatus] = useState({ running: false, progress_pct: 0, current_task: '' });
  const [removedApps, setRemovedApps] = useState(null);   // null = API 없음
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState(null);
  // 앱 항목별 설치 여부: 'installed' | 'not_installed' | 'unknown'. null = 아직 확인 중.
  // 설치되지 않은 앱은 고를 수 없게 한다(예전에는 골라 실행해야 '변경 없음' 을 알 수 있었다).
  const [installState, setInstallState] = useState(null);
  // 설치된 앱 항목별로 지운 뒤에도 설치 파일이 남는지: true(되살릴 수 있음) | false(Windows 가 지움) | null(모름).
  // Windows 는 이 계정에만 설치된 스토어 앱을 지우면 설치 파일까지 지운다. 그 앱은 '제거한 앱' 에서 되살릴 수 없다.
  const [restorable, setRestorable] = useState({});

  const fetchInstallState = async () => {
    const a = api();
    if (!a || typeof a.getDebloatInstallState !== 'function') return;
    try {
      const r = await a.getDebloatInstallState();
      const state = r?.items || {};
      setInstallState(state);
      setRestorable(r?.restorable || {});
      // 이제 설치돼 있지 않은 앱(방금 제거한 앱 등)은 선택에서 뺀다. 예전에는 일부 실패 뒤 그 앱이 선택된 채
      // 비활성화돼 해제할 수 없었고, 다음 확인 창이 이미 지운 앱을 '제거합니다' 로 다시 나열했다.
      setSelectedIds(prev => prev.filter(id => state[id] !== 'not_installed'));
    } catch (e) {
      console.error('Error fetching install state:', e);
      setInstallState({});
    }
  };
  const selectable = (item) => item.kind !== 'appx' || (installState && installState[item.id] !== 'not_installed');

  const fetchRemoved = async () => {
    const a = api();
    if (!a || typeof a.getRemovedDebloatApps !== 'function') return;
    try {
      const list = await a.getRemovedDebloatApps();
      setRemovedApps(Array.isArray(list) ? list : []);
    } catch (e) {
      console.error('Error fetching removed apps:', e);
    }
  };

  const restoreApps = async (names) => {
    const a = api();
    if (!a || typeof a.restoreRemovedDebloatApps !== 'function') return;
    setRestoring(true);
    setRestoreResult(null);
    try {
      const res = await a.restoreRemovedDebloatApps(names || null);
      setRestoreResult(res);
      if (addToast) addToast(res?.message || '되살리기를 마쳤습니다.', res?.success ? 'success' : 'error');
    } catch (e) {
      if (addToast) addToast(`되살리기 실패: ${e}`, 'error');
    }
    setRestoring(false);
    fetchRemoved();
    fetchInstallState();
  };

  useEffect(() => {
    const fetchDebloat = () => {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getDebloatList === 'function') {
        fetchItems();
        fetchRemoved();
        fetchInstallState();
      }
    };

    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getDebloatList === 'function') {
      fetchDebloat();
    } else {
      window.addEventListener('pywebviewready', fetchDebloat);
      return () => window.removeEventListener('pywebviewready', fetchDebloat);
    }
  }, []);

  const fetchItems = async () => {
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getDebloatList === 'function') {
        const list = await window.pywebview.api.getDebloatList();
        if (Array.isArray(list)) {
          setItems(list);
        } else {
          setItems([]);
        }
      } else {
        setItems([]);
      }
    } catch (e) {
      console.error('Error fetching debloat list:', e);
      setItems([]);
    }
  };

  const toggleItem = (id) => {
    const item = items.find(x => x.id === id);
    if (!item || !selectable(item)) return;
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  // '전체 선택' 은 고를 수 있는 항목만(설치되지 않은 앱 제외)
  const selectableIds = items.filter(selectable).map(x => x.id);
  const allSelected = selectableIds.length > 0 && selectableIds.every(id => selectedIds.includes(id));
  const selectAll = () => {
    setSelectedIds(allSelected ? [] : selectableIds);
  };

  const startDebloat = async () => {
    if (selectedIds.length === 0) return;

    // 되돌릴 수 없는 항목(앱 제거)과 되돌릴 수 있는 항목(정책)을 나눠서 보여준다.
    const chosen = items.filter(x => selectedIds.includes(x.id) && selectable(x));
    if (chosen.length === 0) return;
    const irreversible = chosen.filter(x => !x.reversible);
    const reversible = chosen.filter(x => x.reversible);
    const line = (x) => `  · ${x.name}${x.packages ? ` (${x.packages.join(', ')})` : ''}`;
    const gone = irreversible.filter(x => restorable[x.id] === false);
    const kept = irreversible.filter(x => restorable[x.id] === true);
    const unsure = irreversible.filter(x => restorable[x.id] !== false && restorable[x.id] !== true);
    let msg = '';
    if (gone.length > 0) {
      msg += `아래 앱은 이 계정에만 설치되어 있어, 제거하면 Windows 가 설치 파일까지 지웁니다. `
        + `이 화면에서 되살릴 수 없고 Microsoft Store 에서 다시 설치해야 합니다.\n`
        + gone.map(line).join('\n') + '\n\n';
    }
    if (kept.length > 0) {
      msg += `아래 앱을 이 계정에서 제거합니다. 설치 파일이 남으므로 이 화면의 '제거한 앱' 에서 되살릴 수 있습니다.\n`
        + kept.map(line).join('\n') + '\n\n';
    }
    if (unsure.length > 0) {
      msg += `아래 앱을 이 계정에서 제거합니다. 되살릴 수 있는지(설치 파일이 남는지) 확인하지 못했습니다. `
        + `설치 파일이 지워지면 Microsoft Store 에서 다시 설치해야 합니다.\n`
        + unsure.map(line).join('\n') + '\n\n';
    }
    if (reversible.length > 0) {
      msg += `아래 정책을 바꿉니다. 원래 값을 기록해 두므로 '변경 내역 · 되돌리기' 에서 되돌릴 수 있습니다.\n`
        + reversible.map(x => `  · ${x.name}`).join('\n') + '\n\n';
    }
    if (!window.confirm(msg + '계속할까요?')) {
      return;
    }

    setIsScanning(true);
    
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.startDebloater === 'function') {
        const res = await window.pywebview.api.startDebloater(chosen.map(x => x.id));   // 확인 창에 보인 것만
        if (!res?.success) {
          if (addToast) addToast(res?.message || '시작하지 못했습니다.', 'error');
          setIsScanning(false);
          return;
        }
        
        const poll = setInterval(async () => {
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.getDebloatStatus === 'function') {
            try {
              const st = await window.pywebview.api.getDebloatStatus();
              if (st) {
                setStatus(st);
                if (!st.running) {
                  clearInterval(poll);
                  setIsScanning(false);
                  if (st.error) {
                    if (addToast) addToast("오류 발생: " + st.error, 'error');
                  } else {
                    // 백엔드가 항목별 성패를 돌려준다. 하나도 못 지웠는데
                    // '완료'라고 띄우지 않도록 실제 결과를 그대로 보여준다.
                    const failed = st.failed || [];
                    const succeeded = st.succeeded || [];
                    const skipped = st.skipped || [];
                    const skipNote = skipped.length > 0 ? ` (${skipped.length}개는 설치돼 있지 않아 변경 없음)` : '';
                    if (failed.length > 0 && succeeded.length > 0) {
                      if (addToast) addToast(`${succeeded.length}개 완료, ${failed.length}개 실패: ${failed.join(', ')}${skipNote}`, 'error');
                    } else if (failed.length > 0) {
                      if (addToast) addToast(`처리하지 못했습니다: ${failed.join(', ')}${skipNote}`, 'error');
                    } else if (succeeded.length > 0) {
                      if (addToast) addToast(`${succeeded.length}개 항목을 처리했습니다.${skipNote}`, 'success');
                      setSelectedIds([]);
                    } else {
                      if (addToast) addToast(`바뀐 것이 없습니다${skipNote}.`, 'info');
                      setSelectedIds([]);
                    }
                    fetchRemoved();
                    fetchInstallState();
                  }
                }
              }
            } catch (e) {
              clearInterval(poll);
              setIsScanning(false);
              if (addToast) addToast(`진행 상태를 확인하지 못했습니다: ${e}. 작업은 계속 진행 중일 수 있습니다.`, 'error');
            }
          }
        }, 500);
      } else {
        if (addToast) addToast("API가 준비되지 않았습니다.", 'error');
        setIsScanning(false);
      }
    } catch (e) {
      console.error('Error starting debloater:', e);
      setIsScanning(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
        <div className="space-y-1 z-10">
          <div className="flex items-center gap-2 text-red-400 font-mono text-xs font-semibold">
            <ServerCrash className="w-4 h-4" />
            WINDOWS DEBLOATER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white tracking-tight">Windows 기본 앱 정리</h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm max-w-xl">
            잘 쓰지 않는 Windows 기본 앱을 이 계정에서 제거하고(설치 파일이 남는 앱은 아래 '제거한 앱' 에서 되살릴 수 있습니다),
            원격 분석·Cortana 정책을 바꿉니다('변경 내역 · 되돌리기' 에서 되돌릴 수 있습니다).
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
            <h3 className="font-bold text-black dark:text-white">정리할 수 있는 항목{items.length ? ` (${items.length})` : ''}</h3>
            <button
              onClick={selectAll}
              disabled={isScanning || selectableIds.length === 0}
              className="text-xs font-bold text-cyan-500 hover:text-cyan-400 transition-colors disabled:opacity-40"
            >
              {allSelected ? '전체 해제' : '전체 선택'}
            </button>
          </div>
          {installState === null && items.some(x => x.kind === 'appx') && (
            <p className="px-2 text-[0.6875rem] text-gray-500 flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" /> 이 PC 에 설치된 앱을 확인하는 중…
            </p>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[500px] overflow-y-auto pr-2 custom-scrollbar">
            {items.map(item => {
              const state = item.kind === 'appx' ? installState?.[item.id] : null;
              const canPick = selectable(item);
              return (
              <button
                type="button"
                key={item.id}
                onClick={() => toggleItem(item.id)}
                disabled={isScanning || !canPick}
                aria-pressed={selectedIds.includes(item.id)}
                title={!canPick && state === 'not_installed' ? '이 PC 에 설치되어 있지 않아 고를 수 없습니다' : undefined}
                className={`glass-panel p-4 flex items-center gap-3 text-left transition-all duration-300 border-2 disabled:cursor-not-allowed ${
                  selectedIds.includes(item.id)
                    ? 'border-red-500/50 bg-red-500/5'
                    : 'border-transparent hover:border-black/10 dark:hover:border-white/10'
                } ${isScanning || !canPick ? 'opacity-50' : 'cursor-pointer'}`}
              >
                <div className={`w-5 h-5 rounded flex items-center justify-center shrink-0 border transition-colors ${
                  selectedIds.includes(item.id)
                    ? 'bg-red-500 border-red-500'
                    : 'border-gray-300 dark:border-gray-600'
                }`}>
                  {selectedIds.includes(item.id) && <CheckCircle2 className="w-3.5 h-3.5 text-white" />}
                </div>
                <div className="min-w-0">
                  <div className="font-bold text-sm text-black dark:text-white flex items-center gap-2 flex-wrap">
                    {item.name}
                    {state === 'installed' && (
                      <span className="text-[0.625rem] font-bold px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-500">설치됨</span>
                    )}
                    {state === 'not_installed' && (
                      <span className="text-[0.625rem] font-bold px-1.5 py-0.5 rounded bg-gray-500/15 text-gray-500">설치되어 있지 않음</span>
                    )}
                    {state === 'unknown' && (
                      <span className="text-[0.625rem] font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-500">설치 여부 확인 못 함</span>
                    )}
                  </div>
                  <div className={`text-[0.6875rem] font-semibold mt-0.5 ${item.reversible ? 'text-emerald-500'
                    : restorable[item.id] === false ? 'text-red-500' : 'text-amber-500'}`}>
                    {item.reversible
                      ? "되돌리기 가능 ('변경 내역 · 되돌리기')"
                      : !item.restorable
                        ? '되돌릴 수 없음 (Store 에서 재설치)'
                        : restorable[item.id] === false
                          ? '이 계정에만 설치됨 · 제거하면 설치 파일도 지워져 되살릴 수 없음 (Store 에서 재설치)'
                          : restorable[item.id] === true
                            ? "이 계정에서 제거 · 아래 '제거한 앱' 에서 되살리기"
                            : "이 계정에서 제거 · 설치 파일이 남으면 아래 '제거한 앱' 에서 되살리기"}
                  </div>
                  {item.note && <div className="text-[0.6875rem] text-gray-500 mt-0.5 leading-snug">{item.note}</div>}
                </div>
              </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-6">
          <div className="glass-panel p-5 bg-red-500/5 border-red-500/20">
            <h3 className="font-bold text-red-500 mb-2 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4" />
              주의사항
            </h3>
            <p className="text-xs text-black/70 dark:text-white/70 leading-relaxed mb-4">
              앱은 이 프로그램을 실행한 계정에서만 제거합니다. Windows 기본 설치 앱이나 다른 계정에도 설치된 앱은 설치 파일이 남아 아래 '제거한 앱' 에서 되살릴 수 있습니다. 이 계정에만 설치된 앱은 Windows 가 설치 파일까지 지우므로 Microsoft Store 에서 다시 설치해야 합니다(항목마다 표시합니다). 쓰고 있는 앱(예: 휴대폰과 연결)은 선택하지 마세요. 원격 분석·Cortana 항목은 정책만 바꾸며 '변경 내역 · 되돌리기' 에서 되돌릴 수 있습니다.
            </p>
          </div>

          <div className="glass-panel p-5 text-center">
            <h3 className="font-bold text-black dark:text-white mb-2">선택된 항목: {selectedIds.length}개</h3>
            <button
              onClick={startDebloat}
              disabled={selectedIds.length === 0 || isScanning || restoring}
              className={`w-full py-4 rounded-xl font-bold flex items-center justify-center gap-2 transition-all ${
                selectedIds.length === 0
                  ? 'bg-gray-200 dark:bg-zinc-800 text-gray-400 cursor-not-allowed'
                  : 'bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/20'
              }`}
            >
              {isScanning ? (
                <>
                  <RotateCw className="w-5 h-5 animate-spin" />
                  <span>진행 중...</span>
                </>
              ) : (
                <>
                  <Trash2 className="w-5 h-5" />
                  <span>선택 항목 제거·적용</span>
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

      {/* 제거한 앱 — 되살리기 */}
      {removedApps !== null && (removedApps.length > 0 || restoreResult) && (
        <div className="glass-panel p-6">
          <div className="flex items-center justify-between gap-3 mb-4">
            <div>
              <h3 className="font-bold text-black dark:text-white flex items-center gap-2">
                <PackageX className="w-4 h-4 text-cyan-400" />
                제거한 앱 {removedApps.length}개
              </h3>
              <p className="text-sm text-gray-500 mt-0.5">
                이 프로그램이 제거한 앱입니다. 앱의 설치 파일을 다시 등록해 되살립니다.
              </p>
            </div>
            {removedApps.length > 0 && (
              <button
                onClick={() => restoreApps(null)}
                disabled={isScanning || restoring}
                className="shrink-0 flex items-center gap-2 px-4 py-2.5 rounded-xl font-bold text-sm bg-cyan-500 text-black disabled:opacity-40"
              >
                {restoring ? <Loader2 className="w-4 h-4 animate-spin" /> : <Undo2 className="w-4 h-4" />}
                모두 되살리기
              </button>
            )}
          </div>

          <div className="space-y-2">
            {removedApps.map((app) => (
              <div key={app.fullName} className="p-3.5 rounded-xl border border-black/10 dark:border-slate-700 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-bold text-sm text-black dark:text-white">
                    {app.appName ? `${app.appName} · ` : ''}{app.label || app.name}
                  </p>
                  <p className="text-[0.6875rem] text-gray-500 font-mono truncate">{app.name}</p>
                  <p className="text-[0.6875rem] text-gray-500">
                    {app.removedAt} 제거{app.account ? ` · 계정 ${app.account}` : ''}
                    {app.manifestFound === false && ' · 설치 파일이 남아 있지 않아 Microsoft Store 에서 다시 설치해야 합니다'}
                  </p>
                </div>
                <button
                  onClick={() => restoreApps([app.fullName])}
                  disabled={isScanning || restoring}
                  className="shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-xl font-bold text-xs border border-black/10 dark:border-slate-700 hover:border-cyan-500 disabled:opacity-40"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> 되살리기
                </button>
              </div>
            ))}
          </div>

          {restoreResult && (
            <div className="mt-4 flex items-start gap-3">
              {restoreResult.success
                ? <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                : <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />}
              <div className="min-w-0">
                <p className="font-bold text-sm text-black dark:text-white">{restoreResult.message}</p>
                {(restoreResult.failed || []).length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {restoreResult.failed.map((f, i) => (
                      <li key={i} className="text-xs text-gray-500 break-all">
                        · {f.label || f.name}: {f.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
