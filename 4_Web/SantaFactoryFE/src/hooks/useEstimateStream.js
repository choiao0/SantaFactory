import { useEffect, useState } from 'react'
import { openEstimateStream } from '../api/estimates.js'

const RETRY_DELAY_MS = 3000
const IDLE = { id: null, estimate: null, verdict: null, connected: false, error: null }

export function useEstimateStream(estimateId) {
  const [state, setState] = useState(IDLE)

  useEffect(() => {
    if (estimateId == null) return undefined

    const patch = (update) => setState((s) => (s.id === estimateId ? { ...s, ...update } : { ...IDLE, id: estimateId, ...update }))
    let close = null
    let retryTimer = null
    let retried = false
    let finished = false

    const connect = () => {
      close = openEstimateStream(estimateId, {
        onSnapshot: (snapshot) => patch({ estimate: snapshot, connected: true, error: null }),
        onRun: (run) =>
          setState((s) =>
            s.id === estimateId && s.estimate
              ? { ...s, estimate: { ...s.estimate, runs: s.estimate.runs.map((r) => (r.run_id === run.run_id ? run : r)) } }
              : s,
          ),
        onDone: (done) => {
          finished = true
          setState((s) =>
            s.id === estimateId
              ? { ...s, verdict: done, connected: false, estimate: s.estimate ? { ...s.estimate, status: done.status } : s.estimate }
              : { ...IDLE, id: estimateId, verdict: done },
          )
        },
        onError: () => {
          if (finished) return
          close?.()
          if (retried) {
            patch({ connected: false, error: '진행 상황 연결이 끊어졌습니다. 새로고침하면 현재 상태를 다시 불러옵니다.' })
            return
          }
          retried = true
          patch({ connected: false })
          retryTimer = setTimeout(connect, RETRY_DELAY_MS)
        },
      })
    }

    connect()
    return () => {
      clearTimeout(retryTimer)
      close?.()
    }
  }, [estimateId])

  return state.id === estimateId ? state : IDLE
}
