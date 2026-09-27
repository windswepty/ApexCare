import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  FileCog,
  XCircle,
  MinusCircle,
  HelpCircle,
  Undo2,
} from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;

/** 백엔드가 돌려주는 항목별 결과 상태. 변경이 없던 항목은 성공으로 세지 않는다. */
const STATUS_META = {
  removed: { label: '제거함', tone: 'ok' },
  applied: { label: '적용함', tone: 'ok' },
  not_installed: { label: '설치돼 있지 않음', tone: 'skip' },
  already: { label: '이미 적용돼 있음', tone: 'skip' },
  partial: { label: '일부만 됨', tone: 'warn' },
  unknown: { label: '확인 못 함', tone: 'warn' },
  failed: { label: '실패', tone: 'bad' },
};

const TONE_ICON = {
  ok: <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />,
  skip: <MinusCircle className="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />,
  warn: <HelpCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />,
  bad: <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />,
};

/** 미리보기 상태를 카드에 붙일 한 줄 설명과 선택 가능 여부로 바꾼다. */
function describeState(item, pv) {
  if (!pv) return { text: '', selectable: true };
  if (item.kind === 'appx') {
    if (pv.state === 'not_installed') return { text: '설치돼 있지 않음', selectable: false };
    if (pv.state === 'installed') {
      return { text: `설치됨: ${(pv.installed || []).map((p) => p.name).join(', ')}`, selectable: true };
    }
    return { text: '설치 상태를 확인하지 못했습니다', selectable: true };
  }
  if (pv.state === 'applied') {
    return pv.recorded
      ? { text: '적용돼 있음 · 복구 센터에서 되돌릴 수 있음', selectable: false }
      : { text: '이미 설정돼 있음 · APEX CARE 기록 없음 (다른 프로그램, 조직 정책, 이전 버전이 설정했을 수 있음)', selectable: false };
  }
  if (pv.state === 'partial') {
    const done = (pv.steps || []).filter((s) => s.applied).map((s) => s.label);
    return { text: `일부 적용돼 있음: ${done.join(', ')}`, selectable: true };
  }
  if (pv.state === 'unknown') return { text: '현재 값을 읽지 못했습니다', selectable: true };
  return { text: '', selectable: true };
}

