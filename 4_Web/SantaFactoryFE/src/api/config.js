import { api } from './client.js'
import { toTrialMode } from '../utils/trial.js'

/** 로그인 전에도 읽는 서버 설정 — 체험 모드 여부 (S15P21A106-283). 토큰이 필요 없다. */
export async function getTrialMode() {
  return toTrialMode(await api.get('/config'))
}
