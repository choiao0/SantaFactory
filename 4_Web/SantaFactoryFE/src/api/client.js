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

async function request(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })

  const text = await response.text()
  const payload = text ? JSON.parse(text) : null

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

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body }),
}

export function streamUrl(path) {
  return `${BASE_URL}${path}`
}
