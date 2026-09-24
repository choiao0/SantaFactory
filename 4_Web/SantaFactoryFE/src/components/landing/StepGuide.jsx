import { STEPS } from '../../data/steps.js'

/** 다섯 단계에서 각각 무엇을 하고 무엇을 보는지 (S15P21A106-274). */
export default function StepGuide() {
  return (
    <section className="step section-dark" id="guide">
      <div className="eyebrow red">
        <span className="live-dot" />
        어떻게 진행되나
      </div>
      <h2>Five steps.</h2>
      <p className="desc">각 단계는 따로 열리고, 다음 버튼으로 넘어갑니다. 중간에 나갔다 와도 그 자리에서 이어집니다.</p>

      <ol className="guide">
        {STEPS.map((step) => (
          <li key={step.key}>
            <span className="guide-no">{step.no}</span>
            <div>
              <h4>{step.title}<em>{step.desc}</em></h4>
              <p>{step.what}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
