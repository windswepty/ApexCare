// CPU 실제 속도 표시. 백엔드가 잰 값(cpuClockMHz)과 기본 클럭(cpuBaseMHz)만 쓴다. 값이 없으면 지어내지 않는다.
export function clockLabel(mhz, baseMhz) {
  if (typeof mhz !== 'number' || !Number.isFinite(mhz) || mhz <= 0) {
    return { text: '측정 중', state: null, stateClass: '' };
  }
  const text = `${(mhz / 1000).toFixed(2)} GHz`;
  if (typeof baseMhz !== 'number' || baseMhz <= 0) {
    return { text, state: null, stateClass: '' };
  }
  const ratio = mhz / baseMhz;
  if (ratio >= 1.03) return { text, state: '부스트', stateClass: 'text-rose-400' };
  if (ratio <= 0.9) return { text, state: '절전', stateClass: 'text-emerald-400' };
  return { text, state: '기본', stateClass: 'text-gray-400' };
}
