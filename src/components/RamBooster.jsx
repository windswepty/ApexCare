import React, { useState, useCallback } from 'react';
import { usePolling } from '../usePolling';
import {
  Cpu,
  Zap,
  RotateCcw,
  Activity,
  CheckCircle2,
  XCircle
} from 'lucide-react';

// 예전 화면의 문제:
//   - 백엔드 응답 전·실패 시 14.2 / 7.8 / 32 GB 같은 지어낸 값을 실제 측정값처럼 보여줬다.
//   - 대기 메모리는 계산 오류로 늘 0 이었고, 해제 버튼은 사실상 누를 수 없었다.
//   - API 가 없으면 1.5초 기다린 뒤 무조건 '성공' 으로 처리했다.
//   - 프로세스 종료를 확인 없이, 결과를 받기 전에 목록에서 먼저 지웠다.
// 이제 백엔드가 측정한 값만 보여주고, 없으면 '측정 중' / '알 수 없음' 으로 둔다.

const fmtGB = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(1)} GB` : '알 수 없음');

export default function RamBooster({ addToast, active = true }) {
  // null: 아직 받지 못함. { error: true }: 받지 못했음.
  const [ram, setRam] = useState(null);
  const [processes, setProcesses] = useState(null);

  const fetchRealData = useCallback(async () => {
      const api = window.pywebview && window.pywebview.api;
      if (!api) return;
      if (typeof api.getSystemStats === 'function') {
        try {
          const stats = await api.getSystemStats();
          if (stats && !stats.error && Number(stats.ramTotalGB) > 0) {
            const num = (v) => (v === null || v === undefined || v === '' ? null : Number(v));
            setRam({
              totalGB: num(stats.ramTotalGB),
              pct: num(stats.ramPct),
              availableGB: num(stats.ramAvailableGB),
              inUseGB: num(stats.ramInUseGB),
              modifiedGB: num(stats.ramModifiedGB),
              standbyGB: num(stats.ramStandbyGB),
              freeGB: num(stats.ramFreeGB),
            });
          } else {
            setRam({ error: true });
          }
        } catch (e) {
          console.error('Error fetching memory stats:', e);
          setRam({ error: true });
        }
      }

      if (typeof api.getProcesses === 'function') {
        try {
          const realProcs = await api.getProcesses();
          setProcesses(Array.isArray(realProcs) ? realProcs : []);
        } catch (e) {
          console.error('Error fetching processes:', e);
        }
      }
  }, []);
  // 이 탭이 보일 때만 2초마다 갱신한다(프로세스 목록 수집이 가장 무거운 호출이다).
  usePolling(fetchRealData, 2000, active);

  const [isPurging, setIsPurging] = useState(false);
  const [purgeResult, setPurgeResult] = useState(null);

  const handlePurgeStandby = async () => {
    if (isPurging) return;
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.purgeRam !== 'function') {
      if (addToast) addToast('API가 준비되지 않아 대기 메모리를 비울 수 없습니다.', 'error');
      return;
    }
    setIsPurging(true);
    setPurgeResult(null);
    try {
      const res = await api.purgeRam();
      if (res?.success) {
        setPurgeResult(res);
        if (addToast) addToast(res.message || '대기 메모리를 비웠습니다.', 'success');
      } else {
        if (addToast) addToast(res?.message || '대기 메모리를 비우지 못했습니다.', 'error');
      }
    } catch (e) {
      if (addToast) addToast(`대기 메모리를 비우지 못했습니다: ${e}`, 'error');
    } finally {
      setIsPurging(false);
    }
  };

  // 종료 확인 중인 PID, 종료 요청 중인 PID
  const [confirmPid, setConfirmPid] = useState(null);
  const [killingPid, setKillingPid] = useState(null);

  const killProcess = async (proc) => {
    const api = window.pywebview && window.pywebview.api;
    setConfirmPid(null);
    if (!api || typeof api.killProcess !== 'function') {
      if (addToast) addToast('API가 준비되지 않아 프로세스를 종료할 수 없습니다.', 'error');
      return;
    }
    setKillingPid(proc.pid);
    try {
      const res = await api.killProcess(proc.pid);
      if (res?.success) {
        // 결과를 받은 뒤에만 목록에서 뺀다
        setProcesses(prev => (prev || []).filter(p => p.pid !== proc.pid));
        if (addToast) addToast(res.message || `'${proc.name}' 프로세스를 종료했습니다.`, 'success');
      } else {
        // 시스템 보호 프로세스 차단 사유를 백엔드 한국어 메시지 그대로 보여준다
        if (addToast) addToast(res?.message || '프로세스 종료에 실패했습니다.', 'error');
      }
    } catch (e) {
      if (addToast) addToast(`프로세스 종료에 실패했습니다: ${e}`, 'error');
    } finally {
      setKillingPid(null);
    }
  };

  const loading = ram === null;
  const unavailable = ram?.error === true;
  const hasBreakdown = !loading && !unavailable &&
    [ram.inUseGB, ram.modifiedGB, ram.standbyGB, ram.freeGB].every(v => typeof v === 'number');
  const noStandby = typeof ram?.standbyGB === 'number' && ram.standbyGB < 0.1;
  const waiting = loading ? '측정 중…' : null;

  const segments = hasBreakdown ? [
    { key: 'inUse', label: '사용 중', gb: ram.inUseGB, cls: 'bg-cyan-500' },
    { key: 'modified', label: '수정됨', gb: ram.modifiedGB, cls: 'bg-amber-500' },
    { key: 'standby', label: '대기 (캐시)', gb: ram.standbyGB, cls: 'bg-purple-500' },
    { key: 'free', label: '여유', gb: ram.freeGB, cls: 'bg-gray-300 dark:bg-slate-700' },
  ] : [];

  return (
    <div className="space-y-6">
      {/* Header Panel */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 text-purple-400 font-mono text-xs font-semibold mb-1">
            <Cpu className="w-4 h-4" />
            MEMORY
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">RAM 메모리 최적화</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1 max-w-2xl">
            대기(Standby) 메모리는 Windows 가 최근에 읽은 파일을 담아 둔 캐시입니다. 다른 프로그램이 메모리를 요청하면 Windows 가 알아서 내어주므로 평소에는 비울 필요가 없습니다.
            비우면 '여유' 수치는 늘지만 캐시가 사라져 한동안 파일·게임 로딩이 느려질 수 있습니다.
          </p>
        </div>

        <button
          onClick={handlePurgeStandby}
          disabled={isPurging || loading || unavailable || noStandby}
          className={`btn-primary bg-gradient-to-r from-purple-600 to-pink-600 shadow-purple-500/30 px-6 py-3.5 flex-shrink-0 ${
            isPurging || loading || unavailable || noStandby ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {isPurging ? (
            <>
              <RotateCcw className="w-5 h-5 animate-spin text-black dark:text-white" />
              <span>대기 메모리 비우는 중...</span>
            </>
          ) : (
            <>
              <Zap className="w-5 h-5 text-black dark:text-white fill-current" />
              <span>
                {noStandby ? '비울 대기 메모리가 없습니다'
                  : typeof ram?.standbyGB === 'number' ? `대기 메모리 (${ram.standbyGB.toFixed(1)} GB) 비우기`
                  : '대기 메모리 비우기'}
              </span>
            </>
          )}
        </button>
      </div>

      {/* Result — 백엔드가 측정해 돌려준 값만 */}
      {purgeResult && (
        <div className="glass-panel border-purple-500/40 bg-purple-950/20 p-4 rounded-xl flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-6 h-6 text-purple-400 flex-shrink-0" />
            <div>
              <h4 className="font-bold text-purple-300 text-sm">{purgeResult.message}</h4>
              {typeof purgeResult.freeBeforeGB === 'number' && typeof purgeResult.freeAfterGB === 'number' && (
                <p className="text-xs text-gray-700 dark:text-slate-300 font-mono">
                  여유 메모리 {purgeResult.freeBeforeGB.toFixed(1)} GB → {purgeResult.freeAfterGB.toFixed(1)} GB (비운 직후 측정)
                </p>
              )}
            </div>
          </div>
          <button onClick={() => setPurgeResult(null)} className="text-xs text-gray-500 dark:text-slate-400 hover:text-black dark:hover:text-white underline flex-shrink-0">
            닫기
          </button>
        </div>
      )}

      {/* Memory composition */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="glass-panel p-4 border-l-4 border-l-cyan-400">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">사용 중</span>
          <div className="text-2xl font-black font-mono text-black dark:text-white mt-1">{waiting || fmtGB(ram.inUseGB)}</div>
          <span className="text-[10px] text-slate-500 font-mono">프로그램과 Windows 가 쓰는 메모리</span>
        </div>

        <div className="glass-panel p-4 border-l-4 border-l-purple-500">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">대기 (Standby)</span>
          <div className="text-2xl font-black font-mono text-purple-400 mt-1">{waiting || fmtGB(ram.standbyGB)}</div>
          <span className="text-[10px] text-slate-500 font-mono">최근 파일 캐시 · 필요하면 자동 반환</span>
        </div>

        <div className="glass-panel p-4 border-l-4 border-l-emerald-400">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">여유 (Free)</span>
          <div className="text-2xl font-black font-mono text-emerald-400 mt-1">{waiting || fmtGB(ram.freeGB)}</div>
          <span className="text-[10px] text-slate-500 font-mono">아무것도 담기지 않은 메모리</span>
        </div>

        <div className="glass-panel p-4 border-l-4 border-l-slate-500">
          <span className="text-xs font-mono text-gray-500 dark:text-slate-400">메모리 사용률</span>
          <div className="text-2xl font-black font-mono text-gray-800 dark:text-slate-200 mt-1">
            {waiting || (typeof ram.pct === 'number' ? `${ram.pct}%` : '알 수 없음')}
          </div>
          <span className="text-[10px] text-slate-500 font-mono">
            {loading ? '' : `전체 ${fmtGB(ram.totalGB)} · 사용 가능 ${fmtGB(ram.availableGB)}`}
          </span>
        </div>
      </div>

      {/* Composition bar */}
      <div className="glass-panel p-5 space-y-3">
        <div className="flex justify-between items-center text-xs font-mono gap-4">
          <span className="text-gray-700 dark:text-slate-300 font-bold">메모리 구성</span>
          <span className="text-gray-500 dark:text-slate-400 text-right">
            Windows 성능 카운터 값 (작업 관리자와 같은 출처) · 2초마다 갱신
          </span>
        </div>
        {hasBreakdown ? (
          <>
            <div className="w-full h-4 bg-white dark:bg-slate-900 rounded-full overflow-hidden flex">
              {segments.map(s => (
                <div
                  key={s.key}
                  className={`${s.cls} h-full transition-all duration-500`}
                  style={{ width: `${Math.max(0, (s.gb / ram.totalGB) * 100)}%` }}
                  title={`${s.label} ${s.gb.toFixed(1)} GB`}
                ></div>
              ))}
            </div>
            <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs font-mono pt-1">
              {segments.map(s => (
                <div key={s.key} className="flex items-center gap-2">
                  <span className={`w-3 h-3 rounded ${s.cls}`}></span>
                  <span className="text-gray-700 dark:text-slate-300">{s.label} {s.gb.toFixed(1)} GB</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-slate-500 text-center">
              수정됨: 디스크에 기록되기를 기다리는 메모리입니다. 기록이 끝나면 대기로 옮겨집니다.
            </p>
          </>
        ) : (
          <p className="text-xs text-gray-500 dark:text-slate-400 py-2">
            {loading ? '측정 중…' : '메모리 구성을 읽지 못했습니다. 성능 카운터를 사용할 수 없는 환경일 수 있습니다.'}
          </p>
        )}
      </div>

      {/* Process table */}
      <div className="glass-panel p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-gray-900 dark:text-slate-100 text-sm flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            메모리를 많이 쓰는 프로세스 {processes ? `(상위 ${processes.length}개)` : ''}
          </h3>
          <span className="text-xs text-gray-500 dark:text-slate-400 font-mono">메모리 사용량 순</span>
        </div>

        {processes === null ? (
          <p className="text-xs text-gray-500 dark:text-slate-400 py-2">측정 중…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-black/10 dark:border-slate-800 text-gray-500 dark:text-slate-400">
                  <th className="pb-3 px-2">프로세스명</th>
                  <th className="pb-3 px-2">PID</th>
                  <th className="pb-3 px-2">메모리 (작업 집합)</th>
                  <th className="pb-3 px-2">CPU</th>
                  <th className="pb-3 px-2">우선순위</th>
                  <th className="pb-3 px-2 text-right">작업</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {processes.map((proc) => (
                  <tr key={proc.pid} className="hover:bg-gray-50 dark:hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-2 font-bold text-gray-800 dark:text-slate-200">{proc.name}</td>
                    <td className="py-3 px-2 text-gray-500 dark:text-slate-400">{proc.pid}</td>
                    <td className="py-3 px-2 text-purple-400 font-bold">{proc.memoryMB} MB</td>
                    <td className="py-3 px-2 text-cyan-400">{proc.cpuPct ?? <span className="text-slate-500">측정 중</span>}</td>
                    <td className="py-3 px-2">
                      <span className={`px-2 py-0.5 rounded text-[10px] ${
                        proc.priority === '높음' || proc.priority === '실시간'
                          ? 'bg-amber-500/20 text-amber-300'
                          : 'bg-gray-50 dark:bg-slate-800 text-gray-700 dark:text-slate-300'
                      }`}>
                        {proc.priority}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-right">
                      {confirmPid === proc.pid ? (
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-[10px] text-rose-300 text-right">저장하지 않은 작업은 사라집니다</span>
                          <button
                            onClick={() => killProcess(proc)}
                            className="text-white bg-rose-600 hover:bg-rose-500 px-2 py-1 rounded font-bold"
                          >
                            강제 종료
                          </button>
                          <button
                            onClick={() => setConfirmPid(null)}
                            className="text-gray-600 dark:text-slate-300 hover:bg-black/5 dark:hover:bg-white/10 px-2 py-1 rounded"
                          >
                            취소
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmPid(proc.pid)}
                          disabled={killingPid !== null}
                          className="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 px-2 py-1 rounded transition-all flex items-center gap-1 ml-auto disabled:opacity-40"
                        >
                          <XCircle className="w-3.5 h-3.5" />
                          {killingPid === proc.pid ? '종료 중…' : '프로세스 종료'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
