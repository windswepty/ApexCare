import { useEffect, useRef } from 'react';

// 화면에 보이는 탭에서만 주기적으로 fn 을 부른다. 창이 최소화·가려지면(document.hidden) 멈추고,
// 다시 보이거나 탭이 활성화되면 바로 한 번 부른 뒤 이어 간다.
//
// 모든 탭이 처음부터 떠 있고 display:none 으로 숨길 뿐이라, 예전에는 보지 않는 탭도 각자
// 2~5초마다 백엔드를 불렀다(프로세스 목록 수집 포함, 1분에 100번 넘게). enabled 로 막는다.
export function usePolling(fn, ms, enabled = true) {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return undefined;
    let id = null;
    const run = () => { if (!document.hidden) fnRef.current(); };
    const start = () => { if (id === null) id = setInterval(run, ms); };
    const stop = () => { if (id !== null) { clearInterval(id); id = null; } };
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        run();
        start();
      }
    };
    run();
    start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [ms, enabled]);
}
