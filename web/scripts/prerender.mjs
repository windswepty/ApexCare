// 각 라우트를 정적 HTML 로 뽑는다.
//
// 왜 필요한가: SPA 는 모든 주소에 같은 빈 index.html 을 준다. 그래서
//  1) 카카오톡·디스코드·커뮤니티 링크 미리보기가 전부 홈 문구로 뜨고,
//  2) JS 실행이 약한 크롤러(특히 네이버)에는 본문이 아예 보이지 않는다.
// 공유와 검색이 이 사이트의 주 유입 경로라 둘 다 치명적이다.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const distDir = join(root, 'dist')

// 윈도우 절대경로("C:\...")는 ESM 로더가 프로토콜로 오해한다. file:// URL 로 넘겨야 한다.
const { render, ROUTES, SITE } = await import(
  pathToFileURL(join(root, 'dist-ssr', 'entry-server.js')).href
)

const template = readFileSync(join(distDir, 'index.html'), 'utf-8')
const base = SITE.url.replace(/\/$/, '')

const esc = (s) =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

function buildHead(route) {
  const url = base + route.path
  const title = esc(route.title)
  const desc = esc(route.description)
  return [
    `<title>${title}</title>`,
    `<meta name="description" content="${desc}" />`,
    `<link rel="canonical" href="${esc(url)}" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:site_name" content="${esc(SITE.name)}" />`,
    `<meta property="og:url" content="${esc(url)}" />`,
    `<meta property="og:title" content="${title}" />`,
    `<meta property="og:description" content="${desc}" />`,
    `<meta property="og:locale" content="ko_KR" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${title}" />`,
    `<meta name="twitter:description" content="${desc}" />`
  ].join('\n    ')
}

function jsonLd(route) {
  const data =
    route.path === '/'
      ? {
          '@context': 'https://schema.org',
          '@type': 'WebSite',
          name: SITE.name,
          url: SITE.url,
          description: route.description
        }
      : {
          '@context': 'https://schema.org',
          '@type': 'WebApplication',
          name: route.title.split(' — ')[0],
          url: base + route.path,
          description: route.description,
          applicationCategory: 'UtilitiesApplication',
          operatingSystem: 'Any (웹 브라우저)',
          // 무료라는 사실 자체가 후원 명분이므로 구조화 데이터에도 명시한다
          offers: { '@type': 'Offer', price: '0', priceCurrency: 'KRW' }
        }
  return `<script type="application/ld+json">${JSON.stringify(data)}</script>`
}

let written = 0
for (const route of ROUTES) {
  const appHtml = render(route.path)

  const html = template
    // 템플릿의 기본 메타를 라우트별 값으로 통째로 교체한다
    .replace(/<title>[\s\S]*?<\/title>/, '@@HEAD@@')
    .replace(/\s*<meta name="description"[^>]*>/, '')
    .replace(/\s*<meta property="og:type"[^>]*>/, '')
    .replace(/\s*<meta property="og:title"[^>]*>/, '')
    .replace(/\s*<meta property="og:description"[^>]*>/, '')
    .replace('@@HEAD@@', buildHead(route))
    .replace('</head>', `  ${jsonLd(route)}\n  </head>`)
    .replace('<div id="root"></div>', `<div id="root">${appHtml}</div>`)

  if (route.path === '/') {
    writeFileSync(join(distDir, 'index.html'), html, 'utf-8')
  } else {
    // 정적 호스트마다 슬래시 없는 주소를 푸는 방식이 다르다.
    //   어떤 곳은 "<경로>.html", 어떤 곳은 "<경로>/index.html" 을 찾는다.
    // 둘 다 만들어 두지 않으면 호스트에 따라 SPA 폴백(=홈 HTML)이 나가면서
    // 라우트별 메타와 본문이 통째로 무의미해진다.
    const slug = route.path.replace(/^\//, '')
    mkdirSync(join(distDir, slug), { recursive: true })
    writeFileSync(join(distDir, slug, 'index.html'), html, 'utf-8')
    writeFileSync(join(distDir, `${slug}.html`), html, 'utf-8')
  }
  written++
  console.log(`  prerendered ${route.path.padEnd(22)} ${(html.length / 1024).toFixed(1)} KB`)
}

const today = new Date().toISOString().slice(0, 10)
const urls = ROUTES.map((r) =>
  [
    '  <url>',
    `    <loc>${base}${r.path}</loc>`,
    `    <lastmod>${today}</lastmod>`,
    `    <changefreq>${r.changefreq}</changefreq>`,
    `    <priority>${r.priority}</priority>`,
    '  </url>'
  ].join('\n')
).join('\n')

const sitemap = [
  '<?xml version="1.0" encoding="UTF-8"?>',
  '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
  urls,
  '</urlset>',
  ''
].join('\n')
writeFileSync(join(distDir, 'sitemap.xml'), sitemap, 'utf-8')

writeFileSync(
  join(distDir, 'robots.txt'),
  ['User-agent: *', 'Allow: /', '', `Sitemap: ${base}/sitemap.xml`, ''].join('\n'),
  'utf-8'
)

console.log(`\n  ${written}개 라우트 프리렌더 + sitemap.xml + robots.txt 생성 완료`)
