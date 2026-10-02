import Lenis from 'lenis';

// 부드러운 스크롤(Lenis)을 붙이고, 스크롤 애니메이션이 움직이는 동안에만 프레임을 돌린다.
//
// 예전에는 App 과 Sidebar 가 각각 requestAnimationFrame 을 초당 60번, 창이 떠 있는 내내 돌렸다.
// 스크롤하지 않을 때도 매 프레임 자바스크립트가 깨어나 CPU·GPU 를 썼다. 이제 휠·터치로 스크롤이
// 시작될 때('virtual-scroll') 루프를 켜고, 애니메이션이 끝나면 멈춘다.
export function attachSmoothScroll(wrapper, content) {
  const lenis = new Lenis({
    wrapper,
    content,
    lerp: 0.05,
    smoothWheel: true,
    wheelMultiplier: 1.0,
    // 안쪽에 따로 스크롤되는 목록(프로그램 목록, 남은 폴더 확인 목록, 대용량 파일 결과, 기본 앱 목록 등)이 휠을 받게 한다.
    // 없으면 Lenis 가 휠 이벤트를 막아, 지울 대상 목록을 휠로 내려 볼 수 없었다.
    allowNestedScroll: true,
  });

  let frameId = null;
  const loop = (time) => {
    lenis.raf(time);
    frameId = lenis.animate.isRunning ? requestAnimationFrame(loop) : null;
  };
  const start = () => {
    if (frameId !== null) return;
    // 쉬는 동안 흐른 시간을 한 프레임으로 계산하면 애니메이션이 끝까지 한 번에 튄다.
    lenis.time = performance.now();
    frameId = requestAnimationFrame(loop);
  };
  const off = lenis.on('virtual-scroll', start);

  return () => {
    if (frameId !== null) cancelAnimationFrame(frameId);
    if (typeof off === 'function') off();
    lenis.destroy();
  };
}
