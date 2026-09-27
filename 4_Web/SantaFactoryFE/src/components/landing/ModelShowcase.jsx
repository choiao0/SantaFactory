import { Link } from 'react-router-dom'
import { MODEL_PHOTO } from '../../data/models.js'
import { FIRST_STEP_PATH } from '../../data/steps.js'
import { formatWon } from '../../utils/format.js'

/**
 * 고를 수 있는 AMR 과 그 단가 (S15P21A106-274).
 *
 * 단가는 견적의 구축비용을 만드는 값이라, 견적을 내기 전에 한 번 보여 두면 결과의 금액이
 * 어디서 나왔는지가 설명된다.
 */
export default function ModelShowcase({ robots }) {
  return (
    <section className="step section-light" id="models">
      <div className="eyebrow red">
        <span className="live-dot" />
        AMR
      </div>
      <h2>고를 수 있는 로봇</h2>

      {robots.error && <p className="form-error">모델 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>}
      {robots.loading && <p className="mono dim">모델 목록을 불러오는 중…</p>}

      <div className="mdl-grid">
        {robots.items.map((m) => (
          <article className="mdl" key={m.model}>
            {MODEL_PHOTO[m.model] && <img src={MODEL_PHOTO[m.model]} alt="" />}
            <div className="mdl-body">
              <h4>{m.model}</h4>
              <dl>
                <dt>속도</dt>
                <dd>{m.speed}<span>m/s</span></dd>
                <dt>적재 용량</dt>
                <dd>{m.capacity}<span>kg</span></dd>
                <dt>대당 단가</dt>
                <dd>{formatWon(m.price)}</dd>
                <dt>설치비</dt>
                <dd>{formatWon(m.cost)}</dd>
              </dl>
            </div>
          </article>
        ))}
      </div>

      <div className="herocta">
        <Link className="button" to={FIRST_STEP_PATH}>견적 시작하기</Link>
      </div>
    </section>
  )
}
