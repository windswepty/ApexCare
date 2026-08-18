import { useEffect, useState } from 'react'
import { Download, Share2, X } from 'lucide-react'
import { drawScorecard, canvasToBlob } from '../lib/scorecard.js'

/**
 * 결과 이미지를 화면에 바로 띄우고, 그 아래에 저장 버튼을 둔다.
 *
 * 예전에는 버튼을 누르면 곧장 파일이 내려받아졌다. 뭐가 저장됐는지 보이지 않아
 * 다운로드 폴더를 열어봐야 했고, 공유할 만한 물건인지 판단할 수도 없었다.
 * 공유가 이 사이트의 주 유입 경로라 이미지를 먼저 보여주는 편이 낫다.
 *
 * spec 은 부모의 state 에 담아 넘겨야 한다. 렌더마다 새 객체를 만들면
 * 아래 효과가 매번 다시 돌면서 이미지가 계속 새로 그려진다.
 */
export default function Scorecard({ spec, filename, onClose }) {
  const [url, setUrl] = useState(null)
  const [blob, setBlob] = useState(null)
  const [shareState, setShareState] = useState('idle')

  useEffect(() => {
    let objectUrl = null
    let cancelled = false

    const canvas = drawScorecard(spec)
    canvasToBlob(canvas).then((b) => {
      if (cancelled || !b) return
      objectUrl = URL.createObjectURL(b)
      setBlob(b)
      setUrl(objectUrl)
    })

    return () => {
      cancelled = true
      // 안 놓아주면 이미지가 메모리에 계속 남는다
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [spec])

  const canShare =
    blob && typeof navigator !== 'undefined' && navigator.canShare?.({
      files: [new File([blob], filename, { type: 'image/png' })]
    })

  const share = async () => {
    if (!blob) return
    try {
      await navigator.share({ files: [new File([blob], filename, { type: 'image/png' })] })
      setShareState('done')
    } catch (e) {
      // 사용자가 취소한 것은 오류가 아니다
      if (e?.name !== 'AbortError') setShareState('failed')
    }
  }

  return (
    <div className="scorecard">
      <div className="scorecard-head">
        <h3>결과 이미지</h3>
        {onClose && (
          <button className="icon-btn" onClick={onClose} aria-label="결과 이미지 닫기" title="닫기">
            <X size={15} />
          </button>
        )}
      </div>

      {url ? (
        <img src={url} alt="측정 결과를 담은 공유용 이미지" className="scorecard-img" />
      ) : (
        <div className="scorecard-img scorecard-loading">이미지 만드는 중...</div>
      )}

      <div className="btn-row" style={{ marginTop: 14 }}>
        <a
          className={`btn primary${url ? '' : ' is-disabled'}`}
          href={url || undefined}
          download={filename}
          aria-disabled={!url}
        >
          <Download size={16} /> 이미지 저장
        </a>
        {canShare && (
          <button className="btn" onClick={share}>
            <Share2 size={16} /> {shareState === 'done' ? '공유했습니다' : '공유'}
          </button>
        )}
      </div>

      {shareState === 'failed' && (
        <p className="dim" style={{ fontSize: 13, marginTop: 10 }}>
          공유에 실패했습니다. 이미지 저장을 눌러 파일로 받아 주세요.
        </p>
      )}
      <p className="dim" style={{ fontSize: 13, marginTop: 10, marginBottom: 0 }}>
        이미지는 이 기기에서 만들어집니다. 서버로 올라가지 않습니다.
      </p>
    </div>
  )
}
