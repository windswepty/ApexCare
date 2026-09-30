import { useState, useEffect } from 'react';
import {
  ShieldCheck,
  RotateCw,
  CheckCircle2,
  AlertCircle,
  Terminal,
  Activity,
  Layers
} from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;

const elapsedLabel = (sec) => `${Math.floor(sec / 60)}분 ${sec % 60}초`;

/**
 * SFC·DISM 한 가지를 실행하고 끝날 때까지 상태를 읽는다.
 *
 * 예전 문제:
 *   - 끝나면 '무결성 복구 완료' 를 띄웠다. SFC 는 손상을 못 고쳐도 검사를 마치면 성공 코드로 끝난다.
 *     이제 도구가 마지막에 쓴 결과 문장(summary)을 그대로 보여 준다.
 *   - 실패하면 이유와 상관없이 '(관리자 권한 필요)' 라고 했다. 이제 실제 오류 내용을 보여 준다.
 *   - 한 번 끝나면 버튼이 사라져 앱을 다시 켜야 다시 실행할 수 있었다.
 */
// 부를 백엔드 함수. 이름을 문자열로 넘기지 않고 직접 적어 두어야 API 이름 검사 테스트가 확인할 수 있다.
const SFC = { label: 'SFC 검사', start: () => api()?.runSfc?.(), status: () => api()?.getSfcStatus?.() };
const DISM = { label: 'DISM 복구', start: () => api()?.runDism?.(), status: () => api()?.getDismStatus?.() };

