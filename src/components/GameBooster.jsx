import React, { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../usePolling';
import {
  Crosshair, Gamepad2, Activity, Zap, ShieldCheck, AlertTriangle,
  RotateCcw, Loader2, Cpu, ChevronUp, ChevronDown, Minus, Search
} from 'lucide-react';

const api = () => (typeof window !== 'undefined' && window.pywebview && window.pywebview.api) || null;

/** 각 설정이 무엇을 바꾸고 되돌릴 수 있는지 사용자에게 그대로 보여준다. */
const BOOST_OPTIONS = [
  {
    key: 'boost_timer_resolution',
    title: '타이머 해상도 높이기',
    desc: '시스템 타이머를 0.5ms 로 올려 입력 지연을 줄입니다.',
    scope: '세션 한정 · 프로그램을 끄면 자동 복구',
    risk: 'safe',
  },
  {
    key: 'boost_tame_background',
    title: '바쁜 백그라운드 앱 양보시키기',
    desc: 'CPU 를 많이 쓰는 백그라운드 앱의 우선순위를 낮춥니다. 게임·백신·통화 앱은 건드리지 않습니다.',
    scope: '세션 한정 · 원래 우선순위로 복구',
    risk: 'safe',
  },
  {
    key: 'boost_auto_power_mode',
    title: '게임 감지 시 게이밍 전원 모드로 전환',
    desc: '전원 플랜과 CPU 속도 설정을 게이밍 모드로 바꿉니다.',
    scope: 'OS 설정 변경 · 게임 종료 시 되돌림',
    risk: 'moderate',
  },
  {
    key: 'boost_disable_nagle',
    title: 'Nagle 알고리즘 끄기',
    desc: '네트워크 어댑터의 패킷 묶음 전송을 꺼서 온라인 게임 반응을 빠르게 합니다. 대신 패킷 수가 늘어납니다.',
    scope: '레지스트리 영구 변경 · 되돌리기 가능',
    risk: 'high',
  },
];

const RISK_STYLE = {
  safe: 'text-emerald-400',
  moderate: 'text-amber-400',
  high: 'text-rose-400',
};

export default function GameBooster({ addToast, active = true }) {
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState({});
  const [procs, setProcs] = useState([]);
  const [adjusted, setAdjusted] = useState(0);
  const [busyPid, setBusyPid] = useState(null);
  const [filter, setFilter] = useState('');
  const [toggling, setToggling] = useState(false);

  const refresh = useCallback(async () => {
    const a = api();
    if (!a) return;
    try {
      if (a.getGameBoosterStatus) setStatus(await a.getGameBoosterStatus());
      if (a.getBoostSettings) setSettings(await a.getBoostSettings());
      if (a.getAdjustedProcessCount) {
        const c = await a.getAdjustedProcessCount();
        setAdjusted(c?.count || 0);
      }
      if (a.getProcesses) {
        const list = await a.getProcesses();
        if (Array.isArray(list)) setProcs(list);
      }
    } catch (e) {
      console.error('게임 부스터 상태 조회 실패:', e);
    }
  }, []);

  useEffect(() => {
    const onReady = () => refresh();
    window.addEventListener('pywebviewready', onReady);
    return () => window.removeEventListener('pywebviewready', onReady);
  }, [refresh]);
  // 이 탭이 보일 때만 갱신한다. 탭을 열면 바로 한 번 새로 읽는다.
  usePolling(refresh, 4000, active);

  const toggleBooster = async () => {
    const a = api();
    if (!a?.toggleGameBooster || toggling) return;
    setToggling(true);
    const next = !status?.enabled;
    try {
      const res = await a.toggleGameBooster(next);
      addToast?.(
        next ? '게임 자동 감지를 켰습니다.' : '게임 자동 감지를 껐습니다. 적용했던 설정은 되돌렸습니다.',
        res?.success === false ? 'error' : 'success'
      );
    } catch (e) {
      addToast?.(`전환 실패: ${e}`, 'error');
    }
    setToggling(false);
    refresh();
  };

  const toggleOption = async (key) => {
    const a = api();
    if (!a?.setBoostSetting) return;
    const next = !settings[key];
    const opt = BOOST_OPTIONS.find((o) => o.key === key);

    // 영구 변경을 켤 때는 무엇이 바뀌는지 먼저 알린다
    if (next && opt?.risk === 'high') {
      if (!window.confirm(
        `${opt.title}\n\n${opt.desc}\n\n${opt.scope}\n\n계속할까요?`
      )) return;
    }

    try {
      const res = await a.setBoostSetting(key, next);
      if (res?.success) {
        setSettings((s) => ({ ...s, [key]: next }));
      } else {
        addToast?.(res?.message || '설정 변경에 실패했습니다.', 'error');
      }
    } catch (e) {
      addToast?.(`설정 변경 실패: ${e}`, 'error');
    }
  };

  const changePriority = async (pid, priority, name) => {
    const a = api();
    if (!a?.boostProcess) return;
    setBusyPid(pid);
    try {
      const res = await a.boostProcess(pid, priority);
      if (res?.ok) {
        addToast?.(`${res.name}: 우선순위를 ${priority} 로 바꿨습니다.`, 'success');
      } else {
        // 백엔드가 왜 막았는지 한국어로 돌려주므로 그대로 보여준다
        addToast?.(res?.reason || `${name} 의 우선순위를 바꾸지 못했습니다.`, 'error');
      }
    } catch (e) {
      addToast?.(`우선순위 변경 실패: ${e}`, 'error');
    }
    setBusyPid(null);
    refresh();
  };

  const restoreAll = async () => {
    const a = api();
    if (!a?.restoreAllProcesses) return;
    const res = await a.restoreAllProcesses();
    addToast?.(
      res?.ok ? `${res.restored}개 프로세스를 원래 우선순위로 되돌렸습니다.`
              : `${res?.restored || 0}개 복구, ${res?.failed?.length || 0}개 실패`,
      res?.ok ? 'success' : 'error'
    );
    refresh();
  };

  const visible = procs
    .filter((p) => !filter || (p.name || '').toLowerCase().includes(filter.toLowerCase()))
    .slice(0, 60);

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="glass-panel p-6 flex flex-col md:flex-row md:items-center justify-between gap-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-rose-400 font-mono text-xs font-semibold">
            <Crosshair className="w-4 h-4" />
            SMART GAME BOOSTER
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white tracking-tight">스마트 게임 부스터</h2>
          <p className="text-gray-500 dark:text-gray-400 text-sm max-w-2xl">
            게임 실행을 감지하면 아래에서 켜둔 항목만 적용하고, 게임이 끝나면 되돌립니다.
          </p>
        </div>
        <button
          onClick={toggleBooster}
          disabled={toggling}
          className={`shrink-0 flex items-center gap-2 px-5 py-3 rounded-xl font-bold text-sm transition-colors disabled:opacity-50 ${
            status?.enabled
              ? 'bg-rose-500 text-white hover:bg-rose-600'
              : 'border border-black/10 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-rose-500'
          }`}
        >
          {toggling ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          {status?.enabled ? '자동 감지 켜짐' : '자동 감지 꺼짐'}
        </button>
      </div>

      {/* 현재 상태 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="glass-panel p-5">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Gamepad2 className="w-3.5 h-3.5" /> 감지된 게임
          </div>
          <p className="font-bold text-black dark:text-white truncate">
            {status?.detected_game || '없음'}
          </p>
        </div>
        <div className="glass-panel p-5">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Activity className="w-3.5 h-3.5" /> 부스트 상태
          </div>
          <p className={`font-bold ${status?.active ? 'text-rose-400' : 'text-black dark:text-white'}`}>
            {status?.active ? '적용 중' : '대기 중'}
          </p>
          {status?.appliedBoosts?.length > 0 && (
            <p className="text-[11px] text-gray-500 mt-1">{status.appliedBoosts.join(' · ')}</p>
          )}
        </div>
        <div className="glass-panel p-5">
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Cpu className="w-3.5 h-3.5" /> 우선순위 조정됨
          </div>
          <div className="flex items-center justify-between gap-2">
            <p className="font-bold text-black dark:text-white">{adjusted}개</p>
            {adjusted > 0 && (
              <button onClick={restoreAll}
                className="text-xs font-bold text-cyan-500 hover:text-cyan-400 flex items-center gap-1">
                <RotateCcw className="w-3 h-3" /> 되돌리기
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 부스트 항목 설정 */}
      <div className="glass-panel p-6">
        <h3 className="font-bold text-black dark:text-white mb-1">부스트할 항목 고르기</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          각 항목이 무엇을 바꾸고 되돌릴 수 있는지 함께 적었습니다.
          되돌릴 수 있고 세션 안에서만 유효한 항목만 기본으로 켜져 있습니다.
        </p>
        <div className="space-y-3">
          {BOOST_OPTIONS.map((opt) => {
            const on = !!settings[opt.key];
            return (
              <button
                key={opt.key}
                onClick={() => toggleOption(opt.key)}
                className={`w-full text-left p-4 rounded-xl border transition-colors ${
                  on ? 'border-cyan-500/50 bg-cyan-500/5'
                     : 'border-black/10 dark:border-slate-700 hover:border-black/20 dark:hover:border-slate-600'
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className={`mt-0.5 w-9 h-5 rounded-full shrink-0 transition-colors relative ${
                    on ? 'bg-cyan-500' : 'bg-gray-300 dark:bg-slate-700'}`}>
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${
                      on ? 'left-[18px]' : 'left-0.5'}`} />
                  </div>
                  <div className="min-w-0">
                    <p className="font-bold text-sm text-black dark:text-white">{opt.title}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-relaxed">{opt.desc}</p>
                    <p className={`text-[11px] mt-1.5 font-mono ${RISK_STYLE[opt.risk]}`}>{opt.scope}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 프로세스 우선순위 직접 조정 */}
      <div className="glass-panel p-6">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div>
            <h3 className="font-bold text-black dark:text-white">프로세스 우선순위 직접 조정</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              바꾸기 전 원래 값을 기록하므로 언제든 되돌릴 수 있습니다.
            </p>
          </div>
        </div>

        <div className="relative mb-3">
          <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="프로세스 이름으로 찾기"
            className="w-full pl-9 pr-3 py-2.5 rounded-xl text-sm bg-white dark:bg-slate-900 border border-black/10 dark:border-slate-700 outline-none focus:border-cyan-500"
          />
        </div>

        <div className="max-h-[360px] overflow-y-auto custom-scrollbar space-y-1.5 pr-1">
          {visible.length === 0 && (
            <p className="text-sm text-gray-500 py-6 text-center">표시할 프로세스가 없습니다.</p>
          )}
          {visible.map((p) => (
            <div key={p.pid}
              className="flex items-center gap-3 p-2.5 rounded-lg border border-black/5 dark:border-slate-800 hover:border-black/10 dark:hover:border-slate-700">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-black dark:text-white truncate">{p.name}</p>
                <p className="text-[11px] text-gray-500 font-mono">
                  PID {p.pid} · {p.cpuPct ?? p.cpu_percent ?? '0%'} · {p.memoryMB ?? 0}MB
                </p>
              </div>
              <div className="flex gap-1 shrink-0">
                {[
                  { k: 'high', Icon: ChevronUp, label: '높음', cls: 'hover:border-rose-500 hover:text-rose-400' },
                  { k: 'normal', Icon: Minus, label: '보통', cls: 'hover:border-sky-500 hover:text-sky-400' },
                  { k: 'idle', Icon: ChevronDown, label: '낮음', cls: 'hover:border-emerald-500 hover:text-emerald-400' },
                ].map(({ k, Icon, label, cls }) => (
                  <button
                    key={k}
                    onClick={() => changePriority(p.pid, k, p.name)}
                    disabled={busyPid === p.pid}
                    title={`${label}으로 변경`}
                    className={`w-8 h-8 grid place-items-center rounded-lg border border-black/10 dark:border-slate-700 text-gray-500 transition-colors disabled:opacity-40 ${cls}`}
                  >
                    {busyPid === p.pid ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Icon className="w-3.5 h-3.5" />}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 안전 안내 */}
      <div className="glass-panel p-4 flex gap-3">
        <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
        <div className="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
          Windows 필수 프로세스, 실행 중인 게임, 백신·통화·백업 프로그램은 우선순위 조정 대상에서
          자동으로 제외됩니다. <strong className="text-black dark:text-white">realtime</strong> 우선순위는
          입력까지 멈출 수 있어 아예 제공하지 않습니다.
        </div>
      </div>
    </div>
  );
}
