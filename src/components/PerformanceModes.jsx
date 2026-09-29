import React, { useState, useEffect, useCallback } from 'react';
import {
  Zap, Gamepad2, Leaf, Gauge, CheckCircle2, AlertTriangle,
  RotateCcw, Loader2, ChevronDown, ChevronRight, Info, ShieldCheck, Cpu, MinusCircle
} from 'lucide-react';
import { usePolling } from '../usePolling';
import { clockLabel } from '../cpuClock';

const MODE_ICON = { standard: Gauge, gaming: Gamepad2, eco: Leaf };
const MODE_LABEL = { standard: '표준', gaming: '게이밍', eco: '에코' };
const MODE_ACCENT = {
  standard: { text: 'text-sky-400', ring: 'border-sky-500/60', glow: 'bg-sky-500/10' },
  gaming: { text: 'text-rose-400', ring: 'border-rose-500/60', glow: 'bg-rose-500/10' },
  eco: { text: 'text-emerald-400', ring: 'border-emerald-500/60', glow: 'bg-emerald-500/10' },
};

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;

export default function PerformanceModes({ currentMode, setCurrentMode, addToast, active = true }) {
  // 지금 CPU 실제 속도. 모드를 바꾸면 이 숫자가 달라지는 것을 바로 볼 수 있게 한다(측정값만 쓴다).
  const [live, setLive] = useState({ mhz: null, base: null, usage: null });
  const readLive = useCallback(async () => {
    const a = api();
    if (!a?.getSystemStats) return;
    try {
      const st = await a.getSystemStats();
      if (st) setLive({ mhz: st.cpuClockMHz ?? null, base: st.cpuBaseMHz ?? null, usage: st.cpuUsage ?? null });
    } catch (e) {
      // 이전 값을 그대로 둔다
    }
  }, []);
  usePolling(readLive, 2000, active);

  // 모드별 CPU 측정 결과. 같은 계산을 3초 돌린 점수라 모드의 효과를 숫자로 비교할 수 있다.
  const [bench, setBench] = useState({});
  const [benching, setBenching] = useState(false);
  const loadBench = useCallback(async () => {
    const a = api();
    if (!a?.getCpuBenchmarks) return;
    try {
      const r = await a.getCpuBenchmarks();
      if (r && typeof r === 'object') setBench(r);
    } catch (e) {
      // 결과를 못 읽으면 표를 비워 둔다
    }
  }, []);
  useEffect(() => { loadBench(); }, [loadBench]);
  const runBench = async () => {
    const a = api();
    if (!a?.runCpuBenchmark || benching) return;
    setBenching(true);
    try {
      const r = await a.runCpuBenchmark();
      if (r?.success) {
        setBench(r.results || {});
        addToast?.(`${MODE_LABEL[r.mode] || r.mode} 모드 측정: ${r.result.score} MB/s`, 'success');
      } else {
        addToast?.(r?.message || '측정하지 못했습니다.', 'error');
      }
    } catch (e) {
      addToast?.(`측정하지 못했습니다: ${e}`, 'error');
    }
    setBenching(false);
  };

  const [modes, setModes] = useState([]);
  const [applying, setApplying] = useState(null);      // 적용 중인 모드 id
  const [result, setResult] = useState(null);          // 마지막 적용 결과 (steps 포함)
  const [showSteps, setShowSteps] = useState(false);
  const [status, setStatus] = useState(null);          // getOptimizationMode 결과
  const [pending, setPending] = useState(0);           // 되돌리지 않은 변경 수
  const [reverting, setReverting] = useState(false);

  const refresh = useCallback(async () => {
    const a = api();
    if (!a) return;
    try {
      if (a.listOptimizationModes) setModes(await a.listOptimizationModes());
      if (a.getOptimizationMode) {
        const s = await a.getOptimizationMode();
        setStatus(s);
        if (s?.mode) setCurrentMode(s.mode);
      }
      if (a.getPendingSystemChanges) {
        const p = await a.getPendingSystemChanges();
        setPending(p?.count || 0);
      }
    } catch (e) {
      console.error('모드 정보 조회 실패:', e);
    }
  }, [setCurrentMode]);

  useEffect(() => {
    refresh();
    const onReady = () => refresh();
    window.addEventListener('pywebviewready', onReady);
    return () => window.removeEventListener('pywebviewready', onReady);
  }, [refresh]);

  /**
   * 모드를 적용하고 '실제 결과'를 보여준다.
   *
   * 예전에는 클릭하자마자 성공 토스트를 띄우고, App.jsx 가 백엔드 반환값을
   * await 만 하고 버렸다. 그래서 관리자 권한이 없어 아무것도 적용되지 않아도
   * 사용자에게는 항상 "프로필이 적용되었습니다!" 로 보였다.
   */
  const applyMode = async (modeId) => {
    const a = api();
    if (!a || typeof a.setOptimizationMode !== 'function') {
      addToast?.('백엔드가 준비되지 않았습니다.', 'error');
      return;
    }
    if (applying) return;

    setApplying(modeId);
    setResult(null);
    setShowSteps(false);

    let res = null;
    try {
      res = await a.setOptimizationMode(modeId);
    } catch (e) {
      res = { success: false, message: `적용 중 오류가 발생했습니다: ${e}` };
    }

    setResult(res);
    setApplying(null);

    if (res?.error === 'UAC_REQUIRED') {
      addToast?.('관리자 권한이 필요합니다. 프로그램을 관리자 권한으로 다시 실행해 주세요.', 'error');
    } else if (res?.success) {
      setCurrentMode(modeId);
      addToast?.(res.message || '모드를 적용했습니다.', 'success');
    } else if (res?.partial) {
      // 일부만 적용됨 — 성공으로 포장하지 않는다
      setCurrentMode(modeId);
      setShowSteps(true);
      addToast?.(res.message || '일부 항목이 적용되지 않았습니다.', 'error');
    } else {
      // 모드가 바뀌지 않았으므로 선택 상태도 바꾸지 않는다
      setShowSteps(true);
      addToast?.(res?.message || '모드 적용에 실패했습니다.', 'error');
    }

    refresh();
  };

  const revertAll = async () => {
    const a = api();
    if (!a?.revertAllSystemChanges) return;
    if (!window.confirm(
      '이 프로그램이 바꾼 모든 시스템 설정을 원래대로 되돌립니다.\n\n' +
      '전원 플랜, CPU 속도 설정, 레지스트리 값이 프로그램을 쓰기 전 상태로 복구됩니다.\n계속할까요?'
    )) return;

    setReverting(true);
    let res = null;
    try {
      res = await a.revertAllSystemChanges();
    } catch (e) {
      res = { success: false, message: String(e) };
    }
    setReverting(false);
    addToast?.(res?.message || '되돌리기를 완료했습니다.', res?.success ? 'success' : 'error');
    refresh();
  };

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="glass-panel p-6 flex flex-col md:flex-row md:items-center justify-between gap-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold">
            <Zap className="w-4 h-4" />
            PERFORMANCE MODE
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white tracking-tight">성능 부스트 모드</h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm max-w-2xl">
            전원 플랜과 CPU 동작 방식을 한 번에 바꿉니다. 바뀌는 항목은 모두 기록되며
            언제든 원래대로 되돌릴 수 있습니다.
          </p>
        </div>
        {pending > 0 && (
          <button
            onClick={revertAll}
            disabled={reverting}
            className="shrink-0 flex items-center gap-2 px-4 py-2.5 rounded-xl border border-black/10 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm font-bold hover:border-cyan-500 transition-colors disabled:opacity-50"
          >
            {reverting ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
            전부 원래대로 ({pending})
          </button>
        )}
      </div>

      {/* CPU 실제 속도 — 모드의 효과를 숫자로 보여 준다 */}
      {(() => {
        const c = clockLabel(live.mhz, live.base);
        const pct = live.mhz && live.base ? Math.round((live.mhz / live.base) * 100) : null;
        return (
          <div className="glass-panel p-5 flex flex-col md:flex-row md:items-center gap-5">
            <div className="flex items-center gap-4 shrink-0">
              <div className="w-12 h-12 rounded-xl grid place-items-center bg-cyan-500/10">
                <Cpu className="w-6 h-6 text-cyan-400" />
              </div>
              <div>
                <p className="text-xs text-gray-500">지금 CPU 실제 속도</p>
                <p className="text-2xl font-black font-mono text-black dark:text-white">
                  {c.text}
                  {c.state && <span className={`ml-2 text-sm font-sans ${c.stateClass}`}>{c.state}</span>}
                </p>
                <p className="text-[11px] text-gray-500 font-mono">
                  {live.base ? `기본 ${(live.base / 1000).toFixed(2)} GHz` : '기본 클럭 알 수 없음'}
                  {pct !== null && ` · 기본의 ${pct}%`}
                  {typeof live.usage === 'number' && ` · 사용률 ${live.usage}%`}
                </p>
              </div>
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed md:border-l md:pl-5 border-black/5 dark:border-slate-800">
              <p><strong className="text-rose-400">게이밍</strong>: 부스트를 공격적으로 써서 기본 클럭보다 높게 돌고, 가만히 있어도 속도를 낮추지 않습니다.</p>
              <p><strong className="text-emerald-400">에코</strong>: 부스트를 끄고 상한을 낮춰 기본 클럭보다 낮게 돕니다. 발열·소음·전력이 줄어듭니다.</p>
              <p className="mt-1">모드를 바꾸고 몇 초 뒤 이 숫자가 달라집니다. 그래픽카드가 한계인 게임은 FPS 차이가 작을 수 있습니다.</p>
            </div>
            <div className="md:ml-auto md:border-l md:pl-5 border-black/5 dark:border-slate-800 md:w-[300px] shrink-0">
              <button
                onClick={runBench}
                disabled={benching || !!applying}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-black/10 dark:border-slate-700 text-sm font-bold hover:border-cyan-500 transition-colors disabled:opacity-50"
              >
                {benching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Gauge className="w-4 h-4" />}
                <span className="whitespace-nowrap">{benching ? '측정 중…' : '성능 측정 (3초)'}</span>
              </button>
              {(() => {
                const rows = ['gaming', 'standard', 'eco'].filter((m) => bench[m]);
                if (rows.length === 0) {
                  return <p className="text-[11px] text-gray-500 mt-2 leading-snug">모드마다 한 번씩 측정하면 여기서 비교됩니다. 측정은 계산만 하고 설정은 바꾸지 않습니다.</p>;
                }
                const best = Math.max(...rows.map((m) => bench[m].score || 0)) || 1;
                return (
                  <div className="mt-2 space-y-1">
                    {rows.map((m) => (
                      <div key={m} className="flex items-baseline gap-3 text-xs font-mono">
                        <span className="w-10 shrink-0 whitespace-nowrap text-gray-500 font-sans">{MODE_LABEL[m]}</span>
                        <span className="flex-1 whitespace-nowrap text-right text-black dark:text-white">
                          <strong>{Math.round((bench[m].score / best) * 100)}%</strong>
                          <span className="text-gray-500"> · {bench[m].score} MB/s</span>
                          {bench[m].clockMHz ? <span className="text-gray-500"> · {(bench[m].clockMHz / 1000).toFixed(2)} GHz</span> : null}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          </div>
        );
      })()}

      {/* 게임 부스트가 게임 동안만 게이밍 모드를 쓰는 중 */}
      {status?.boostOverride && (
        <div className="glass-panel p-4 flex gap-3 border border-sky-500/30">
          <Info className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
          <div className="text-sm text-black/80 dark:text-white/80">
            <strong className="text-black dark:text-white">게임 부스트가 게임 동안만 게이밍 전원 모드를 쓰고 있습니다.</strong>{' '}
            게임이 끝나면 <span className="font-mono">{status.label}</span> 모드로 돌아갑니다.
            지금 다른 모드를 고르면 그 선택이 우선합니다.
          </div>
        </div>
      )}

      {/* 앱 밖에서 전원 플랜이 바뀐 경우 알림 */}
      {status && status.inSync === false && status.userSet && !status.boostOverride && (
        <div className="glass-panel p-4 flex gap-3 border border-amber-500/30">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="text-sm text-black/80 dark:text-white/80">
            <strong className="text-black dark:text-white">현재 시스템 상태가 선택한 모드와 다릅니다.</strong>{' '}
            저장된 모드는 <span className="font-mono">{status.label}</span> 인데 실제 전원 플랜은{' '}
            <span className="font-mono">{status.activePlanName}</span> 입니다.
            다른 프로그램이나 Windows 설정에서 전원 플랜이 바뀌었을 수 있습니다.
            아래에서 모드를 다시 누르면 맞춰집니다.
          </div>
        </div>
      )}

      {/* 모드 카드 */}
      <div className="flex flex-col lg:flex-row gap-4">
        {modes.map((mode) => {
          const Icon = MODE_ICON[mode.id] || Gauge;
          const accent = MODE_ACCENT[mode.id] || MODE_ACCENT.standard;
          const isActive = currentMode === mode.id;
          const isBusy = applying === mode.id;

          return (
            <div
              key={mode.id}
              role="button"
              tabIndex={0}
              onClick={() => applyMode(mode.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); applyMode(mode.id); } }}
              className={`relative flex-1 glass-panel p-6 cursor-pointer transition-all duration-300 border-2 ${
                isActive ? `${accent.ring} shadow-xl` : 'border-transparent hover:border-black/10 dark:hover:border-slate-700'
              } ${applying && !isBusy ? 'opacity-50 pointer-events-none' : ''}`}
            >
              {isActive && (
                <div className="absolute top-4 right-4 flex items-center gap-1 text-[10px] font-mono font-bold px-2.5 py-1 rounded-full bg-gray-50 dark:bg-slate-800 border border-black/10 dark:border-slate-700">
                  <CheckCircle2 className={`w-3.5 h-3.5 ${accent.text}`} />
                  ACTIVE
                </div>
              )}

              <div className={`w-11 h-11 rounded-xl grid place-items-center ${accent.glow} mb-4`}>
                {isBusy ? <Loader2 className={`w-5 h-5 animate-spin ${accent.text}`} />
                        : <Icon className={`w-5 h-5 ${accent.text}`} />}
              </div>

              <h3 className="font-black text-lg text-black dark:text-white">{mode.label}</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1.5 leading-relaxed">{mode.summary}</p>

              <div className="mt-4 pt-4 border-t border-black/5 dark:border-slate-800 space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">전원 플랜</span>
                  <span className="font-mono font-bold text-black dark:text-white">{mode.planName}</span>
                </div>
                {!mode.planAvailable && (
                  <p className="text-[11px] text-amber-500 leading-snug">{mode.note}</p>
                )}
                {mode.changes.length > 0 ? (
                  <ul className="pt-1 space-y-1">
                    {mode.changes.map((c, i) => (
                      <li key={i} className="text-[11px] text-gray-500 dark:text-gray-400 flex gap-1.5">
                        <ChevronRight className="w-3 h-3 mt-0.5 shrink-0 opacity-50" />{c}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 pt-1 leading-snug">
                    이 프로그램이 바꾼 설정을 모두 원래대로 돌려놓습니다.
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 적용 결과 — 항목별 성패를 숨기지 않는다 */}
      {result && (
        <div className="glass-panel p-5">
          <button
            onClick={() => setShowSteps((v) => !v)}
            className="w-full flex items-center justify-between gap-3 text-left"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              {result.success
                ? <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                : <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />}
              <div className="min-w-0">
                <p className="font-bold text-black dark:text-white text-sm truncate">{result.message}</p>
                {typeof result.appliedCount === 'number' && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    적용 {result.appliedCount}건
                    {result.skippedCount > 0 && <span> · 이 PC 에 없어 건너뜀 {result.skippedCount}건</span>}
                    {result.failedCount > 0 && <span className="text-amber-500"> · 실패 {result.failedCount}건</span>}
                  </p>
                )}
              </div>
            </div>
            <ChevronDown className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${showSteps ? 'rotate-180' : ''}`} />
          </button>

          {showSteps && result.steps && (
            <div className="mt-4 pt-4 border-t border-black/5 dark:border-slate-800 space-y-2">
              {result.steps.map((s, i) => (
                <div key={i} className="flex items-start gap-2.5 text-sm">
                  {s.skipped
                    ? <MinusCircle className="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
                    : s.ok
                      ? <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                      : <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />}
                  <div className="min-w-0">
                    <span className={s.ok ? 'text-black/80 dark:text-white/80' : 'text-black dark:text-white font-semibold'}>
                      {s.name}
                    </span>
                    {s.detail && <span className="text-gray-500 text-xs block mt-0.5">{s.detail}</span>}
                  </div>
                </div>
              ))}
              {result.notes?.map((n, i) => (
                <div key={`n${i}`} className="flex items-start gap-2.5 text-sm pt-1">
                  <Info className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
                  <span className="text-black/70 dark:text-white/70">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 안전 안내 */}
      <div className="glass-panel p-4 flex gap-3">
        <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
        <div className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
          모드를 바꾸면 <strong className="text-black dark:text-white">이전 모드가 바꾼 설정을 먼저 되돌린</strong> 뒤
          새 설정을 적용합니다. 바꾸기 전 원래 값을 기록해 두므로 <strong className="text-black dark:text-white">전부 원래대로</strong> 버튼으로
          언제든 되돌릴 수 있습니다. 재부팅이 필요한 변경이나 GPU 드라이버 설정은 건드리지 않습니다.
        </div>
      </div>
    </div>
  );
}
