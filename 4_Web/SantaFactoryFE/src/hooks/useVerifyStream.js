import { useEffect, useState } from 'react'
import { openVerifyStream } from '../api/estimates.js'

const IDLE = { id: null, recommendedCount: null, physicsLimit: null, verifications: [] }

/** 대수 오름차순 — 카드를 항상 같은 순서로 그린다. */
function sorted(list) {
  return [...list].sort((a, b) => a.n_robots - b.n_robots)
}

/** verify.run 은 회차 하나만 온다 — 같은 대수 카드를 교체하고 없으면 새로 끼워 넣는다. */
function upsert(list, run) {
  const idx = list.findIndex((v) => v.n_robots === run.n_robots)
  if (idx === -1) return sorted([...list, run])
  const next = list.slice()
  next[idx] = run
  return sorted(next)
}

/**
 * 대수별 물리 검증 진행 상황 (S15P21A106-244). 후보 여러 대수를 동시에 검증하므로 결과는
 * `verifications` 배열로 온다 — 화면은 대수마다 카드 하나씩 그린다.
 */
export function useVerifyStream(estimateId) {
  const [state, setState] = useState(IDLE)

  useEffect(() => {
    if (estimateId == null) return undefined

    const applySnapshot = (payload) =>
      setState({
        id: estimateId,
        recommendedCount: payload.recommended_count,
        physicsLimit: payload.physics_limit,
        verifications: sorted(payload.verifications ?? []),
      })

    const applyRun = (payload) =>
      setState((prev) => (prev.id === estimateId
        ? { ...prev, physicsLimit: payload.physics_limit, verifications: upsert(prev.verifications, payload.run) }
        : prev))

    const close = openVerifyStream(estimateId, {
      onSnapshot: applySnapshot,
      onRun: applyRun,
      onDone: applySnapshot,
      onError: () => console.error(`[verify] estimateId=${estimateId} 스트림 연결 실패`),
    })
    return close
  }, [estimateId])

  return state.id === estimateId ? state : IDLE
}
