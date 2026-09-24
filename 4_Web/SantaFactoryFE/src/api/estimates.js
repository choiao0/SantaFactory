import { api, streamUrl } from './client.js'

export function createWarehouse(form) {
  return api.post('/warehouses', {
    worker_count: form.workerCount,
    // 입고는 화면에서 받지 않는다 — 서버가 창고 기본값을 쓴다 (S15P21A106-266)
    outbound_start: form.outboundStart,
    outbound_end: form.outboundEnd,
    outbound_avg: form.outboundAvg,
    target_throughput: form.targetThroughput,
    target_utilization: form.targetUtilization,
    budget_limit: form.budgetLimit,
  })
}

export function getWarehouse(warehouseId) {
  return api.get(`/warehouses/${warehouseId}`)
}

/**
 * 내가 저장해 둔 창고 운영 조건들. 견적을 낼 때마다 창고가 하나씩 쌓이므로 최근 것부터 쓸 만하다.
 *
 * 관리자에게는 서버가 전체를 준다(WarehouseService.list 의 isAdmin 분기) — 화면에서 관리자에게는
 * 이 목록을 쓰지 않는다. 남의 창고가 "내 조건"으로 보이기 때문이다.
 */
export function getWarehouses() {
  return api.get('/warehouses')
}

export function getRobots() {
  return api.get('/robots')
}

export function createEstimate({ warehouseId, amrModel, fleetMin, fleetMax }) {
  return api.post('/estimates', {
    warehouse_id: warehouseId,
    amr_model: amrModel,
    fleet_min: fleetMin,
    fleet_max: fleetMax,
  })
}

/** 견적을 지운다 — 대수별 결과와 주행 리플레이까지 함께 사라진다 (S15P21A106-271). */
export function deleteEstimate(estimateId) {
  return api.del(`/estimates/${estimateId}`)
}

export function getEstimate(estimateId) {
  return api.get(`/estimates/${estimateId}`)
}

export function requestVerify(estimateId) {
  return api.post(`/estimates/${estimateId}/verify`)
}

/** 견적서 PDF 를 받아 저장한다. 계산이 끝난 견적만 가능(409), 변환기가 없으면 503. */
export function downloadQuotePdf(estimateId) {
  return api.download(`/estimates/${estimateId}/quote.pdf`)
}

/** 로그인 계정 이메일로 견적서 PDF 를 보낸다. 202 면 뒤에서 발송 중. */
export function emailQuote(estimateId) {
  return api.post(`/estimates/${estimateId}/quote/email`)
}

export function openEstimateStream(estimateId, { onSnapshot, onRun, onDone, onError }) {
  const source = new EventSource(streamUrl(`/estimates/${estimateId}`))
  const parse = (event) => JSON.parse(event.data)

  source.addEventListener('snapshot', (e) => onSnapshot?.(parse(e)))
  source.addEventListener('run', (e) => onRun?.(parse(e)))
  source.addEventListener('estimate.done', (e) => {
    onDone?.(parse(e))
    source.close()
  })
  source.onerror = (e) => onError?.(e)

  return () => source.close()
}

export function openVerifyStream(estimateId, { onSnapshot, onDone, onError }) {
  const source = new EventSource(streamUrl(`/estimates/${estimateId}/verify`))
  const parse = (event) => JSON.parse(event.data)

  source.addEventListener('snapshot', (e) => onSnapshot?.(parse(e)))
  source.addEventListener('verify.done', (e) => {
    onDone?.(parse(e))
    source.close()
  })
  source.onerror = (e) => onError?.(e)

  return () => source.close()
}

/** 한 화면에 담을 견적 수. 서버 기본값과 맞춰 둔다. */
export const ESTIMATE_PAGE_SIZE = 20

/**
 * 내 견적 목록 (최근순). 서버가 세션 회원 것만 준다 — 남의 견적은 애초에 내려오지 않는다.
 * 페이지 응답이라 목록은 `content`, 총 건수는 `totalElements` 다.
 */
export function getMyEstimates(page = 0, size = ESTIMATE_PAGE_SIZE) {
  return api.get(`/estimates?page=${page}&size=${size}`)
}
