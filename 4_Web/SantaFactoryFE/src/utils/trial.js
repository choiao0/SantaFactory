/**
 * 체험 모드 (S15P21A106-283) — 서버 설정 응답(`GET /config`)에서 켜짐 여부만 꺼낸다.
 *
 * 정확히 `true` 일 때만 켠다. 모르는 모양이면 꺼진 것으로 보는데, 화면이 틀려도 새 견적·검증은
 * 서버가 403 으로 막으므로 워커 비용이 새지 않는다.
 */
export function toTrialMode(config) {
  return config?.trial_mode === true
}
