import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

const ROLES = [
  { key: 'user', label: '일반 유저' },
  { key: 'admin', label: '관리자' },
]

const DEFAULT_FORM = { username: '', password: '', passwordConfirm: '', companyName: '' }

export default function SignupPage() {
  const navigate = useNavigate()
  const [role, setRole] = useState('user')
  const [form, setForm] = useState(DEFAULT_FORM)

  const onChange = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  // 기능 연동 전 — 실제 가입 처리 없이 로그인 화면으로 돌아간다.
  const handleSubmit = (e) => {
    e.preventDefault()
    navigate('/')
  }

  return (
    <section className="section-dark login-page signup-page" id="top">
      <div className="login-brand">
        <a className="brand" href="#top">
          <img className="brand-mark" src="/santafactory-logo.png" alt="Santa Factory" width={30} height={30} />
          <span>SANTA FACTORY</span>
        </a>
        <span className="eyebrow red login-eyebrow">
          <span className="live-dot" />
          <span>SIGN UP</span>
        </span>
      </div>

      <div className="login-card">
        <h1 className="login-title">Join the fleet.</h1>

        <div className="login-fields">
          <form className="login-form" onSubmit={handleSubmit}>
            <label>
              <span>아이디</span>
              <input value={form.username} onChange={onChange('username')} autoComplete="username" />
            </label>
            <label>
              <span>비밀번호</span>
              <input type="password" value={form.password} onChange={onChange('password')} autoComplete="new-password" />
            </label>
            <label>
              <span>비밀번호 확인</span>
              <input
                type="password"
                value={form.passwordConfirm}
                onChange={onChange('passwordConfirm')}
                autoComplete="new-password"
              />
            </label>
            <label>
              <span>회사명</span>
              <input value={form.companyName} onChange={onChange('companyName')} autoComplete="organization" />
            </label>

            <div>
              <span className="login-form-label">계정 유형</span>
              <div className="tabs" role="tablist">
                {ROLES.map((r) => (
                  <button
                    key={r.key}
                    type="button"
                    role="tab"
                    aria-selected={role === r.key}
                    className={`tab${role === r.key ? ' on' : ''}`}
                    onClick={() => setRole(r.key)}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>

            <button type="submit" className="button login-submit">가입하기</button>
            <Link className="login-alt-link" to="/">이미 계정이 있으신가요? 로그인</Link>
          </form>
        </div>
      </div>
    </section>
  )
}
