import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  // 기능 연동 전 — 실제 인증 없이 견적 화면으로 이동한다. 역할(일반/관리자) 분기는
  // 나중에 로그인 응답의 역할 값을 보고 처리한다(회원가입 시 정하는 값이라 로그인엔 없음).
  const handleSubmit = (e) => {
    e.preventDefault()
    navigate('/estimate')
  }

  return (
    <section className="section-dark login-page" id="top">
      <div className="login-brand">
        <a className="brand" href="#top">
          <img className="brand-mark" src="/santafactory-logo.png" alt="Santa Factory" width={30} height={30} />
          SANTA FACTORY
        </a>
        <span className="eyebrow red login-eyebrow">
          <span className="live-dot" />
          LOGIN
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
              아이디
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            </label>
            <label>
              비밀번호
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" className="button login-submit">로그인</button>
            <Link className="login-alt-link" to="/signup">계정이 없으신가요? 회원가입</Link>
          </form>
        </div>
      </div>
    </section>
  )
}
