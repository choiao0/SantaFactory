/** 무엇을 해주는 서비스인가 — 처음 온 사람이 스크롤 없이 읽는 자리 (S15P21A106-274). */
const DOES = [
  ['조건을 넣습니다', '하루에 몇 건을 내보내는지, 언제 내보내는지, 목표와 예산이 얼마인지. 창고를 다시 재지 않아도 됩니다.'],
  ['대수를 바꿔가며 돌립니다', '3대·4대·5대… 정한 범위만큼, 하루치 주문을 대수마다 따로 시뮬레이션합니다.'],
  ['권장 대수와 비용을 냅니다', '목표를 만족하는 구성 중 가장 효율이 좋은 대수와 그때의 구축비용을 견적서로 드립니다.'],
]

export default function ServiceIntro() {
  return (
    <section className="step section-light" id="intro">
      <div className="eyebrow red">
        <span className="live-dot" />
        무엇을 하는 서비스인가
      </div>
      <h2>Answer before you buy.</h2>
      <p className="desc">
        AMR 을 몇 대 사야 하는지는 사 보기 전에는 알기 어렵습니다.
        이 서비스는 그 답을 <b>사기 전에</b> 숫자로 냅니다.
      </p>

      <ol className="does">
        {DOES.map(([title, body], i) => (
          <li key={title}>
            <span className="does-no">{String(i + 1).padStart(2, '0')}</span>
            <h4>{title}</h4>
            <p>{body}</p>
          </li>
        ))}
      </ol>

      <div className="why">
        <h3>근거는 두 번 확인합니다</h3>
        <div className="why-two">
          <div>
            <h4>계산으로 한 번</h4>
            <p>
              주문 하나하나가 언제 들어와 어느 통로로 가고 언제 나가는지를 시간 순서대로 따라갑니다.
              로봇끼리 길에서 만나 기다리는 시간까지 셉니다.
            </p>
          </div>
          <div>
            <h4>물리로 또 한 번</h4>
            <p>
              권장 대수를 로봇 물리 엔진으로 실제로 돌립니다. 계산이 놓칠 수 있는 충돌과 정체를
              눈으로 확인하고, 그 장면을 영상으로 남깁니다.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
