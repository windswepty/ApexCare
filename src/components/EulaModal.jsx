import React, { useState } from 'react';
import { ShieldCheck, CheckCircle2, Lock } from 'lucide-react';
import { playSound } from '../utils/audio';

export default function EulaModal({ onAccept }) {
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [agreeOpt, setAgreeOpt] = useState(false);
  const [agreePrivacy, setAgreePrivacy] = useState(false);

  const canProceed = agreeTerms && agreeOpt && agreePrivacy;

  const handleConfirm = () => {
    if (!canProceed) return;
    playSound('success');
    localStorage.setItem('apex_eula_accepted', 'true');
    onAccept();
  };

  return (
    <div className="fixed inset-0 z-50 bg-gray-100 dark:bg-slate-950/85 backdrop-blur-md flex items-center justify-center p-4 selection:bg-cyan-500 selection:text-slate-950">
      <div className="glass-panel max-w-xl w-full p-6 md:p-8 space-y-6 border-cyan-500/40 shadow-2xl relative overflow-hidden animate-in fade-in zoom-in duration-300">
        {/* Ambient Top Glow */}
        <div className="absolute -top-20 -left-20 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none"></div>

        {/* Header Title */}
        <div className="flex items-center gap-3 border-b border-black/10 dark:border-slate-800 pb-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-cyan-400 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/30 flex-shrink-0">
            <ShieldCheck className="w-7 h-7 text-slate-950" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-extrabold text-black dark:text-white">APEX CARE 이용약관 동의</h2>
              <span className="bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 text-[10px] font-mono px-2 py-0.5 rounded-full font-bold">
                EULA v3.8
              </span>
            </div>
            <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
              원활하고 안전한 PC 최적화 서비스를 위해 아래 이용약관에 동의해 주세요.
            </p>
          </div>
        </div>

        {/* Scrollable EULA Contract Text Area */}
        <div className="bg-gray-100 dark:bg-slate-950/70 p-4 rounded-xl border border-black/10 dark:border-slate-800 h-44 overflow-y-auto font-mono text-xs text-gray-700 dark:text-slate-300 space-y-3 scrollbar-thin scrollbar-thumb-cyan-500/30">
          <p className="font-bold text-cyan-400">[APEX CARE 최종 사용자 라이선스 계약서 - EULA]</p>
          
          <div>
            <strong className="text-black dark:text-white">제1조 (목적 및 소프트웨어 라이선스)</strong>
            <p className="text-gray-500 dark:text-slate-400 text-[11px] mt-1 leading-relaxed">
              본 약관은 APEX CARE 유틸리티(이하 "소프트웨어")를 사용함에 있어 사용자에게 제공되는 비독점적 개인용 라이선스 범위를 규정합니다.
            </p>
          </div>

          <div>
            <strong className="text-black dark:text-white">제2조 (시스템 최적화 및 임시 파일 세척 동의)</strong>
            <p className="text-gray-500 dark:text-slate-400 text-[11px] mt-1 leading-relaxed">
              사용자는 본 소프트웨어가 성능 향상을 위해 사용자 임시 폴더(%TEMP%) 및 시스템 공용 임시 폴더(C:\Windows\Temp)의 잔여 정크 파일 세척, 대기 메모리(Standby RAM) 퍼지 및 SSD TRIM 명령어를 수행하는 것에 동의합니다.
            </p>
          </div>

          <div>
            <strong className="text-black dark:text-white">제3조 (개인정보 수집 및 외부 전송 금지 보장)</strong>
            <p className="text-gray-500 dark:text-slate-400 text-[11px] mt-1 leading-relaxed">
              본 소프트웨어는 사용자의 개인 문서, 비밀번호, 방문 기록 등의 개인 식별 정보(PII)를 절대로 외부 서버로 수집하거나 전송하지 않으며, 모든 최적화 연산은 로컬 컴퓨터 내부에서만 완벽히 수행됩니다.
            </p>
          </div>
        </div>

        {/* Checkboxes List */}
        <div className="space-y-2.5 font-mono text-xs">
          <label className="flex items-center gap-3 p-3 rounded-xl bg-white dark:bg-slate-900/60 border border-black/10 dark:border-slate-800 cursor-pointer hover:border-black/10 dark:border-slate-700 transition-all">
            <input
              type="checkbox"
              checked={agreeTerms}
              onChange={(e) => {
                playSound('toggle');
                setAgreeTerms(e.target.checked);
              }}
              className="w-4 h-4 rounded bg-gray-100 dark:bg-slate-950 border-black/10 dark:border-slate-700 text-cyan-500 focus:ring-cyan-500 accent-cyan-500 cursor-pointer"
            />
            <span className="text-gray-800 dark:text-slate-200 font-semibold">
              [필수] APEX CARE 소프트웨어 서비스 이용약관 동의
            </span>
          </label>

          <label className="flex items-center gap-3 p-3 rounded-xl bg-white dark:bg-slate-900/60 border border-black/10 dark:border-slate-800 cursor-pointer hover:border-black/10 dark:border-slate-700 transition-all">
            <input
              type="checkbox"
              checked={agreeOpt}
              onChange={(e) => {
                playSound('toggle');
                setAgreeOpt(e.target.checked);
              }}
              className="w-4 h-4 rounded bg-gray-100 dark:bg-slate-950 border-black/10 dark:border-slate-700 text-cyan-500 focus:ring-cyan-500 accent-cyan-500 cursor-pointer"
            />
            <span className="text-gray-800 dark:text-slate-200 font-semibold">
              [필수] %TEMP% 및 C:\Windows\Temp 세척 & 자원 제어 동의
            </span>
          </label>

          <label className="flex items-center gap-3 p-3 rounded-xl bg-white dark:bg-slate-900/60 border border-black/10 dark:border-slate-800 cursor-pointer hover:border-black/10 dark:border-slate-700 transition-all">
            <input
              type="checkbox"
              checked={agreePrivacy}
              onChange={(e) => {
                playSound('toggle');
                setAgreePrivacy(e.target.checked);
              }}
              className="w-4 h-4 rounded bg-gray-100 dark:bg-slate-950 border-black/10 dark:border-slate-700 text-cyan-500 focus:ring-cyan-500 accent-cyan-500 cursor-pointer"
            />
            <span className="text-gray-800 dark:text-slate-200 font-semibold flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-emerald-400" />
              [필수] 개인정보 수집 없음 및 로컬 전용 처리 방침 확인
            </span>
          </label>
        </div>

        {/* Action Button */}
        <div className="pt-2">
          <button
            onClick={handleConfirm}
            disabled={!canProceed}
            className={`w-full py-3.5 rounded-xl font-black text-sm flex items-center justify-center gap-2 transition-all ${
              canProceed
                ? 'btn-primary shadow-lg shadow-cyan-500/20'
                : 'bg-gray-50 dark:bg-slate-800 text-slate-500 cursor-not-allowed border border-black/10 dark:border-slate-700/50'
            }`}
          >
            <CheckCircle2 className="w-5 h-5" />
            <span>약관 동의 및 APEX CARE 시작하기</span>
          </button>
        </div>
      </div>
    </div>
  );
}
