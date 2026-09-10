import { useVerifyStream } from '../hooks/useVerifyStream.js'

const STATUS_LABEL = { done: '완료', failed: '실패', PENDING: '대기' }
const STATUS_CLASS = { done: 'DONE', failed: 'FAILED', PENDING: 'QUEUED' }

export default function VerifyStep({ estimateId, ready }) {
  const verify = useVerifyStream(ready ? estimateId : null)
  const status = verify.status ?? 'PENDING'

  if (!ready) return null

  return (
    <section className="step section-dark reveal" id="verify">
      <div className="eyebrow red">
        <span className="live-dot" />
        04 — VERIFY
      </div>
      <h2>Confirm it physically.</h2>
      <p className="desc">권장 대수를 Isaac Sim으로 재현해 실제로 문제없이 동작하는지 검증합니다.</p>

      {status === 'PENDING' && (
        <div className="runs-empty"><span className="live-dot pulse" /> 물리 검증 대기 중</div>
      )}

      {status === 'failed' && (
        <div className="runs-empty form-error">검증 실패: {verify.error ?? '원인 미상'}</div>
      )}

      {status === 'done' && verify.videoUrl && (
        <div className="sim-board">
          <div className="board-head">
            <span>PHYSICAL VERIFICATION · ISAAC SIM</span>
            <span className={`status ${STATUS_CLASS[status]}`}>{STATUS_LABEL[status]}</span>
          </div>
          <video className="verify-video" src={verify.videoUrl} controls />
        </div>
      )}
    </section>
  )
}
