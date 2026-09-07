import { useEffect, useState } from 'react'
import {
  BOTS,
  DOCK,
  ESTIMATE,
  ESTIMATE_STATUS_LABEL,
  RACK,
  RUNS,
  RUN_STATUS_LABEL,
  STATION,
  GRID,
  buildLayout,
} from '../data/mock.js'

const CELL_CLASS = { [RACK]: 'c1', [STATION]: 'c2', [DOCK]: 'c3' }

const FAIL_LABEL = { FAILED: '실패', TIMEOUT: '시간 초과' }

function RunCard({ run }) {
  const failed = run.status === 'FAILED' || run.status === 'TIMEOUT'
  return (
    <div className={`run ${run.status}`}>
      <span className="n">{run.n}<span>대</span></span>
      {run.status === 'DONE' && (
        <span className="metric">
          처리량 <b>{run.throughput.toFixed(1)}</b>/h
          <br />
          가동률 <b>{Math.round(run.utilization * 100)}%</b>
        </span>
      )}
      {failed && (
        <>
          <span className="fail">{FAIL_LABEL[run.status]}</span>
          <button type="button" className="ghost sm">재실행</button>
        </>
      )}
      {(run.status === 'QUEUED' || run.status === 'RUNNING') && (
        <span className="wait">{RUN_STATUS_LABEL[run.status]}</span>
      )}
    </div>
  )
}

const SPEEDS = [1, 2, 4, 8]
const BASE_DURATION = 9
const START_SECONDS = 2 * 3600 + 14 * 60 + 36

function formatClock(sec) {
  const h = String(Math.floor(sec / 3600)).padStart(2, '0')
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0')
  const s = String(sec % 60).padStart(2, '0')
  return `T+${h}:${m}:${s}`
}

function ReplayBoard() {
  const cells = buildLayout()
  const cellPct = 100 / GRID.width
  const rowPct = 100 / GRID.length
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(4)
  const [clock, setClock] = useState(START_SECONDS)

  useEffect(() => {
    if (!playing) return undefined
    const id = setInterval(() => setClock((c) => c + speed), 1000)
    return () => clearInterval(id)
  }, [playing, speed])

  const nextSpeed = () => setSpeed((v) => SPEEDS[(SPEEDS.indexOf(v) + 1) % SPEEDS.length])
  const boardStyle = {
    aspectRatio: `${GRID.width} / ${GRID.length}`,
    '--bot-duration': `${BASE_DURATION / speed}s`,
    '--bot-play': playing ? 'running' : 'paused',
  }

  return (
    <div className="rp-wrap">
      <div className="rp-bar">
        <h4>
          REPRESENTATIVE RUN
          <span>est_{ESTIMATE.id}_n{ESTIMATE.recommended} · SEED {ESTIMATE.seed}</span>
        </h4>
        <div className="rp-ctrl">
          <span className="rp-clock">{formatClock(clock)}</span>
          <button type="button" className="ghost" onClick={() => setPlaying((v) => !v)}>
            {playing ? '⏸ PAUSE' : '▶ PLAY'}
          </button>
          <button type="button" className="ghost" onClick={nextSpeed}>SPEED ×{speed}</button>
          <button type="button" className="ghost" disabled>RUN ▾</button>
        </div>
      </div>

      <div className="sim-board">
        <div className="board-head">
          <span>TOP VIEW · SIMPY QUOTE ENGINE</span>
          <span>{GRID.width} × {GRID.length} · 1 CELL = 1 m</span>
        </div>
        <div className="hud tl"><b>{ESTIMATE.recommended}</b> AMR · ACTIVE 8 · CHARGING 0</div>
        <div className="hud tr">ORDERS <b>212</b> / 500 · LEAD <b>3m 28s</b></div>
        <div className="replay" style={boardStyle}>
          {cells.map((c, i) => (
            <div key={i} className={`cell ${CELL_CLASS[c] ?? ''}`} />
          ))}
          {BOTS.map((b) => (
            <div
              key={b.path}
              className={`bot ${b.state} path-${b.path}`}
              style={{ left: `${b.x * cellPct}%`, top: `${b.y * rowPct}%`, animationDelay: `${-b.x * 0.4}s` }}
            >
              <i />
              <span className="tote" />
            </div>
          ))}
        </div>
        <div className="board-foot">
          <span>P = 픽업 스테이션 · D = 출고 도크</span>
          <span>{playing ? 'PLAYING' : 'PAUSED'}<b>×{speed}</b></span>
        </div>
        <div className="legend">
          <span><i style={{ background: '#1d1d1d', border: '1px solid #e8e8e4' }} />이동(공차)</span>
          <span><i style={{ background: '#d9d7d2' }} />이동(적재)</span>
          <span><i style={{ background: 'var(--red)' }} />픽/드롭 중</span>
          <span><i style={{ background: '#555' }} />대기</span>
          <span><i style={{ background: '#3f3f3d' }} />랙</span>
        </div>
      </div>
    </div>
  )
}

export default function RunsStep() {
  const done = RUNS.filter((r) => r.status === 'DONE').length
  return (
    <section className="step section-dark reveal" id="s3">
      <div className="eyebrow red">
        <span className="live-dot" />
        03 — RUNS
      </div>
      <h2>Watch the sweep.</h2>
      <p className="desc">대수마다 run 하나가 큐에 들어가 순서대로 계산됩니다. 실패한 run은 개별 재실행할 수 있습니다.</p>

      <div className="runs-head">
        <span className="mono">
          ESTIMATE #{ESTIMATE.id} · {ESTIMATE.createdAt}<b>{done} / {RUNS.length} DONE</b>
        </span>
        <div className="runs-legend">
          <span><i className="DONE" />완료</span>
          <span><i className="FAILED" />실패</span>
          <span><i className="QUEUED" />대기</span>
          <span className={`status ${ESTIMATE.status}`}>{ESTIMATE_STATUS_LABEL[ESTIMATE.status]}</span>
        </div>
      </div>
      <div className="runlist">
        {RUNS.map((r) => <RunCard key={r.n} run={r} />)}
      </div>

      <ReplayBoard />
    </section>
  )
}
