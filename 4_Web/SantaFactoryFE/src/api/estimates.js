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
