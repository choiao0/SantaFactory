import { useRef } from 'react'
import { formatWon } from '../utils/format.js'

const MIN = 1
const MAX = 28
const TICKS = [1, 4, 8, 12, 16, 20, 24, 28]

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

export default function FleetStep({ fleet, onChange, model, requesting, error, onRequest }) {
  const trackRef = useRef(null)
  const dragging = useRef(null)

  const pct = (n) => ((n - MIN) / (MAX - MIN)) * 100
  const counts = []
  for (let n = fleet.min; n <= fleet.max; n += 1) counts.push(n)

  const perUnit = model ? model.price + model.cost : null
  const cost = (n) => (perUnit == null ? null : perUnit * n)

  const valueAt = (clientX) => {
    const rect = trackRef.current.getBoundingClientRect()
    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1)
    return Math.round(MIN + ratio * (MAX - MIN))
  }

  const move = (which, n) => {
    if (Number.isNaN(n)) return
    onChange(
      which === 'min'
        ? { ...fleet, min: clamp(n, MIN, fleet.max - 1) }
        : { ...fleet, max: clamp(n, fleet.min + 1, MAX) },
    )
  }

  // 점을 직접 누르면 그 점을 잡는다. 두 점이 붙어 있을 때 위치로만 고르면 왼쪽 점의 오른쪽 절반이
  // 오른쪽 점으로 판정돼 왼쪽 점을 잡을 수 없다
  // 한 대 차이면 두 점이 겹쳐 어느 쪽을 눌렀는지 구분이 안 된다. 그때는 처음 끄는 방향으로 정한다 —
  // 왼쪽으로 끌면 왼쪽 점, 오른쪽으로 끌면 오른쪽 점
  const grab = (which) => (e) => {
    e.stopPropagation()
    dragging.current = fleet.max - fleet.min === 1 ? { startX: e.clientX } : which
    trackRef.current.setPointerCapture(e.pointerId)
  }

  // 빈 트랙을 누르면 픽셀 거리로 가까운 점을 옮긴다
  const onPointerDown = (e) => {
    const rect = trackRef.current.getBoundingClientRect()
    const x = clamp(e.clientX - rect.left, 0, rect.width)
    const xMin = (pct(fleet.min) / 100) * rect.width
    const xMax = (pct(fleet.max) / 100) * rect.width
    const which = Math.abs(x - xMin) <= Math.abs(x - xMax) ? 'min' : 'max'
    dragging.current = which
    move(which, valueAt(e.clientX))
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e) => {
    if (!dragging.current) return
    if (typeof dragging.current === 'object') {
      const dx = e.clientX - dragging.current.startX
      if (Math.abs(dx) < 4) return
      dragging.current = dx < 0 ? 'min' : 'max'
    }
    move(dragging.current, valueAt(e.clientX))
  }
  const onPointerUp = () => {
    dragging.current = null
  }

  const canRequest = Boolean(model) && counts.length > 0 && !requesting

  return (
    <section className="step section-dark reveal" id="s2">
      <div className="eyebrow red">
        <span className="live-dot" />
        02 — 대수 범위
      </div>
      <h2>Pick the range.</h2>
      <p className="desc">비교할 AMR 대수 범위를 정합니다.</p>

      <div className="fleetbox">
        <div className="mono dim">대수 스윕 · 최대 {MAX}대</div>
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
          {/* 겹치면 움직일 여지가 있는 쪽을 위에 둔다 — 오른쪽 끝에 몰리면 왼쪽 점을, 왼쪽 끝에 몰리면 오른쪽 점을 */}
          <div
            className="knob"
            style={{ left: `${pct(fleet.min)}%`, zIndex: pct(fleet.min) > 50 ? 3 : 2 }}
            onPointerDown={grab('min')}
            role="slider"
            aria-label="최소 대수"
            aria-valuemin={MIN}
            aria-valuemax={fleet.max - 1}
            aria-valuenow={fleet.min}
          />
          <div
            className="knob"
            style={{ left: `${pct(fleet.max)}%`, zIndex: pct(fleet.min) > 50 ? 2 : 3 }}
            onPointerDown={grab('max')}
            role="slider"
            aria-label="최대 대수"
            aria-valuemin={fleet.min + 1}
            aria-valuemax={MAX}
            aria-valuenow={fleet.max}
          />
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
              max={fleet.max - 1}
              value={fleet.min}
              onChange={(e) => move('min', Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="fleet-max">최대 대수</label>
            <input
              id="fleet-max"
              type="number"
              min={fleet.min + 1}
              max={MAX}
              value={fleet.max}
              onChange={(e) => move('max', Number(e.target.value))}
            />
          </div>
        </div>

        <p className="fleetnote">
          시뮬레이션 <b>{counts.length}회</b> — {fleet.min}대 ~ {fleet.max}대
          <br />
          {model ? (
            <>
              구축비용 <b>{formatWon(cost(fleet.min))}</b> ~ <b>{formatWon(cost(fleet.max))}</b>
            </>
          ) : (
            '01 단계에서 AMR 모델을 먼저 선택하세요'
          )}
        </p>

        <div className="runcta">
          <button type="button" className="button" disabled={!canRequest} onClick={onRequest}>
            {requesting ? '요청 중…' : `견적 요청 — ${counts.length}회 ↗`}
          </button>
          {error && <span className="form-error">요청 실패: {error}</span>}
        </div>
      </div>
    </section>
  )
}
