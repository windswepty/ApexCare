import { useState, useEffect } from 'react';
import { Monitor, Clock, Cpu } from 'lucide-react';
import { clockLabel } from '../cpuClock';

// 가동 시간 표시. 하루가 넘으면 '3일 4시간 5분' 처럼 날짜를 넣는다(예전에는 '76h 5m 2s').
function uptimeLabel(totalSec) {
  if (typeof totalSec !== 'number' || !Number.isFinite(totalSec) || totalSec < 0) return '확인 중…';
  const s = Math.floor(totalSec);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d}일 ${h}시간 ${m}분`;
  if (h > 0) return `${h}시간 ${m}분 ${sec}초`;
  return `${m}분 ${sec}초`;
}

// 헤더에는 상태만 보여 준다. 예전의 표준·게이밍·에코 스위치는 화면의 선택만 바꾸고 실제 모드는 바꾸지 않아
// '게이밍' 으로 보이는데 PC 는 에코로 도는 일이 있었다. 모드 전환은 '성능 부스트 모드' 탭 한 곳에서만 한다.
export default function Header() {
  // 가동 시간은 '마지막으로 받은 값 + 받은 뒤 흐른 시간' 으로 센다. 백엔드 값을 받기 전에는 표시하지 않는다.
  const [uptimeBase, setUptimeBase] = useState(null);   // { sec, at }
  const [now, setNow] = useState(() => Date.now());
  const [osLabel, setOsLabel] = useState('확인 중…');
  const [cpuLabel, setCpuLabel] = useState('확인 중…');
  // 지금 CPU 가 실제로 도는 속도. 성능 모드를 바꾸면 몇 초 안에 이 숫자가 달라진다.
  const [clock, setClock] = useState({ mhz: null, base: null });

  useEffect(() => {
    const fetchInfo = async () => {
      if (window.pywebview?.api?.getSystemStats) {
        try {
          const stats = await window.pywebview.api.getSystemStats();
          if (stats) {
            if (stats.osInfo) setOsLabel(stats.osInfo);
            if (stats.cpuModel) setCpuLabel(stats.cpuModel);
            setClock({ mhz: stats.cpuClockMHz ?? null, base: stats.cpuBaseMHz ?? null });
            if (typeof stats.uptimeSec === 'number') setUptimeBase({ sec: stats.uptimeSec, at: Date.now() });
          }
        } catch {
          // 받지 못하면 이전 값을 그대로 둔다
        }
      }
    };

    // 백엔드가 연결될 때까지 기다렸다가 한 번 읽는다
    const initialFetch = setInterval(() => {
      if (window.pywebview?.api) {
        fetchInfo();
        clearInterval(initialFetch);
      }
    }, 100);

    // 1초마다 가동 시간을 갱신하고, 5초마다 백엔드 값을 다시 읽는다
    let tickCount = 0;
    const timer = setInterval(() => {
      tickCount++;
      // 창이 최소화·가려져 있으면 백엔드를 부르지 않는다(가동 시간 숫자만 센다).
      if (tickCount >= 5 && !document.hidden) {
        fetchInfo();
        tickCount = 0;
      }
      setNow(Date.now());
    }, 1000);

    return () => {
      clearInterval(initialFetch);
      clearInterval(timer);
    };
  }, []);

  const uptimeSec = uptimeBase ? uptimeBase.sec + Math.max(0, Math.floor((now - uptimeBase.at) / 1000)) : null;

  return (
    <header className="glass-panel p-4 flex flex-wrap items-center justify-between gap-4 mb-6">
      {/* OS & Device Info */}
      <div className="flex items-center gap-4">
        <div className="w-11 h-11 rounded-xl bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 flex items-center justify-center text-black dark:text-white transition-colors duration-300">
          <Monitor className="w-6 h-6" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-bold text-black dark:text-white text-sm tracking-wide truncate max-w-[200px] transition-colors duration-300">{osLabel}</h2>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-3 mt-1 font-mono transition-colors duration-300">
            <span className="truncate max-w-[260px]" title={cpuLabel}>{cpuLabel}</span>
          </p>
        </div>
      </div>

      {/* Quick Status Pill Monitors */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* System Uptime */}
        <div className="bg-white dark:bg-black border border-black/10 dark:border-white/10 px-3.5 py-2 rounded-xl flex items-center gap-2 text-xs font-mono text-black dark:text-white shadow-sm transition-colors duration-300">
          <Clock className="w-4 h-4 text-gray-600 dark:text-gray-400" />
          <div>
            <div className="text-[10px] text-gray-500 dark:text-gray-400 font-sans">시스템 가동 시간</div>
            <div className="font-bold">{uptimeLabel(uptimeSec)}</div>
          </div>
        </div>

        {/* CPU 실제 속도 */}
        {(() => {
          const c = clockLabel(clock.mhz, clock.base);
          return (
            <div
              className="bg-white dark:bg-black border border-black/10 dark:border-white/10 px-3.5 py-2 rounded-xl flex items-center gap-2 text-xs font-mono text-black dark:text-white shadow-sm transition-colors duration-300"
              title="작업 관리자의 '속도' 와 같은 값입니다. 성능 모드를 바꾸면 몇 초 뒤 달라집니다."
            >
              <Cpu className="w-4 h-4 text-gray-600 dark:text-gray-400" />
              <div>
                <div className="text-[10px] text-gray-500 dark:text-gray-400 font-sans">CPU 실제 속도</div>
                <div className="font-bold">
                  {c.text}
                  {c.state && <span className={`ml-1.5 text-[10px] font-sans ${c.stateClass}`}>{c.state}</span>}
                </div>
              </div>
            </div>
          );
        })()}
      </div>
    </header>
  );
}
