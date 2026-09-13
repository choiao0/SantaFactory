import { api } from './client.js'

/**
 * 인증 API (S15P21A106-186 백엔드).
 *
 * 토큰을 다루는 함수가 하나도 없는 게 정상이다 — access·refresh 는 HttpOnly 쿠키라
 * JS 가 읽지도 쓰지도 못한다. 로그인 여부는 저장해 둔 값이 아니라 `me()` 로 확인한다.
 */

/** 가입. 역할은 보내지 않는다 — 서버가 항상 USER 로 만든다. */
export function signUp({ email, password, name, company, phone }) {
  return api.post('/auth/signup', { email, password, name, company, phone })
}

/** 로그인. 응답 본문은 회원 정보고, 토큰은 Set-Cookie 로만 온다. */
export function login({ email, password }) {
  return api.post('/auth/login', { email, password })
}

/** 로그아웃. 서버가 이 기기의 refresh 를 폐기하고 쿠키를 지운다. 다른 기기는 유지된다. */
export function logout() {
  return api.post('/auth/logout')
}

/** 내 정보. 실패하면 비로그인이다. */
export function me() {
  return api.get('/auth/me')
}
