import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/authContext.js'

export default function LoginPage() {
  const navigate = useNavigate()
  const { member, loading, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // 이미 로그인한 채로 주소창에 "/" 를 치면 로그인 화면을 다시 보여줄 이유가 없다
  if (!loading && member) {
    return <Navigate to={member.role === 'ADMIN' ? '/admin' : '/estimate'} replace />
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const loggedIn = await login({ email, password })
      // 역할은 로그인 응답에 담겨 온다 — 관리자는 전체 견적 화면이 첫 화면이다
      navigate(loggedIn.role === 'ADMIN' ? '/admin' : '/estimate', { replace: true })
    } catch (e) {
      // 서버가 "없는 이메일"과 "틀린 비밀번호"를 구분해 주지 않는다 — 구분하면 어떤
      // 이메일이 가입돼 있는지 알려주는 셈이다. 화면도 같은 이유로 구분하지 않는다
      setError(e.message)
      setSubmitting(false)
    }
  }

  return (
    <section className="section-dark login-page" id="top">
      <div className="login-brand">
        <a className="brand" href="#top">
          <img className="brand-mark" src="/santafactory-logo.png" alt="Santa Factory" width={30} height={30} />
          <span>SANTA FACTORY</span>
        </a>
        <span className="eyebrow red login-eyebrow">
          <span className="live-dot" />
          <span>LOGIN</span>
        </span>
      </div>

      <div className="login-card">
        <h1 className="login-title">
          Size it.
          <br />
          <span>Before you buy.</span>
        </h1>

        <div className="login-fields">
          <form className="login-form" onSubmit={handleSubmit}>
            <label>
              <span>이메일</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label>
              <span>비밀번호</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            {error && <p className="form-error">{error}</p>}
            <button type="submit" className="button login-submit" disabled={submitting}>
              {submitting ? '로그인 중…' : '로그인'}
            </button>
            <Link className="login-alt-link" to="/signup">계정이 없으신가요? 회원가입</Link>
          </form>
        </div>
      </div>
    </section>
  )
}
