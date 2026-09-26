import { useMemo, useRef, useState } from 'react'
import { getEstimate } from '../api/estimates.js'
import { keepSigned } from '../utils/signedUrl.js'
import AmrRunning from './AmrRunning.jsx'
import VerifyTrigger from './VerifyTrigger.jsx'
import { useVerifyStream } from '../hooks/useVerifyStream.js'

/**
 * 영상 URL 은 서명본이라 30분이면 만료된다. 만료 뒤 구간 이동은 새 Range 요청이 403 으로 거절되어
 * video 의 error 로 온다 — 그때 상세를 다시 불러 새 URL 을 받고, 보던 위치에서 이어 간다.
 * 재요청은 이 간격 안에서 한 번만 — 영상 자체가 깨진 경우 무한 반복하지 않게.
 */
const REFRESH_COOLDOWN_MS = 10_000

const STATUS_LABEL = { PENDING: '대기', RUNNING: '검증 중', DONE: '완료', FAILED: '실패' }
const VERDICT_LABEL = { PASS: '통과', WARN: '주의', FAIL: '실패', NA: '해당없음' }

const pct = (ratio) => (ratio == null ? '—' : `${Math.round(ratio * 100)}%`)
const secs = (v) => (v == null ? '—' : `${v.toFixed(1)}초`)
const meters = (v) => (v == null ? '—' : `${v.toFixed(2)} m`)
const contactsOf = (p) => (p?.robot_contacts ?? 0) + (p?.rack_contacts ?? 0)

/** 카드 한 장의 지표 목록 — 명세 §D 문구 그대로. physics 가 없으면(N/A) 빈 배열. */
function metricsFor(run) {
  const p = run.physics
  if (!p) return []
  return [
    ['창 안 계획 동작 중 시작한 비율', pct(p.window_actions?.ratio)],
    ['시작 지연 중앙값', secs(p.lag?.p50_s)],
    ['시작 지연 상위 10%', secs(p.lag?.p90_s)],
    ['로봇 접촉', p.robot_contacts ?? '—'],
    ['랙 접촉', p.rack_contacts ?? '—'],
    ['최소 간격', meters(p.robot_min_gap_m)],
    ['다른 로봇 대기 비율', pct(p.blocked?.ratio)],
    ['배속', p.rtf != null ? `${p.rtf.toFixed(2)}x` : '—'],
    ['DES 창 완료 태스크', run.slice?.tasks_done ?? p.des_window?.tasks_done ?? '—'],
  ]
}

/** 아직 후보가 하나도 없을 때(검증 전) 보여줄 자리 — 기존 단일 검증 화면과 같은 문구. */
function idlePlaceholder({ estimateId, ready, recommendedCount, started }) {
  if (estimateId == null) {
    return { tag: 'QUEUED', label: '대기', text: '견적을 요청하면 물리 검증 결과가 여기에 표시됩니다.' }
  }
  if (!ready) {
    return { tag: 'RUNNING', label: '계산 중', live: true, text: '시뮬레이션 판정이 끝나면 권장 대수 전후로 물리 검증을 돌립니다.' }
  }
  if (recommendedCount == null) {
    return {
      tag: 'QUEUED', label: '대기',
      text: '권장 대수가 없어 물리 검증을 돌릴 수 없습니다',
      hint: ['목표를 만족하는 구성이 나오면 이 자리에서 검증을 시작할 수 있습니다.'],
    }
  }
  if (!started) {
    return {
      tag: 'QUEUED', label: '대기', action: true,
      text: `권장 ${recommendedCount}대 전후로 물리 검증을 시작할 수 있습니다`,
      hint: ['Isaac Sim 이 후보 대수마다 실제 로봇 물리로 재현해 동작을 확인합니다.'],
    }
  }
  return {
    tag: 'RUNNING', label: '검증 중', live: true,
    text: 'Isaac Sim에서 로봇 동작을 검증하고 있습니다',
    hint: ['실제 환경에 가까운 정밀한 물리 검증을 위해 다소 시간이 필요합니다.', '완료되면 이 화면에서 후보 대수별 결과를 바로 확인할 수 있습니다.'],
  }
}

