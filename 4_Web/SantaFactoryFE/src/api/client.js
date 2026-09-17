const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  constructor(code, message, status, result) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.result = result
  }
}

/**
 * 여기서 난 401 에는 갱신을 시도하지 않는다.
 * `/auth/refresh` 에 걸면 무한 루프가 되고, 로그인·가입 실패는 토큰이 없어서가 아니라
 * 자격 증명이 틀려서라 갱신해봐야 결과가 같다.
 */
const NO_REFRESH = ['/auth/login', '/auth/signup', '/auth/refresh', '/auth/logout', '/auth/email']

let refreshing = null
let onSessionLost = () => {}

/** 갱신까지 실패했을 때 부를 콜백. AuthProvider 가 회원 상태를 비우는 데 쓴다. */
export function setSessionLostHandler(handler) {
  onSessionLost = handler ?? (() => {})
}

async function send(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    // 인증 토큰이 HttpOnly 쿠키라 이 옵션이 없으면 쿠키가 아예 실리지 않는다
    credentials: 'same-origin',
    headers: body
      ? { 'Content-Type': 'application/json', Accept: 'application/json' }
      : { Accept: 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })

  const text = await response.text()
  return { response, payload: text ? JSON.parse(text) : null }
}

/**
 * access 쿠키는 15분이면 만료된다. 토큰을 읽을 수 없으니(HttpOnly) 프론트가 만료를 미리
 * 알 방법이 없다 — 401 을 받고 나서 갱신하고 원 요청을 다시 보낸다.
 *
 * 재시도는 한 번뿐이다. 갱신 직후에도 401 이면 만료가 아니라 권한 문제이고, 다시
 * 갱신해봐야 같은 응답이 돌아온다.
 */
async function request(path, options = {}, allowRefresh = true) {
  const { response, payload } = await send(path, options)

  if (response.status === 401 && allowRefresh && !NO_REFRESH.some((p) => path.startsWith(p))) {
    if (await refreshSession()) {
      return request(path, options, false)
    }
    onSessionLost()
  }

  if (!response.ok || (payload && payload.isSuccess === false)) {
    throw new ApiError(
      payload?.code ?? `HTTP${response.status}`,
      payload?.message ?? response.statusText,
      response.status,
      payload?.result,
    )
  }
  return payload?.result ?? null
}

/**
 * 동시에 여러 요청이 401 을 받아도 갱신은 한 번만 보낸다.
 *
 * 서버는 갱신할 때마다 refresh 토큰을 회전시키고, 이미 쓴 토큰이 다시 오면 탈취 신호로
 * 보고 그 회원의 토큰을 전부 폐기한다. 갱신을 두 번 보내면 두 번째가 옛 쿠키를 들고 가
 * 정상 사용자가 스스로 로그아웃당한다.
 */
function refreshSession() {
  refreshing ??= fetch(`${BASE_URL}/auth/refresh`, { method: 'POST', credentials: 'same-origin' })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body }),
  download: (path) => download(path),
}

/**
 * 파일 응답(PDF 등)을 받아 저장까지 한다. 실패 응답은 JSON 이라 위 request 와 같은 규칙으로 에러를 만든다.
 * 401 은 한 번 갱신 뒤 재시도 — 견적서 버튼은 보통 화면을 오래 열어 둔 뒤 누르기 때문이다.
 */
async function download(path, allowRefresh = true) {
  const response = await fetch(`${BASE_URL}${path}`, { credentials: 'same-origin' })

  if (response.status === 401 && allowRefresh && (await refreshSession())) {
    return download(path, false)
  }
  if (!response.ok) {
    let payload = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    if (response.status === 401) onSessionLost()
    throw new ApiError(payload?.code ?? `HTTP${response.status}`, payload?.message ?? response.statusText, response.status, payload?.result)
  }

  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]
  const plain = /filename="?([^";]+)"?/i.exec(disposition)?.[1]
  const filename = encoded ? decodeURIComponent(encoded) : (plain ?? 'download')

  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  return filename
}

export function streamUrl(path) {
  return `${BASE_URL}${path}`
}
