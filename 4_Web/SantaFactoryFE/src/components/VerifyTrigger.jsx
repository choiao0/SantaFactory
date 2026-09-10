import { useState } from 'react'
import { requestVerify } from '../api/estimates.js'

// 임시 컴포넌트 — 물리 검증 자동 트리거가 생기면 이 파일과 App.jsx 의 사용 지점을 지운다.
export default function VerifyTrigger({ estimateId, recommendedCount }) {
  const [state, setState] = useState('idle') // idle | loading | done | error
  const [error, setError] = useState(null)

  if (recommendedCount == null) return null

  const onClick = async () => {
    setState('loading')
    setError(null)
    try {
      await requestVerify(estimateId)
      setState('done')
    } catch (e) {
      setState('error')
      setError(e.message)
    }
  }

  return (
    <section className="step section-dark">
      <button type="button" className="button" onClick={onClick} disabled={state === 'loading' || state === 'done'}>
        {state === 'loading' ? '요청 중…' : state === 'done' ? '검증 요청됨' : '물리 검증 시작 (임시)'}
      </button>
      {state === 'error' && <p className="form-error">{error}</p>}
    </section>
  )
}