function useRepairTask(task, addToast) {
  const { label } = task;
  const [status, setStatus] = useState('idle');
  const [elapsed, setElapsed] = useState(0);
  const [detail, setDetail] = useState({ summary: '', error: '' });

  // 화면을 새로 띄웠을 때(오류 화면에서 다시 불러오기 등) 이미 돌고 있거나 끝난 작업이 있으면 그 상태를 보여 준다.
  // 예전에는 늘 '대기' 로 시작해, 돌고 있는 검사를 다시 누르면 '이미 실행 중' 만 떴다.
  useEffect(() => {
    let alive = true;
    Promise.resolve(task.status()).then((st) => {
      if (!alive || !st || st.status === 'idle') return;
      if (st.status !== 'running') setDetail({ summary: st.summary || '', error: st.error || '' });
      setStatus(st.status);
    }).catch(() => {});
    return () => { alive = false; };
  }, [task]);

  useEffect(() => {
    if (status !== 'running') return undefined;
    const interval = setInterval(async () => {
      setElapsed((t) => t + 1);
      try {
        const state = await task.status();
        if (state && state.status !== 'running' && state.status !== 'idle') {
          setDetail({ summary: state.summary || '', error: state.error || '' });
          setStatus(state.status);
          if (state.status === 'success') {
            addToast?.(`${label}를 마쳤습니다. 화면의 결과 문장을 확인하세요.`, 'success');
          } else {
            addToast?.(`${label}에 실패했습니다${state.error ? `: ${state.error}` : '.'}`, 'error');
          }
        }
      } catch (e) {
        console.error(`${label} 상태 확인 실패:`, e);
        setDetail({ summary: '', error: '상태를 확인하지 못했습니다. 작업은 계속 진행 중일 수 있습니다.' });
        setStatus('error');
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [status, task, label, addToast]);

  const run = async () => {
    if (!api()) {
      addToast?.('API가 준비되지 않았습니다.', 'error');
      return;
    }
    try {
      const res = await task.start();
      if (res?.success) {
        setElapsed(0);
        setDetail({ summary: '', error: '' });
        setStatus('running');
      } else {
        addToast?.(res?.message || `${label}를 시작하지 못했습니다.`, 'error');
      }
    } catch (e) {
      addToast?.(`${label}를 시작하지 못했습니다: ${e}`, 'error');
    }
  };

  return { status, elapsed, detail, run };
}

function ResultLine({ status, detail, elapsed }) {
  if (status === 'success') {
    return (
      <div className="p-3 rounded-xl bg-emerald-500/5 border border-emerald-500/20 text-xs space-y-1">
        <p className="font-bold text-emerald-500 flex items-center gap-1.5">
          <CheckCircle2 className="w-4 h-4" /> 끝났습니다 (걸린 시간 {elapsedLabel(elapsed)})
        </p>
        <p className="text-gray-600 dark:text-slate-300">
          {detail.summary || '도구가 결과 문장을 남기지 않았습니다. 자세한 내용은 C:\\Windows\\Logs\\CBS\\CBS.log 에 있습니다.'}
        </p>
      </div>
    );
  }
  if (status === 'error') {
    return (
      <div className="p-3 rounded-xl bg-rose-500/5 border border-rose-500/20 text-xs space-y-1">
        <p className="font-bold text-rose-400 flex items-center gap-1.5">
          <AlertCircle className="w-4 h-4" /> 실패했습니다
        </p>
        <p className="text-gray-600 dark:text-slate-300 break-words">{detail.error || '원인을 알 수 없습니다.'}</p>
      </div>
    );
  }
  return null;
}

export default function SystemRepair({ addToast }) {
  const sfc = useRepairTask(SFC, addToast);
  const dism = useRepairTask(DISM, addToast);
  const isAnyRunning = sfc.status === 'running' || dism.status === 'running';

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
        <div className="space-y-1 z-10">
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold">
            <ShieldCheck className="w-4 h-4" />
            WINDOWS SYSTEM FILE REPAIR
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">시스템 파일 복구</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            손상된 Windows 시스템 파일을 검사해 원본으로 복구하고(SFC), 그 원본이 들어 있는 Windows 이미지의 손상을 복구합니다(DISM). 시스템 파일 손상이 원인인 오류에만 효과가 있습니다.
            SFC 가 손상을 고치지 못했다고 하면 DISM 을 먼저 실행한 뒤 SFC 를 다시 실행하세요.
          </p>
        </div>
      </div>

      {/* SFC Panel */}
      <div className={`glass-panel p-5 flex flex-col gap-4 transition-all duration-300 ${
        sfc.status === 'running' ? 'border-cyan-500/50 shadow-lg shadow-cyan-500/10' : 'border-black/10 dark:border-slate-800'
      }`}>
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-start gap-4 flex-1">
            <div className="p-3 rounded-2xl border bg-cyan-500/10 text-cyan-400 border-cyan-500/20">
              <Terminal className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-cyan-400 font-bold bg-white dark:bg-slate-900 px-2 py-0.5 rounded border border-black/10 dark:border-slate-800">
                  SFC /SCANNOW
                </span>
              </div>
              <h3 className="font-bold text-black dark:text-white text-base">시스템 파일 검사기 (SFC)</h3>
              <p className="text-xs text-gray-500 dark:text-slate-400">보호된 시스템 파일을 모두 검사하고, 손상된 파일은 Windows 가 보관한 원본으로 바꿉니다. 보통 5~15분 걸립니다.</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {sfc.status === 'running' ? (
              <button disabled className="btn-primary text-xs px-5 py-2.5 flex items-center gap-2 opacity-75 cursor-not-allowed">
                <RotateCw className="w-4 h-4 animate-spin" />
                <span>검사 진행 중...</span>
              </button>
            ) : (
              <button
                onClick={sfc.run}
                disabled={isAnyRunning}
                className={`btn-primary text-xs px-5 py-2.5 flex items-center gap-2 ${isAnyRunning ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <RotateCw className="w-4 h-4" />
                <span>{sfc.status === 'idle' ? 'SFC 검사 실행' : 'SFC 검사 다시 실행'}</span>
              </button>
            )}
          </div>
        </div>

        {sfc.status === 'running' && (
          <div className="mt-2 p-4 rounded-xl bg-black/5 dark:bg-black/40 border border-black/10 dark:border-white/5 flex flex-col gap-3">
            <div className="flex items-center justify-between text-cyan-500 dark:text-cyan-400 font-mono text-sm">
              <div className="flex items-center gap-2">
                <RotateCw className="w-5 h-5 animate-spin" />
                <span>시스템 파일을 검사하는 중...</span>
              </div>
              <div className="text-right">
                <span className="font-bold">경과 {elapsedLabel(sfc.elapsed)}</span>
                <span className="text-xs ml-3 text-slate-500">보통 5~15분 걸립니다</span>
              </div>
            </div>
            <div className="relative w-full bg-slate-200 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div className="absolute inset-y-0 w-1/3 bg-cyan-400 rounded-full animate-indeterminate motion-reduce:w-full motion-reduce:opacity-40"></div>
            </div>
          </div>
        )}
        <ResultLine status={sfc.status} detail={sfc.detail} elapsed={sfc.elapsed} />
      </div>

      {/* DISM Panel */}
      <div className={`glass-panel p-5 flex flex-col gap-4 transition-all duration-300 ${
        dism.status === 'running' ? 'border-purple-500/50 shadow-lg shadow-purple-500/10' : 'border-black/10 dark:border-slate-800'
      }`}>
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-start gap-4 flex-1">
            <div className="p-3 rounded-2xl border bg-purple-500/10 text-purple-400 border-purple-500/20">
              <Layers className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-purple-400 font-bold bg-white dark:bg-slate-900 px-2 py-0.5 rounded border border-black/10 dark:border-slate-800">
                  DISM /RESTOREHEALTH
                </span>
              </div>
              <h3 className="font-bold text-black dark:text-white text-base">Windows 이미지 복구 (DISM)</h3>
              <p className="text-xs text-gray-500 dark:text-slate-400">SFC 가 원본으로 쓰는 Windows 구성 요소 저장소를 검사하고, 손상된 부분은 Windows Update 에서 받아 고칩니다. 인터넷 연결이 필요하며 보통 10~30분 걸립니다.</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {dism.status === 'running' ? (
              <button disabled className="btn-primary bg-gradient-to-r from-purple-500 to-indigo-600 shadow-purple-500/30 text-xs px-5 py-2.5 flex items-center gap-2 opacity-75 cursor-not-allowed">
                <RotateCw className="w-4 h-4 animate-spin" />
                <span>복구 진행 중...</span>
              </button>
            ) : (
              <button
                onClick={dism.run}
                disabled={isAnyRunning}
                className={`btn-primary bg-gradient-to-r from-purple-500 to-indigo-600 shadow-purple-500/30 text-xs px-5 py-2.5 flex items-center gap-2 ${isAnyRunning ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <Activity className="w-4 h-4" />
                <span>{dism.status === 'idle' ? 'DISM 복구 실행' : 'DISM 복구 다시 실행'}</span>
              </button>
            )}
          </div>
        </div>

        {dism.status === 'running' && (
          <div className="mt-2 p-4 rounded-xl bg-black/5 dark:bg-black/40 border border-black/10 dark:border-white/5 flex flex-col gap-3">
            <div className="flex items-center justify-between text-purple-500 dark:text-purple-400 font-mono text-sm">
              <div className="flex items-center gap-2">
                <RotateCw className="w-5 h-5 animate-spin" />
                <span>Windows 이미지를 검사·복구하는 중...</span>
              </div>
              <div className="text-right">
                <span className="font-bold">경과 {elapsedLabel(dism.elapsed)}</span>
                <span className="text-xs ml-3 text-slate-500">보통 10~30분 걸립니다</span>
              </div>
            </div>
            <div className="relative w-full bg-slate-200 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-purple-500 to-indigo-600 rounded-full animate-indeterminate motion-reduce:w-full motion-reduce:opacity-40"></div>
            </div>
          </div>
        )}
        <ResultLine status={dism.status} detail={dism.detail} elapsed={dism.elapsed} />
      </div>

    </div>
  );
}
