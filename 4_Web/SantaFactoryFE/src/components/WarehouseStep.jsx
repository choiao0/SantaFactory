import { useState } from 'react'
import { AMR_MODELS, formatWon } from '../data/mock.js'

export default function WarehouseStep() {
  const [selected, setSelected] = useState([AMR_MODELS[0].id])
  const toggle = (id) =>
    setSelected((cur) => {
      if (cur.includes(id)) return cur.length > 1 ? cur.filter((v) => v !== id) : cur
      return [...cur, id]
    })
  return (
    <section className="step section-light reveal" id="s1">
      <div className="eyebrow red">
        <span className="live-dot" />
        01 — WAREHOUSE
      </div>
      <h2>Define the operation.</h2>
      <p className="desc">창고 운영 조건과 목표, 예산을 입력하고 비교할 AMR 모델을 선택합니다. 모델은 여러 개 고를 수 있습니다.</p>

      <div className="duo">
        <form onSubmit={(e) => e.preventDefault()}>
          <div className="formgrid">
            <div>
              <label htmlFor="workers">작업자 수</label>
              <input id="workers" type="number" defaultValue={4} min={1} />
              <span className="unit">명</span>
            </div>
            <div>
              <label htmlFor="inbound-avg">일 평균 입고</label>
              <input id="inbound-avg" type="number" defaultValue={480} min={0} />
              <span className="unit">건 / 일</span>
            </div>
            <div>
              <label htmlFor="outbound-avg">일 평균 출고 주문</label>
              <input id="outbound-avg" type="number" defaultValue={500} min={0} />
              <span className="unit">건 / 일</span>
            </div>
            <div>
              <label htmlFor="seed">시드</label>
              <input id="seed" type="number" defaultValue={42} />
              <span className="unit">재현용 난수</span>
            </div>

            <div className="span2">
              <label htmlFor="inbound-start">입고 시간대</label>
              <div className="timerange">
                <input id="inbound-start" type="time" defaultValue="01:00" />
                <span>–</span>
                <input id="inbound-end" type="time" defaultValue="09:00" />
              </div>
            </div>
            <div className="span2">
              <label htmlFor="outbound-start">출고 시간대</label>
              <div className="timerange">
                <input id="outbound-start" type="time" defaultValue="13:00" />
                <span>–</span>
                <input id="outbound-end" type="time" defaultValue="18:00" />
              </div>
            </div>

            <div className="span2">
              <label htmlFor="target">목표 처리량</label>
              <input id="target" type="number" defaultValue={90} min={1} />
              <span className="unit">주문 / 시</span>
            </div>
            <div className="span2">
              <label htmlFor="budget">최대 구축 예산</label>
              <input id="budget" type="number" defaultValue={60000} step={1000} min={0} />
              <span className="unit">만원</span>
            </div>
          </div>

          <p className="formsum">
            출고 피크 <b>13:00–18:00</b> · 시간당 <b>100건</b> 도착 → 목표 <b>90건/시</b> · 예산 <b>{formatWon(60000)}</b>
          </p>

          <div className="runcta">
            <button type="button" className="ghost">주문 로그 CSV 업로드 (선택)</button>
          </div>
        </form>

        <aside className="models">
          <div className="models-head">
            <span className="mono dim">AMR MODEL</span>
            <span className="mono dim">복수 선택 가능 · {selected.length}개 선택</span>
          </div>
          {AMR_MODELS.map((m) => {
            const on = selected.includes(m.id)
            return (
              <button
                type="button"
                key={m.id}
                className={`spec selectable${on ? ' on' : ''}`}
                onClick={() => toggle(m.id)}
                aria-pressed={on}
              >
                <span className="lock">{on ? '✓ SELECTED' : 'SELECT'}</span>
                <h4>{m.model}</h4>
                <div className="sub">{m.vendor} · {m.note}</div>
                <dl>
                  <dt>속도 (공차 / 적재)</dt>
                  <dd>{m.speedEmpty} / {m.speedLoaded}<span>m/s</span></dd>
                  <dt>적재 용량</dt>
                  <dd>{m.capacity}<span>토트</span></dd>
                  <dt>충전 임계 / 시간</dt>
                  <dd>{m.chargeThreshold * 100}% / {m.chargeTime / 60}<span>분</span></dd>
                  <dt>대당 단가</dt>
                  <dd>{formatWon(m.price)}</dd>
                </dl>
              </button>
            )
          })}
        </aside>
      </div>
    </section>
  )
}
