import React, { useState, useEffect, useCallback } from 'react';
import {
  History, RotateCcw, ShieldCheck, Loader2, CheckCircle2,
  AlertTriangle, Cpu, Zap, Network, Server, HardDrive
} from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;

/** 백엔드가 쓰는 그룹 키를 사람이 읽을 이름으로. */
const GROUP_META = {
  perf_mode: { label: '성능 모드', icon: Zap, desc: '전원 플랜과 CPU 동작 설정' },
  hw_tuning: { label: '하드웨어 맞춤 튜닝', icon: Server, desc: '사양에 맞춘 서비스 시작 설정' },
  network: { label: '네트워크 튜닝', icon: Network, desc: 'TCP·Winsock 설정' },
  기타: { label: '기타 변경', icon: HardDrive, desc: '' },
};

export default function RestoreCenter({ addToast }) {
  const [pending, setPending] = useState({ count: 0, groups: {} });
  const [procCount, setProcCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const refresh = useCallback(async () => {
    const a = api();
    if (!a) return;
    try {
      if (a.getPendingSystemChanges) setPending(await a.getPendingSystemChanges());
      if (a.getAdjustedProcessCount) {
        const c = await a.getAdjustedProcessCount();
        setProcCount(c?.count || 0);
      }
    } catch (e) {
      console.error('변경 내역 조회 실패:', e);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    const onReady = () => refresh();
    window.addEventListener('pywebviewready', onReady);
    return () => { clearInterval(id); window.removeEventListener('pywebviewready', onReady); };
  }, [refresh]);

  const revertSystem = async () => {
    const a = api();
    if (!a?.revertAllSystemChanges) return;
    if (!window.confirm(
      '이 프로그램이 바꾼 모든 시스템 설정을 원래대로 되돌립니다.\n\n' +
      '전원 플랜, CPU 속도 설정, 레지스트리 값, 서비스 시작 설정, 네트워크 튜닝이\n' +
      '프로그램을 쓰기 전 상태로 복구됩니다.\n\n계속할까요?'
    )) return;

    setBusy(true);
    setResult(null);
    try {
      const res = await a.revertAllSystemChanges();
      setResult(res);
      addToast?.(res?.message || '되돌리기를 완료했습니다.', res?.success ? 'success' : 'error');
    } catch (e) {
      addToast?.(`되돌리기 실패: ${e}`, 'error');
    }
    setBusy(false);
    refresh();
  };

  const revertProcesses = async () => {
    const a = api();
    if (!a?.restoreAllProcesses) return;
    setBusy(true);
    try {
      const res = await a.restoreAllProcesses();
      addToast?.(
        res?.ok ? `${res.restored}개 프로세스를 원래 우선순위로 되돌렸습니다.`
                : `${res?.restored || 0}개 복구, ${res?.failed?.length || 0}개 실패`,
        res?.ok ? 'success' : 'error'
      );
    } catch (e) {
      addToast?.(`복구 실패: ${e}`, 'error');
    }
    setBusy(false);
    refresh();
  };

  const nothingToRevert = pending.count === 0 && procCount === 0;
  const groups = Object.entries(pending.groups || {});

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6">
        <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold">
          <History className="w-4 h-4" /> RESTORE CENTER
        </div>
        <h2 className="text-2xl font-black text-black dark:text-white tracking-tight mt-1">변경 내역 · 되돌리기</h2>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1 max-w-2xl">
          이 프로그램이 시스템에서 바꾼 것을 전부 기록해 둡니다.
          무엇이 바뀌었는지 여기서 확인하고, 언제든 원래대로 되돌릴 수 있습니다.
        </p>
      </div>

      {nothingToRevert ? (
        <div className="glass-panel p-8 text-center">
          <ShieldCheck className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
          <p className="font-bold text-black dark:text-white">되돌릴 변경이 없습니다.</p>
          <p className="text-sm text-gray-500 mt-1">
            현재 시스템은 이 프로그램을 쓰기 전과 같은 상태입니다.
          </p>
        </div>
      ) : (
        <>
          {groups.length > 0 && (
            <div className="glass-panel p-6">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div>
                  <h3 className="font-bold text-black dark:text-white">시스템 설정 변경 {pending.count}건</h3>
                  <p className="text-sm text-gray-500 mt-0.5">
                    바꾸기 전 원래 값을 기록해 두었습니다.
                  </p>
                </div>
                <button onClick={revertSystem} disabled={busy}
                  className="shrink-0 flex items-center gap-2 px-4 py-2.5 rounded-xl font-bold text-sm bg-cyan-500 text-black disabled:opacity-40">
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                  전부 원래대로
                </button>
              </div>

              <div className="space-y-3">
                {groups.map(([key, items]) => {
                  const meta = GROUP_META[key] || { label: key, icon: HardDrive, desc: '' };
                  const Icon = meta.icon;
                  return (
                    <div key={key} className="p-4 rounded-xl border border-black/10 dark:border-slate-700">
                      <div className="flex items-center gap-2.5 mb-2">
                        <Icon className="w-4 h-4 text-cyan-400 shrink-0" />
                        <p className="font-bold text-sm text-black dark:text-white">{meta.label}</p>
                        <span className="text-xs text-gray-500 font-mono ml-auto">{items.length}건</span>
                      </div>
                      {meta.desc && <p className="text-xs text-gray-500 mb-2">{meta.desc}</p>}
                      <ul className="space-y-1">
                        {items.slice(0, 8).map((it, i) => (
                          <li key={i} className="text-xs text-gray-500 dark:text-gray-400 truncate">
                            · {it.what}
                          </li>
                        ))}
                        {items.length > 8 && (
                          <li className="text-xs text-gray-500">· 외 {items.length - 8}건</li>
                        )}
                      </ul>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {procCount > 0 && (
            <div className="glass-panel p-6 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <Cpu className="w-5 h-5 text-cyan-400 shrink-0" />
                <div className="min-w-0">
                  <p className="font-bold text-sm text-black dark:text-white">
                    우선순위가 조정된 프로세스 {procCount}개
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    프로그램을 끄면 자동으로 복구되지만, 지금 되돌릴 수도 있습니다.
                  </p>
                </div>
              </div>
              <button onClick={revertProcesses} disabled={busy}
                className="shrink-0 flex items-center gap-2 px-4 py-2.5 rounded-xl font-bold text-sm border border-black/10 dark:border-slate-700 hover:border-cyan-500 disabled:opacity-40">
                <RotateCcw className="w-4 h-4" /> 되돌리기
              </button>
            </div>
          )}
        </>
      )}

      {result && (
        <div className="glass-panel p-5">
          <div className="flex items-start gap-3">
            {result.success
              ? <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
              : <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />}
            <div className="min-w-0">
              <p className="font-bold text-black dark:text-white text-sm">{result.message}</p>
              {result.parts?.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {result.parts.map((p, i) => (
                    <li key={i} className="text-xs flex items-start gap-2">
                      <span className={p.ok ? 'text-emerald-400' : 'text-rose-400'}>
                        {p.ok ? '✓' : '✗'}
                      </span>
                      <span className="text-gray-500 dark:text-gray-400">
                        {p.name}{p.detail ? ` — ${p.detail}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {result.failed?.length > 0 && (
                <p className="text-xs text-gray-500 mt-2">
                  실패한 항목은 기록에 남아 있어 다시 시도할 수 있습니다.
                  대부분 관리자 권한으로 실행하면 해결됩니다.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="glass-panel p-4 flex gap-3">
        <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
        <div className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
          파일 삭제는 여기에 기록되지 않습니다. 대신 사용자 파일은 모두
          <strong className="text-black dark:text-white"> 휴지통을 거쳐</strong> 삭제되므로
          Windows 휴지통에서 직접 복구하시면 됩니다.
          임시 파일과 캐시는 OS 가 다시 만들어 냅니다.
        </div>
      </div>
    </div>
  );
}
