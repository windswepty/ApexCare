// 우선순위 '되돌리기' 결과 문장. 백엔드 process_boost.restore_all() 의 값을 그대로 옮긴다.
// 이미 끝난 프로세스(gone)는 되돌린 수에 넣지 않는다. 예전에는 둘을 합쳐 숫자가 부풀었다.
export function restoreMessage(res) {
  const restored = Number(res?.restored) || 0;
  const gone = Number(res?.gone) || 0;
  const failed = Array.isArray(res?.failed) ? res.failed : [];
  const goneNote = gone > 0 ? ` (${gone}개는 이미 종료되어 되돌릴 필요가 없었습니다)` : '';
  if (failed.length) {
    const why = failed[0]?.reason ? `: ${failed[0].reason}` : '';
    return `${restored}개 되돌림, ${failed.length}개 실패${why}${goneNote}`;
  }
  if (restored === 0) {
    return gone > 0 ? `되돌릴 프로세스가 없습니다. 조정했던 ${gone}개는 이미 종료됐습니다.` : '되돌릴 프로세스가 없습니다.';
  }
  return `${restored}개 프로세스를 원래 우선순위로 되돌렸습니다.${goneNote}`;
}
