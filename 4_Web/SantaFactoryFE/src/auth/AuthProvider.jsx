import { useCallback, useEffect, useMemo, useState } from 'react'
import { setSessionLostHandler } from '../api/client.js'
import { clearEstimateDraft } from '../hooks/useEstimateDraft.js'
import * as authApi from '../api/auth.js'
import { AuthContext } from './authContext.js'

/**
 * 회원이 바뀌면 화면이 들고 있던 입력값도 같이 버린다.
 *
 * 보던 견적 번호는 이제 주소에 있어 지울 것이 없다 — 남의 견적 주소를 그대로 들고 있어도
 * 서버가 404 를 준다 (S15P21A106-274).
 */
function clearViewState() {
  clearEstimateDraft()
}

/**
 * 로그인 상태를 한 곳에서 들고 있는다.
 *
 * 토큰을 localStorage 에 두는 흔한 방식과 다르다 — 우리 토큰은 HttpOnly 쿠키라 JS 가
 * 볼 수 없다. 그래서 "로그인했나"를 저장된 값으로 판단할 수 없고, 앱이 뜰 때 서버에
 * `GET /auth/me` 를 한 번 물어서 정한다. 그 대신 XSS 로 토큰이 새지 않는다.
 */
export function AuthProvider({ children }) {
  const [member, setMember] = useState(null)
  // 첫 조회가 끝나기 전에는 비로그인과 구분이 안 된다. 나눠두지 않으면 새로고침할 때마다
  // 로그인 화면이 한 번 번쩍이고 원래 보던 페이지로 돌아온다.
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 갱신까지 실패하면(=refresh 도 만료·폐기) 화면 상태를 비운다
    setSessionLostHandler(() => setMember(null))
    return () => setSessionLostHandler(null)
  }, [])

  useEffect(() => {
    // access 가 만료됐어도 refresh 가 살아 있으면 client.js 가 조용히 갱신해 준다.
    // 그래서 브라우저를 껐다 켜도 7일 안이면 로그인이 유지된다.
    authApi.me()
      .then(setMember)
      .catch(() => setMember(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (credentials) => {
    const loggedIn = await authApi.login(credentials)
    // 앞사람이 치던 창고 조건이 남아 있으면, 새 계정의 첫 입력칸이 남의 숫자로 차 있다
    clearViewState()
    setMember(loggedIn)
    return loggedIn
  }, [])

  /** 가입 후 바로 로그인까지 한다 — 방금 입력한 비밀번호를 다시 치게 할 이유가 없다. */
  const signUp = useCallback(async (form) => {
    await authApi.signUp(form)
    return login({ email: form.email, password: form.password })
  }, [login])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      // 서버 호출이 실패해도 화면에서는 내보낸다. 남겨두면 사용자는 로그아웃한 줄 아는데
      // 화면만 로그인 상태로 남는다
      clearViewState()
      setMember(null)
    }
  }, [])

  const value = useMemo(
    () => ({ member, loading, isAdmin: member?.role === 'ADMIN', login, signUp, logout }),
    [member, loading, login, signUp, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
