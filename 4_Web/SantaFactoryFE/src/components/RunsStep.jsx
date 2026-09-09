import { useEffect, useState } from 'react'
import { BOTS, DOCK, ESTIMATE_STATUS_LABEL, GRID, RACK, RUN_STATUS_LABEL, STATION, buildLayout } from '../data/replay.js'
import { formatDateTime } from '../utils/format.js'

const CELL_CLASS = { [RACK]: 'c1', [STATION]: 'c2', [DOCK]: 'c3' }

const FAIL_LABEL = { FAILED: '실패', TIMEOUT: '시간 초과' }

function RunCard({ run }) {
  const failed = run.status === 'FAILED' || run.status === 'TIMEOUT'
  return (
    <div className={`run ${run.status}`}>
      <span className="n">{run.amr_count}<span>대</span></span>
      {run.status === 'DONE' && (
        <span className="metric">
          처리율 <b>{run.throughput?.toFixed(1)}%</b>
          <br />
          가동률 <b>{run.utilization?.toFixed(0)}%</b>
        </span>
      )}
      {failed && (
        <>
          <span className="fail" title={run.error ?? ''}>{FAIL_LABEL[run.status]}</span>
          <button type="button" className="ghost sm" disabled title="재실행 API 연동 예정">재실행</button>
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

function ReplayBoard({ runLabel, amrCount }) {
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
          <span>{runLabel} · SEED 101</span>
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
        <div className="hud tl"><b>{amrCount ?? '—'}</b> AMR · PREVIEW</div>
        <div className="hud tr">위치 로그 연동 예정 · 샘플 재생</div>
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

export default function RunsStep({ estimateId, estimate, connected, error }) {
  const runs = estimate?.runs ?? []
  const finished = runs.filter((r) => r.status !== 'QUEUED' && r.status !== 'RUNNING').length
  const representative = estimate?.recommended_count ?? runs.at(-1)?.amr_count ?? null
  const runLabel = estimate ? `est_${estimate.estimate_id}_n${representative ?? '?'}` : 'est_?_n?'

  return (
    <section className="step section-dark reveal" id="s3">
      <div className="eyebrow red">
        <span className="live-dot" />
        03 — RUNS
      </div>
      <h2>Watch the sweep.</h2>
      <p className="desc">대수마다 run 하나가 큐에 들어가 순서대로 계산됩니다. 결과가 도착하는 대로 카드가 갱신됩니다.</p>

      {estimateId == null && (
        <div className="runs-empty">02 단계에서 견적을 요청하면 run 진행 상황이 여기에 표시됩니다.</div>
      )}

      {estimateId != null && !estimate && !error && (
        <div className="runs-empty"><span className="live-dot pulse" /> ESTIMATE #{estimateId} · 진행 상황 연결 중…</div>
      )}

      {error && <div className="runs-empty form-error">{error}</div>}

      {estimate && (
        <>
          <div className="runs-head">
            <span className="mono">
              ESTIMATE #{estimate.estimate_id} · {formatDateTime(estimate.created_at)}
              <b>{finished} / {runs.length} DONE</b>
            </span>
            <div className="runs-legend">
              <span><i className="DONE" />완료</span>
              <span><i className="FAILED" />실패</span>
              <span><i className="QUEUED" />대기</span>
              <span className={`status ${estimate.status}`}>
                {ESTIMATE_STATUS_LABEL[estimate.status]}
                {connected && estimate.status === 'RUNNING' && ' · LIVE'}
              </span>
            </div>
          </div>
          <div className="runlist">
            {runs.map((r) => <RunCard key={r.run_id} run={r} />)}
          </div>
        </>
      )}

      <ReplayBoard runLabel={runLabel} amrCount={representative} />
    </section>
  )
}
