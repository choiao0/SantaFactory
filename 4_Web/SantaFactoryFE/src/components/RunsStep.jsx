import { useEffect, useState } from 'react'
import { ESTIMATE_STATUS_LABEL, RUN_STATUS_LABEL } from '../data/replay.js'
import { formatDateTime, formatPercent } from '../utils/format.js'
import ReplayCanvas from '../replay/ReplayCanvas.jsx'
import { useReplay } from '../hooks/useReplay.js'

const FAIL_LABEL = { FAILED: '실패', TIMEOUT: '시간 초과' }

function RunCard({ run, selected, onSelect }) {
  const failed = run.status === 'FAILED' || run.status === 'TIMEOUT'
  const playable = run.status === 'DONE'
  // 완료된 run 만 누를 수 있다 — 나머지는 보여줄 궤적이 없다
  const Tag = playable ? 'button' : 'div'
  return (
    <Tag
      type={playable ? 'button' : undefined}
      className={`run ${run.status}${playable ? ' playable' : ''}${selected ? ' on' : ''}`}
      onClick={playable ? () => onSelect(run.amr_count) : undefined}
      aria-pressed={playable ? selected : undefined}
    >
      <span className="n">{run.amr_count}<span>대</span></span>
      {run.status === 'DONE' && (
        <span className="metric">
          처리율 <b>{formatPercent(run.throughput)}%</b>
          <br />
          가동률 <b>{formatPercent(run.utilization)}%</b>
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
      {playable && <span className="play-hint">{selected ? '재생 중' : '주행 보기'}</span>}
    </Tag>
  )
}

// run 전체(6시간)를 담으므로 배속이 커야 한다 — ×32 면 11분, ×64 면 5.6분에 다 본다.
// 그래도 프레임당 시뮬 0.5~1초라 샘플(4.4초 간격) 사이를 보간이 메운다
const SPEEDS = [8, 16, 32, 64]

function formatDuration(sec) {
  const h = String(Math.floor(sec / 3600)).padStart(2, '0')
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0')
  const s = String(Math.floor(sec % 60)).padStart(2, '0')
  return `${h}:${m}:${s}`
}

/**
 * 선택한 대수의 주행을 재생한다 (S15P21A106-205).
 *
 * 그리는 일은 ReplayCanvas 가 하고 여기서는 시간만 민다. 틱을 state 로 두면 프레임마다 리렌더가
 * 돌지만, 실제로 다시 그리는 건 캔버스 하나뿐이라 그게 더 단순하다.
 */
/** 1시간 창으로 본 최근 처리율. 누적만 보면 "지금 잘 돌고 있나"를 알 수 없다. */
const RECENT_WINDOW_S = 3600

/**
 * 출고 현황 (S15P21A106-205). 재생 시각까지 <b>주문</b> 몇 건이 나갔는지 센다.
 *
 * 왕복(태스크)이 아니라 주문이다 — 주문 하나가 여러 통로에 걸치면 토트가 나뉘어 AMR 이 여러 번
 * 오간다(실측 500주문 → 630왕복). 왕복을 보여주면 사용자가 입력한 출고 건수와 어긋난다.
 *
 * 입고는 넣지 않는다 — 견적 판정도 출고 처리율만 보고, 시뮬의 입고는 아직 시나리오가 보류다.
 * 완료 시각 배열이 정렬돼 오므로 이분 탐색으로 센다(6시간이면 수천 건이라 매 프레임 훑으면 밀린다).
 */
function OutboundPanel({ replay, seconds }) {
  const done = replay.outbound_done
  if (!done || done.length === 0) {
    return (
      <aside className="rp-side">
        <h5>출고 주문</h5>
        <p className="mono dim">이 run 에는 출고 기록이 없습니다.</p>
      </aside>
    )
  }

  // done[i] <= t 인 마지막 i + 1 = 그 시각까지의 완료 건수
  const countUntil = (t) => {
    let lo = 0
    let hi = done.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (done[mid] <= t) lo = mid + 1; else hi = mid
    }
    return lo
  }

  const now = countUntil(seconds)
  const windowStart = Math.max(0, seconds - RECENT_WINDOW_S)
  const recent = now - countUntil(windowStart)
  const elapsedHours = Math.max(seconds - windowStart, 1) / 3600
  const perHour = Math.round(recent / elapsedHours)
  const total = done.length
  const pct = Math.round((now / total) * 100)

  return (
    <aside className="rp-side">
      <h5>출고 주문</h5>
      <dl className="rp-stat">
        <dt>완료</dt>
        <dd>{now.toLocaleString()}<span>건</span></dd>
        <dt>최근 1시간</dt>
        <dd>{perHour.toLocaleString()}<span>건/시간</span></dd>
      </dl>
      <div className="rp-progress" role="img" aria-label={`처리 ${total}건 중 ${now}건 완료`}>
        <i style={{ width: `${pct}%` }} />
      </div>
      <p className="mono dim">처리 {total.toLocaleString()}건 중 {pct}% 완료</p>
    </aside>
  )
}

/**
 * 재생 루프. 대수가 바뀌면 부모가 key 를 갈아 이 컴포넌트를 새로 만든다 —
 * 그래야 "새 데이터가 오면 0초부터" 를 초기화 effect 없이 얻는다.
 */
function ReplayPlayer({ replay, playing, speed, onTogglePlay, onNextSpeed }) {
  const [tick, setTick] = useState(0)
  const ticks = Math.max(...Object.values(replay.robots).map((a) => a.length))
  const dt = replay.dt_s ?? 1

  useEffect(() => {
    if (!playing || ticks === 0) return undefined
    let raf = 0
    let last = performance.now()
    const step = (now) => {
      const elapsed = (now - last) / 1000
      last = now
      // 실제 경과 시간으로 민다 — 프레임 수로 세면 화면이 느린 기기에서 재생도 같이 느려진다
      setTick((t) => (t + (elapsed * speed) / dt) % ticks)
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed, ticks, dt])

  const seconds = tick * dt
  return (
    <>
      <div className="rp-stage">
        <ReplayCanvas replay={replay} tick={tick} />
        <div className="rp-sidecol">
          <OutboundPanel replay={replay} seconds={seconds} />
          <div className="rp-controls">
            <button type="button" className="button rp-btn" onClick={onTogglePlay}>
              {playing ? '⏸︎ PAUSE' : '▶︎ PLAY'}
            </button>
            <button type="button" className="ghost rp-btn" onClick={onNextSpeed}>SPEED ×{speed}</button>
          </div>
        </div>
      </div>
      {/* 전체를 담으니 건너뛸 수단이 없으면 뒤쪽은 사실상 못 본다 */}
      <div className="rp-seekrow">
        <input
          className="rp-seek"
          type="range"
          min={0}
          max={Math.max(0, ticks - 1)}
          step={1}
          value={Math.floor(tick)}
          onChange={(e) => setTick(Number(e.target.value))}
          aria-label="재생 위치"
        />
        <span className="rp-time">{formatDuration(seconds)} / {formatDuration(replay.seconds ?? (ticks - 1) * dt)}</span>
      </div>
    </>
  )
}

/** 선택한 대수의 주행을 재생한다 (S15P21A106-205). 데이터 수급과 컨트롤만 맡는다. */
function ReplayBoard({ estimateId, amrCount }) {
  const { replay, loading, error } = useReplay(estimateId, amrCount)
  const [playing, setPlaying] = useState(true)
  // 6시간을 ×64 로 보면 5.6분. ×32 는 11분이라 끝까지 보는 사람이 없다
  const [speed, setSpeed] = useState(64)

  const nextSpeed = () => setSpeed((v) => SPEEDS[(SPEEDS.indexOf(v) + 1) % SPEEDS.length])
  const togglePlay = () => setPlaying((v) => !v)

  return (
    <div className="rp-wrap">
      <div className="rp-bar">
        <h4>RUN REPLAY</h4>
      </div>

      <div className="sim-board">
        <div className="board-head">
          <span>SIMPY ENGINE</span>
          <span>1 CELL = 1 m</span>
        </div>
        <div className="hud tl"><b>{amrCount ?? '—'}</b> AMR</div>

        {replay && (
          <ReplayPlayer key={`${estimateId}:${amrCount}`} replay={replay}
                        playing={playing} speed={speed} onTogglePlay={togglePlay} onNextSpeed={nextSpeed} />
        )}
        {!replay && (
          <div className="rp-placeholder">
            {loading && <span className="mono dim">주행 데이터를 불러오는 중…</span>}
            {!loading && error && <span className="form-error">{error}</span>}
            {!loading && !error && (
              <span className="mono dim">
                {amrCount == null
                  ? '완료된 대수를 선택하면 그 구성의 주행이 재생됩니다.'
                  : '이 대수의 주행 기록이 없습니다.'}
              </span>
            )}
          </div>
        )}

        <div className="board-foot">
          <span>{replay ? `AMR ${Object.keys(replay.robots).length}대` : ''}</span>
        </div>
        {/* 화면에 실제로 칠해지는 것만 적는다. 로봇 상태(주행·대기 등)는 데이터에 없어서 색이 하나다 */}
        <div className="legend">
          <span><i style={{ background: 'var(--rp-amr)' }} />AMR</span>
          <span><i style={{ background: 'var(--rp-pack)' }} />출고(패킹)</span>
          <span><i style={{ background: 'var(--rp-pick)' }} />통로 집하</span>
          <span><i style={{ background: 'var(--rp-in)' }} />입고</span>
          <span><i style={{ background: 'var(--rp-charge)' }} />충전</span>
          <span><i style={{ background: 'var(--rp-wall)' }} />랙</span>
        </div>
      </div>
    </div>
  )
}

export default function RunsStep({ estimateId, estimate, connected, error }) {
  const runs = estimate?.runs ?? []
  const finished = runs.filter((r) => r.status !== 'QUEUED' && r.status !== 'RUNNING').length
  const [picked, setPicked] = useState(null)

  // 아무것도 고르지 않았으면 권장 대수를 보여준다 — 사용자가 제일 궁금해할 구성이다.
  // 권장이 없는 견적(사유만 있는 판정)이면 완료된 것 중 마지막 대수로 떨어진다
  const done = runs.filter((r) => r.status === 'DONE')
  const fallback = estimate?.recommended_count ?? done.at(-1)?.amr_count ?? null
  const shown = picked ?? fallback

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
        <div className="runs-empty"><span className="live-dot pulse" /> 진행 상황 연결 중…</div>
      )}

      {error && <div className="runs-empty form-error">{error}</div>}

      {estimate && (
        <>
          <div className="runs-head">
            <span className="mono">
              {formatDateTime(estimate.created_at)}
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
            {runs.map((r) => (
              <RunCard key={r.run_id} run={r} selected={r.amr_count === shown} onSelect={setPicked} />
            ))}
          </div>
        </>
      )}

      <ReplayBoard estimateId={estimateId} amrCount={shown} />
    </section>
  )
}
