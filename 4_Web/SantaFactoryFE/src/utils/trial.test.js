// node --test src/  (npm test) — 체험 모드 판정 (S15P21A106-283)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { toTrialMode } from './trial.js'

test('서버가 trial_mode: true 를 주면 체험 모드다', () => {
  assert.equal(toTrialMode({ trial_mode: true }), true)
})

test('false·빈 응답·모르는 모양은 체험 모드가 아니다', () => {
  assert.equal(toTrialMode({ trial_mode: false }), false)
  assert.equal(toTrialMode(null), false)
  assert.equal(toTrialMode(undefined), false)
  assert.equal(toTrialMode({}), false)
  // 문자열 "true" 처럼 어긋난 값으로 화면을 바꾸지 않는다 — 막는 것은 어차피 서버다
  assert.equal(toTrialMode({ trial_mode: 'true' }), false)
})
