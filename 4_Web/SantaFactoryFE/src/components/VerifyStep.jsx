import { useRef, useState } from 'react'
import { getEstimate } from '../api/estimates.js'
import { useVerifyStream } from '../hooks/useVerifyStream.js'

/**
 * 영상 URL 은 서명본이라 30분이면 만료된다. 만료 뒤 구간 이동은 새 Range 요청이 403 으로 거절되어
 * video 의 error 로 온다 — 그때 상세를 다시 불러 새 URL 을 받고, 보던 위치에서 이어 간다.
 * 재요청은 이 간격 안에서 한 번만 — 영상 자체가 깨진 경우 무한 반복하지 않게.
 */
const REFRESH_COOLDOWN_MS = 10_000

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

  if (!ready || verify.status !== 'done' || !videoUrl) return null

  return (
    <section className="step section-dark" id="verify">
      <div className="eyebrow red">
        <span className="live-dot" />
        04 — VERIFY
      </div>
      <h2>Confirm it physically.</h2>
      <p className="desc">권장 대수를 Isaac Sim으로 재현해 실제로 문제없이 동작하는지 검증합니다.</p>

      <div className="sim-board">
        <div className="board-head">
          <span>PHYSICAL VERIFICATION · ISAAC SIM</span>
          <span className="status DONE">완료</span>
        </div>
        <video
          ref={videoRef}
          className="verify-video"
          src={videoUrl}
          controls
          onError={refreshUrl}
          onLoadedMetadata={resume}
        />
      </div>
    </section>
  )
}
