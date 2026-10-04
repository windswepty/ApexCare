import { useState, useEffect, useCallback } from 'react';
import { HeartPulse, HardDrive, Thermometer, Clock, AlertTriangle, RefreshCw, Loader2, Timer, Gauge } from 'lucide-react';

// PC 건강 진단. 읽기만 한다(디스크 상태·부팅 시간). Windows 가 알려 주지 않는 값은 '알 수 없음' 으로 둔다.
const api = () => (window.pywebview && window.pywebview.api) || null;

const HEALTH_STYLE = {
  정상: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  주의: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  위험: 'bg-red-500/15 text-red-400 border-red-500/30',
};

function hoursText(h) {
  if (typeof h !== 'number') return null;
  const days = Math.floor(h / 24);
  return days >= 1 ? `${h.toLocaleString()}시간 (약 ${days.toLocaleString()}일)` : `${h}시간`;
}

function sizeText(gb) {
  if (typeof gb !== 'number') return '';
  return gb >= 1000 ? `${(gb / 1024).toFixed(1)} TB` : `${Math.round(gb)} GB`;
}

function dateText(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const year = d.getFullYear() !== new Date().getFullYear() ? { year: 'numeric' } : {};
  return d.toLocaleString('ko-KR', { ...year, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// 디스크 제조사가 쓰는 10진 단위(TBW 와 같은 단위)
function bytesText(b) {
  if (typeof b !== 'number') return null;
  if (b >= 1e12) return `${(b / 1e12).toFixed(1)} TB`;
  if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`;
  return `${Math.round(b / 1e6)} MB`;
}

function Fact({ label, value, warn }) {
  if (value === null || value === undefined) return null;
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-gray-500 dark:text-gray-400">{label}</span>
      <span className={`font-mono font-semibold ${warn ? 'text-amber-400' : 'text-black dark:text-white'}`}>{value}</span>
    </div>
  );
}

function Metric({ icon: Icon, label, value, hint, children }) {
  return (
    <div className="rounded-xl border border-black/5 dark:border-white/5 bg-gray-50 dark:bg-zinc-900/60 p-3">
      <div className="flex items-center gap-1.5 text-[0.6875rem] text-gray-500 dark:text-gray-400">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className={`mt-1 font-bold ${value ? 'text-black dark:text-white' : 'text-gray-500 text-sm'}`}>
        {value || '디스크가 알려 주지 않음'}
      </div>
      {children}
      {hint && <div className="text-[0.6875rem] text-gray-500 mt-0.5">{hint}</div>}
    </div>
  );
}

function DiskCard({ d }) {
  const wear = typeof d.wearPct === 'number' ? d.wearPct : null;
  // NVMe 는 디스크 기록의 '복구하지 못한 데이터 오류', 그 밖에는 Windows 카운터의 읽기·쓰기 오류
  const nvmeErrors = typeof d.mediaErrors === 'number';
  const errors = nvmeErrors ? d.mediaErrors : (d.readErrors || 0) + (d.writeErrors || 0);
  const knownErrors = nvmeErrors || typeof d.readErrors === 'number' || typeof d.writeErrors === 'number';
  const n = d.nvme;
  return (
    <div className="glass-panel p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2.5 rounded-xl bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10">
            <HardDrive className="w-5 h-5 text-black dark:text-white" />
          </div>
          <div className="min-w-0">
            <h3 className="font-bold text-black dark:text-white truncate" title={d.name}>{d.name}</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {[d.media, d.bus, sizeText(d.sizeGB), d.letters?.length ? d.letters.join(' ') : '드라이브 문자 없음']
                .filter(Boolean).join(' · ')}
            </p>
          </div>
        </div>
        <span className={`shrink-0 text-xs font-bold px-2.5 py-1 rounded-full border ${HEALTH_STYLE[d.health] || 'bg-gray-500/15 text-gray-400 border-gray-500/30'}`}
          title={d.status ? `Windows 상태: ${d.healthRaw} / ${d.status}` : undefined}>
          {d.health}
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Metric icon={Gauge} label="수명 사용량 (SSD)"
          value={wear !== null ? `${wear}%` : d.media === 'HDD' ? '해당 없음 (HDD)' : null}
          hint={wear === null ? null : wear >= 100 ? '제조사가 정한 예상 수명을 다 썼습니다' : '100% 에 가까울수록 교체 시기'}>
          {wear !== null && (
            <div className="mt-1.5 w-full h-1.5 rounded-full bg-gray-200 dark:bg-zinc-800 overflow-hidden">
              <div className={`h-full rounded-full ${wear >= 90 ? 'bg-red-500' : wear >= 70 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                style={{ width: `${Math.max(2, Math.min(100, wear))}%` }} />
            </div>
          )}
        </Metric>
        <Metric icon={Thermometer} label="온도"
          value={typeof d.temperatureC === 'number' ? `${d.temperatureC}°C` : null}
          hint={typeof d.temperatureMaxC === 'number' ? `디스크가 정한 상한 ${d.temperatureMaxC}°C` : null} />
        <Metric icon={Clock} label="사용 시간" value={hoursText(d.powerOnHours)} />
        <Metric icon={AlertTriangle} label={nvmeErrors ? '복구하지 못한 데이터 오류' : '고치지 못한 읽기·쓰기 오류'}
          value={knownErrors ? `${errors.toLocaleString()}건` : null}
          hint={knownErrors && errors > 0 ? '중요한 파일은 백업해 두세요' : null} />
      </div>

      {d.warnings?.length > 0 && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-400 space-y-1">
          {d.warnings.map((w) => <div key={w} className="flex gap-1.5"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> 디스크 경고: {w}</div>)}
        </div>
      )}

      {n && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1.5 rounded-xl bg-gray-50 dark:bg-zinc-900/40 p-3">
          <Fact label="지금까지 쓴 양" value={bytesText(n.dataWrittenBytes)} />
          <Fact label="지금까지 읽은 양" value={bytesText(n.dataReadBytes)} />
          <Fact label="전원 켠 횟수" value={typeof n.powerCycles === 'number' ? `${n.powerCycles.toLocaleString()}회` : null} />
          <Fact label="갑자기 꺼진 횟수" value={typeof n.unsafeShutdowns === 'number' ? `${n.unsafeShutdowns.toLocaleString()}회` : null} />
          <Fact label="남은 예비 공간"
            value={typeof n.availableSparePct === 'number'
              ? `${n.availableSparePct}%${typeof n.spareThresholdPct === 'number' ? ` (기준 ${n.spareThresholdPct}%)` : ''}` : null}
            warn={typeof n.availableSparePct === 'number' && typeof n.spareThresholdPct === 'number' && n.availableSparePct <= n.spareThresholdPct} />
          <Fact label="디스크 오류 기록" value={typeof n.errorLogEntries === 'number' ? `${n.errorLogEntries.toLocaleString()}건` : null} />
        </div>
      )}
      <p className="text-[0.6875rem] text-gray-500">
        {d.source === 'nvme' ? '디스크가 직접 기록한 값입니다 (NVMe 건강 기록).' : 'Windows 저장소 관리가 알려 준 값입니다.'}
        {n && ' 디스크 오류 기록은 명령 거부처럼 데이터 손상이 아닌 일도 포함합니다.'}
      </p>
    </div>
  );
}

