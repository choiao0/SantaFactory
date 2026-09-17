import { api, streamUrl } from './client.js'

export function createWarehouse(form) {
  return api.post('/warehouses', {
    worker_count: form.workerCount,
    inbound_start: form.inboundStart,
    inbound_end: form.inboundEnd,
    outbound_start: form.outboundStart,
    outbound_end: form.outboundEnd,
    inbound_avg: form.inboundAvg,
    outbound_avg: form.outboundAvg,
    target_throughput: form.targetThroughput,
    budget_limit: form.budgetLimit,
  })
}

export function getWarehouse(warehouseId) {
  return api.get(`/warehouses/${warehouseId}`)
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
