import React, { useState, useEffect, useCallback } from 'react';
import {
  HardDrive, Trash2, SearchCode, Gauge, Loader2, AlertTriangle,
  CheckCircle2, ChevronDown, RotateCcw, Play, XCircle, Info
} from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;
const fmtMB = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${Number(mb || 0).toFixed(1)} MB`);

const SECTIONS = [
  { id: 'junk', label: '정크 파일', icon: Trash2 },
  { id: 'files', label: '대용량 · 중복', icon: SearchCode },
  { id: 'disk', label: '디스크 최적화', icon: Gauge },
];

export default function StorageCenter({ addToast }) {
  const [tab, setTab] = useState('junk');
  const [overview, setOverview] = useState(null);

  const loadOverview = useCallback(async () => {
    const a = api();
    if (!a?.getStorageOverview) return;
    try {
      setOverview(await a.getStorageOverview());
    } catch (e) {
      console.error('저장공간 현황 조회 실패:', e);
    }
  }, []);

  useEffect(() => {
    loadOverview();
    const onReady = () => loadOverview();
    window.addEventListener('pywebviewready', onReady);
    return () => window.removeEventListener('pywebviewready', onReady);
  }, [loadOverview]);

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6">
        <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold">
          <HardDrive className="w-4 h-4" /> STORAGE
        </div>
        <h2 className="text-2xl font-black text-black dark:text-white tracking-tight mt-1">저장공간 정리</h2>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
          정리 대상을 먼저 보여주고, 확인한 뒤에만 지웁니다. 사용자 파일은 휴지통을 거칩니다.
        </p>

        {overview && (
          <div className="mt-5 space-y-3">
            {overview.drives.map((d) => (
              <div key={d.mount}>
                <div className="flex justify-between items-baseline text-sm mb-1.5">
                  <span className="font-bold text-black dark:text-white">
                    {d.label}
                    <span className="ml-2 text-[11px] font-mono text-gray-500 uppercase">
                      {d.fstype}{d.mediaType !== 'unknown' && ` · ${d.mediaType.toUpperCase()}`}
                    </span>
                  </span>
                  <span className="font-mono text-xs text-gray-500">
                    {d.freeGB}GB 남음 / {d.totalGB}GB
                  </span>
                </div>
                <div className="h-2.5 rounded-full bg-gray-200 dark:bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${d.low ? 'bg-rose-500' : 'bg-cyan-500'}`}
                    style={{ width: `${d.percent}%` }}
                  />
                </div>
              </div>
            ))}
            {overview.lowDrives.length > 0 && (
              <p className="text-xs text-rose-400 flex items-center gap-1.5 pt-1">
                <AlertTriangle className="w-3.5 h-3.5" />
                {overview.lowDrives.join(', ')} 의 여유 공간이 10% 미만입니다. Windows 자체가 느려질 수 있습니다.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="flex gap-2">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setTab(s.id)}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold transition-colors ${
              tab === s.id
                ? 'bg-cyan-500 text-black'
                : 'border border-black/10 dark:border-slate-700 text-gray-500 hover:border-cyan-500'
            }`}
          >
            <s.icon className="w-4 h-4" /> {s.label}
          </button>
        ))}
      </div>

      {tab === 'junk' && <JunkSection addToast={addToast} onDone={loadOverview} />}
      {tab === 'files' && <FileSection addToast={addToast} onDone={loadOverview} />}
      {tab === 'disk' && <DiskSection addToast={addToast} overview={overview} />}
    </div>
  );
}

/* ───────────────────────── 정크 정리 ───────────────────────── */
function JunkSection({ addToast, onDone }) {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [scanning, setScanning] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);

  const scan = useCallback(async () => {
    const a = api();
    if (!a?.scanJunk) return;
    setScanning(true);
    setResult(null);
    try {
      await a.scanJunk();
      // 스캔은 백그라운드 스레드라 상태를 폴링해야 한다
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 400));
        const st = await a.getJunkScanStatus();
        if (st?.data) {
          setItems(st.data);
          // 백엔드가 정한 기본 선택을 그대로 따른다.
          // 휴지통 비우기는 되돌릴 수 없어 기본 해제로 내려온다.
          setSelected(new Set(st.data.filter((d) => d.selected).map((d) => d.id)));
        }
        if (st?.status !== 'running') break;
      }
    } catch (e) {
      addToast?.(`스캔 실패: ${e}`, 'error');
    }
    setScanning(false);
  }, [addToast]);

  useEffect(() => { scan(); }, [scan]);

  const toggle = (id) => setSelected((s) => {
    const n = new Set(s);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });

  const chosen = items.filter((i) => selected.has(i.id));
  const totalMB = chosen.reduce((s, i) => s + (i.sizeMB || 0), 0);
  const hasIrreversible = chosen.some((i) => i.irreversible);

  const clean = async () => {
    const a = api();
    if (!a?.cleanJunk || !chosen.length) return;

    // 무엇이 지워지는지 먼저 보여준다. 예전에는 확인 절차가 전혀 없었다.
    const lines = chosen.map((i) => `  · ${i.name} (${fmtMB(i.sizeMB)})`).join('\n');
    const warn = hasIrreversible
      ? '\n\n★ 휴지통 비우기가 포함되어 있습니다. 이 항목은 되돌릴 수 없습니다.'
      : '';
    if (!window.confirm(`다음 항목을 정리합니다 (약 ${fmtMB(totalMB)}):\n\n${lines}${warn}\n\n계속할까요?`)) return;

    setCleaning(true);
    setResult(null);
    try {
      await a.cleanJunk([...selected]);
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 400));
        const st = await a.getJunkCleanStatus();
        setProgress(st);
        if (st?.status !== 'running') {
          setResult(st);
          break;
        }
      }
    } catch (e) {
      addToast?.(`정리 실패: ${e}`, 'error');
    }
    setCleaning(false);
    setProgress(null);
    onDone?.();
    scan();
  };

  const cancel = async () => {
    const a = api();
    if (a?.cancelJunkClean) {
      await a.cancelJunkClean();
      addToast?.('정리를 중단했습니다. 이미 삭제된 파일은 되돌아오지 않습니다.', 'error');
    }
  };

  return (
    <div className="space-y-4">
      <div className="glass-panel p-5">
        <div className="flex items-center justify-between gap-3 mb-4">
          <h3 className="font-bold text-black dark:text-white">정리 대상</h3>
          <button onClick={scan} disabled={scanning || cleaning}
            className="text-xs font-bold text-cyan-500 hover:text-cyan-400 flex items-center gap-1 disabled:opacity-40">
            {scanning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
            다시 검사
          </button>
        </div>

        {scanning && !items.length && (
          <p className="text-sm text-gray-500 py-6 text-center">검사 중...</p>
        )}

        <div className="space-y-2">
          {items.map((it) => (
            <button
              key={it.id}
              onClick={() => toggle(it.id)}
              disabled={cleaning}
              className={`w-full text-left p-3.5 rounded-xl border transition-colors disabled:opacity-50 ${
                selected.has(it.id)
                  ? 'border-cyan-500/50 bg-cyan-500/5'
                  : 'border-black/10 dark:border-slate-700 hover:border-black/20'
              }`}
            >
              <div className="flex items-center gap-3">
                <div className={`w-5 h-5 rounded shrink-0 grid place-items-center border ${
                  selected.has(it.id) ? 'bg-cyan-500 border-cyan-500' : 'border-gray-300 dark:border-slate-600'}`}>
                  {selected.has(it.id) && <CheckCircle2 className="w-3.5 h-3.5 text-black" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="font-bold text-sm text-black dark:text-white truncate">{it.name}</p>
                    {it.irreversible && (
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-400 shrink-0">
                        되돌릴 수 없음
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">{it.description}</p>
                </div>
                <span className="font-mono text-sm font-bold text-black dark:text-white shrink-0">
                  {fmtMB(it.sizeMB)}
                </span>
              </div>
            </button>
          ))}
        </div>

        {cleaning && progress && (
          <div className="mt-4 pt-4 border-t border-black/5 dark:border-slate-800">
            <div className="flex justify-between text-xs mb-1.5">
              <span className="text-gray-500">정리 중... {progress.progress ?? 0}%</span>
              <button onClick={cancel} className="text-rose-400 font-bold flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> 중단
              </button>
            </div>
            <div className="h-2 rounded-full bg-gray-200 dark:bg-slate-800 overflow-hidden">
              <div className="h-full bg-cyan-500 transition-all" style={{ width: `${progress.progress ?? 0}%` }} />
            </div>
          </div>
        )}

        <button
          onClick={clean}
          disabled={cleaning || scanning || !chosen.length}
          className="w-full mt-4 py-3.5 rounded-xl font-bold bg-cyan-500 text-black disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {cleaning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
          {chosen.length ? `${chosen.length}개 항목 정리 (약 ${fmtMB(totalMB)})` : '정리할 항목을 선택하세요'}
        </button>
      </div>

      {result && (
        <div className="glass-panel p-5 flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold text-black dark:text-white">
              {fmtMB(result.freed_mb)} 를 확보했습니다.
            </p>
            {result.skipped_mb > 0 && (
              <p className="text-xs text-gray-500 mt-1">
                {fmtMB(result.skipped_mb)} 는 다른 프로그램이 사용 중이라 건너뛰었습니다.
                바탕화면의 APEX_Skipped_Files.log 에서 목록을 볼 수 있습니다.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─────────────────── 대용량 · 중복 파일 ─────────────────── */
function FileSection({ addToast, onDone }) {
  const [mode, setMode] = useState('large');
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [minMB, setMinMB] = useState(500);

  const run = async () => {
    const a = api();
    if (!a) return;
    setBusy(true);
    setRows([]);
    setSelected(new Set());
    try {
      const res = mode === 'large'
        ? await a.findLargeFiles(minMB)
        : await a.findDuplicateFiles();
      setRows(Array.isArray(res) ? res : (res?.files || res?.groups || []));
    } catch (e) {
      addToast?.(`검색 실패: ${e}`, 'error');
    }
    setBusy(false);
  };

  const toggle = (p) => setSelected((s) => {
    const n = new Set(s);
    n.has(p) ? n.delete(p) : n.add(p);
    return n;
  });

  const remove = async () => {
    const a = api();
    if (!a?.deleteFiles || !selected.size) return;
    if (!window.confirm(
      `${selected.size}개 파일을 휴지통으로 보냅니다.\n\n휴지통에서 복구할 수 있습니다.\n계속할까요?`
    )) return;
    setBusy(true);
    try {
      const res = await a.deleteFiles([...selected]);
      addToast?.(res?.message || '삭제했습니다.', res?.success ? 'success' : 'error');
      if (res?.failed?.length) {
        console.warn('삭제 실패 목록:', res.failed);
      }
      setSelected(new Set());
      run();
      onDone?.();
    } catch (e) {
      addToast?.(`삭제 실패: ${e}`, 'error');
    }
    setBusy(false);
  };

  return (
    <div className="glass-panel p-5 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {[['large', '대용량 파일'], ['dup', '중복 파일']].map(([k, label]) => (
          <button key={k} onClick={() => { setMode(k); setRows([]); setSelected(new Set()); }}
            className={`px-3.5 py-2 rounded-lg text-sm font-bold transition-colors ${
              mode === k ? 'bg-cyan-500 text-black' : 'border border-black/10 dark:border-slate-700 text-gray-500'}`}>
            {label}
          </button>
        ))}
        {mode === 'large' && (
          <select value={minMB} onChange={(e) => setMinMB(Number(e.target.value))}
            className="px-3 py-2 rounded-lg text-sm bg-white dark:bg-slate-900 border border-black/10 dark:border-slate-700">
            {[100, 300, 500, 1000, 2000].map((v) => <option key={v} value={v}>{v}MB 이상</option>)}
          </select>
        )}
        <button onClick={run} disabled={busy}
          className="ml-auto px-4 py-2 rounded-lg text-sm font-bold bg-cyan-500 text-black disabled:opacity-40 flex items-center gap-2">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} 검색
        </button>
      </div>

      <div className="flex gap-2 text-xs">
        <Info className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
        <p className="text-gray-500 dark:text-gray-400 leading-relaxed">
          시스템 폴더와 게임 설치 폴더는 검색에서 제외됩니다. 삭제는 휴지통을 거치므로
          잘못 골라도 복구할 수 있습니다. <strong className="text-black dark:text-white">선택은 직접 하세요</strong> —
          자동으로 체크되는 항목은 없습니다.
        </p>
      </div>

      <div className="max-h-[420px] overflow-y-auto custom-scrollbar space-y-1.5 pr-1">
        {!rows.length && !busy && (
          <p className="text-sm text-gray-500 py-8 text-center">검색 버튼을 눌러 시작하세요.</p>
        )}
        {rows.map((f, i) => {
          const path = f.path || f;
          return (
            <button key={path + i} onClick={() => toggle(path)}
              className={`w-full text-left flex items-center gap-3 p-2.5 rounded-lg border transition-colors ${
                selected.has(path) ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-black/5 dark:border-slate-800'}`}>
              <div className={`w-4 h-4 rounded shrink-0 border ${
                selected.has(path) ? 'bg-cyan-500 border-cyan-500' : 'border-gray-300 dark:border-slate-600'}`} />
              <span className="text-xs font-mono text-black/80 dark:text-white/80 truncate flex-1">{path}</span>
              {f.sizeMB != null && (
                <span className="text-xs font-mono font-bold shrink-0">{fmtMB(f.sizeMB)}</span>
              )}
            </button>
          );
        })}
      </div>

      {selected.size > 0 && (
        <button onClick={remove} disabled={busy}
          className="w-full py-3 rounded-xl font-bold bg-rose-500 text-white disabled:opacity-40 flex items-center justify-center gap-2">
          <Trash2 className="w-4 h-4" /> 선택한 {selected.size}개를 휴지통으로
        </button>
      )}
    </div>
  );
}

