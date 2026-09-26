import { Link } from 'react-router-dom'
import { FIRST_STEP_PATH } from '../data/steps.js'

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
        운영 조건과 예산을 입력하면 AMR 대수별로 시뮬레이션합니다.
        <br/>
        목표를 달성하는 구성 중 운영 효율이 가장 높은 대수와 예상 구축 비용을 제시합니다.
      </p>
      <span className="badge">운영 조건 → 대수 범위 → 시뮬레이션 → 3D 주행 검증 → 견적</span>
      <div className="philos">
        <b>모든 대수의 결과를 비교해 직접 결정할 수 있습니다.</b>
      </div>
      {/* 다섯 단계 안내는 아래 제 구역이 맡는다 — 같은 내용을 두 번 늘어놓지 않는다 */}
      <div className="herocta">
        <Link className="button" to={FIRST_STEP_PATH}>견적 시작하기</Link>
        <Link className="ghost" to="/estimates">지난 견적 보기</Link>
      </div>
    </section>
  )
}
