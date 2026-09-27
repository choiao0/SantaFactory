/**
 * 서명 URL 은 조회할 때마다 서명(쿼리)만 바뀐다 — 같은 객체면 지금 재생 중인 URL 을 유지해야 한다 (S15P21A106-279).
 * 스냅샷·verify.done 이 올 때마다 `<video src>` 를 바꾸면 영상이 처음으로 돌아가 다시 받는다.
 */
export function objectPath(url) {
  if (!url) return null
  try {
    return new URL(url, 'http://local').pathname
  } catch {
    return url
  }
}

/** 같은 객체(경로)면 쓰던 URL 을, 다른 객체거나 처음이면 새 URL 을 돌려준다. */
export function keepSigned(current, incoming) {
  if (current && incoming && objectPath(current) === objectPath(incoming)) return current
  return incoming ?? current ?? null
}

/** 이 시간 안쪽으로 남은 서명은 이미 만료된 것처럼 다룬다 — 요청이 가는 사이에 끝나지 않게. */
const STALE_MARGIN_MS = 60_000

/**
 * 서명 URL 의 만료 시각(ms) — 서명 시각(X-Amz-Date, UTC `YYYYMMDDTHHMMSSZ`) + 유효 시간(X-Amz-Expires, 초).
 * 서명이 없거나 형식이 깨졌으면 null (S15P21A106-280).
 */
export function expiresAt(url) {
  if (!url) return null
  let params
  try {
    params = new URL(url, 'http://local').searchParams
  } catch {
    return null
  }
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(params.get('X-Amz-Date') ?? '')
  const ttl = Number(params.get('X-Amz-Expires'))
  if (!m || !Number.isFinite(ttl) || ttl <= 0) return null
  const [, y, mo, d, h, mi, s] = m.map(Number)
  return Date.UTC(y, mo - 1, d, h, mi, s) + ttl * 1000
}

/**
 * 곧 만료되는(또는 이미 만료된) 서명인가. 페이지를 오래 열어 두면 받아 둔 서명이 끝나 첫 재생이 403 이 된다 —
 * 재생·구간 이동 직전에 이걸로 보고 새 URL 을 먼저 받는다. 만료를 모르는 URL(서명 없는 로컬)은 false.
 */
export function isStale(url, now = Date.now()) {
  const at = expiresAt(url)
  return at != null && now >= at - STALE_MARGIN_MS
}