/* ───────────────────── 디스크 최적화 ───────────────────── */
function DiskSection({ addToast, overview }) {
  const [status, setStatus] = useState(null);
  const [running, setRunning] = useState(false);

  const start = async () => {
    const a = api();
    if (!a?.runTrim) return;
    setRunning(true);
    try {
      const res = await a.runTrim();
      if (!res?.success) {
        addToast?.(res?.message || '이미 실행 중입니다.', 'error');
        setRunning(false);
        return;
      }
      for (let i = 0; i < 900; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const st = await a.getTrimStatus();
        setStatus(st);
        if (st?.status !== 'running') break;
      }
      addToast?.('디스크 최적화를 마쳤습니다.', 'success');
    } catch (e) {
      addToast?.(`실행 실패: ${e}`, 'error');
    }
    setRunning(false);
  };

  const hasHdd = overview?.drives?.some((d) => d.mediaType === 'hdd');

  return (
    <div className="glass-panel p-6 space-y-4">
      <h3 className="font-bold text-black dark:text-white">디스크 최적화 (TRIM / 조각모음)</h3>
      <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
        Windows 기본 도구로 모든 볼륨을 최적화합니다. 매체에 맞는 작업이 자동으로 선택됩니다 —
        <strong className="text-black dark:text-white"> SSD 는 TRIM</strong>(빈 블록 정리, 수 초),
        <strong className="text-black dark:text-white"> HDD 는 조각모음</strong>(수십 분 걸릴 수 있음).
      </p>

      {overview?.drives && (
        <div className="flex flex-wrap gap-2">
          {overview.drives.map((d) => (
            <span key={d.mount} className="text-xs font-mono px-2.5 py-1 rounded-lg border border-black/10 dark:border-slate-700">
              {d.label} {d.mediaType === 'unknown' ? '종류 확인 불가' : d.mediaType.toUpperCase()}
            </span>
          ))}
        </div>
      )}

      {!hasHdd && overview?.drives?.length > 0 && (
        <div className="flex gap-2 text-xs">
          <Info className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
          <p className="text-gray-500 dark:text-gray-400">
            전부 SSD 입니다. TRIM 만 수행되며 보통 몇 초 안에 끝납니다.
            SSD 에 조각모음을 하면 수명만 깎이므로 Windows 가 알아서 하지 않습니다.
          </p>
        </div>
      )}

      {status && (
        <div className="text-sm">
          <p className="text-gray-500">
            상태: <span className="font-mono font-bold text-black dark:text-white">{status.status}</span>
          </p>
          {status.error && <p className="text-rose-400 text-xs mt-1">{status.error}</p>}
        </div>
      )}

      <button onClick={start} disabled={running}
        className="w-full py-3.5 rounded-xl font-bold bg-cyan-500 text-black disabled:opacity-40 flex items-center justify-center gap-2">
        {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Gauge className="w-4 h-4" />}
        {running ? '최적화 중... (중단하지 마세요)' : '디스크 최적화 시작'}
      </button>
    </div>
  );
}
