import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const TABS = [
  { key: 'user', label: '일반 유저' },
  { key: 'admin', label: '관리자' },
]

export default function LoginPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('user')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  // 기능 연동 전 — 실제 인증 없이 선택된 탭에 따라 라우팅만 한다.
  const handleSubmit = (e) => {
    e.preventDefault()
    navigate(tab === 'admin' ? '/admin' : '/estimate')
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
          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={`tab${tab === t.key ? ' on' : ''}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>

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
          </form>
        </div>
      </div>
    </section>
  )
}
