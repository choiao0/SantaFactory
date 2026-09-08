// 견적 API. 백엔드는 모든 응답을 { isSuccess, code, message, result } 로 감싸고
// 필드는 snake_case 로 내린다 (@JsonNaming SnakeCaseStrategy). 화면에서 쓰기 편하게
// 여기서 봉투를 벗기고 camelCase 로 바꾼다 — 컴포넌트가 응답 형태를 몰라도 되게.

const BASE = '/api/estimates'

/** snake_case 키를 camelCase 로. 값은 그대로 두고 객체·배열만 재귀한다. */
export function camelize(value) {
  if (Array.isArray(value)) return value.map(camelize)
  if (value === null || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value).map(([k, v]) => [k.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase()), camelize(v)]),
  )
}

/** 봉투를 벗기고 result 를 돌려준다. isSuccess=false 면 code·message 를 담아 throw. */
async function unwrap(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    throw new ApiError('SERVER', `응답을 읽을 수 없습니다 (HTTP ${res.status})`)
  }
  if (!res.ok || body?.isSuccess === false) {
    throw new ApiError(body?.code ?? String(res.status), body?.message ?? '요청이 실패했습니다')
  }
  return camelize(body?.result ?? null)
}

export class ApiError extends Error {
  constructor(code, message) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

/**
 * 견적 생성. 대수 범위를 비우면 백엔드가 1~상한을 전부 돈다.
 * @returns {Promise<{estimateId: number, maxAmrCount: number, runIds: string[]}>}
 */
export function createEstimate({ warehouseId, amrModel, fleetMin, fleetMax, fleetStep } = {}) {
  return fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      warehouse_id: warehouseId,
      amr_model: amrModel,
      fleet_min: fleetMin,
      fleet_max: fleetMax,
      fleet_step: fleetStep,
    }),
  }).then(unwrap)
}

/** 견적 상세 1회 조회. Accept 를 명시해 SSE 핸들러로 넘어가지 않게 한다. */
export function getEstimate(estimateId) {
  return fetch(`${BASE}/${estimateId}`, { headers: { Accept: 'application/json' } }).then(unwrap)
}

export function cancelEstimate(estimateId) {
  return fetch(`${BASE}/${estimateId}`, { method: 'DELETE' }).then((res) => {
    if (!res.ok) throw new ApiError(String(res.status), '견적 취소에 실패했습니다')
  })
}

/**
 * 진행 스트림. 같은 URL 을 EventSource 로 열면 백엔드가 SSE 핸들러로 보낸다
 * (EventSource 의 Accept 가 text/event-stream 이다).
 *
 * 이벤트: snapshot(현재 전체 상태) → run(결과 도착마다 1건) → estimate.done(종료 후 닫힘)
 *
 * @returns {() => void} 구독 해제 함수
 */
export function subscribeEstimate(estimateId, { onSnapshot, onRun, onDone, onError } = {}) {
  const source = new EventSource(`${BASE}/${estimateId}`)
  let finished = false
  const listen = (name, handler) =>
    handler && source.addEventListener(name, (e) => handler(camelize(JSON.parse(e.data))))

  // snapshot·run 은 snake_case(@JsonNaming), estimate.done 은 애노테이션이 없어 camelCase 로
  // 내려온다. camelize 는 밑줄이 없는 키를 그대로 두므로 둘 다 안전하게 통과한다.
  listen('snapshot', onSnapshot)
  listen('run', onRun)
  listen('estimate.done', (payload) => {
    finished = true
    onDone?.(payload)
    source.close()   // 백엔드가 닫으므로 EventSource 의 자동 재연결을 막는다
  })

  // EventSource 는 정상 종료도 error 로 알린다. readyState 만으로는 구분이 안 되므로
  // estimate.done 을 받았는지로 가른다 — 안 받았는데 닫혔으면 실패다(연결 거부·프록시 끊김 등).
  // 이 구분이 없으면 스트림이 거부돼도 화면이 낡은 값을 조용히 붙들고 있게 된다.
  source.onerror = () => {
    if (finished) return
    onError?.(new ApiError('SSE', '진행 스트림이 끊겼습니다'))
    if (source.readyState === EventSource.CLOSED) return
    source.close()   // 재연결을 반복하며 같은 오류를 계속 내지 않게 접는다
  }

  return () => source.close()
}
