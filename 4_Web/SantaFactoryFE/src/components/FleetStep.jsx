import { useRef } from 'react'
import { formatWon } from '../data/mock.js'

const MIN = 1
const MAX = 28
const TICKS = [1, 4, 8, 12, 16, 20, 24, 28]

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

export default function FleetStep({ fleet, onChange, model, requesting, error, estimateId, onRequest }) {
  const trackRef = useRef(null)
  const dragging = useRef(null)

  const pct = (n) => ((n - MIN) / (MAX - MIN)) * 100
  const counts = []
  for (let n = fleet.min; n <= fleet.max; n += fleet.step) counts.push(n)

  const perUnit = model ? model.price + model.cost : null
  const costMan = (n) => (perUnit == null ? null : Math.round((perUnit * n) / 10000))

  const valueAt = (clientX) => {
    const rect = trackRef.current.getBoundingClientRect()
    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1)
    return Math.round(MIN + ratio * (MAX - MIN))
  }

  const move = (which, n) => {
    if (Number.isNaN(n)) return
    onChange(
      which === 'min'
        ? { ...fleet, min: clamp(n, MIN, fleet.max) }
        : { ...fleet, max: clamp(n, fleet.min, MAX) },
    )
  }

  const onPointerDown = (e) => {
    const n = valueAt(e.clientX)
    const which = Math.abs(n - fleet.min) <= Math.abs(n - fleet.max) ? 'min' : 'max'
    dragging.current = which
    move(which, n)
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e) => {
    if (dragging.current) move(dragging.current, valueAt(e.clientX))
  }
  const onPointerUp = () => {
    dragging.current = null
  }

  const canRequest = Boolean(model) && counts.length > 0 && !requesting

  return (
    <section className="step section-dark reveal" id="s2">
      <div className="eyebrow red">
        <span className="live-dot" />
        02 — FLEET
      </div>
      <h2>Pick the range.</h2>
      <p className="desc">비교할 AMR 대수 범위를 정합니다. 대수 하나가 시뮬레이션 run 하나입니다.</p>

      <div className="fleetbox">
        <div className="mono dim">FLEET SIZE SWEEP · 최대 {MAX}대</div>
        <div
          className="range"
          ref={trackRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div className="track" />
          <div className="fill" style={{ left: `${pct(fleet.min)}%`, width: `${pct(fleet.max) - pct(fleet.min)}%` }} />
          <div className="knob" style={{ left: `${pct(fleet.min)}%` }} />
          <div className="knob" style={{ left: `${pct(fleet.max)}%` }} />
          {TICKS.map((n) => (
            <span key={n} className={`tick${n >= fleet.min && n <= fleet.max ? ' on' : ''}`} style={{ left: `${pct(n)}%` }}>
              {n}
            </span>
          ))}
        </div>

        <div className="fleetrow">
          <div>
            <label htmlFor="fleet-min">최소 대수</label>
            <input
              id="fleet-min"
              type="number"
              min={MIN}
              max={fleet.max}
              value={fleet.min}
              onChange={(e) => move('min', Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="fleet-max">최대 대수</label>
            <input
              id="fleet-max"
              type="number"
              min={fleet.min}
              max={MAX}
              value={fleet.max}
              onChange={(e) => move('max', Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="fleet-step">간격</label>
            <select id="fleet-step" value={fleet.step} onChange={(e) => onChange({ ...fleet, step: Number(e.target.value) })}>
              <option value={1}>1대</option>
              <option value={2}>2대</option>
              <option value={3}>3대</option>
              <option value={4}>4대</option>
            </select>
          </div>
        </div>

        <p className="fleetnote">
          RUNS <b>{counts.length}건</b> — {counts.map((n) => `n${n}`).join(' · ')}
          <br />
          {model ? (
            <>
              {model.model} 구축비용 <b>{formatWon(costMan(fleet.min))}</b> ~ <b>{formatWon(costMan(fleet.max))}</b>
            </>
          ) : (
            '01 단계에서 AMR 모델을 먼저 선택하세요'
          )}
        </p>

        <div className="runcta">
          <button type="button" className="button" disabled={!canRequest} onClick={onRequest}>
            {requesting ? '요청 중…' : `견적 요청 — ${counts.length} RUNS ↗`}
          </button>
          {estimateId != null && !error && (
            <span className="mono dim">ESTIMATE #{estimateId} 접수 · 아래에서 진행 상황을 확인하세요</span>
          )}
          {error && <span className="form-error">요청 실패: {error}</span>}
        </div>
      </div>
    </section>
  )
}
