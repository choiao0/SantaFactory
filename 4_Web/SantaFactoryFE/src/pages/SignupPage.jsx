import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/authContext.js'

const DEFAULT_FORM = { email: '', password: '', passwordConfirm: '', name: '', company: '', phone: '' }

// 서버와 같은 규칙. 여기서 먼저 걸러야 비밀번호를 왕복시키지 않고 바로 알려줄 수 있다
const MIN_PASSWORD = 8
const PHONE_PATTERN = '[0-9\\-]{9,20}'

export default function SignupPage() {
  const navigate = useNavigate()
  const { member, loading, signUp } = useAuth()
  const [form, setForm] = useState(DEFAULT_FORM)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // 로그인한 채로 가입 화면에 오는 건 대개 주소를 직접 친 경우다. 새 계정을 만들려면
  // 먼저 로그아웃해야 하므로(가입이 곧 로그인이라) 원래 화면으로 돌려보낸다
  if (!loading && member && !submitting) {
    return <Navigate to={member.role === 'ADMIN' ? '/admin' : '/estimate'} replace />
  }

  const onChange = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (form.password.length < MIN_PASSWORD) {
      setError(`비밀번호는 ${MIN_PASSWORD}자 이상이어야 합니다.`)
      return
    }
    if (form.password !== form.passwordConfirm) {
      setError('비밀번호가 서로 다릅니다.')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      // 가입에 성공하면 바로 로그인까지 된다 — 방금 친 비밀번호를 또 치게 할 이유가 없다.
      // 역할은 보내지 않는다. 서버가 항상 USER 로 만든다
      await signUp(form)
      navigate('/estimate', { replace: true })
    } catch (e) {
      setError(e.message)
      setSubmitting(false)
    }
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
              <span>이메일</span>
              <input type="email" value={form.email} onChange={onChange('email')} autoComplete="username" required />
            </label>
            <label>
              <span>비밀번호</span>
              <input
                type="password"
                value={form.password}
                onChange={onChange('password')}
                autoComplete="new-password"
                minLength={MIN_PASSWORD}
                required
              />
            </label>
            <label>
              <span>비밀번호 확인</span>
              <input
                type="password"
                value={form.passwordConfirm}
                onChange={onChange('passwordConfirm')}
                autoComplete="new-password"
                required
              />
            </label>
            <label>
              <span>담당자명</span>
              <input value={form.name} onChange={onChange('name')} autoComplete="name" required />
            </label>
            <label>
              <span>회사명</span>
              <input value={form.company} onChange={onChange('company')} autoComplete="organization" required />
            </label>
            <label>
              {/*
                견적 뒤 영업이 연락하는 게 이 서비스의 목적이라 서버도 필수로 받는다.
                pattern 의 하이픈은 반드시 이스케이프한다 — 브라우저가 이 값을 정규식 v 플래그로
                해석해서, 문자클래스 끝의 맨 하이픈은 문법 오류가 되고 속성이 통째로 무시된다.
              */}
              <span>연락처</span>
              <input
                type="tel"
                value={form.phone}
                onChange={onChange('phone')}
                autoComplete="tel"
                placeholder="010-1234-5678"
                pattern={PHONE_PATTERN}
                required
              />
            </label>

            {error && <p className="form-error">{error}</p>}
            <button type="submit" className="button login-submit" disabled={submitting}>
              {submitting ? '가입 중…' : '가입하기'}
            </button>
            <Link className="login-alt-link" to="/">이미 계정이 있으신가요? 로그인</Link>
          </form>
        </div>
      </div>
    </section>
  )
}