/** 재생 중인 회차의 시점 버튼·영상 자리 — 대수 카드를 고르면 바뀐다. */
function VerifyPlayer({ estimateId, current }) {
  const [view, setView] = useState('top')
  const [refreshed, setRefreshed] = useState(null)
  const videoRef = useRef(null)
  const resumeAt = useRef(null)
  const lastRefresh = useRef(0)

  // (S15P21A106-279) 시점별로 재생 중인 URL 을 붙잡아 둔다. 스냅샷·verify.done 이 올 때마다 서명만 바뀐 URL 이
  // 오는데, 그대로 src 에 넣으면 영상이 처음으로 돌아가 다시 받는다. 객체(경로)가 바뀔 때만 갈아 끼운다.
  //   이전 렌더의 값에서 이어 가는 것이라 effect 가 아니라 렌더 중에 상태를 맞춘다(React 권장 패턴).
  const [pinned, setPinned] = useState(() => ({ top: current.video_url, fpv: current.video_fpv_url }))
  const topUrl = keepSigned(pinned.top, current.video_url)
  const fpvUrl = keepSigned(pinned.fpv, current.video_fpv_url)
  if (topUrl !== pinned.top || fpvUrl !== pinned.fpv) setPinned({ top: topUrl, fpv: fpvUrl })

  const views = useMemo(() => [
    { key: 'top', label: '상단 시점', url: topUrl },
    { key: 'fpv', label: 'AMR 추종 시점', url: fpvUrl },
  ].filter((v) => v.url), [topUrl, fpvUrl])
  const activeView = views.find((v) => v.key === view) ?? views[0]
  const videoUrl = refreshed && refreshed.replaces === activeView?.url ? refreshed.url : activeView?.url
  const playable = current.status === 'DONE' && Boolean(videoUrl)

  const refreshUrl = async () => {
    const now = Date.now()
    if (now - lastRefresh.current < REFRESH_COOLDOWN_MS) return
    lastRefresh.current = now
    const video = videoRef.current
    resumeAt.current = { time: video?.currentTime ?? 0, playing: Boolean(video && !video.paused) }
    try {
      const detail = await getEstimate(estimateId)
      const match = detail?.verifications?.find((v) => v.n_robots === current.n_robots)
      const fresh = view === 'fpv' ? match?.video_fpv_url : match?.video_url
      if (fresh) setRefreshed({ replaces: activeView?.url, url: fresh })
    } catch (e) {
      console.error(`[verify] estimateId=${estimateId} 영상 URL 재발급 실패`, e)
    }
  }

  const resume = () => {
    const video = videoRef.current
    const at = resumeAt.current
    if (!video || !at) return
    resumeAt.current = null
    video.currentTime = at.time
    if (at.playing) video.play().catch(() => {})
  }

  return (
    <>
      {playable && views.length > 1 && (
        <div className="verify-views" role="group" aria-label="카메라 시점">
          {views.map((v) => (
            <button
              key={v.key}
              type="button"
              className={`ghost sm${v.key === activeView.key ? ' on' : ''}`}
              aria-pressed={v.key === activeView.key}
              onClick={() => setView(v.key)}
            >
              {v.label}
            </button>
          ))}
        </div>
      )}
      {playable ? (
        <video
          key={`${current.n_robots}-${activeView.key}`}
          ref={videoRef}
          className="verify-video"
          src={videoUrl}
          controls
          onError={refreshUrl}
          onLoadedMetadata={resume}
        />
      ) : (
        <div className="verify-placeholder">
          {current.status === 'RUNNING' && <AmrRunning />}
          <p className="vp-note">
            {current.status === 'PENDING' && '검증 대기 중입니다.'}
            {current.status === 'RUNNING' && 'Isaac Sim에서 로봇 동작을 검증하고 있습니다.'}
            {current.status === 'FAILED' && `물리 검증에 실패했습니다${current.error ? ` — ${current.error}` : ''}`}
            {current.status === 'DONE' && '검증은 끝났지만 재생할 영상이 남지 않았습니다.'}
          </p>
        </div>
      )}
    </>
  )
}