export default function Debloater({ addToast }) {
  const [items, setItems] = useState([]);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState({ running: false, progress_pct: 0, current_task: '' });
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [removedApps, setRemovedApps] = useState(null);   // null = API 없음
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState(null);
  const pollRef = useRef(null);

  const fetchItems = useCallback(async () => {
    const a = api();
    if (!a?.getDebloatList) return;
    try {
      const list = await a.getDebloatList();
      setItems(Array.isArray(list) ? list : []);
    } catch (e) {
      console.error('Error fetching debloat list:', e);
      setItems([]);
    }
  }, []);

  // 설치 여부·현재 정책 값을 읽기만 한다. 몇 초 걸린다.
  const fetchPreview = useCallback(async () => {
    const a = api();
    if (!a?.getDebloatPreview) return;
    setPreviewLoading(true);
    try {
      const pv = await a.getDebloatPreview();
      setPreview(pv && pv.items ? pv : null);
    } catch (e) {
      console.error('Error fetching debloat preview:', e);
      setPreview(null);
    }
    setPreviewLoading(false);
  }, []);

  const fetchRemoved = useCallback(async () => {
    const a = api();
    if (!a?.getRemovedDebloatApps) return;
    try {
      const list = await a.getRemovedDebloatApps();
      setRemovedApps(Array.isArray(list) ? list : []);
    } catch (e) {
      console.error('Error fetching removed apps:', e);
    }
  }, []);

  const refreshAll = useCallback(() => {
    fetchItems();
    fetchPreview();
    fetchRemoved();
  }, [fetchItems, fetchPreview, fetchRemoved]);

  useEffect(() => {
    if (api()?.getDebloatList) {
      refreshAll();
    } else {
      window.addEventListener('pywebviewready', refreshAll);
    }
    return () => {
      window.removeEventListener('pywebviewready', refreshAll);
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refreshAll]);

  // 다시 확인한 뒤 '설치돼 있지 않음' 이나 '이미 적용됨' 이 된 항목은 선택에서 뺀다
  useEffect(() => {
    setSelectedIds((prev) => prev.filter((id) => {
      const it = items.find((x) => x.id === id);
      return it && describeState(it, preview?.items?.[id]).selectable;
    }));
  }, [preview, items]);

  const stateOf = (item) => describeState(item, preview?.items?.[item.id]);
  const selectable = items.filter((it) => stateOf(it).selectable);
  const chosen = items.filter((it) => selectedIds.includes(it.id));
  const chosenApps = chosen.filter((it) => it.kind === 'appx');
  const chosenPolicies = chosen.filter((it) => it.kind === 'policy');
  const account = preview?.account || '';
  const desktopAccount = preview?.desktopAccount || '';
  const otherAccount = account && desktopAccount && account.toLowerCase() !== desktopAccount.toLowerCase();

  const toggleItem = (id) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const allSelected = selectable.length > 0 && selectable.every((it) => selectedIds.includes(it.id));
  const selectAll = () => {
    setSelectedIds(allSelected ? [] : selectable.map((x) => x.id));
  };

  const finish = (st) => {
    setIsRunning(false);
    setLastResult(st);
    if (st.error) {
      addToast?.(`오류 발생: ${st.error}`, 'error');
    } else {
      // 백엔드가 항목별 성패를 돌려준다. 그대로 보여준다.
      const failed = st.failed || [];
      const succeeded = st.succeeded || [];
      const skipped = st.skipped || [];
      if (failed.length > 0) {
        addToast?.(`${succeeded.length}개 완료, ${failed.length}개 실패`, 'error');
      } else if (succeeded.length > 0) {
        addToast?.(`${succeeded.length}개 항목을 처리했습니다.${skipped.length ? ` (${skipped.length}개 변경 없음)` : ''}`, 'success');
      } else {
        addToast?.('변경한 항목이 없습니다.', 'error');
      }
    }
    setSelectedIds([]);
    refreshAll();
  };

  const startDebloat = async () => {
    setConfirmOpen(false);
    const a = api();
    if (!a?.startDebloater || selectedIds.length === 0) {
      addToast?.('API가 준비되지 않았습니다.', 'error');
      return;
    }
    setIsRunning(true);
    setLastResult(null);
    setStatus({ running: true, progress_pct: 0, current_task: '시작 중...' });
    try {
      const res = await a.startDebloater(selectedIds);
      if (!res?.success) {
        addToast?.(res?.message || '시작하지 못했습니다.', 'error');
        setIsRunning(false);
        return;
      }
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const st = await a.getDebloatStatus();
          if (!st) return;
          setStatus(st);
          if (!st.running) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            finish(st);
          }
        } catch (e) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setIsRunning(false);
          addToast?.(`진행 상태를 읽지 못했습니다: ${e}`, 'error');
        }
      }, 500);
    } catch (e) {
      console.error('Error starting debloater:', e);
      addToast?.(`시작하지 못했습니다: ${e}`, 'error');
      setIsRunning(false);
    }
  };

  const restoreApps = async (names) => {
    const a = api();
    if (!a?.restoreRemovedDebloatApps) return;
    setRestoring(true);
    setRestoreResult(null);
    try {
      const res = await a.restoreRemovedDebloatApps(names || null);
      setRestoreResult(res);
      addToast?.(res?.message || '되살리기를 마쳤습니다.', res?.success ? 'success' : 'error');
    } catch (e) {
      addToast?.(`되살리기 실패: ${e}`, 'error');
    }
    setRestoring(false);
    refreshAll();
  };

  const busy = isRunning || restoring;

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
        <div className="space-y-1 z-10">
          <div className="flex items-center gap-2 text-red-400 font-mono text-xs font-semibold">
            <ServerCrash className="w-4 h-4" />
            WINDOWS DEBLOATER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white tracking-tight">윈도우 하드코어 적출</h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm max-w-xl">
            쓰지 않는 기본 앱을 현재 계정에서 제거하고, 진단 데이터·Cortana 정책을 바꿉니다.
            항목마다 실제로 바뀌는 내용을 적어 두었습니다.
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
          <div className="flex justify-between items-center px-2 gap-3">
            <h3 className="font-bold text-black dark:text-white">항목 ({items.length})</h3>
            <div className="flex items-center gap-4">
              <button
                onClick={fetchPreview}
                disabled={previewLoading || busy}
                className="text-xs font-bold text-cyan-500 hover:text-cyan-400 flex items-center gap-1 disabled:opacity-40"
              >
                {previewLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
                {previewLoading ? '확인 중...' : '다시 확인'}
              </button>
              <button
                onClick={selectAll}
                disabled={busy || selectable.length === 0}
                className="text-xs font-bold text-cyan-500 hover:text-cyan-400 transition-colors disabled:opacity-40"
              >
                {allSelected ? '전체 해제' : '전체 선택'}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[560px] overflow-y-auto pr-2 custom-scrollbar">
            {items.map((item) => {
              const st = stateOf(item);
              const selected = selectedIds.includes(item.id);
              const disabled = busy || !st.selectable;
              return (
                <div
                  key={item.id}
                  onClick={() => !disabled && toggleItem(item.id)}
                  className={`glass-panel p-4 flex items-start gap-3 transition-all duration-300 border-2 ${
                    selected
                      ? 'border-red-500/50 bg-red-500/5'
                      : 'border-transparent hover:border-black/10 dark:hover:border-white/10'
                  } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                >
                  <div className={`w-5 h-5 mt-0.5 rounded flex items-center justify-center shrink-0 border transition-colors ${
                    selected ? 'bg-red-500 border-red-500' : 'border-gray-300 dark:border-gray-600'
                  }`}>
                    {selected && <CheckCircle2 className="w-3.5 h-3.5 text-white" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-sm text-black dark:text-white">{item.name}</span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        item.kind === 'policy' ? 'bg-amber-500/10 text-amber-500' : 'bg-cyan-500/10 text-cyan-500'
                      }`}>
                        {item.kind === 'policy' ? '정책 변경' : '앱 제거'}
                      </span>
                    </div>
                    <ul className="mt-1 space-y-0.5">
                      {(item.changes || []).map((c, i) => (
                        <li key={i} className="text-[11px] text-gray-500 font-mono break-all">{c}</li>
                      ))}
                    </ul>
                    {item.note && <p className="text-[11px] text-gray-500 mt-1">{item.note}</p>}
                    {st.text && (
                      <p className={`text-[11px] mt-1 font-semibold ${st.selectable ? 'text-black/60 dark:text-white/60' : 'text-gray-400'}`}>
                        {st.text}
                      </p>
                    )}
                  </div>
                </div>
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
            <ul className="text-xs text-black/70 dark:text-white/70 leading-relaxed space-y-1.5">
              <li>· 앱 제거는 현재 계정에서만 합니다. 다른 계정과 새로 만들 계정은 그대로입니다.</li>
              <li>· 제거한 앱은 아래 '제거한 앱' 에서 되살립니다. 안 되면 Microsoft Store 에서 다시 설치할 수 있습니다.</li>
              <li>· 정책 항목은 설정 앱에서 '조직에서 관리' 로 잠깁니다. 복구 센터에서 되돌립니다.</li>
              <li>· 쓰고 있는 앱(휴대폰과 연결, Xbox 등)은 선택하지 마세요.</li>
            </ul>
            {otherAccount && (
              <p className="text-xs text-amber-500 mt-3">
                APEX CARE 가 다른 계정({account})으로 실행 중입니다. 앱은 그 계정에서 제거되고,
                지금 바탕 화면 계정({desktopAccount})의 앱은 그대로 남습니다.
              </p>
            )}
          </div>

          <div className="glass-panel p-5 text-center">
            <h3 className="font-bold text-black dark:text-white mb-2">선택된 항목: {selectedIds.length}개</h3>
            <button
              onClick={() => setConfirmOpen(true)}
              disabled={selectedIds.length === 0 || busy}
              className={`w-full py-4 rounded-xl font-bold flex items-center justify-center gap-2 transition-all ${
                selectedIds.length === 0 || busy
                  ? 'bg-gray-200 dark:bg-zinc-800 text-gray-400 cursor-not-allowed'
                  : 'bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/20'
              }`}
            >
              {isRunning ? (
                <>
                  <RotateCw className="w-5 h-5 animate-spin" />
                  <span>진행 중...</span>
                </>
              ) : (
                <>
                  <Trash2 className="w-5 h-5" />
                  <span>선택 항목 실행</span>
                </>
              )}
            </button>
          </div>

          {isRunning && (
            <div className="glass-panel p-5">
              <div className="flex justify-between text-xs font-mono mb-2 gap-2">
                <span className="text-gray-500 truncate">{status.current_task}</span>
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

          {!isRunning && lastResult && (
            <div className="glass-panel p-5">
              <p className="font-bold text-sm text-black dark:text-white mb-3">
                {lastResult.error ? `오류 발생: ${lastResult.error}` : lastResult.current_task}
              </p>
              <ul className="space-y-2">
                {(lastResult.results || []).map((r) => {
                  const meta = STATUS_META[r.status] || STATUS_META.failed;
                  return (
                    <li key={r.id} className="flex items-start gap-2 text-xs">
                      {TONE_ICON[meta.tone]}
                      <div className="min-w-0">
                        <span className="font-bold text-black dark:text-white">{r.name}</span>
                        <span className="text-gray-500"> · {meta.label}</span>
                        {r.detail && <p className="text-gray-500 break-all mt-0.5">{r.detail}</p>}
                      </div>
                    </li>
                  );
                })}
              </ul>
              {(lastResult.results || []).some((r) => r.kind === 'policy' && ['applied', 'partial'].includes(r.status)) && (
                <p className="text-xs text-gray-500 mt-3">바뀐 정책은 복구 센터에서 되돌릴 수 있습니다.</p>
              )}
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
                이 프로그램이 현재 계정에서 제거한 앱입니다. 다시 등록해 되살립니다.
              </p>
            </div>
            {removedApps.length > 0 && (
              <button
                onClick={() => restoreApps(null)}
                disabled={busy}
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
                  <p className="font-bold text-sm text-black dark:text-white">{app.label || app.name}</p>
                  <p className="text-[11px] text-gray-500 font-mono truncate">{app.name}</p>
                  <p className="text-[11px] text-gray-500">
                    {app.removedAt} 제거{app.account ? ` · 계정 ${app.account}` : ''}
                    {app.manifestFound === false && ' · 설치 파일이 남아 있지 않아 Microsoft Store 에서 다시 설치해야 합니다'}
                  </p>
                </div>
                <button
                  onClick={() => restoreApps([app.fullName])}
                  disabled={busy}
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

      {/* 실행 전 확인 — 앱 제거와 정책 변경은 영향이 달라 따로 적는다 */}
      {confirmOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setConfirmOpen(false)}></div>
          <div className="relative glass-panel bg-white dark:bg-zinc-900 p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto space-y-5 rounded-2xl shadow-2xl">
            <h3 className="text-lg font-bold text-black dark:text-white">다음 내용을 실행합니다</h3>

            {chosenApps.length > 0 && (
              <div className="space-y-2">
                <p className="font-bold text-sm text-black dark:text-white flex items-center gap-2">
                  <PackageX className="w-4 h-4 text-cyan-500" /> 앱 제거 ({chosenApps.length}개)
                </p>
                <ul className="space-y-1">
                  {chosenApps.map((it) => {
                    const inst = preview?.items?.[it.id]?.installed;
                    const pk = inst && inst.length ? inst.map((p) => p.name) : it.packages || [];
                    return (
                      <li key={it.id} className="text-xs text-gray-500">
                        · {it.name} <span className="font-mono">({pk.join(', ')})</span>
                      </li>
                    );
                  })}
                </ul>
                <p className="text-xs text-black/70 dark:text-white/70 leading-relaxed">
                  현재 계정{account ? `(${account})` : ''}에서만 제거합니다. 다른 계정과 새로 만들 계정은 그대로입니다.
                  이 화면의 '제거한 앱' 에서 되살릴 수 있고, 안 되면 Microsoft Store 에서 다시 설치할 수 있습니다.
                </p>
                {otherAccount && (
                  <p className="text-xs text-amber-500">
                    지금 바탕 화면 계정({desktopAccount})의 앱은 제거되지 않습니다.
                  </p>
                )}
              </div>
            )}

            {chosenPolicies.length > 0 && (
              <div className="space-y-2">
                <p className="font-bold text-sm text-black dark:text-white flex items-center gap-2">
                  <FileCog className="w-4 h-4 text-amber-500" /> 정책 변경 ({chosenPolicies.length}개)
                </p>
                <ul className="space-y-1">
                  {chosenPolicies.map((it) => (
                    <li key={it.id} className="text-xs text-gray-500">
                      · {it.name}
                      {(it.changes || []).map((c, i) => (
                        <span key={i} className="block pl-3 font-mono">{c}</span>
                      ))}
                      {it.note && <span className="block pl-3">{it.note}</span>}
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-black/70 dark:text-white/70 leading-relaxed">
                  설정 앱의 관련 항목이 '조직에서 관리' 로 잠기고, 재부팅 후에도 유지됩니다.
                  원래 값을 기록해 두며, 복구 센터에서 되돌릴 수 있습니다.
                </p>
              </div>
            )}

            <div className="flex gap-3 pt-1">
              <button
                onClick={() => setConfirmOpen(false)}
                className="flex-1 py-3 rounded-xl font-bold text-sm border border-black/10 dark:border-slate-700 text-black dark:text-white"
              >
                취소
              </button>
              <button
                onClick={startDebloat}
                className="flex-1 py-3 rounded-xl font-bold text-sm bg-red-500 hover:bg-red-600 text-white"
              >
                실행
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
