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

const STATUS_LABEL = { PENDING: '대기', RUNNING: '검증 중', DONE: '완료', FAILED: '미완료' }
const VERDICT_LABEL = { PASS: '적합', WARN: '주의', FAIL: '부적합', NA: '판정 불가' }

const pct = (ratio) => (ratio == null ? '—' : `${Math.round(ratio * 100)}%`)
const secs = (v) => (v == null ? '—' : `${v.toFixed(1)}초`)
const meters = (v) => (v == null ? '—' : `${v.toFixed(2)} m`)
const times = (v) => (v == null ? '—' : `${v}회`)
const tasks = (v) => (v == null ? '—' : `${v}건`)
const contactsOf = (p) => (p?.robot_contacts ?? 0) + (p?.rack_contacts ?? 0)

/** 카드 한 장의 지표 목록. physics 가 없으면(N/A) 빈 배열. */
function metricsFor(run) {
  const p = run.physics
  if (!p) return []
  return [
    ['계획 대비 수행률', pct(p.window_actions?.ratio)],
    ['작업 지연(보통)', secs(p.lag?.p50_s)],
    ['작업 지연(상위 10%)', secs(p.lag?.p90_s)],
    ['로봇 충돌', times(p.robot_contacts)],
    ['랙 충돌', times(p.rack_contacts)],
    ['로봇 간 최소 거리', meters(p.robot_min_gap_m)],
    ['혼잡 대기 비율', pct(p.blocked?.ratio)],
    ['완료 작업(시뮬레이션 기준)', tasks(run.slice?.tasks_done ?? p.des_window?.tasks_done)],
  ]
}

/** 아직 후보가 하나도 없을 때(검증 전) 보여줄 자리 — 기존 단일 검증 화면과 같은 문구. */
function idlePlaceholder({ estimateId, ready, recommendedCount, started }) {
  if (estimateId == null) {
    return { tag: 'QUEUED', label: '대기', text: '견적을 요청하면 3D 주행 검증 결과가 여기에 표시됩니다.' }
  }
  if (!ready) {
    return { tag: 'RUNNING', label: '계산 중', live: true, text: '대수별 시뮬레이션이 끝나면 권장 대수와 앞뒤 대수의 3D 주행 검증을 시작할 수 있습니다.' }
  }
  if (recommendedCount == null) {
    return {
      tag: 'QUEUED', label: '대기',
      text: '권장 대수가 없어 3D 주행 검증을 진행할 수 없습니다.',
      hint: ['목표나 예산을 조정해 견적을 다시 요청해 주세요.'],
    }
  }
  if (!started) {
    return {
      tag: 'QUEUED', label: '대기', action: true,
      text: `권장 ${recommendedCount}대와 앞뒤 대수의 3D 주행 검증을 시작할 수 있습니다.`,
      hint: ['주문 집중 10분을 대수별로 3D 환경에서 재현해 로봇이 막힘없이 움직이는지 확인합니다.'],
    }
  }
  return {
    tag: 'RUNNING', label: '검증 중', live: true,
    text: '3D 주행 검증을 진행하고 있습니다.',
    hint: ['검증에는 다소 시간이 걸립니다.', '완료되면 이 화면에서 대수별 결과를 바로 확인할 수 있습니다.'],
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
    { key: 'top', label: '전체 보기', url: topUrl },
    { key: 'fpv', label: '로봇 따라가기', url: fpvUrl },
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
            {current.status === 'RUNNING' && '3D 주행 검증을 진행하고 있습니다.'}
            {current.status === 'FAILED' && '3D 주행 검증을 완료하지 못했습니다. 다시 요청해 주세요.'}
            {current.status === 'DONE' && '검증은 완료되었지만 재생할 영상이 없습니다.'}
          </p>
        </div>
      )}
    </>
  )
}

export default function VerifyStep({ estimateId, ready, recommendedCount }) {
  // 다시 검증을 요청하면 올린다 — 닫힌 스트림을 새로 열어 새 회차를 받는다
  const [epoch, setEpoch] = useState(0)
  const stream = useVerifyStream(ready ? estimateId : null, epoch)
  // 서버는 '요청 전'과 '검증 중'을 구분해 주지 않는다 — 눌렀다는 사실은 화면이 기억한다
  const [started, setStarted] = useState(false)
  const [selected, setSelected] = useState(null)

  const verifications = stream.verifications
  const effectiveRecommended = stream.recommendedCount ?? recommendedCount
  const current = verifications.find((v) => v.n_robots === selected) ?? verifications[0] ?? null
  const placeholder = idlePlaceholder({ estimateId, ready, recommendedCount, started })
  // (S15P21A106-279) 실패한 대수는 화면에서 다시 검증할 수 있어야 한다. 서버가 진행 중인 회차가 있으면 새 요청을
  // 거부하므로 대수마다 따로가 아니라 실패한 대수를 한 번에 보낸다.
  const failedCounts = verifications.filter((v) => v.status === 'FAILED').map((v) => v.n_robots)
  const anyPending = verifications.some((v) => v.status === 'PENDING' || v.status === 'RUNNING')

  return (
    <section className="step section-dark" id="verify">
      <div className="eyebrow red">
        <span className="live-dot" />
        04 · 3D 주행 검증
      </div>
      <h2>Confirm it physically.</h2>
      <p className="desc">권장 대수와 앞뒤 대수로 주문 집중 10분을 3D로 재현해 로봇이 문제없이 움직이는지 확인합니다.</p>

      {verifications.length === 0 ? (
        <div className="sim-board">
          <div className="board-head">
            <span>3D 주행 검증</span>
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
                  <span className={`vc-verdict ${v.verdict ?? 'NA'}`}>{VERDICT_LABEL[v.verdict] ?? '판정 불가'}</span>
                </div>
                <div className="vc-status mono dim">{STATUS_LABEL[v.status] ?? v.status}</div>
                {v.error && <div className="vc-error">검증을 완료하지 못했습니다.</div>}
              </button>
            ))}
          </div>

          <p className="verify-limit mono dim">
            {stream.physicsLimit != null
              ? `${stream.physicsLimit}대까지 3D 주행 검증을 통과했습니다.`
              : '아직 3D 주행 검증을 통과한 대수가 없습니다.'}
          </p>

          {failedCounts.length > 0 && !anyPending && (
            <div className="verify-retry">
              <VerifyTrigger
                key={failedCounts.join(',')}
                estimateId={estimateId}
                recommendedCount={effectiveRecommended}
                counts={failedCounts}
                idleLabel={`미완료 ${failedCounts.join('·')}대 다시 검증`}
                onStarted={() => setEpoch((e) => e + 1)}
              />
            </div>
          )}

          {current && (
            <div className="sim-board">
              <div className="board-head">
                <span>{current.n_robots}대 3D 주행 검증</span>
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
                    <th>대수</th><th>판정</th><th>계획 대비 수행률</th><th>작업 지연(보통)</th><th>충돌</th><th>로봇 간 최소 거리</th>
                  </tr>
                </thead>
                <tbody>
                  {verifications.map((v) => (
                    <tr key={v.n_robots} className={v.n_robots === current?.n_robots ? 'on' : ''}>
                      <td>{v.n_robots}대{v.n_robots === effectiveRecommended ? ' (권장)' : ''}</td>
                      <td>{VERDICT_LABEL[v.verdict] ?? '판정 불가'}</td>
                      <td>{pct(v.physics?.window_actions?.ratio)}</td>
                      <td>{secs(v.physics?.lag?.p50_s)}</td>
                      <td>{v.physics ? times(contactsOf(v.physics)) : '—'}</td>
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
