import { useEffect, useState } from 'react'
import { getReplay } from '../api/replay.js'

/**
 * 한 번 받은 대수는 다시 받지 않는다 — 카드를 왔다 갔다 누르는 화면이라 같은 200 KB 를 매번
 * 내려받을 이유가 없다. 견적이 바뀌면 통째로 버린다(키에 견적 번호가 들어 있다).
 */
const cache = new Map()
let cachedEstimateId = null

/**
 * 값이 아니라 <b>요청</b>을 캐시한다. 같은 대수를 두 번 눌러도 200 KB 를 다시 받지 않고,
 * 아직 오는 중에 또 누르면 같은 요청에 붙는다(중복 발사 없음).
 * 실패한 요청은 버린다 — 한 번 끊겼다고 영원히 못 보게 할 이유가 없다.
 */
function fetchReplay(estimateId, amrCount) {
  if (cachedEstimateId !== estimateId) {
    cache.clear()               // 견적이 바뀌면 통째로 버린다
    cachedEstimateId = estimateId
  }
  const key = `${estimateId}:${amrCount}`
  let pending = cache.get(key)
  if (!pending) {
    pending = getReplay(estimateId, amrCount)
    pending.catch(() => cache.delete(key))
    cache.set(key, pending)
  }
  return pending
}

/**
 * 대수 하나의 주행 리플레이를 가져온다 (S15P21A106-205).
 *
 * 404 는 오류로 다루지 않는다. "아직 결과가 없다"와 "그 run 이 실패했다"가 모두 404 이고,
 * 화면에서는 둘 다 "볼 것이 없다"로 같기 때문이다.
 */
export function useReplay(estimateId, amrCount) {
  const key = estimateId == null || amrCount == null ? null : `${estimateId}:${amrCount}`
  const [entry, setEntry] = useState({ key: null, replay: null, error: null })

  useEffect(() => {
    if (!key) return undefined
    let cancelled = false
    fetchReplay(estimateId, amrCount)
      .then((replay) => { if (!cancelled) setEntry({ key, replay, error: null }) })
      .catch((e) => {
        if (!cancelled) setEntry({ key, replay: null, error: e.status === 404 ? null : e.message })
      })
    // 카드를 빠르게 여러 번 누르면 먼저 보낸 응답이 나중에 올 수 있다 — 지나온 대수를 그리지 않는다
    return () => { cancelled = true }
  }, [key, estimateId, amrCount])

  // 요청한 키와 받아둔 키가 다르면 아직 오는 중이다. 별도 loading 상태를 두지 않는다
  const ready = entry.key === key
  return {
    replay: ready ? entry.replay : null,
    loading: Boolean(key) && !ready,
    error: ready ? entry.error : null,
  }
}
