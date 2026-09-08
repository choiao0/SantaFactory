import { useEffect, useState } from 'react'
import { getEstimate, subscribeEstimate } from '../api/estimate.js'
import { MOCK_ESTIMATE } from '../data/mock.js'

/**
 * 견적 상세를 들고, 진행 중이면 SSE 로 갱신한다.
 *
 * <p>estimateId 가 없으면 목업을 준다 — 백엔드 없이도 화면이 보이게. 입력 플로우가 붙기
 * 전까지는 `?estimate=77` 쿼리로 실제 견적을 지정한다.
 *
 * @returns {{estimate: object|null, loading: boolean, error: Error|null, live: boolean}}
 *          live = 실제 백엔드 데이터인가 (false 면 목업)
 */
export function useEstimate(estimateId) {
  // id 를 함께 담아 두고 렌더 중에 비교한다. effect 안에서 동기 setState 를 하지 않으려는 것 —
  // id 가 바뀐 직후에는 이전 견적을 잠깐 보여주는 대신 loading 으로 떨어진다.
  const [fetched, setFetched] = useState({ id: null, detail: null, error: null })

  useEffect(() => {
    if (!estimateId) return undefined

    let alive = true
    let unsubscribe = null

    const patch = (fn) =>
      alive && setFetched((prev) => (prev.id === estimateId && prev.detail ? { ...prev, detail: fn(prev.detail) } : prev))

    getEstimate(estimateId)
      .then((detail) => {
        if (!alive) return
        setFetched({ id: estimateId, detail, error: null })
        if (detail.status !== 'RUNNING') return   // 끝난 견적이면 스트림을 열지 않는다
        unsubscribe = subscribeEstimate(estimateId, {
          // snapshot 은 구독 직후 전체 상태 — 위 GET 과 겹치지만 그 사이의 변화를 메운다
          onSnapshot: (detail) => alive && setFetched({ id: estimateId, detail, error: null }),
          onRun: (run) => patch((detail) => replaceRun(detail, run)),
          onDone: (done) => patch((detail) => ({ ...detail, ...finished(done) })),
          onError: (e) => alive && setFetched((prev) => ({ ...prev, error: e })),
        })
      })
      .catch((e) => alive && setFetched({ id: estimateId, detail: null, error: e }))

    return () => {
      alive = false
      unsubscribe?.()
    }
  }, [estimateId])

  if (!estimateId) {
    return { estimate: MOCK_ESTIMATE, loading: false, error: null, live: false }
  }
  const current = fetched.id === estimateId ? fetched : { detail: null, error: null }
  return {
    estimate: current.detail,
    loading: !current.detail && !current.error,
    error: current.error,
    live: true,
  }
}

/** run 이벤트 1건을 대수 기준으로 갈아끼운다. */
function replaceRun(estimate, run) {
  return {
    ...estimate,
    runs: estimate.runs.map((r) => (r.amrCount === run.amrCount ? { ...r, ...run } : r)),
  }
}

/** estimate.done 에서 화면이 쓰는 필드만 뽑는다 (estimateId 는 덮지 않는다). */
function finished({ status, recommendedCount, kneeCount, reasonCode }) {
  return { status, recommendedCount, kneeCount, reasonCode }
}
