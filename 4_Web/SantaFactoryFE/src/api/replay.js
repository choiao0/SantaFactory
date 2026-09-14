import { api } from './client.js'

/**
 * 대수 하나의 주행 리플레이 (S15P21A106-205).
 *
 * 견적을 돌릴 때 함께 만들어 둔 것이라 즉시 온다. 아직 결과가 없거나 그 run 이 실패했으면
 * 404 — 호출부는 둘을 구분하지 않는다("아직 못 본다"로 같다).
 */
export function getReplay(estimateId, amrCount) {
  return api.get(`/estimates/${estimateId}/runs/${amrCount}/replay`)
}
