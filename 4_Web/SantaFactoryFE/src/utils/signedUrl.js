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
