import { useVerifyStream } from '../hooks/useVerifyStream.js'

export default function VerifyStep({ estimateId, ready }) {
  const verify = useVerifyStream(ready ? estimateId : null)

  if (!ready || verify.status !== 'done' || !verify.videoUrl) return null

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
        <video className="verify-video" src={verify.videoUrl} controls />
      </div>
    </section>
  )
}
