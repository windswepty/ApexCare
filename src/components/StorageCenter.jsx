import { useState, useEffect, useCallback, useRef } from 'react';
import {
  HardDrive, Trash2, SearchCode, Gauge, Loader2, AlertTriangle,
  CheckCircle2, RotateCcw, Play, XCircle, Info, Copy
} from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;
const fmtMB = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${Number(mb || 0).toFixed(1)} MB`);
// 백엔드가 크기를 읽지 못한 항목(null)은 0 MB 가 아니라 '크기 모름'
const sizeText = (mb) => (mb == null ? '크기 모름' : fmtMB(mb));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 디스크 최적화 상태를 사람이 읽는 말로. 예전에는 'running'·'error' 같은 내부 값이 그대로 보였다.
const TRIM_STATUS_LABEL = { idle: '대기 중', running: '진행 중', success: '완료', error: '실패' };

const SECTIONS = [
  { id: 'junk', label: '정크 파일', icon: Trash2 },
  { id: 'files', label: '대용량 · 중복', icon: SearchCode },
  { id: 'disk', label: '디스크 최적화', icon: Gauge },
];

// 숨겨 둔 화면이 다시 보일 때 true 가 된다(처음 보일 때는 아니다). 그동안 다른 화면이 상태를 바꿨을 수 있다.
function useShownAgain(visible) {
  const was = useRef(visible);
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (visible && !was.current) setCount((c) => c + 1);
    was.current = visible;
  }, [visible]);
  return count;
}

export default function StorageCenter({ addToast, active = true }) {
  const [tab, setTab] = useState('junk');
  // 한 번 연 하위 화면은 숨기기만 하고 없애지 않는다. 예전에는 탭을 옮기면 화면이 사라져, 진행 중인 검색·정리 결과가
  // 버려지고 돌아오면 '검색 버튼을 눌러 시작하세요' 가 떠 같은 검색을 두 번 돌리게 됐다.
  const [opened, setOpened] = useState(() => new Set(['junk']));
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
  // 탭을 다시 열면 드라이브 현황도 다시 읽는다(원클릭 정리 뒤 남은 용량이 바뀌었다)
  const shownAgain = useShownAgain(active);
  useEffect(() => { if (shownAgain) loadOverview(); }, [shownAgain, loadOverview]);

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6">
        <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold">
          <HardDrive className="w-4 h-4" /> STORAGE
        </div>
        <h2 className="text-2xl font-black text-black dark:text-white tracking-tight mt-1">저장공간 정리</h2>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
          정리 대상을 먼저 보여주고, 확인한 뒤에만 지웁니다. 대용량·중복 파일은 휴지통을 거칩니다.
          임시 파일·캐시는 휴지통을 거치지 않고 바로 지워집니다.
        </p>

        {overview && (
          <div className="mt-5 space-y-3">
            {overview.drives.map((d) => (
              <div key={d.mount}>
                <div className="flex justify-between items-baseline text-sm mb-1.5">
                  <span className="font-bold text-black dark:text-white">
                    {d.label}
                    <span className="ml-2 text-[0.6875rem] font-mono text-gray-500 uppercase">
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
                {overview.lowDrives.join(', ')} 드라이브의 여유 공간이 10% 미만입니다. Windows 자체가 느려질 수 있습니다.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="flex gap-2">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => { setTab(s.id); setOpened((prev) => new Set(prev).add(s.id)); }}
            aria-pressed={tab === s.id}
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

      {opened.has('junk') && <div hidden={tab !== 'junk'}><JunkSection addToast={addToast} onDone={loadOverview} visible={active && tab === 'junk'} /></div>}
      {opened.has('files') && <div hidden={tab !== 'files'}><FileSection addToast={addToast} onDone={loadOverview} /></div>}
      {opened.has('disk') && <div hidden={tab !== 'disk'}><DiskSection addToast={addToast} overview={overview} visible={active && tab === 'disk'} /></div>}
    </div>
  );
}

/* ───────────────────────── 정크 정리 ───────────────────────── */
function JunkSection({ addToast, onDone, visible = true }) {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState(null);
  const [cleaning, setCleaning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);

  const scan = useCallback(async () => {
    const a = api();
    if (!a?.scanJunk) return;
    setScanning(true);
    setScanError(null);
    try {
      const started = await a.scanJunk();
      if (started && started.success === false && !/이미/.test(started.message || '')) {
        setScanError(started.message || '검사를 시작하지 못했습니다.');
      } else {
        // 스캔은 백그라운드 스레드라 끝날 때까지 상태를 읽는다. 예전에는 48초에서 멈춰,
        // 폴더가 큰 PC 에서는 검사가 끝나지 않았는데 '검사 중' 표시가 사라졌다.
        for (;;) {
          await sleep(400);
          const st = await a.getJunkScanStatus();
          if (st?.status === 'running') continue;
          if (st?.status === 'error') {
            setItems([]);
            setSelected(new Set());
            setScanError(st.error || '검사 중 오류가 났습니다.');
          } else if (Array.isArray(st?.data)) {
            setItems(st.data);
            // 백엔드가 정한 기본 선택을 그대로 따른다.
            // 휴지통 비우기·Windows Update 캐시는 기본 해제로 내려온다.
            setSelected(new Set(st.data.filter((d) => d.selected).map((d) => d.id)));
          }
          break;
        }
      }
    } catch (e) {
      setScanError(`검사하지 못했습니다: ${e}`);
    }
    setScanning(false);
  }, []);

  useEffect(() => { scan(); }, [scan]);
  // 다시 보이면 다시 검사한다. 예전에는 처음 검사한 크기가 계속 남아, 원클릭이 지운 뒤에도 '약 1.5 GB' 로 보였다.
  const shownAgain = useShownAgain(visible);
  const busyRef = useRef(false);
  busyRef.current = scanning || cleaning;
  useEffect(() => { if (shownAgain && !busyRef.current) scan(); }, [shownAgain, scan]);

  const toggle = (id) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  const chosen = items.filter((i) => selected.has(i.id));
  const totalMB = chosen.reduce((s, i) => s + (i.sizeMB || 0), 0);
  // 크기를 모르는 항목이 있으면 합계는 '이상' 이다
  const totalText = `${fmtMB(totalMB)}${chosen.some((i) => i.sizeMB == null) ? ' 이상' : ''}`;
  const hasIrreversible = chosen.some((i) => i.irreversible);

  const clean = async () => {
    const a = api();
    if (!a?.cleanJunk || !chosen.length) return;

    // 무엇이 지워지는지 먼저 보여준다. 예전에는 확인 절차가 전혀 없었다.
    const lines = chosen.map((i) => `  · ${i.name} (${sizeText(i.sizeMB)})`).join('\n');
    const warn = hasIrreversible
      ? '\n\n★ 휴지통 비우기가 포함되어 있습니다. 이 항목은 되돌릴 수 없습니다.'
      : '';
    if (!window.confirm(
      `다음 항목을 정리합니다 (약 ${totalText}):\n\n${lines}\n\n`
      + `임시 파일·캐시는 휴지통을 거치지 않고 바로 지워집니다. 사용 중인 파일은 건너뜁니다.${warn}\n\n계속할까요?`
    )) return;

    setCleaning(true);
    setResult(null);
    try {
      // 확인 창에 보인 휴지통 크기를 함께 넘긴다. 그 뒤 다른 화면에서 휴지통으로 보낸 파일이 있으면 백엔드가 비우지 않는다.
      const bin = chosen.find((i) => i.id === 5);
      const started = await a.cleanJunk([...selected], bin && Number.isInteger(bin.sizeBytes) ? bin.sizeBytes : null);
      if (started && started.success === false) {
        addToast?.(started.message || '정리를 시작하지 못했습니다.', 'error');
      } else {
        for (;;) {
          await sleep(400);
          const st = await a.getJunkCleanStatus();
          setProgress(st);
          if (st?.status !== 'running') {
            setResult(st);
            if (st?.status === 'error') addToast?.(`정리 중 오류가 났습니다: ${st.error || '알 수 없는 오류'}`, 'error');
            break;
          }
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
    if (!a?.cancelJunkClean) return;
    const res = await a.cancelJunkClean();
    if (res?.success) addToast?.('정리를 중단하는 중입니다. 이미 삭제된 파일은 되돌아오지 않습니다.', 'info');
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
        {scanError && !scanning && (
          <p className="text-sm text-rose-400 py-4 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /> {scanError}
          </p>
        )}

        <div className="space-y-2">
          {items.map((it) => (
            <button
              key={it.id}
              onClick={() => toggle(it.id)}
              aria-pressed={selected.has(it.id)}
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
                      <span className="text-[0.625rem] font-bold px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-400 shrink-0">
                        되돌릴 수 없음
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">{it.description}</p>
                </div>
                <span className="font-mono text-sm font-bold text-black dark:text-white shrink-0">
                  {sizeText(it.sizeMB)}
                </span>
              </div>
            </button>
          ))}
        </div>

        {cleaning && progress && (
          <div className="mt-4 pt-4 border-t border-black/5 dark:border-slate-800">
            <div className="flex justify-between text-xs mb-1.5">
              <span className="text-gray-500">
                정리 중... {progress.progress ?? 0}%
                {typeof progress.files_done === 'number' && ` · 파일 ${progress.files_done.toLocaleString()}개 삭제`}
              </span>
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
          {chosen.length ? `${chosen.length}개 항목 정리 (약 ${totalText})` : '정리할 항목을 선택하세요'}
        </button>
      </div>

      {result && result.status !== 'running' && <JunkResult result={result} />}
    </div>
  );
}

// 정리 결과. 끝난 상태(완료·중단·오류)를 그대로 보여 준다. 예전에는 오류가 나도 '0 MB 를 확보했습니다' 가 떴다.
function JunkResult({ result }) {
  const ok = result.status === 'success';
  const cancelled = result.status === 'cancelled';
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const Icon = result.status === 'error' || warnings.length ? AlertTriangle : CheckCircle2;
  const iconClass = result.status === 'error' ? 'text-rose-400' : warnings.length || cancelled ? 'text-amber-400' : 'text-emerald-400';
  let title;
  if (ok) title = `${fmtMB(result.freed_mb)} 를 확보했습니다.`;
  else if (cancelled) title = `정리를 중단했습니다. 중단 전까지 ${fmtMB(result.freed_mb)} 를 확보했습니다.`;
  else title = `정리하지 못했습니다${result.error ? `: ${result.error}` : '.'}`;
  return (
    <div className="glass-panel p-5 flex items-start gap-3">
      <Icon className={`w-5 h-5 shrink-0 mt-0.5 ${iconClass}`} />
      <div className="min-w-0">
        <p className="font-bold text-black dark:text-white">{title}</p>
        {warnings.map((w, i) => (
          <p key={i} className="text-xs text-amber-500 mt-1">{w}</p>
        ))}
        {result.skipped_count > 0 && (
          <p className="text-xs text-gray-500 mt-1">
            사용 중인 파일 {result.skipped_count.toLocaleString()}개({fmtMB(result.skipped_mb)})는 건너뛰었습니다.
            {result.skipped_log && <> 목록: <span className="break-all">{result.skipped_log}</span></>}
          </p>
        )}
      </div>
    </div>
  );
}

/* ─────────────────── 대용량 · 중복 파일 ─────────────────── */
function FileSection({ addToast, onDone }) {
  const [mode, setMode] = useState('large');
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);
  const [minMB, setMinMB] = useState(500);
  const [failures, setFailures] = useState([]);
  // 검색 진행 상황(백엔드가 센 폴더·파일·찾은 수)과 중단 여부. 예전에는 몇 분 동안 '검색 중' 만 보이고 멈출 수 없었다.
  const [progress, setProgress] = useState(null);
  const [cancelled, setCancelled] = useState(false);
  const [stopping, setStopping] = useState(false);

  const run = async () => {
    const a = api();
    if (!a) return;
    setBusy(true);
    setRows([]);
    setSelected(new Set());
    setProgress(null);
    setCancelled(false);
    setStopping(false);
    let done = false;
    const follow = (async () => {
      while (!done) {
        await sleep(500);
        if (done || !a.getFileScanProgress) break;
        try {
          const p = await a.getFileScanProgress();
          if (!done && p) setProgress(p);
        } catch { /* 다음 주기에 다시 묻는다 */ }
      }
    })();
    try {
      const res = mode === 'large'
        ? await a.findLargeFiles(minMB)
        : await a.findDuplicateFiles();
      setRows(Array.isArray(res) ? res : []);
      setSearched(true);
      if (a.getFileScanProgress) {
        const p = await a.getFileScanProgress();
        setCancelled(Boolean(p?.cancelled));
      }
    } catch (e) {
      addToast?.(`검색 실패: ${e}`, 'error');
    } finally {
      done = true;
      await follow;
    }
    setProgress(null);
    setStopping(false);
    setBusy(false);
  };

  const stop = async () => {
    const a = api();
    if (!a?.cancelFileScan) return;
    setStopping(true);
    try {
      await a.cancelFileScan();
    } catch { /* 검색이 끝나면 버튼도 사라진다 */ }
  };

  const progressText = (p) => {
    if (!p) return '검색을 시작하는 중…';
    if (p.phase === 'compare') {
      return `같은 크기 파일 묶음 ${p.groupsDone.toLocaleString()} / ${p.groupsTotal.toLocaleString()} 비교 중 · 중복 ${p.found.toLocaleString()}개`;
    }
    return `폴더 ${p.dirs.toLocaleString()}개 · 파일 ${p.files.toLocaleString()}개 확인`
      + (mode === 'large' ? ` · ${p.found.toLocaleString()}개 찾음` : '');
  };

  const toggle = (p) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(p)) n.delete(p); else n.add(p);
    return n;
  });

  // 중복 파일은 같은 내용끼리 묶어 보여 준다. 예전에는 묶음 없이 한 줄로 늘어놓아
  // 어느 파일이 어느 파일의 사본인지 알 수 없었고, 한 묶음을 전부 골라 원본까지 지울 수 있었다.
  const groups = mode === 'dup'
    ? rows.reduce((acc, f) => {
        const key = f.groupId || f.path;
        const g = acc.find((x) => x.key === key);
        if (g) g.files.push(f); else acc.push({ key, files: [f] });
        return acc;
      }, [])
    : [];
  const allCopiesChosen = groups.filter((g) => g.files.length > 1 && g.files.every((f) => selected.has(f.path)));

  const remove = async () => {
    const a = api();
    if (!a?.deleteFiles || !selected.size) return;
    const warnAll = allCopiesChosen.length
      ? `\n\n★ 중복 묶음 ${allCopiesChosen.length}개는 모든 사본을 골랐습니다. 이 PC 에 한 부도 남지 않습니다.`
      : '';
    if (!window.confirm(
      `${selected.size}개 파일을 휴지통으로 보냅니다.\n\n휴지통에서 복구할 수 있습니다. 휴지통에 들어가지 않는 파일(휴지통보다 큰 파일 등)은 지우지 않고 알려 드립니다.${warnAll}\n계속할까요?`
    )) return;
    setBusy(true);
    setFailures([]);
    try {
      const res = await a.deleteFiles([...selected]);
      const failed = Array.isArray(res?.failed) ? res.failed : [];
      setFailures(failed);
      const type = !res?.success ? 'error' : failed.length ? 'info' : 'success';
      addToast?.(res?.message || '삭제했습니다.', type);
      setSelected(new Set());
      await run();
      onDone?.();
    } catch (e) {
      addToast?.(`삭제 실패: ${e}`, 'error');
    }
    setBusy(false);
  };

  const fileRow = (f) => (
    <button key={f.path} onClick={() => toggle(f.path)} aria-pressed={selected.has(f.path)}
      className={`w-full text-left flex items-center gap-3 p-2.5 rounded-lg border transition-colors ${
        selected.has(f.path) ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-black/5 dark:border-slate-800'}`}>
      <div className={`w-4 h-4 rounded shrink-0 border ${
        selected.has(f.path) ? 'bg-cyan-500 border-cyan-500' : 'border-gray-300 dark:border-slate-600'}`} />
      <span className="text-xs font-mono text-black/80 dark:text-white/80 truncate flex-1" title={f.path}>{f.path}</span>
      {f.sizeMB != null && (
        <span className="text-xs font-mono font-bold shrink-0">{fmtMB(f.sizeMB)}</span>
      )}
    </button>
  );

  return (
    <div className="glass-panel p-5 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {[['large', '대용량 파일'], ['dup', '중복 파일']].map(([k, label]) => (
          <button key={k} onClick={() => { setMode(k); setRows([]); setSelected(new Set()); setSearched(false); setFailures([]); setCancelled(false); }}
            disabled={busy} aria-pressed={mode === k}
            className={`px-3.5 py-2 rounded-lg text-sm font-bold transition-colors disabled:opacity-40 ${
              mode === k ? 'bg-cyan-500 text-black' : 'border border-black/10 dark:border-slate-700 text-gray-500'}`}>
            {label}
          </button>
        ))}
        {mode === 'large' && (
          <select value={minMB} onChange={(e) => setMinMB(Number(e.target.value))} disabled={busy}
            className="px-3 py-2 rounded-lg text-sm bg-white dark:bg-slate-900 border border-black/10 dark:border-slate-700">
            {/* 크기 표시(fmtMB)와 같은 1 GB = 1024 MB 기준. 예전 값 1000·2000 은 '2GB 이상' 목록에 1.96 GB 가 섞였다 */}
            {[100, 300, 500, 1024, 2048].map((v) => <option key={v} value={v}>{v >= 1024 ? `${v / 1024}GB` : `${v}MB`} 이상</option>)}
          </select>
        )}
        <button onClick={run} disabled={busy}
          className="ml-auto px-4 py-2 rounded-lg text-sm font-bold bg-cyan-500 text-black disabled:opacity-40 flex items-center gap-2">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} 검색
        </button>
      </div>

      <div className="flex gap-2 text-xs">
        <Info className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" />
        <p className="text-gray-500 dark:text-gray-400 leading-relaxed">
          시스템 폴더와 알려진 게임 런처(Steam·Epic·Xbox·EA·Riot·넥슨 등)의 설치 폴더는 검색에서 제외됩니다.
          다른 이름의 폴더에 직접 설치한 게임은 걸러지지 않을 수 있으니 경로를 확인하세요.
          삭제는 휴지통을 거치므로 잘못 골라도 복구할 수 있고, 휴지통에 들어가지 않는 파일(휴지통보다 큰 파일 등)은 지우지 않습니다.
          USB 메모리·네트워크 드라이브는 검색하지 않습니다. <strong className="text-black dark:text-white">선택은 직접 하세요</strong> —
          자동으로 체크되는 항목은 없습니다.
          {mode === 'dup' && ' 중복 파일은 10MB 가 넘는 파일만 내용을 비교해 같은 것끼리 묶습니다.'}
        </p>
      </div>

      <div className="max-h-[420px] overflow-y-auto custom-scrollbar space-y-1.5 pr-1">
        {busy && !rows.length && (
          <div className="py-8 text-center space-y-3">
            <p className="text-sm text-gray-500 flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              {stopping ? '멈추는 중…' : '모든 드라이브를 검색하는 중입니다. 파일이 많으면 몇 분 걸릴 수 있습니다.'}
            </p>
            <p className="text-xs font-mono text-gray-500">{progressText(progress)}</p>
            <button onClick={stop} disabled={stopping}
              className="text-xs font-bold text-rose-400 hover:text-rose-300 inline-flex items-center gap-1 disabled:opacity-40">
              <XCircle className="w-3.5 h-3.5" /> 검색 중단
            </button>
          </div>
        )}
        {cancelled && !busy && (
          <p className="text-xs text-amber-500 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            검색을 중단했습니다. 그때까지 {mode === 'large' ? '찾은 파일' : '끝까지 비교한 묶음'}만 보입니다.
          </p>
        )}
        {!rows.length && !busy && (
          <p className="text-sm text-gray-500 py-8 text-center">
            {searched
              ? (cancelled ? '중단하기 전까지 찾은 것이 없습니다.'
                : mode === 'large' ? '조건에 맞는 대용량 파일이 없습니다.' : '중복 파일이 없습니다.')
              : '검색 버튼을 눌러 시작하세요.'}
          </p>
        )}
        {mode === 'large' && rows.map(fileRow)}
        {mode === 'dup' && groups.map((g, gi) => (
          <div key={g.key} className="rounded-xl border border-black/10 dark:border-slate-700 p-2 space-y-1.5">
            <div className="flex items-center gap-2 px-1 text-[0.6875rem] text-gray-500">
              <Copy className="w-3.5 h-3.5" />
              <span>묶음 {gi + 1} · 같은 파일 {g.files.length}개 · 각 {fmtMB(g.files[0]?.sizeMB)}</span>
              {allCopiesChosen.includes(g) && <span className="text-amber-500 font-bold">모든 사본 선택됨</span>}
            </div>
            {g.files.map(fileRow)}
          </div>
        ))}
      </div>

      {failures.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 space-y-1">
          <p className="text-xs font-bold text-amber-500">건너뛴 파일 {failures.length}개</p>
          {failures.slice(0, 20).map((f, i) => (
            <p key={i} className="text-[0.6875rem] text-gray-500 break-all">· {String(f.path)} — {f.reason}</p>
          ))}
          {failures.length > 20 && <p className="text-[0.6875rem] text-gray-500">· 외 {failures.length - 20}개</p>}
        </div>
      )}

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
function DiskSection({ addToast, overview, visible = true }) {
  const [status, setStatus] = useState(null);
  const [running, setRunning] = useState(false);

  const refresh = useCallback(async () => {
    const a = api();
    if (!a?.getTrimStatus) return;
    try { setStatus(await a.getTrimStatus()); } catch { /* 이전 표시를 둔다 */ }
  }, []);

  // 다시 보이면 다시 읽는다. 원클릭이 '저장공간 → 디스크 최적화에서 결과를 확인' 하라고 안내하는데,
  // 예전에는 이 화면을 한 번 연 적이 있으면 지난 결과가 그대로 보였다.
  const shownAgain = useShownAgain(visible);
  useEffect(() => { if (shownAgain) refresh(); }, [shownAgain, refresh]);
  // 다른 곳(원클릭)이 시작한 최적화가 돌고 있으면, 보이는 동안 끝날 때까지 따라간다
  const followElsewhere = visible && !running && status?.status === 'running';
  useEffect(() => {
    if (!followElsewhere) return undefined;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [followElsewhere, refresh]);

  // 탭을 열 때 진행 중인 최적화가 있으면(원클릭 최적화가 시작한 것 포함) 그 상태를 보여 준다
  useEffect(() => {
    const a = api();
    if (!a?.getTrimStatus) return;
    a.getTrimStatus().then((st) => { if (st && st.status !== 'idle') setStatus(st); }).catch(() => {});
  }, []);

  const start = async () => {
    const a = api();
    if (!a?.runTrim) return;
    setRunning(true);
    try {
      const res = await a.runTrim();
      if (!res?.success) {
        addToast?.(res?.message || '디스크 최적화를 시작하지 못했습니다.', 'error');
        setRunning(false);
        refresh();          // '이미 실행 중' 이면 그 상태를 보여 준다
        return;
      }
      let st = null;
      for (let i = 0; i < 900; i++) {
        await sleep(1000);
        st = await a.getTrimStatus();
        setStatus(st);
        if (st?.status !== 'running') break;
      }
      // 끝난 상태를 그대로 알린다. 실패나 시간 초과를 '마쳤습니다' 로 보이지 않는다.
      if (st?.status === 'success') addToast?.('디스크 최적화를 마쳤습니다.', 'success');
      else if (st?.status === 'running') addToast?.('디스크 최적화가 아직 진행 중입니다. 잠시 뒤 다시 확인해 주세요.', 'info');
      else addToast?.(`디스크 최적화에 실패했습니다${st?.error ? `: ${st.error}` : '.'}`, 'error');
    } catch (e) {
      addToast?.(`실행 실패: ${e}`, 'error');
    }
    setRunning(false);
  };

  const drives = overview?.drives || [];
  // '전부 SSD' 는 모든 드라이브가 SSD 로 확인됐을 때만 말한다. 종류를 모르는 드라이브가 있으면 말하지 않는다.
  const allSsd = drives.length > 0 && drives.every((d) => d.mediaType === 'ssd');
  const busyElsewhere = !running && status?.status === 'running';

  return (
    <div className="glass-panel p-6 space-y-4">
      <h3 className="font-bold text-black dark:text-white">디스크 최적화 (TRIM / 조각 모음)</h3>
      <p className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
        Windows 기본 도구로 모든 볼륨을 최적화합니다. 매체에 맞는 작업이 자동으로 선택됩니다 —
        <strong className="text-black dark:text-white"> SSD 는 TRIM</strong>(빈 블록 정리, 보통 수 초),
        <strong className="text-black dark:text-white"> HDD 는 조각 모음</strong>(수십 분 걸릴 수 있음).
      </p>

      {drives.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {drives.map((d) => (
            <span key={d.mount} className="text-xs font-mono px-2.5 py-1 rounded-lg border border-black/10 dark:border-slate-700">
              {d.label} {d.mediaType === 'unknown' ? '종류 확인 불가' : d.mediaType.toUpperCase()}
            </span>
          ))}
        </div>
      )}

      {allSsd && (
        <div className="flex gap-2 text-xs">
          <Info className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" />
          <p className="text-gray-500 dark:text-gray-400">
            모든 드라이브가 SSD 입니다. TRIM 만 수행되며 보통 몇 초 안에 끝납니다.
            SSD 에는 조각 모음이 필요 없어 Windows 가 하지 않습니다.
          </p>
        </div>
      )}

      {status && (
        <div className="text-sm space-y-1">
          <p className="text-gray-500 flex items-center gap-2">
            상태: <span className="font-bold text-black dark:text-white">{TRIM_STATUS_LABEL[status.status] || status.status}</span>
            {!running && (
              <button onClick={refresh} className="text-xs font-bold text-cyan-500 hover:text-cyan-400 flex items-center gap-1">
                <RotateCcw className="w-3 h-3" /> 새로 고침
              </button>
            )}
          </p>
          {status.status === 'success' && status.summary && <p className="text-gray-500 text-xs">{status.summary}</p>}
          {status.error && <p className="text-rose-400 text-xs">{status.error}</p>}
        </div>
      )}

      <button onClick={start} disabled={running || busyElsewhere}
        className="w-full py-3.5 rounded-xl font-bold bg-cyan-500 text-black disabled:opacity-40 flex items-center justify-center gap-2">
        {running || busyElsewhere ? <Loader2 className="w-4 h-4 animate-spin" /> : <Gauge className="w-4 h-4" />}
        {running || busyElsewhere ? '최적화 중... (중단하지 마세요)' : '디스크 최적화 시작'}
      </button>
    </div>
  );
}
