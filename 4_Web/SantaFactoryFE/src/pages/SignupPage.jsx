import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { sendEmailCode, verifyEmailCode } from '../api/auth.js'
import { useAuth } from '../auth/authContext.js'

const DEFAULT_FORM = { email: '', password: '', passwordConfirm: '', name: '', company: '', phone: '' }

// 서버와 같은 규칙. 여기서 먼저 걸러야 비밀번호를 왕복시키지 않고 바로 알려줄 수 있다
const MIN_PASSWORD = 8
const PHONE_PATTERN = '[0-9\\-]{9,20}'
// 서버의 재발송 쿨다운(60초)과 같다. 화면이 먼저 막아야 429 를 보지 않는다
const RESEND_SECONDS = 60

export default function SignupPage() {
  const navigate = useNavigate()
  const { member, loading, signUp } = useAuth()
  const [form, setForm] = useState(DEFAULT_FORM)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // 이메일 인증: 코드를 보낸 이메일, 남은 재발송 시간, 입력한 코드, 확인 뒤 받은 토큰
  const [codeSentTo, setCodeSentTo] = useState(null)
  const [cooldown, setCooldown] = useState(0)
  const [code, setCode] = useState('')
  const [emailToken, setEmailToken] = useState(null)
  const [busy, setBusy] = useState(null) // 'send' | 'verify' | null

  useEffect(() => {
    if (cooldown <= 0) return undefined
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  // 로그인한 채로 가입 화면에 오는 건 대개 주소를 직접 친 경우다. 새 계정을 만들려면
  // 먼저 로그아웃해야 하므로(가입이 곧 로그인이라) 원래 화면으로 돌려보낸다
  if (!loading && member && !submitting) {
    return <Navigate to={member.role === 'ADMIN' ? '/admin' : '/estimate'} replace />
  }

  const verified = emailToken != null
  const onChange = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const handleSendCode = async () => {
    if (!form.email) {
      setError('이메일을 먼저 입력해 주세요.')
      return
    }
    setBusy('send')
    setError(null)
    try {
      await sendEmailCode(form.email)
      setCodeSentTo(form.email)
      setCode('')
      setCooldown(RESEND_SECONDS)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const handleVerifyCode = async () => {
    setBusy('verify')
    setError(null)
    try {
      const { email_token } = await verifyEmailCode(codeSentTo, code)
      setEmailToken(email_token)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!verified) {
      setError('이메일 인증을 먼저 완료해 주세요.')
      return
    }
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
      // 역할은 보내지 않는다. 서버가 항상 USER 로 만든다. 이메일은 인증한 그 값으로 보낸다
      await signUp({ ...form, email: codeSentTo, emailToken })
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
          <span>회원가입</span>
        </span>
      </div>

      <div className="login-card">
        <h1 className="login-title">Join the fleet.</h1>

        <div className="login-fields">
          <form className="login-form" onSubmit={handleSubmit}>
            <label>
              <span>이메일</span>
              <div className="verify-row">
                <input
                  type="email"
                  value={form.email}
                  onChange={onChange('email')}
                  autoComplete="username"
                  readOnly={verified}
                  required
                />
                <button
                  type="button"
                  className="button verify-button"
                  onClick={handleSendCode}
                  disabled={verified || busy != null || cooldown > 0}
                >
                  {verified ? '인증 완료' : cooldown > 0 ? `${cooldown}초 후 재전송` : codeSentTo ? '다시 보내기' : '인증 코드 보내기'}
                </button>
              </div>
            </label>
            {codeSentTo && !verified && (
              <label>
                <span>인증 코드 · {codeSentTo}에 보냈습니다</span>
                <div className="verify-row">
                  <input
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                    placeholder="6자리"
                    autoComplete="one-time-code"
                  />
                  <button
                    type="button"
                    className="button verify-button"
                    onClick={handleVerifyCode}
                    disabled={code.length !== 6 || busy != null}
                  >
                    {busy === 'verify' ? '확인 중…' : '확인'}
                  </button>
                </div>
              </label>
            )}
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
            <button type="submit" className="button login-submit" disabled={submitting || !verified}>
              {submitting ? '가입 중…' : verified ? '가입하기' : '이메일 인증 후 가입할 수 있습니다'}
            </button>
            <Link className="login-alt-link" to="/">이미 계정이 있으신가요? 로그인</Link>
          </form>
        </div>
      </div>
    </section>
  )
}
