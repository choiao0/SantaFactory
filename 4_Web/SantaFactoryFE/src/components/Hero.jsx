import { Link } from 'react-router-dom'
import { FIRST_STEP_PATH, STEPS } from '../data/steps.js'

export default function Hero() {
  return (
    <section className="hero section-dark" id="top">
      <div className="eyebrow red">
        <span className="live-dot" />
        AMR 도입 규모 산정 서비스
      </div>
      <h1>
        Size it.
        <br />
        <span>Before you buy.</span>
      </h1>
      <p>
        운영 조건과 예산을 입력하면 AMR 대수를 바꿔가며 시뮬레이션합니다.
        <br/>
        목표 처리량을 만족하는 최소 대수와 예상 구축비용을 제시합니다.
      </p>
      <span className="badge">요청 → 대기 → 시뮬레이션 → 검증 → 견적</span>
      <div className="philos">
        <b>선택은 고객이, 근거는 시스템이</b>
      </div>
      <div className="herocta">
        <Link className="button" to={FIRST_STEP_PATH}>견적 시작하기 ↗</Link>
        <Link className="ghost" to="/estimates">지난 견적 보기</Link>
      </div>
      {/* 앞으로 지날 길의 안내다 — 아직 시작하지 않아 갈 수 있는 곳이 없으므로 링크로 두지 않는다 */}
      <nav className="stepper" aria-label="진행 순서">
        {STEPS.map((step) => (
          <span key={step.key} className="stepitem">
            {step.no} — {step.title}
            <b>{step.desc}</b>
          </span>
        ))}
      </nav>
    </section>
  )
}
