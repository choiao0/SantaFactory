import { useState } from 'react'
import TimeField from './TimeField.jsx'
import { formatWon } from '../utils/format.js'

/** 모델 사진. 백엔드 목록에는 사양·단가만 있어 화면에서 붙인다 — 모델이 늘면 한 줄 더한다. */
const MODEL_PHOTO = { 'iw.hub': '/amr-iw-hub.webp' }

export default function WarehouseStep({ form, onChange, models, modelsError, model, onSelectModel }) {
  /** 고르는 중인가 — 고르기 전에는 안내만 보이고, 누르면 그때 고르는 판을 펼친다 */
  const [picking, setPicking] = useState(false)
  /** 판 안에서 짚어 둔 모델. 선택 완료를 눌러야 바깥으로 나간다 — 취소로 되돌릴 수 있어야 한다 */
  const [draft, setDraft] = useState(null)
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
          {modelsError && <p className="form-error">모델 목록을 불러오지 못했습니다. {modelsError}</p>}
          {!modelsError && models.length === 0 && <p className="mono dim">모델 목록을 불러오는 중…</p>}

          {/* 고르기 전에는 사양을 늘어놓지 않는다 — 고른 적도 없는데 선택됨으로 보이던 것을 고친다 */}
          {!modelsError && models.length > 0 && model == null && !picking && (
            <div className="modelask">
              <h4>AMR 모델을 선택해주세요</h4>
              <p>선택 후 사양과 단가를 확인할 수 있습니다.</p>
              <button type="button" className="button"
                      onClick={() => { setDraft(model); setPicking(true) }}>
                AMR 선택하기 <span aria-hidden="true">›</span>
              </button>
            </div>
          )}

          {picking && (
            <div className="modelpick">
              <h4>AMR 모델 선택</h4>
              <div className="picktiles">
                {models.map((m) => (
                  <button
                    type="button"
                    key={m.model}
                    className={`picktile${draft === m.model ? ' on' : ''}`}
                    onClick={() => setDraft((d) => (d === m.model ? null : m.model))}
                    aria-pressed={draft === m.model}
                  >
                    <span>{m.model}</span>
                    {MODEL_PHOTO[m.model] && <img src={MODEL_PHOTO[m.model]} alt="" />}
                  </button>
                ))}
              </div>
              <div className="pickcta">
                <button type="button" className="button" disabled={draft == null}
                        onClick={() => { onSelectModel(draft); setPicking(false) }}>
                  선택 완료
                </button>
              </div>
            </div>
          )}

          {!picking && models.filter((m) => m.model === model).map((m) => (
            <div className="picked" key={m.model}>
              <div className="picked-head">
                <h4>{m.model}</h4>
                {/* 카드 전체를 누르게 하지 않는다 — 사양을 읽다가 잘못 눌러 고르는 판이 열린다.
                    다시 고르기 시작하면 고른 것을 비운다 — 선택 완료를 누르기 전까지는 고르지
                    않은 것이고, 그동안 견적 요청도 막혀야 한다 */}
                <button type="button" className="again"
                        onClick={() => { setDraft(m.model); onSelectModel(null); setPicking(true) }}>
                  <span aria-hidden="true">↻</span> 다시 선택하기
                </button>
              </div>
              {/* 사진을 위에 깔면 높이가 모자라 띠처럼 눌린다 — 왼쪽에 세워 두고 사양을 옆에 붙인다 */}
              <div className="picked-body">
                {MODEL_PHOTO[m.model] && <img src={MODEL_PHOTO[m.model]} alt="" />}
                <dl className="picked-specs">
                  <dt>속도</dt>
                  <dd>{m.speed}<i>m/s</i></dd>
                  <dt>적재 용량</dt>
                  <dd>{m.capacity}<i>kg</i></dd>
                  <dt>배터리</dt>
                  <dd>{m.battery}<i>%</i></dd>
                  <dt>대당 단가</dt>
                  <dd>{formatWon(m.price)}</dd>
                  <dt>설치비</dt>
                  <dd>{formatWon(m.cost)}</dd>
                </dl>
              </div>
            </div>
          ))}
        </aside>
      </div>
    </section>
  )
}
