import { api } from './client.js'

/** 관리자 조회 API. ADMIN 이 아니면 서버가 403 을 준다. */

/** 한 화면에 담을 견적 수. 서버 기본값과 맞춰 둔다. */
export const ESTIMATE_PAGE_SIZE = 20

/** 회원 목록 — 행마다 창고 수·견적 수가 붙는다. 페이지를 나누지 않는다(회원 수가 적다). */
export function getMembers() {
  return api.get('/admin/members')
}

/**
 * 전체 견적 목록(최근순). 페이지 응답이라 목록은 `content`, 총 건수는 `totalElements` 다.
 *
 * 페이지를 넘기지 않으면 서버가 20건에서 자르므로, 화면도 반드시 총 건수를 같이 보여줘야
 * 한다 — 안 그러면 21번째부터는 없는 것처럼 보인다.
 */
export function getAllEstimates(page = 0, size = ESTIMATE_PAGE_SIZE) {
  return api.get(`/admin/estimates?page=${page}&size=${size}`)
}
