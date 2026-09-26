// node --test src/  (npm test) — 브라우저 없이 도는 순수 함수만 여기서 본다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { expiresAt, isStale, keepSigned } from './signedUrl.js'

// MinIO 서명 URL 모양(SigV4 쿼리) — 서명 값은 가짜
const signed = (date, expires) =>
  'https://j15a106.p.ssafy.io/media/verify-videos/verify_20_n11_2/demo_verify_20_n11_2.mp4'
  + `?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=reader%2F20260926%2Fus-east-1%2Fs3%2Faws4_request`
  + `&X-Amz-Date=${date}&X-Amz-Expires=${expires}&X-Amz-SignedHeaders=host&X-Amz-Signature=abc`

const URL_A = signed('20260926T120000Z', 1800)

test('만료 시각 = 서명 시각 + 유효 시간', () => {
  assert.equal(expiresAt(URL_A), Date.UTC(2026, 8, 26, 12, 30, 0))
})

test('서명 정보가 없거나 깨진 URL 은 만료를 모른다', () => {
  assert.equal(expiresAt('https://example.com/demo.mp4'), null)
  assert.equal(expiresAt(signed('2026-09-26', 1800)), null)
  assert.equal(expiresAt(signed('20260926T120000Z', 'x')), null)
  assert.equal(expiresAt(null), null)
})

test('만료 1분 전부터 낡은 것으로 본다', () => {
  assert.equal(isStale(URL_A, Date.UTC(2026, 8, 26, 12, 20, 0)), false)
  assert.equal(isStale(URL_A, Date.UTC(2026, 8, 26, 12, 29, 30)), true)
  assert.equal(isStale(URL_A, Date.UTC(2026, 8, 26, 13, 0, 0)), true)
})

test('만료를 모르는 URL 은 낡지 않은 것으로 둔다 — 서명 없는 로컬 주소를 괜히 다시 받지 않게', () => {
  assert.equal(isStale('http://localhost/demo.mp4', Date.now()), false)
})

test('같은 객체면 쓰던 URL 을 유지한다 (S15P21A106-279)', () => {
  const later = signed('20260926T121000Z', 1800)
  assert.equal(keepSigned(URL_A, later), URL_A)
  assert.equal(keepSigned(null, later), later)
})
