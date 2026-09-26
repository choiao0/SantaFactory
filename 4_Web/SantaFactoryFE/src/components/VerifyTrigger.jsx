import { useState } from 'react'
import { requestVerify } from '../api/estimates.js'

const BUTTON_LABEL = { idle: '물리 검증 시작', loading: '요청 중…', done: '검증 요청됨', error: '다시 시도' }

/**
 * 물리 검증을 사람이 시작한다 (S15P21A106-265 에서 수동 유지로 결정).
 *
 * <p>자동 발행을 안 하는 이유 — Isaac 은 한 번에 한 건씩 약 10분을 문다. 견적이 끝날 때마다
 * 자동으로 걸면 큐가 그대로 쌓여 뒤 요청이 몇십 분씩 밀린다. 언제 돌릴지는 사람이 정한다.
 */
export default function VerifyTrigger({ estimateId, recommendedCount, onStarted, counts, idleLabel }) {
  const [state, setState] = useState('idle') // idle | loading | done | error
  const [error, setError] = useState(null)

  if (recommendedCount == null) return null

  const onClick = async () => {
    setState('loading')
    setError(null)
    try {
      await requestVerify(estimateId, counts)
      setState('done')
      onStarted?.()
    } catch (e) {
      setState('error')
      setError(e.message)
    }
  }

  return (
    <>
      <button type="button" className="button" onClick={onClick} disabled={state === 'loading' || state === 'done'}>
        {state === 'idle' && idleLabel ? idleLabel : BUTTON_LABEL[state]}
      </button>
      {state === 'error' && <p className="form-error">{error}</p>}
    </>
  )
}
