import React, { useState, useEffect } from 'react';
import AppLogo from './AppLogo';

// 이 화면이 실제로 기다리는 것은 하나다: 백엔드가 연결되고 첫 시스템 정보를 받는 것
// (App.jsx 의 isBackendReady). 얼마나 남았는지는 알 수 없으므로 퍼센트를 보여주지 않는다.
// 예전에는 진행률을 무작위로 90%까지 올리며 '시스템 환경 분석 중', '하드웨어 상태 스캔 중' 처럼
// 실제로 하지 않는 작업 이름을 돌려 보여줬다.
const SLOW_AFTER_MS = 15000;

export default function LoadingScreen({ isAppReady, onComplete, isDarkMode }) {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (isAppReady) return;
    const tm = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(tm);
  }, [isAppReady]);

  useEffect(() => {
    if (isAppReady) {
      const tm = setTimeout(() => {
        onComplete();
      }, 300);
      return () => clearTimeout(tm);
    }
  }, [isAppReady, onComplete]);

  return (
    <div className={`fixed inset-0 z-50 flex flex-col items-center justify-center ${isDarkMode ? 'bg-zinc-950 text-black dark:text-white' : 'bg-white text-black'}`}>
      <div className="w-64 flex flex-col items-center">
        <AppLogo className="w-16 h-16 mb-8 image-reveal-animation" />
        <h2 className="text-2xl font-black tracking-tight mb-6 flex items-center gap-2">
          APEX <span className="text-gray-500">CARE</span>
        </h2>

        {/* 남은 양을 모르므로 끝이 정해지지 않은 막대 */}
        <div
          role="progressbar"
          aria-label="시스템 정보를 읽는 중"
          aria-busy={!isAppReady}
          className="relative w-full h-2 bg-gray-100 dark:bg-zinc-900 border border-black/10 dark:border-white/10 rounded-full overflow-hidden mb-3"
        >
          {isAppReady ? (
            <div className="h-full w-full bg-black dark:bg-white"></div>
          ) : (
            <div className="absolute inset-y-0 w-1/3 bg-black dark:bg-white rounded-full animate-indeterminate motion-reduce:w-full motion-reduce:opacity-40"></div>
          )}
        </div>

        <p className="w-full px-1 text-[0.6875rem] font-mono text-gray-500 dark:text-gray-400 text-center">
          {isAppReady ? '준비됐습니다' : '시스템 정보를 읽는 중…'}
        </p>
        {slow && !isAppReady && (
          <p className="mt-3 text-[0.6875rem] text-amber-500 text-center leading-relaxed">
            {SLOW_AFTER_MS / 1000}초가 넘도록 응답이 없습니다. 계속 기다리고 있으며,
            오래 걸리면 앱을 닫았다가 다시 실행해 보세요.
          </p>
        )}
      </div>
    </div>
  );
}
