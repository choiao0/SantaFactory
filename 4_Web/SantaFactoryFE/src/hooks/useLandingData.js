import { useEffect, useState } from 'react'
import { getMyEstimates, getRobots, getWarehouses } from '../api/estimates.js'

/** 랜딩에 늘어놓을 최근 견적 수. 총 건수는 서버가 따로 준다(totalElements). */
const RECENT_SIZE = 5

const LOADING = { data: null, loading: true, error: null }
const OFF = { data: null, loading: false, error: null }

/**
 * 묶음 하나를 불러온다.
 *
 * 셋을 Promise.all 로 묶지 않는 이유는, 하나가 실패해도 나머지는 보여야 하기 때문이다 —
 * 모델 목록이 안 왔다고 내 견적까지 사라지면 첫 화면이 통째로 비어 보인다.
 */
function useResource(load, enabled) {
  const [state, setState] = useState(LOADING)

  useEffect(() => {
    if (!enabled) return undefined
    let cancelled = false
    load()
      .then((data) => { if (!cancelled) setState({ data, loading: false, error: null }) })
      .catch((e) => { if (!cancelled) setState({ data: null, loading: false, error: e.message }) })
    return () => { cancelled = true }
  }, [load, enabled])

  // 끄고 있는 동안은 "불러오는 중"이 아니다 — 상태로 저장하지 않고 렌더에서 정한다
  return enabled ? state : OFF
}

// 모듈 수준 함수여야 effect 가 매 렌더 다시 돌지 않는다
const loadRecent = () => getMyEstimates(0, RECENT_SIZE)

/**
 * 랜딩이 쓰는 세 묶음 (S15P21A106-274).
 *
 * @param mine 내 것(견적·창고)까지 부를지. 관리자에게는 서버가 전체를 주므로 남의 창고가
 *             "내 조건"으로 보인다 — 그래서 관리자에게는 끈다.
 */
export function useLandingData({ mine = true } = {}) {
  const estimates = useResource(loadRecent, mine)
  const warehouses = useResource(getWarehouses, mine)
  const robots = useResource(getRobots, true)

  const items = estimates.data?.content ?? []
  return {
    recent: {
      loading: estimates.loading,
      error: estimates.error,
      items,
      total: estimates.data?.totalElements ?? 0,
      // 지금 돌고 있는 견적 — 있으면 첫 화면 맨 위에서 이어가게 한다
      running: items.find((e) => e.status === 'RUNNING') ?? null,
      lastDone: items.find((e) => e.recommended_count != null) ?? null,
    },
    warehouses: { loading: warehouses.loading, error: warehouses.error, items: warehouses.data ?? [] },
    robots: { loading: robots.loading, error: robots.error, items: robots.data ?? [] },
  }
}
