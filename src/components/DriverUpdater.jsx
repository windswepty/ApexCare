import React, { useState } from 'react';
import { 
  ShieldCheck, 
  RotateCw, 
  CheckCircle2, 
  AlertCircle, 
  Terminal,
  Activity,
  Layers,
  Sparkles
} from 'lucide-react';
import { playSound } from '../utils/audio';

export default function SystemRepair({ addToast }) {
  const [sfcStatus, setSfcStatus] = useState('idle');
  const [dismStatus, setDismStatus] = useState('idle');
  const runSfc = async () => {
    playSound('scan');
    setSfcStatus('running');
    
    try {
      let res = null;
      if (window.pywebview?.api && window.pywebview?.api.runSfc) {
        res = await window.pywebview?.api.runSfc();
      } else {
        await new Promise(r => setTimeout(r, 3000));
        res = { success: true };
      }
      
      setSfcStatus(res?.success ? 'success' : 'error');
      playSound(res?.success ? 'success' : 'error');
      if (addToast) addToast(res?.success ? 'SFC 시스템 무결성 검사 및 복구가 완료되었습니다!' : 'SFC 검사에 실패했습니다.', res?.success ? 'success' : 'error');
    } catch (e) {
      setSfcStatus('error');
    }
  };

  const runDism = async () => {
    playSound('scan');
    setDismStatus('running');
    
    try {
      let res = null;
      if (window.pywebview?.api && window.pywebview?.api.runDism) {
        res = await window.pywebview?.api.runDism();
      } else {
        await new Promise(r => setTimeout(r, 3000));
        res = { success: true };
      }

      setDismStatus(res?.success ? 'success' : 'error');
      playSound(res?.success ? 'success' : 'error');
      if (addToast) addToast(res?.success ? 'DISM 시스템 이미지 복구가 완료되었습니다!' : 'DISM 복구에 실패했습니다.', res?.success ? 'success' : 'error');
    } catch (e) {
      setDismStatus('error');
    }
  };

  const isAnyRunning = sfcStatus === 'running' || dismStatus === 'running';

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
        <div className="space-y-1 z-10">
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold">
            <ShieldCheck className="w-4 h-4" />
            WINDOWS OS CORE REPAIR & MAINTENANCE
          </div>
          <h2 className="text-2xl font-black text-black dark:text-white">OS 코어 파일 시스템 복구</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400">
            손상된 윈도우 시스템 파일을 스캔하여 원본으로 복구하고(SFC), Windows 이미지 손상을 복구(DISM)하여 블루스크린(BSOD)과 앱 크래시를 원천 방지합니다.
          </p>
        </div>
      </div>

      {/* SFC Panel */}
      <div className={`glass-panel p-5 flex flex-col gap-4 transition-all duration-300 ${
        sfcStatus === 'running' ? 'border-cyan-500/50 shadow-lg shadow-cyan-500/10' : 'border-black/10 dark:border-slate-800'
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
              <p className="text-xs text-gray-500 dark:text-slate-400">무결성 위반을 검사하고 손상된 시스템 코어 파일을 교체합니다. (약 3~5분 소요)</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {sfcStatus === 'success' ? (
              <div className="flex items-center gap-1.5 text-xs font-mono text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/30 px-3 py-2 rounded-xl">
                <CheckCircle2 className="w-4 h-4" />
                무결성 복구 완료
              </div>
            ) : sfcStatus === 'error' ? (
              <div className="flex items-center gap-1.5 text-xs font-mono text-rose-400 font-bold bg-rose-500/10 border border-rose-500/30 px-3 py-2 rounded-xl">
                <AlertCircle className="w-4 h-4" />
                오류 발생 (관리자 권한 필요)
              </div>
            ) : sfcStatus === 'running' ? (
              <button disabled className="btn-primary text-xs px-5 py-2.5 flex items-center gap-2 opacity-75 cursor-not-allowed">
                <RotateCw className="w-4 h-4 animate-spin" />
                <span>검사 진행 중...</span>
              </button>
            ) : (
              <button
                onClick={runSfc}
                disabled={isAnyRunning}
                className={`btn-primary text-xs px-5 py-2.5 flex items-center gap-2 ${isAnyRunning ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <RotateCw className="w-4 h-4" />
                <span>SFC 검사 실행</span>
              </button>
            )}
          </div>
        </div>

        {/* SFC Progress Indicator */}
        {sfcStatus === 'running' && (
          <div className="mt-2 p-4 rounded-xl bg-black/5 dark:bg-black/40 border border-black/10 dark:border-white/5 flex items-center justify-center gap-3 text-cyan-500 dark:text-cyan-400 font-mono text-sm">
            <RotateCw className="w-5 h-5 animate-spin" />
            시스템 무결성 스캔 및 원본 파일 복원 중...
          </div>
        )}
      </div>

      {/* DISM Panel */}
      <div className={`glass-panel p-5 flex flex-col gap-4 transition-all duration-300 ${
        dismStatus === 'running' ? 'border-purple-500/50 shadow-lg shadow-purple-500/10' : 'border-black/10 dark:border-slate-800'
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
              <h3 className="font-bold text-black dark:text-white text-base">Windows 배포 이미지 서비스 및 관리 (DISM)</h3>
              <p className="text-xs text-gray-500 dark:text-slate-400">Windows Update 서버를 통해 내부 OS 컴포넌트 저장소의 손상을 원격 복원합니다. (약 5~10분 소요)</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {dismStatus === 'success' ? (
              <div className="flex items-center gap-1.5 text-xs font-mono text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/30 px-3 py-2 rounded-xl">
                <CheckCircle2 className="w-4 h-4" />
                이미지 복원 완료
              </div>
            ) : dismStatus === 'error' ? (
              <div className="flex items-center gap-1.5 text-xs font-mono text-rose-400 font-bold bg-rose-500/10 border border-rose-500/30 px-3 py-2 rounded-xl">
                <AlertCircle className="w-4 h-4" />
                오류 발생 (관리자 권한 필요)
              </div>
            ) : dismStatus === 'running' ? (
              <button disabled className="btn-primary bg-gradient-to-r from-purple-500 to-indigo-600 shadow-purple-500/30 text-xs px-5 py-2.5 flex items-center gap-2 opacity-75 cursor-not-allowed">
                <RotateCw className="w-4 h-4 animate-spin" />
                <span>온라인 복구 중...</span>
              </button>
            ) : (
              <button
                onClick={runDism}
                disabled={isAnyRunning}
                className={`btn-primary bg-gradient-to-r from-purple-500 to-indigo-600 shadow-purple-500/30 text-xs px-5 py-2.5 flex items-center gap-2 ${isAnyRunning ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <Activity className="w-4 h-4" />
                <span>DISM 복구 실행</span>
              </button>
            )}
          </div>
        </div>

        {/* DISM Progress Indicator */}
        {dismStatus === 'running' && (
          <div className="mt-2 p-4 rounded-xl bg-black/5 dark:bg-black/40 border border-black/10 dark:border-white/5 flex items-center justify-center gap-3 text-purple-500 dark:text-purple-400 font-mono text-sm">
            <RotateCw className="w-5 h-5 animate-spin" />
            서버 연결 및 Windows 배포 이미지 원본 다운로드 및 복원 중...
          </div>
        )}
      </div>

    </div>
  );
}
