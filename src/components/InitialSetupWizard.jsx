import { useState, useEffect } from 'react';
import { Cpu, HardDrive, Monitor, Zap, CheckCircle2, XCircle, ChevronRight, Loader2, Gauge, Sliders, MemoryStick } from 'lucide-react';

// 사양 판정에 쓰는 메모리 용량. 꽂혀 있는 용량(설치)을 쓴다. Windows 가 쓸 수 있는 용량은 내장 그래픽 예약만큼
// 작아서, 예전에는 8GB PC 가 7.8GB 로 읽혀 'RAM 8 GB 미만 = 저사양' 에 걸려 SysMain 이 꺼졌다.
function ramForTier(stats) {
  const installed = Number(stats?.ramInstalledGB);
  return installed > 0 ? installed : Number(stats?.ramTotalGB) || 0;
}

export default function InitialSetupWizard({ stats, onComplete, isDarkMode }) {
  // 'result' | 'consent' | 'applying' | 'done'
  // 예전에는 사양을 이미 받아 놓고도 '하드웨어 스펙 분석 중' 가짜 진행 막대를 보여줬다.
  const [step, setStep] = useState('result');
  const [preview, setPreview] = useState(null);      // 백엔드 미리보기 { tier, changes } — 시스템은 바꾸지 않는다
  const [previewError, setPreviewError] = useState(null);
  const [applyResult, setApplyResult] = useState(null);
  const [consentChecked, setConsentChecked] = useState(false);
  // 사양 정보를 오래 받지 못하면 알린다(건너뛰기는 처음부터 가능)
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (stats) return;
    const tm = setTimeout(() => setSlow(true), 15000);
    return () => clearTimeout(tm);
  }, [stats]);

  // 사양을 받으면 무엇이 바뀌는지 백엔드에 물어본다(consent=false: 미리보기만).
  // 저사양 판정 기준도 백엔드 한 곳(optimizer.apply_hardware_tailored_tuning)에서 온다.
  useEffect(() => {
    if (!stats || preview) return;
    // 코어 수나 메모리 용량을 모르면 사양을 판정하지 않는다(0 은 저사양으로 읽혀 SysMain 을 끄자고 했다)
    if (!(Number(stats.cpuCores) >= 1) || !(ramForTier(stats) > 0)) {
      setPreviewError('코어 수나 메모리 용량을 읽지 못해 사양에 맞는 설정을 제안할 수 없습니다. 건너뛰어도 아무것도 바뀌지 않습니다.');
      return;
    }
    const api = window.pywebview?.api;
    if (!api?.applyHardwareTuning) {
      setPreviewError('API가 준비되지 않아 제안할 설정을 불러오지 못했습니다.');
      return;
    }
    api.applyHardwareTuning(stats.cpuCores, ramForTier(stats), false)
      .then(res => {
        if (res?.success && Array.isArray(res.changes)) setPreview({ tier: res.tier, changes: res.changes });
        else setPreviewError(res?.message || '제안할 설정을 불러오지 못했습니다.');
      })
      .catch(e => setPreviewError(`제안할 설정을 불러오지 못했습니다: ${e}`));
  }, [stats]); // eslint-disable-line react-hooks/exhaustive-deps

  const pendingChanges = preview?.changes || [];
  const tuningTier = preview?.tier;

  // 사용자가 항목을 확인하고 동의한 경우에만 실제 적용하고, 항목별 결과를 보여준다
  const handleApply = async () => {
    setStep('applying');
    try {
      const res = await window.pywebview.api.applyHardwareTuning(stats.cpuCores, ramForTier(stats), true);
      setApplyResult(res || { success: false, message: '응답이 없습니다.' });
    } catch (e) {
      console.error("Failed to apply hardware tuning:", e);
      setApplyResult({ success: false, message: `적용 중 오류가 발생했습니다: ${e}` });
    }
    setStep('done');
  };

  const getTuningInfo = (tier) => {
    if (tier === 'LowEnd') {
      return {
        title: '저사양 PC용 설정',
        desc: "SysMain 서비스를 끄고 대기 메모리를 한 번 비웁니다. Windows Search 는 건드리지 않아 시작 메뉴·탐색기 검색은 그대로입니다. 전원 플랜은 바꾸지 않습니다.",
        icon: Sliders,
        color: 'text-amber-400',
        bg: 'bg-amber-500/20',
        border: 'border-amber-500/50'
      };
    }
    return {
      title: '일반·고사양 PC용 설정',
      desc: "SysMain·Windows Search 서비스를 자동 시작으로 둡니다. 전원 플랜은 바꾸지 않습니다. 고성능 플랜이 필요하면 성능 모드에서 '게이밍'을 고르세요.",
      icon: Gauge,
      color: 'text-cyan-400',
      bg: 'bg-cyan-500/20',
      border: 'border-cyan-500/50'
    };
  };

  const TierInfo = getTuningInfo(tuningTier);
  const InfoIcon = TierInfo.icon;
  const muted = isDarkMode ? 'text-gray-400' : 'text-gray-600';
  const band = isDarkMode ? 'border-white/10 bg-white/5' : 'border-black/10 bg-black/5';
  const card = isDarkMode ? 'bg-black/40 border-white/10' : 'bg-gray-50 border-black/10';
  const primaryBtn = isDarkMode
    ? 'bg-white text-black hover:bg-gray-200 shadow-white/10'
    : 'bg-black text-white hover:bg-gray-800 shadow-black/10';
  const skipBtn = `px-5 py-2.5 rounded-xl text-sm font-semibold transition-all ${isDarkMode ? 'hover:bg-white/10 text-gray-400' : 'hover:bg-black/5 text-gray-600'}`;

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center p-6 ${isDarkMode ? 'bg-black/95 text-white' : 'bg-gray-100/95 text-black'}`}>

      {/* Background Decor */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-cyan-500/10 blur-[120px] rounded-full pointer-events-none"></div>

      <div className={`relative w-full max-w-2xl rounded-3xl border shadow-2xl overflow-hidden transition-all duration-700 ${isDarkMode ? 'bg-zinc-950/80 border-white/10' : 'bg-white/90 border-black/10'}`}>

        {!stats ? (
          // 사양을 아직 받지 못했을 때만 보이는 실제 대기 화면
          <div className="flex flex-col items-center justify-center py-32 px-10">
            <Loader2 className="w-16 h-16 text-cyan-400 animate-spin mb-6" />
            <h2 className="text-2xl font-black mb-2 tracking-tight">PC 사양을 읽는 중</h2>
            <p className={`text-sm ${muted}`}>
              프로세서·메모리·드라이브 정보를 가져오고 있습니다.
            </p>
            {slow && (
              <p className="text-xs text-amber-500 mt-4 text-center">
                15초가 넘도록 사양 정보를 받지 못했습니다. 건너뛰어도 아무것도 바뀌지 않습니다.
              </p>
            )}
            <button onClick={() => onComplete()} className={`${skipBtn} mt-6`}>
              건너뛰기 (적용 안함)
            </button>
          </div>
        ) : step === 'consent' ? (
          <div className="flex flex-col animate-fade-in-up">
            <div className={`p-8 pb-6 border-b ${band}`}>
              <h2 className="text-2xl font-black tracking-tight mb-2">적용 전 확인: 아래 항목이 바뀝니다</h2>
              {/* 예전 제목 '영구적으로 변경됩니다' 는 되돌릴 수 없다는 뜻으로 읽혔다. 실제로는 원래 값을 기록해 되돌릴 수 있다. */}
              <p className={`text-sm ${muted}`}>
                서비스 설정은 재부팅 후에도 유지되며, '변경 내역 · 되돌리기' 에서 원래대로 되돌릴 수 있습니다.
                Windows Update 및 보안 관련 서비스는 변경하지 않습니다.
              </p>
            </div>

            <div className="p-8 space-y-3">
              {pendingChanges.length === 0 ? (
                <div className={`text-sm ${muted}`}>
                  변경 항목을 불러오지 못했습니다. '건너뛰기'를 눌러 아무것도 적용하지 않고 진행할 수 있습니다.
                </div>
              ) : pendingChanges.map((change, idx) => (
                <div key={idx} className={`flex items-start gap-3 p-4 rounded-xl border ${card}`}>
                  <Sliders className="w-4 h-4 mt-0.5 text-amber-400 flex-shrink-0" />
                  <span className="text-xs leading-relaxed">{change}</span>
                </div>
              ))}

              <label className="flex items-center gap-3 pt-4 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={consentChecked}
                  onChange={(e) => setConsentChecked(e.target.checked)}
                  className="w-4 h-4 accent-cyan-400"
                />
                <span className="text-xs font-semibold">위 변경 사항을 이해했으며 적용에 동의합니다.</span>
              </label>
            </div>

            <div className={`p-6 border-t flex justify-end gap-3 ${band}`}>
              <button onClick={() => onComplete()} className={skipBtn}>
                건너뛰기 (적용 안함)
              </button>
              <button
                onClick={handleApply}
                disabled={!consentChecked || pendingChanges.length === 0}
                className={`px-6 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-lg active:scale-95 ${
                  (!consentChecked || pendingChanges.length === 0)
                    ? 'bg-gray-400 text-white cursor-not-allowed opacity-50'
                    : primaryBtn
                }`}
              >
                동의하고 적용
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        ) : step === 'applying' ? (
          <div className="flex flex-col items-center justify-center py-32 px-10">
            <Zap className="w-16 h-16 text-yellow-400 animate-pulse mb-6" />
            <h2 className="text-2xl font-black mb-2 tracking-tight">설정 적용 중...</h2>
            <p className={`text-sm ${muted}`}>
              서비스 시작 유형을 바꾸고 있습니다.
            </p>
          </div>
        ) : step === 'done' ? (
          // 백엔드가 되읽어 확인한 항목별 결과를 그대로 보여준다
          <div className="flex flex-col animate-fade-in-up">
            <div className={`p-8 pb-6 border-b ${band}`}>
              <h2 className="text-2xl font-black tracking-tight mb-2">
                {applyResult?.success ? '설정을 적용했습니다' : '일부 또는 전체를 적용하지 못했습니다'}
              </h2>
              <p className={`text-sm ${muted}`}>{applyResult?.message}</p>
            </div>
            <div className="p-8 space-y-2">
              {(applyResult?.steps || []).map((st, idx) => (
                <div key={idx} className={`flex items-start gap-3 p-3 rounded-xl border ${card}`}>
                  {st.ok
                    ? <CheckCircle2 className="w-4 h-4 mt-0.5 text-emerald-400 flex-shrink-0" />
                    : <XCircle className="w-4 h-4 mt-0.5 text-rose-400 flex-shrink-0" />}
                  <div className="text-xs leading-relaxed">
                    <div className="font-semibold">{st.name}</div>
                    {st.detail && <div className={muted}>{st.detail}</div>}
                  </div>
                </div>
              ))}
              {/* 서비스 시작 유형은 system_state 저널의 hw_tuning 그룹에 기록된다. 전원 플랜은 맞춤 튜닝이 바꾸지 않는다 */}
              <p className="text-xs pt-2 text-gray-500">
                바꾼 설정은 '변경 내역 · 되돌리기' 의 '전부 원래대로' 로 되돌릴 수 있습니다(이 앱이 바꾼 다른 설정도 함께
                되돌아갑니다). 전원 플랜은 성능 모드에서 고릅니다.
              </p>
            </div>
            <div className={`p-6 border-t flex justify-end ${band}`}>
              <button
                onClick={() => onComplete()}
                className={`px-6 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-lg active:scale-95 ${primaryBtn}`}
              >
                계속
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col h-full animate-fade-in-up">
            {/* Header */}
            <div className={`p-8 pb-6 border-b ${band}`}>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-xl bg-black dark:bg-white flex items-center justify-center">
                  <img src="/icon.png" alt="logo" className="w-6 h-6 invert dark:invert-0" />
                </div>
                <div>
                  <h1 className="text-2xl font-black tracking-tight flex items-center gap-2">
                    <span className="text-cyan-400">APEX CARE</span> 초기 설정
                  </h1>
                </div>
              </div>
              <p className={`text-sm mt-2 ${muted}`}>
                이 PC 사양에 맞는 기본 설정을 제안합니다. 적용하지 않고 건너뛸 수도 있습니다.
              </p>
            </div>

            {/* Body */}
            <div className="p-8 grid grid-cols-1 md:grid-cols-2 gap-8">

              {/* Left: Specs */}
              <div>
                <h3 className="text-xs font-bold mb-4 text-gray-500">
                  이 PC 사양
                </h3>

                <div className="grid grid-cols-2 gap-3">
                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <Cpu className={`w-4 h-4 ${muted}`} />
                      <div className={`text-[0.625rem] ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>프로세서</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate" title={stats?.cpuModel}>{stats?.cpuModel || '알 수 없음'}</div>
                      <div className={`text-[0.625rem] font-mono mt-0.5 ${isDarkMode ? 'text-cyan-400/70' : 'text-cyan-600'}`}>
                        {stats?.cpuCores || '?'}코어 / {stats?.cpuThreads || '?'}스레드
                      </div>
                    </div>
                  </div>

                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <Monitor className={`w-4 h-4 ${muted}`} />
                      <div className={`text-[0.625rem] ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>그래픽 (GPU)</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate" title={stats?.gpuModel || '알 수 없음'}>{stats?.gpuModel || '알 수 없음'}</div>
                    </div>
                  </div>

                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <MemoryStick className={`w-4 h-4 ${muted}`} />
                      <div className={`text-[0.625rem] ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>메모리 (RAM)</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate">
                        {Number(stats?.ramInstalledGB) > 0
                          ? `${Number(stats.ramInstalledGB).toFixed(1)} GB 설치 (사용 가능 ${stats.ramTotalGB} GB)`
                          : Number(stats?.ramTotalGB) > 0 ? `${stats.ramTotalGB} GB (사용 가능)` : '알 수 없음'}
                      </div>
                    </div>
                  </div>

                  <div className={`p-3 rounded-xl border flex flex-col justify-center gap-2 ${isDarkMode ? 'bg-black/40 border-white/5' : 'bg-gray-50 border-black/5'}`}>
                    <div className="flex items-center gap-2">
                      <HardDrive className={`w-4 h-4 ${muted}`} />
                      <div className={`text-[0.625rem] font-mono ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>{stats?.systemDrive || '시스템'} 드라이브</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-xs truncate">{Number(stats?.diskTotalGB) > 0 ? `전체 ${stats.diskTotalGB} GB` : '알 수 없음'}</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right: 제안 설정 — 백엔드 미리보기를 받은 뒤에만 */}
              <div className="flex flex-col justify-center">
                <h3 className="text-xs font-bold mb-4 text-gray-500">
                  제안하는 설정
                </h3>

                {tuningTier ? (
                  <div className={`relative p-6 rounded-2xl border-2 ${TierInfo.border} ${TierInfo.bg} overflow-hidden shadow-lg`}>
                    <InfoIcon className={`w-10 h-10 mb-4 ${TierInfo.color}`} />
                    <h4 className="text-lg font-black mb-2">{TierInfo.title}</h4>
                    <p className={`text-xs leading-relaxed ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                      {TierInfo.desc}
                    </p>
                    <p className={`text-[0.625rem] font-mono mt-3 ${muted}`}>
                      기준: 코어 4개 이하 또는 RAM 8 GB 미만이면 저사양 · 이 PC 코어 {stats.cpuCores}개, RAM {ramForTier(stats)} GB
                    </p>
                  </div>
                ) : (
                  <div className={`p-6 rounded-2xl border text-xs ${isDarkMode ? 'border-white/10 text-gray-400' : 'border-black/10 text-gray-600'}`}>
                    {previewError || '제안할 설정을 불러오는 중…'}
                  </div>
                )}
              </div>

            </div>

            {/* Footer Buttons */}
            <div className={`p-6 border-t flex justify-end gap-3 ${band}`}>
              <button onClick={() => onComplete()} className={skipBtn}>
                건너뛰기 (적용 안함)
              </button>

              <button
                onClick={() => { setConsentChecked(false); setStep('consent'); }}
                disabled={!preview}
                className={`px-6 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 transition-all shadow-lg active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed ${primaryBtn}`}
              >
                변경 내용 확인하기
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}
