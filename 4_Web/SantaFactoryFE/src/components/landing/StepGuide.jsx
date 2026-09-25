import { STEPS } from '../../data/steps.js'

/** 다섯 단계에서 각각 무엇을 하는지 한 줄씩 (S15P21A106-274). */
export default function StepGuide() {
  return (
    <section className="step section-dark" id="guide">
      <div className="eyebrow red">
        <span className="live-dot" />
        다섯 단계
      </div>
      <h2>진행 순서</h2>

      <ol className="guide">
        {STEPS.map((step) => (
          <li key={step.key}>
            <span className="guide-no">{step.no}</span>
            <div>
              <h4>{step.title}</h4>
              <p>{step.what}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
