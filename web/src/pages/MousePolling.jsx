import { useCallback, useEffect, useRef, useState } from 'react'
import { MousePointer2, RotateCcw, Share2 } from 'lucide-react'
import { analyze, extractSamples, COMMON_POLLING_RATES } from '../lib/pollingRate.js'
import { histogram } from '../lib/stats.js'
import Scorecard from '../components/Scorecard.jsx'
import { saveResult } from '../lib/storage.js'
import {
  Breadcrumb, Callout, Histogram, KofiSupport, Readout, RelatedTools, Stat, useMeta
} from '../components/ui.jsx'

const MAX_SAMPLES = 20000

export default function MousePolling() {
  useMeta()

  const [result, setResult] = useState(null)
  const [active, setActive] = useState(false)
  const [sampleCount, setSampleCount] = useState(0)
  const [card, setCard] = useState(null)
  const timestamps = useRef([])
  const rafRef = useRef(0)
  const saved = useRef(false)

  const flush = useCallback(() => {
    const r = analyze(timestamps.current)
    setSampleCount(r.sampleCount)
    if (r.ready) setResult(r)
    rafRef.current = 0
  }, [])

  const onPointerMove = useCallback((e) => {
    const samples = extractSamples(e)
    const store = timestamps.current
    for (const s of samples) store.push(s.timeStamp)
    // 오래된 샘플은 버려서 메모리와 계산량을 일정하게 유지한다
    if (store.length > MAX_SAMPLES) store.splice(0, store.length - MAX_SAMPLES)
    setActive(true)
    // 이벤트마다 setState 하면 1000Hz 마우스에서 초당 1000번 리렌더가 난다.
    // 화면 갱신은 프레임당 한 번으로 묶는다.
    if (!rafRef.current) rafRef.current = requestAnimationFrame(flush)
  }, [flush])

  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }, [])

  // 결과가 안정되면 이력에 한 번만 기록한다
  useEffect(() => {
    if (result?.ready && result.sampleCount > 2000 && !saved.current) {
      saved.current = true
      saveResult({ tool: 'mouse-polling', hz: Math.round(result.average), rated: result.rated })
    }
  }, [result])

  const reset = () => {
    timestamps.current = []
    saved.current = false
    setResult(null)
    setSampleCount(0)
    setActive(false)
    setCard(null)
  }

  // spec 을 state 에 담아 넘겨야 Scorecard 가 매 렌더마다 이미지를 다시 그리지 않는다
  const showCard = () => {
    if (!result?.ready) return
    setCard({
      title: '마우스 폴링레이트',
      score: Math.round(result.average),
      scoreLabel: '측정된 폴링레이트 (Hz)',
      rows: [
        ['규격 판정', result.rated ? `${result.rated} Hz` : '비표준'],
        ['순간 최고', `${Math.round(result.peak)} Hz`],
        ['안정성', `${Math.round(result.stability * 100)} %`],
        ['샘플 수', `${result.sampleCount.toLocaleString()} 개`]
      ]
    })
  }

  const limited = result?.precision?.limited
  const buckets = result?.ready ? histogram(result.intervals, 44) : []

  return (
    <>
      <Breadcrumb label="마우스 폴링레이트 측정" />
      <h1>마우스 폴링레이트 측정</h1>
      <p className="lede">
        아래 영역에서 마우스를 <strong>원을 그리듯 계속</strong> 움직이세요. 몇 초면 충분합니다.
        마우스가 초당 몇 번 좌표를 보고하는지(Hz) 실측합니다.
      </p>

      <div
        className={`pad-area ${active ? 'active' : ''}`}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setActive(false)}
      >
        {result?.ready ? (
          <div style={{ width: '100%' }}>
            <Readout
              value={Math.round(result.average)}
              unit="Hz"
              caption={
                result.rated
                  ? `${result.rated}Hz 규격으로 판정 · 샘플 ${result.sampleCount.toLocaleString()}개`
                  : `표준 규격(${COMMON_POLLING_RATES.join('/')}Hz)과 일치하지 않습니다 · 샘플 ${result.sampleCount.toLocaleString()}개`
              }
            />
          </div>
        ) : (
          <div>
            <MousePointer2 size={30} style={{ opacity: .5 }} />
            <p>
              {sampleCount > 0
                ? `측정 중... ${sampleCount}개 샘플 (10개 이상 필요)`
                : '이 영역 안에서 마우스를 계속 움직여 주세요'}
            </p>
          </div>
        )}
      </div>

      {result?.ready && (
        <>
          <div className="grid cols-2 section">
            <div className="card">
              <h2>측정 결과</h2>
              <Stat k="평균 폴링레이트" v={`${Math.round(result.average)} Hz`} />
              <Stat k="순간 최고" v={`${Math.round(result.peak)} Hz`} />
              <Stat k="규격 판정" v={result.rated ? `${result.rated} Hz` : '비표준'} />
              <Stat k="안정성" v={`${Math.round(result.stability * 100)} %`} />
              <Stat k="수집 샘플" v={result.sampleCount.toLocaleString()} />
            </div>

            <div className="card">
              <h2>보고 간격 분포</h2>
              <p className="muted" style={{ fontSize: 13.5, marginTop: -6 }}>
                막대가 한 곳에 몰려 있을수록 안정적입니다. 여러 봉우리로 갈라지면
                무선 간섭이나 USB 대역폭 부족을 의심할 수 있습니다.
              </p>
              <Histogram buckets={buckets} />
            </div>
          </div>

          <div className="section" style={{ display: 'grid', gap: 12 }}>
            {limited && (
              <Callout kind="warn">
                <strong>이 브라우저는 1000Hz 이상을 측정할 수 없습니다.</strong> 파이어폭스는
                개인정보 보호를 위해 입력 시각을 1밀리초 단위로 반올림합니다. 그래서 2000·4000·8000Hz
                마우스도 1000Hz로 나옵니다. 고폴링 마우스를 쓰신다면 크롬·엣지에서 다시 측정해 주세요.
              </Callout>
            )}
            {result.stability < 0.7 && !limited && (
              <Callout kind="warn">
                <strong>보고 간격이 불안정합니다({Math.round(result.stability * 100)}%).</strong>{' '}
                무선 마우스라면 USB 리시버를 본체 뒷면 대신 앞면이나 연장 케이블로 옮겨보세요.
                USB 허브에 물려 있다면 메인보드 포트에 직접 연결하는 것만으로 해결되는 경우가 많습니다.
              </Callout>
            )}
            <Callout>
              측정 원리 — 브라우저는 마우스 입력을 화면 프레임 단위로 <strong>합쳐서</strong> 전달합니다.
              그래서 단순히 이벤트 수를 세면 마우스가 아니라 모니터 주사율이 측정됩니다(대부분의 웹
              측정기가 144Hz 근처를 뱉는 이유입니다). 이 도구는 합쳐지기 전 원본 샘플을 꺼내 계산합니다.
            </Callout>
          </div>

          <div className="btn-row section">
            <button className="btn primary" onClick={showCard}>
              <Share2 size={16} /> 결과 이미지 만들기
            </button>
            <button className="btn" onClick={reset}>
              <RotateCcw size={16} /> 다시 측정
            </button>
          </div>

          {card && (
            <Scorecard spec={card} filename="polling-rate.png" onClose={() => setCard(null)} />
          )}

          <KofiSupport context="마우스가 제 성능을 내는지 확인하셨나요?" />
        </>
      )}

      <RelatedTools current="/mouse-polling-rate" />
    </>
  )
}
