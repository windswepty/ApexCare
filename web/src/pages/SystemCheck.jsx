import { useCallback, useEffect, useState } from 'react'
import { Play, Share2, Trash2 } from 'lucide-react'
import { detectAll } from '../lib/hardware.js'
import { measureRefreshRate } from '../lib/refreshRate.js'
import { benchSingleCore, benchMultiCore, benchGPU, compositeScore } from '../lib/bench.js'
import Scorecard from '../components/Scorecard.jsx'
import { historyFor, saveResult, clearHistory } from '../lib/storage.js'
import {
  Breadcrumb, Callout, KofiSupport, Readout, RelatedTools, Stat, useMeta
} from '../components/ui.jsx'

const fmtOps = (opsPerMs) => {
  const perSec = opsPerMs * 1000
  return perSec >= 1e9 ? `${(perSec / 1e9).toFixed(2)}B/s` : `${(perSec / 1e6).toFixed(1)}M/s`
}

/** 렌더를 한 프레임 양보한다. 벤치 사이에 UI가 갱신될 틈을 준다. */
const yieldFrame = () => new Promise((r) => setTimeout(r, 60))

export default function SystemCheck() {
  useMeta()

  const [specs, setSpecs] = useState(null)
  const [refresh, setRefresh] = useState(null)
  const [scores, setScores] = useState(null)
  const [phase, setPhase] = useState(null)
  const [history, setHistory] = useState([])
  const [card, setCard] = useState(null)

  useEffect(() => {
    detectAll().then(setSpecs)
    measureRefreshRate(1000).then(setRefresh)
    setHistory(historyFor('system-check'))
  }, [])

  const runBenchmark = useCallback(async () => {
    setScores(null)
    setCard(null)

    setPhase('단일 코어 측정 중...')
    await yieldFrame()
    const single = await benchSingleCore(700)

    setPhase('멀티 코어 측정 중...')
    await yieldFrame()
    const multi = await benchMultiCore(700)

    setPhase('그래픽 측정 중...')
    await yieldFrame()
    let gpu = null
    try { gpu = benchGPU(700) } catch { gpu = null }

    const total = compositeScore({ single, multi, gpu })

    // 병렬 효율은 워커 수를 넘을 수 없다. 넘는다면 단일코어 측정이 경합으로
    // 낮게 잡힌 것이므로, 틀린 숫자를 그럴듯하게 보여주느니 아예 감춘다.
    let efficiency = null
    if (multi && single?.opsPerMs > 0) {
      const ratio = multi.opsPerMs / single.opsPerMs
      if (ratio > 0 && ratio <= multi.workers * 1.15) efficiency = ratio
    }

    const result = { single, multi, gpu, total, efficiency }
    setScores(result)
    setPhase(null)

    saveResult({ tool: 'system-check', total, single: single?.score, multi: multi?.score, gpu: gpu?.score })
    setHistory(historyFor('system-check'))
  }, [])

  const showCard = () => {
    if (!scores) return
    setCard({
      title: '내 PC 성능 점수',
      score: scores.total,
      scoreLabel: '종합 점수 (상대 지표)',
      rows: [
        ['GPU', specs?.gpu?.name || '알 수 없음'],
        ['CPU 스레드', specs?.cores ? `${specs.cores} 개` : '알 수 없음'],
        ['단일 / 멀티', `${scores.single?.score ?? '-'} / ${scores.multi?.score ?? '-'}`],
        ['그래픽', scores.gpu ? String(scores.gpu.score) : '측정 불가'],
        ['주사율', refresh ? `${(refresh.snapped || refresh.raw).toFixed(0)} Hz` : '—']
      ]
    })
  }

  const wipe = () => {
    clearHistory()
    setHistory([])
  }

  const previous = history.length > 1 ? history[history.length - 2] : null
  const delta = previous && scores ? scores.total - previous.total : null

  return (
    <>
      <Breadcrumb label="내 PC 진단" />
      <h1>내 PC 사양·성능 진단</h1>
      <p className="lede">
        브라우저가 알 수 있는 범위에서 사양을 감지하고, 실제로 연산을 돌려 성능을 측정합니다.
        어떤 값이 정확하고 어떤 값이 근사치인지 항목마다 표시합니다.
      </p>

      <div className="grid cols-2">
        <div className="card">
          <h2>감지된 사양</h2>
          {!specs ? (
            <p className="muted" style={{ fontSize: 14 }}>감지 중...</p>
          ) : (
            <>
              <Stat k="운영체제" v={specs.platform?.os || '알 수 없음'} />
              {specs.platform?.arch && <Stat k="아키텍처" v={specs.platform.arch} />}
              <Stat k="브라우저" v={specs.platform?.browser || '알 수 없음'} />
              <Stat k="CPU 스레드" v={specs.cores ? `${specs.cores} 개` : '알 수 없음'} />
              <Stat
                k="메모리"
                v={specs.memory.value ? `약 ${specs.memory.value} GB` : '알 수 없음'}
                title={specs.memory.note}
              />
              <Stat k="GPU" v={specs.gpu?.name || '알 수 없음'} title={specs.gpu?.note} />
              <Stat
                k="화면"
                v={`${specs.display.physicalWidth}×${specs.display.physicalHeight}${specs.display.dpr !== 1 ? ` (배율 ${specs.display.dpr})` : ''}`}
              />
              <Stat
                k="주사율"
                v={refresh ? `${refresh.raw.toFixed(1)} Hz${refresh.snapped ? ` (${refresh.snapped}Hz)` : ''}` : '측정 중...'}
              />
              {specs.display.hdr && <Stat k="HDR" v="지원" />}
            </>
          )}
        </div>

        <div className="card">
          <h2>성능 점수</h2>
          {scores ? (
            <>
              <Readout
                value={scores.total}
                caption={
                  delta != null
                    ? `직전 측정 대비 ${delta >= 0 ? '+' : ''}${delta}점`
                    : '상대 비교용 지표입니다'
                }
              />
              <div style={{ marginTop: 12 }}>
                <Stat
                  k="단일 코어"
                  v={`${scores.single.score} · ${fmtOps(scores.single.opsPerMs)}`}
                />
                <Stat
                  k="멀티 코어"
                  v={scores.multi ? `${scores.multi.score} · ${fmtOps(scores.multi.opsPerMs)}` : '측정 불가'}
                />
                {scores.efficiency != null && (
                  <Stat
                    k="병렬 효율"
                    v={
                      `${scores.efficiency.toFixed(1)}× (워커 ${scores.multi.workers}개` +
                      // 일부 워커가 응답하지 않았으면 숨기지 않고 그대로 알린다
                      (scores.multi.requested > scores.multi.workers
                        ? ` / 요청 ${scores.multi.requested}개)`
                        : ')')
                    }
                  />
                )}
                <Stat
                  k="그래픽"
                  v={scores.gpu ? `${scores.gpu.score} · ${scores.gpu.passesPerMs.toFixed(2)} pass/ms` : 'WebGL2 미지원'}
                />
              </div>
            </>
          ) : (
            <p className="muted" style={{ fontSize: 14 }}>
              {phase || '측정을 시작하면 단일코어·멀티코어·그래픽 성능을 각각 잽니다. 약 3초 걸립니다.'}
            </p>
          )}
          <div className="btn-row" style={{ marginTop: 16 }}>
            <button className="btn primary" onClick={runBenchmark} disabled={!!phase}>
              <Play size={16} /> {phase ? '측정 중...' : scores ? '다시 측정' : '성능 측정 시작'}
            </button>
            {scores && (
              <button className="btn" onClick={showCard}>
                <Share2 size={16} /> 결과 이미지
              </button>
            )}
          </div>
        </div>
      </div>

      {card && (
        <Scorecard spec={card} filename="pc-score.png" onClose={() => setCard(null)} />
      )}

      {history.length > 1 && (
        <div className="card section">
          <h2>내 기록 ({history.length}회)</h2>
          <p className="muted" style={{ fontSize: 13.5, marginTop: -6 }}>
            이 기기의 브라우저에만 저장됩니다. 시간이 지나며 점수가 떨어진다면 발열, 전원 설정,
            백그라운드 프로그램을 의심해볼 수 있습니다.
          </p>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 80, marginTop: 12 }}>
            {history.slice(-24).map((h, i) => {
              const max = Math.max(...history.slice(-24).map((x) => x.total || 0), 1)
              return (
                <div
                  key={i}
                  style={{
                    flex: 1, background: 'var(--accent)', opacity: .75,
                    height: `${((h.total || 0) / max) * 100}%`, borderRadius: '3px 3px 0 0', minHeight: 2
                  }}
                  title={`${h.total}점 · ${new Date(h.at).toLocaleString('ko-KR')}`}
                />
              )
            })}
          </div>
          <button className="btn" style={{ marginTop: 14 }} onClick={wipe}>
            <Trash2 size={16} /> 기록 지우기
          </button>
        </div>
      )}

      <div className="section" style={{ display: 'grid', gap: 12 }}>
        <Callout kind="warn">
          <strong>브라우저가 알려주지 않는 것들이 있습니다.</strong> 메모리 용량은 크로미움 계열에서만,
          그것도 2의 거듭제곱으로 반올림된 근사치로 알려줍니다. CPU 모델명은 어떤 브라우저도
          알려주지 않습니다(스레드 수만 알 수 있습니다). 디스크 여유 공간도 알 수 없습니다.
          이건 개인정보 보호를 위한 의도된 제한입니다.
        </Callout>
        <Callout>
          <strong>점수는 상대 지표입니다.</strong> 브라우저 위에서 재는 값이라 같은 PC라도 브라우저와
          백그라운드 상태에 따라 달라집니다. 절대 성능이 아니라 <em>같은 기기에서 시간에 따른 변화</em>를
          보는 용도로 쓰세요. 옆에 함께 표시되는 실측값(ops/s, pass/ms)은 언제나 실제로 측정된 값입니다.
        </Callout>
        {specs?.gpu && !specs.gpu.exact && <Callout kind="warn">{specs.gpu.note}</Callout>}
      </div>

      <KofiSupport context="내 PC가 어느 정도인지 확인하셨나요?" />
      <RelatedTools current="/system-check" />
    </>
  )
}
