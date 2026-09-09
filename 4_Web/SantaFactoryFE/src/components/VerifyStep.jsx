import { useVerifyStream } from '../hooks/useVerifyStream.js'

export default function VerifyStep({ estimateId, ready }) {
  const verify = useVerifyStream(ready ? estimateId : null)

  if (!ready) return null

  return (
    <section id="verify">
      <h3>물리 검증</h3>
      {verify.status === 'done' && verify.videoUrl && <video src={verify.videoUrl} controls />}
      {verify.status === 'failed' && <p>검증 실패: {verify.error}</p>}
      {(verify.status == null || verify.status === 'PENDING') && <p>검증 대기 중</p>}
    </section>
  )
}
