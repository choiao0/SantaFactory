import { useRef, useState } from 'react'
import { getEstimate } from '../api/estimates.js'
import AmrRunning from './AmrRunning.jsx'
import { useVerifyStream } from '../hooks/useVerifyStream.js'

/**
 * 영상 URL 은 서명본이라 30분이면 만료된다. 만료 뒤 구간 이동은 새 Range 요청이 403 으로 거절되어
 * video 의 error 로 온다 — 그때 상세를 다시 불러 새 URL 을 받고, 보던 위치에서 이어 간다.
 * 재요청은 이 간격 안에서 한 번만 — 영상 자체가 깨진 경우 무한 반복하지 않게.
 */
const REFRESH_COOLDOWN_MS = 10_000

/**
 * 영상이 없을 때 자리를 채우는 내용. 섹션 자체는 언제나 그린다 — 헤더의 VERIFY 앵커가 가리키는
 * 곳이라, 영상이 생겨야 섹션이 나타나면 그 전까지는 눌러도 아무 데도 가지 않는다.
 */
function placeholderFor({ estimateId, ready, verify }) {
  if (estimateId == null) {
    return { tag: 'QUEUED', label: '대기', text: '02 단계에서 견적을 요청하면 물리 검증 결과가 여기에 표시됩니다.' }
  }
  if (!ready) {
    return { tag: 'RUNNING', label: '계산 중', live: true, text: '시뮬레이션 판정이 끝나면 권장 대수로 물리 검증을 돌립니다.' }
  }
  if (verify.error) {
    return { tag: 'FAILED', label: '실패', text: `물리 검증에 실패했습니다 — ${verify.error}` }
  }
  // 워커가 끝났다고 알렸는데 영상이 없는 경우 — 검증은 돌았으니 진행 중이라고 하면 안 된다
  if (verify.status && verify.status !== 'PENDING') {
    return { tag: 'PARTIAL', label: '영상 없음', text: '물리 검증은 끝났지만 재생할 영상이 남지 않았습니다.' }
  }
  return {
    tag: 'RUNNING', label: '검증 중', live: true,
    text: 'Isaac Sim에서 로봇 동작을 검증하고 있습니다',
    hint: [
      '실제 환경에 가까운 정밀한 물리 검증을 위해 다소 시간이 필요합니다.',
      '완료되면 이 화면에서 결과 영상을 바로 확인할 수 있습니다.',
    ],
  }
}

export default function VerifyStep({ estimateId, ready }) {
  const verify = useVerifyStream(ready ? estimateId : null)
  const [refreshed, setRefreshed] = useState(null)
  const videoRef = useRef(null)
  const resumeAt = useRef(null)
  const lastRefresh = useRef(0)

  // 재발급본은 그것을 대신하는 스트림 URL 에 묶어 둔다 — 스트림이 다른 영상을 주면 자연히 버려진다
  const videoUrl = refreshed?.replaces === verify.videoUrl ? refreshed.url : verify.videoUrl

  const refreshUrl = async () => {
    const now = Date.now()
    if (now - lastRefresh.current < REFRESH_COOLDOWN_MS) return
    lastRefresh.current = now

    const video = videoRef.current
    resumeAt.current = { time: video?.currentTime ?? 0, playing: Boolean(video && !video.paused) }
    try {
      const detail = await getEstimate(estimateId)
      if (detail?.verify_video_url) setRefreshed({ replaces: verify.videoUrl, url: detail.verify_video_url })
    } catch (e) {
      console.error(`[verify] estimateId=${estimateId} 영상 URL 재발급 실패`, e)
    }
  }

  const resume = () => {
    const video = videoRef.current
    const at = resumeAt.current
    if (!video || !at) return
    resumeAt.current = null
    video.currentTime = at.time
    if (at.playing) video.play().catch(() => {})
  }

  const playable = ready && verify.status === 'done' && Boolean(videoUrl)
  const placeholder = playable ? null : placeholderFor({ estimateId, ready, verify })

  return (
    <section className="step section-dark" id="verify">
      <div className="eyebrow red">
        <span className="live-dot" />
        04 — 물리 검증
      </div>
      <h2>Confirm it physically.</h2>
      <p className="desc">권장 대수를 Isaac Sim으로 재현해 실제로 문제없이 동작하는지 검증합니다.</p>

      <div className="sim-board">
        <div className="board-head">
          <span>물리 검증 · Isaac Sim</span>
          <span className={`status ${playable ? 'DONE' : placeholder.tag}`}>
            {playable ? '완료' : placeholder.label}
          </span>
        </div>
        {playable ? (
          <video
            ref={videoRef}
            className="verify-video"
            src={videoUrl}
            controls
            onError={refreshUrl}
            onLoadedMetadata={resume}
          />
        ) : (
          <div className="verify-placeholder">
            {placeholder.live && <AmrRunning />}
            {/* 검증이 도는 동안만 제목처럼 세운다 — 대기·실패 같은 한 줄 안내는 원래의 옅은 문구 */}
            <p className={placeholder.hint ? 'vp-text' : 'vp-note'}>{placeholder.text}</p>
            {placeholder.hint && (
              <p className="vp-hint">
                {/* 문장 단위로 끊는다 — 폭에 맡기면 "필요합니" / "다." 처럼 문장 가운데서 잘린다 */}
                {placeholder.hint.map((line, i) => (
                  <span key={line}>{i > 0 && <br />}{line}</span>
                ))}
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
