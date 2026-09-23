import TimeField from './TimeField.jsx'
import { formatWon } from '../utils/format.js'

export default function WarehouseStep({ form, onChange, models, modelsError, model, onSelectModel }) {
  const number = (key) => (e) => onChange({ [key]: e.target.value === '' ? '' : Number(e.target.value) })
  const digits = (key) => (e) => {
    const v = e.target.value.replace(/[^0-9]/g, '')
    onChange({ [key]: v === '' ? '' : Number(v) })
  }

  return (
    <section className="step section-light reveal" id="s1">
      <div className="eyebrow red">
        <span className="live-dot" />
        01 — 운영 조건
      </div>
      <h2>Define the operation.</h2>
      <p className="desc">창고 운영 조건과 목표, 예산을 입력하고 시뮬레이션에 쓸 AMR 모델을 선택합니다.</p>

      <div className="duo">
        <form onSubmit={(e) => e.preventDefault()}>
          <div className="formgrid">
            {/* 입고는 받지 않는다 — 시뮬레이션이 출고 구간만 돌아(estimate.shifts=out) 입력해도
                견적이 달라지지 않는다. 입고를 붙일 때 물량·시간대 두 칸을 되살린다 */}
            <div className="span2">
              <label htmlFor="outbound-avg">일 평균 출고 주문</label>
              <div className="field">
                <input id="outbound-avg" type="text" inputMode="numeric" value={form.outboundAvg} onChange={digits('outboundAvg')} />
                <span className="suffix">건/일</span>
              </div>
            </div>

            <div className="span2">
              <label htmlFor="outbound-start">출고 시간대</label>
              <div className="timerange">
                <TimeField id="outbound-start" label="출고 시작 시각" value={form.outboundStart} onChange={(v) => onChange({ outboundStart: v })} />
                <span>–</span>
                <TimeField id="outbound-end" label="출고 종료 시각" value={form.outboundEnd} onChange={(v) => onChange({ outboundEnd: v })} />
              </div>
            </div>

            <div className="span2">
              <label htmlFor="target">목표 출고 처리율</label>
              <div className="field">
                <input id="target" type="number" value={form.targetThroughput} min={1} max={100} onChange={number('targetThroughput')} />
                <span className="suffix">%</span>
              </div>
            </div>
            <div className="span2">
              <label htmlFor="target-util">목표 가동률</label>
              <div className="field">
                <input id="target-util" type="number" value={form.targetUtilization} min={1} max={100} onChange={number('targetUtilization')} />
                <span className="suffix">%</span>
              </div>
            </div>
            <div className="span2">
              <label htmlFor="budget">최대 구축 예산</label>
              <div className="field">
                <input id="budget" type="number" value={form.budgetMan} step={1000} min={0} onChange={number('budgetMan')} />
                <span className="suffix">만원</span>
              </div>
            </div>
          </div>
        </form>

        <aside className="models">
          <div className="models-head">
            <span className="mono dim">AMR 모델</span>
            <span className="mono dim">단일 모델 · 1개 선택</span>
          </div>
          {modelsError && <p className="form-error">모델 목록을 불러오지 못했습니다. {modelsError}</p>}
          {!modelsError && models.length === 0 && <p className="mono dim">모델 목록을 불러오는 중…</p>}
          {models.map((m) => {
            const on = m.model === model
            return (
              <button
                type="button"
                key={m.model}
                className={`spec selectable${on ? ' on' : ''}`}
                onClick={() => onSelectModel(m.model)}
                aria-pressed={on}
              >
                <span className="lock">{on ? '✓ 선택됨' : '선택'}</span>
                <h4>{m.model}</h4>
                <div className="sub">AMR · 사양 · 단가</div>
                <dl>
                  <dt>속도</dt>
                  <dd>{m.speed}<span>m/s</span></dd>
                  <dt>적재 용량</dt>
                  <dd>{m.capacity}<span>kg</span></dd>
                  <dt>배터리</dt>
                  <dd>{m.battery}<span>%</span></dd>
                  <dt>대당 단가 / 설치비</dt>
                  <dd>{formatWon(m.price)} / {formatWon(m.cost)}</dd>
                </dl>
              </button>
            )
          })}
        </aside>
      </div>
    </section>
  )
}
