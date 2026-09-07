import { useRef, useState } from 'react'
import { ESTIMATE, formatWon, totalCost } from '../data/mock.js'

const MIN = 1
const MAX = 20
const TICKS = [1, 3, 5, 7, 9, 11, 13, 15, 17, 20]

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

export default function FleetStep() {
  const [range, setRange] = useState({ min: ESTIMATE.fleetMin, max: ESTIMATE.fleetMax })
  const [step, setStep] = useState(ESTIMATE.fleetStep)
  const trackRef = useRef(null)
  const dragging = useRef(null)

  const pct = (n) => ((n - MIN) / (MAX - MIN)) * 100
  const counts = []
  for (let n = range.min; n <= range.max; n += step) counts.push(n)

  const valueAt = (clientX) => {
    const rect = trackRef.current.getBoundingClientRect()
    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1)
    return Math.round(MIN + ratio * (MAX - MIN))
  }

  const move = (which, n) => {
    setRange((r) =>
      which === 'min'
        ? { ...r, min: clamp(n, MIN, r.max) }
        : { ...r, max: clamp(n, r.min, MAX) },
    )
  }

  const onPointerDown = (e) => {
    const n = valueAt(e.clientX)
    const which = Math.abs(n - range.min) <= Math.abs(n - range.max) ? 'min' : 'max'
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

  return (
    <section className="step section-dark reveal" id="s2">
      <div className="eyebrow red">
        <span className="live-dot" />
        02 — FLEET
      </div>
      <h2>Pick the range.</h2>
      <p className="desc">비교할 AMR 대수 범위를 정합니다. 대수 하나가 시뮬레이션 run 하나입니다.</p>

      <div className="fleetbox">
        <div className="mono dim">FLEET SIZE SWEEP</div>
        <div
          className="range"
          ref={trackRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div className="track" />
          <div className="fill" style={{ left: `${pct(range.min)}%`, width: `${pct(range.max) - pct(range.min)}%` }} />
          <div className="knob" style={{ left: `${pct(range.min)}%` }} />
          <div className="knob" style={{ left: `${pct(range.max)}%` }} />
          {TICKS.map((n) => (
            <span key={n} className={`tick${n >= range.min && n <= range.max ? ' on' : ''}`} style={{ left: `${pct(n)}%` }}>
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
              max={range.max}
              value={range.min}
              onChange={(e) => move('min', Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="fleet-max">최대 대수</label>
            <input
              id="fleet-max"
              type="number"
              min={range.min}
              max={MAX}
              value={range.max}
              onChange={(e) => move('max', Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="fleet-step">간격</label>
            <select id="fleet-step" value={step} onChange={(e) => setStep(Number(e.target.value))}>
              <option value={1}>1대</option>
              <option value={2}>2대</option>
              <option value={3}>3대</option>
            </select>
          </div>
        </div>

        <p className="fleetnote">
          RUNS <b>{counts.length}건</b> — {counts.map((n) => `n${n}`).join(' · ')}
          <br />
          구축비용 <b>{formatWon(totalCost(range.min))}</b> ~ <b>{formatWon(totalCost(range.max))}</b>
        </p>

        <div className="runcta">
          <button type="button" className="button">견적 요청 — {counts.length} RUNS ↗</button>
        </div>
      </div>
    </section>
  )
}