export default function HealthCenter({ active = true }) {
  const [disks, setDisks] = useState(null);         // null = 아직 확인 중
  const [boots, setBoots] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);

  const load = useCallback(async () => {
    const a = api();
    if (!a) return;
    setLoading(true);
    try {
      const [dh, bh] = await Promise.all([
        typeof a.getDiskHealth === 'function' ? a.getDiskHealth().catch((e) => ({ ok: false, error: String(e) })) : null,
        typeof a.getBootHistory === 'function' ? a.getBootHistory().catch((e) => ({ ok: false, error: String(e) })) : null,
      ]);
      setDisks(dh || { ok: false, error: '디스크 정보를 읽을 수 없습니다.' });
      setBoots(bh || { ok: false, error: '부팅 기록을 읽을 수 없습니다.' });
    } finally {
      setLoading(false);
      setLoadedOnce(true);
    }
  }, []);

  // 처음 열 때만 읽는다(PowerShell 조회라 몇 초 걸린다). 다시 보려면 '다시 확인'
  useEffect(() => { if (active && !loadedOnce && !loading) load(); }, [active, loadedOnce, loading, load]);

  const list = boots?.boots || [];
  const secs = list.map((b) => b.seconds);
  const avg = secs.length ? secs.reduce((s, v) => s + v, 0) / secs.length : null;
  const max = secs.length ? Math.max(...secs) : 1;
  const latest = list[0];
  const prevAvg = secs.length > 1 ? secs.slice(1).reduce((s, v) => s + v, 0) / (secs.length - 1) : null;
  const diff = latest && prevAvg ? latest.seconds - prevAvg : null;

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold mb-1">
            <HeartPulse className="w-4 h-4" /> HEALTH
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">PC 건강 진단</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1 max-w-2xl">
            디스크 상태와 부팅 시간을 Windows 가 기록한 값 그대로 보여 줍니다. 읽기만 하고 아무것도 바꾸지 않습니다.
          </p>
        </div>
        <button onClick={load} disabled={loading}
          className="btn-primary px-5 py-3 flex-shrink-0 disabled:opacity-50 disabled:cursor-wait">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          {loading ? '확인하는 중…' : '다시 확인'}
        </button>
      </div>

      {/* 디스크 건강 */}
      <section className="space-y-3">
        <h3 className="font-bold text-black dark:text-white px-1">디스크 건강</h3>
        {disks === null ? (
          <div className="glass-panel p-6 text-sm text-gray-500 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> 디스크 상태를 읽는 중…</div>
        ) : !disks.ok ? (
          <div className="glass-panel p-5 text-sm text-amber-400 flex gap-2"><AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /> {disks.error}</div>
        ) : disks.disks.length === 0 ? (
          <div className="glass-panel p-5 text-sm text-gray-500">Windows 가 알려 준 디스크가 없습니다.</div>
        ) : (
          disks.disks.map((d) => <DiskCard key={d.id || d.name} d={d} />)
        )}
      </section>

      {/* 부팅 시간 */}
      <section className="glass-panel p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-bold text-black dark:text-white flex items-center gap-2"><Timer className="w-4 h-4 text-cyan-400" /> 부팅 시간 기록</h3>
          <span className="text-[0.6875rem] text-gray-500">Windows 가 잰 값 · 전원을 켠 뒤 바탕 화면을 쓸 수 있을 때까지</span>
        </div>
        {boots === null ? (
          <div className="text-sm text-gray-500 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> 부팅 기록을 읽는 중…</div>
        ) : !boots.ok ? (
          <div className="text-sm text-amber-400 flex gap-2"><AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /> {boots.error}</div>
        ) : list.length === 0 ? (
          <div className="space-y-2">
            <div className="text-sm text-gray-500">{boots.note || '기록된 부팅이 없습니다.'}</div>
            {boots.stale && <div className="text-xs text-amber-400 flex gap-2"><AlertTriangle className="w-4 h-4 shrink-0" /> {boots.stale}</div>}
          </div>
        ) : (
          <>
            {boots.stale && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-400 flex gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" /> <span>{boots.stale}</span>
              </div>
            )}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl bg-gray-50 dark:bg-zinc-900/60 p-3">
                <div className="text-[0.6875rem] text-gray-500">{boots.stale ? '기록된 마지막 부팅' : '최근 부팅'}</div>
                <div className="text-xl font-black font-mono text-black dark:text-white">{latest.seconds}초</div>
                {diff !== null && Math.abs(diff) >= 1 && (
                  <div className={`text-[0.6875rem] font-bold ${diff < 0 ? 'text-emerald-400' : 'text-amber-400'}`}>
                    이전 평균보다 {Math.abs(diff).toFixed(1)}초 {diff < 0 ? '빠름' : '느림'}
                  </div>
                )}
              </div>
              <div className="rounded-xl bg-gray-50 dark:bg-zinc-900/60 p-3">
                <div className="text-[0.6875rem] text-gray-500">평균 ({list.length}번)</div>
                <div className="text-xl font-black font-mono text-black dark:text-white">{avg.toFixed(1)}초</div>
              </div>
              <div className="rounded-xl bg-gray-50 dark:bg-zinc-900/60 p-3">
                <div className="text-[0.6875rem] text-gray-500">가장 빠른 부팅</div>
                <div className="text-xl font-black font-mono text-black dark:text-white">{Math.min(...secs)}초</div>
              </div>
            </div>
            <div className="space-y-1.5">
              {list.map((b, i) => (
                <div key={`${b.at}-${i}`} className="flex items-center gap-3 text-xs">
                  <span className="w-28 shrink-0 text-gray-500">{dateText(b.at)}</span>
                  <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-zinc-800 overflow-hidden">
                    <div className={`h-full rounded-full ${i === 0 ? 'bg-cyan-400' : 'bg-gray-400 dark:bg-zinc-600'}`}
                      style={{ width: `${Math.max(3, (b.seconds / max) * 100)}%` }} />
                  </div>
                  <span className="w-14 shrink-0 text-right font-mono text-black dark:text-white">{b.seconds}초</span>
                </div>
              ))}
            </div>
            <p className="text-[0.6875rem] text-gray-500">
              시작 프로그램을 정리한 뒤 다시 부팅하면 이 목록에서 실제로 빨라졌는지 확인할 수 있습니다.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