export default function VerifyStep({ estimateId, ready, recommendedCount }) {
  const stream = useVerifyStream(ready ? estimateId : null)
  // 서버는 '요청 전'과 '검증 중'을 구분해 주지 않는다 — 눌렀다는 사실은 화면이 기억한다
  const [started, setStarted] = useState(false)
  const [selected, setSelected] = useState(null)

  const verifications = stream.verifications
  const effectiveRecommended = stream.recommendedCount ?? recommendedCount
  const current = verifications.find((v) => v.n_robots === selected) ?? verifications[0] ?? null
  const placeholder = idlePlaceholder({ estimateId, ready, recommendedCount, started })

  return (
    <section className="step section-dark" id="verify">
      <div className="eyebrow red">
        <span className="live-dot" />
        04 — 물리 검증
      </div>
      <h2>Confirm it physically.</h2>
      <p className="desc">권장 대수 전후를 Isaac Sim으로 재현해 실제로 문제없이 동작하는지 검증합니다.</p>

      {verifications.length === 0 ? (
        <div className="sim-board">
          <div className="board-head">
            <span>물리 검증 · Isaac Sim</span>
            <span className={`status ${placeholder.tag}`}>{placeholder.label}</span>
          </div>
          <div className="verify-placeholder">
            {placeholder.live && <AmrRunning />}
            <p className={placeholder.hint ? 'vp-text' : 'vp-note'}>{placeholder.text}</p>
            {placeholder.hint && (
              <p className="vp-hint">
                {placeholder.hint.map((line, i) => (
                  <span key={line}>{i > 0 && <br />}{line}</span>
                ))}
              </p>
            )}
            {placeholder.action && (
              <VerifyTrigger estimateId={estimateId} recommendedCount={recommendedCount} onStarted={() => setStarted(true)} />
            )}
          </div>
        </div>
      ) : (
        <>
          <div className="verify-grid" role="list">
            {verifications.map((v) => (
              <button
                key={v.n_robots}
                type="button"
                role="listitem"
                className={`verify-card${current?.n_robots === v.n_robots ? ' on' : ''}`}
                onClick={() => setSelected(v.n_robots)}
              >
                <div className="vc-head">
                  <span className="vc-count">
                    {v.n_robots}대{v.n_robots === effectiveRecommended ? <em> · 권장</em> : null}
                  </span>
                  <span className={`vc-verdict ${v.verdict ?? 'NA'}`}>{VERDICT_LABEL[v.verdict] ?? '해당없음'}</span>
                </div>
                <div className="vc-status mono dim">{STATUS_LABEL[v.status] ?? v.status}</div>
                {v.error && <div className="vc-error">{v.error}</div>}
              </button>
            ))}
          </div>

          <p className="verify-limit mono dim">
            {stream.physicsLimit != null
              ? `물리 상한 ${stream.physicsLimit}대 — 후보 중 물리 판정이 통과인 가장 큰 대수`
              : '물리 상한 없음 — 후보 중 통과한 대수가 아직 없습니다'}
          </p>

          {current && (
            <div className="sim-board">
              <div className="board-head">
                <span>{current.n_robots}대 물리 검증</span>
                <span className={`status ${current.status}`}>{STATUS_LABEL[current.status] ?? current.status}</span>
              </div>
              {/* 대수를 바꾸면 컴포넌트를 새로 만든다 — 시점·재생 위치 같은 내부 상태가 다른 회차로 새지 않게 */}
              <VerifyPlayer key={current.n_robots} estimateId={estimateId} current={current} />
              {metricsFor(current).length > 0 && (
                <dl className="verify-metrics">
                  {metricsFor(current).map(([label, value]) => (
                    <div key={label} className="vm-row">
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}

          {verifications.length > 1 && (
            <div className="verify-compare-wrap">
              <table className="verify-compare">
                <thead>
                  <tr>
                    <th>대수</th><th>판정</th><th>창 동작 비율</th><th>지연(중앙값)</th><th>접촉</th><th>최소 간격</th>
                  </tr>
                </thead>
                <tbody>
                  {verifications.map((v) => (
                    <tr key={v.n_robots} className={v.n_robots === current?.n_robots ? 'on' : ''}>
                      <td>{v.n_robots}대{v.n_robots === effectiveRecommended ? ' (권장)' : ''}</td>
                      <td>{VERDICT_LABEL[v.verdict] ?? '해당없음'}</td>
                      <td>{pct(v.physics?.window_actions?.ratio)}</td>
                      <td>{secs(v.physics?.lag?.p50_s)}</td>
                      <td>{v.physics ? contactsOf(v.physics) : '—'}</td>
                      <td>{meters(v.physics?.robot_min_gap_m)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}
