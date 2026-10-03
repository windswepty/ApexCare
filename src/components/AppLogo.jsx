import React from 'react';

// 앱 로고. 둥근 바탕과 기호를 따로 칠한다. 색은 환경 설정의 '앱 아이콘 색'(theme.js applyIcon)이
// 문서 변수 --icon-tile·--icon-glyph 로 넣는다. 그래서 사이드바·제목 표시줄·로딩 화면의 로고가 한꺼번에 바뀐다.
const layer = (src, color) => ({
  position: 'absolute',
  inset: 0,
  background: color,
  WebkitMaskImage: `url(${src})`,
  maskImage: `url(${src})`,
  WebkitMaskSize: 'contain',
  maskSize: 'contain',
  WebkitMaskRepeat: 'no-repeat',
  maskRepeat: 'no-repeat',
  WebkitMaskPosition: 'center',
  maskPosition: 'center',
});

export default function AppLogo({ className = 'w-10 h-10', tile, glyph }) {
  return (
    <span role="img" aria-label="APEX CARE" className={`relative inline-block flex-shrink-0 ${className}`}>
      <span style={layer('/icon-tile.png', tile || 'var(--icon-tile, #ffffff)')} />
      <span style={layer('/icon-glyph.png', glyph || 'var(--icon-glyph, #000000)')} />
    </span>
  );
}
