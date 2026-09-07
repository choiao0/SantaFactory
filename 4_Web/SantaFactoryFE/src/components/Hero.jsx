const STEPS = [
  ['#s1', '01 — WAREHOUSE', '운영 조건 입력'],
  ['#s2', '02 — FLEET', '대수 범위 선택'],
  ['#s3', '03 — RUNS', '대수별 시뮬레이션'],
  ['#quote', '04 — QUOTE', '적정 대수 · 견적'],
]

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
      <span className="badge">REQUEST → QUEUE → SIMULATE → QUOTE</span>
      <div className="philos">
        <b>선택은 고객이, 근거는 시스템이</b>
      </div>
      <nav className="stepper">
        {STEPS.map(([href, code, label]) => (
          <a key={href} href={href}>
            {code}
            <b>{label}</b>
          </a>
        ))}
      </nav>
    </section>
  )
}
