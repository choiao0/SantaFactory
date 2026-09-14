import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header.jsx'
import { ESTIMATE_PAGE_SIZE, getMyEstimates } from '../api/estimates.js'
import { ESTIMATE_STATUS_LABEL } from '../data/replay.js'
import { formatDateTime } from '../utils/format.js'

/**
 * 내가 요청한 견적 목록 (S15P21A106-205).
 *
 * 이 화면이 없으면 견적을 다시 볼 방법이 없었다 — 진행 중인 견적 번호를 sessionStorage 에만
 * 두고 있어서 탭을 닫으면 주행 리플레이도 결과도 도달할 길이 사라졌다. 데이터는 DB 에
 * 남아 있고 API 도 있었는데 들어가는 문이 없던 셈이다.
 */

/** 카드에 들어갈 짧은 사유. 긴 설명은 QuoteStep 의 REASON_TEXT 가 담당한다 — 값은 백엔드 ReasonCode 그대로다. */
const REASON_LABEL = {
  BUDGET_EXCEEDED: '예산 초과',
  THROUGHPUT_SHORT: '처리율 미달',
  UTILIZATION_SHORT: '가동률 미달',
  ALL_FAILED: '전부 실패',
  LOAD_TOO_LOW: '부하 부족',
}

export default function MyEstimatesPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(0)
  const [result, setResult] = useState(null)
  const [loadedPage, setLoadedPage] = useState(null)
  const [error, setError] = useState(null)

  // 요청한 페이지와 받아둔 페이지가 다르면 아직 오는 중이다
  const loading = loadedPage !== page

  useEffect(() => {
    let cancelled = false
    getMyEstimates(page)
      .then((r) => { if (!cancelled) setResult(r) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoadedPage(page) })
    // 빠르게 두 번 넘기면 먼저 보낸 응답이 나중에 올 수 있다
    return () => { cancelled = true }
  }, [page])

  /** 견적 화면은 번호를 sessionStorage 에서 읽는다 — 그 약속을 그대로 쓴다 (관리자 화면과 같은 방식). */
  const open = (estimateId) => {
    sessionStorage.setItem('estimateId', String(estimateId))
    navigate('/estimate')
  }

  const items = result?.content ?? []
  const total = result?.totalElements ?? 0
  const firstRow = total === 0 ? 0 : page * ESTIMATE_PAGE_SIZE + 1
  const lastRow = page * ESTIMATE_PAGE_SIZE + items.length

  return (
    <>
      <Header sections={false} />
      <main>
        <section className="step section-dark">
          <div className="eyebrow red">
            <span className="live-dot" />
            <span>MY ESTIMATES</span>
          </div>
          <h2>지난 견적.</h2>
          <p className="desc">요청했던 견적을 다시 엽니다. 대수별 결과와 주행 리플레이가 그대로 남아 있습니다.</p>

          {error && <p className="form-error">목록을 불러오지 못했습니다. {error}</p>}
          {!error && loading && <p className="mono dim">불러오는 중…</p>}

          {!error && !loading && total === 0 && (
            <div className="runs-empty">
              아직 요청한 견적이 없습니다.{' '}
              <button type="button" className="ghost sm" onClick={() => navigate('/estimate')}>견적 요청하러 가기</button>
            </div>
          )}

          {!error && !loading && total > 0 && (
            <>
              <h3 className="admin-subhead">
                견적
                <span className="admin-count">전체 {total}건 중 {firstRow}–{lastRow}</span>
              </h3>
              <div className="admin-grid">
                {items.map((e) => (
                  <button
                    key={e.estimate_id}
                    type="button"
                    className="spec selectable admin-card"
                    onClick={() => open(e.estimate_id)}
                  >
                    <span className={`status ${e.status}`}>{ESTIMATE_STATUS_LABEL[e.status] ?? e.status}</span>
                    <h4>#{e.estimate_id}</h4>
                    <div className="sub">{e.amr_model ?? '—'}</div>
                    <dl>
                      <dt>요청</dt>
                      <dd className="admin-plain">{formatDateTime(e.created_at)}</dd>
                      <dt>{e.recommended_count != null ? '권장 대수' : '판정'}</dt>
                      <dd>
                        {e.recommended_count != null
                          ? `${e.recommended_count}대`
                          : (
                            // 사유가 없으면 아직 안 끝난 것이다. 모르는 코드는 코드 그대로 — 조용히 삼키면
                            // 백엔드가 사유를 추가했을 때 화면만 거짓말을 한다
                            <span className="admin-plain">
                              {e.reason_code ? (REASON_LABEL[e.reason_code] ?? e.reason_code) : '진행 중'}
                            </span>
                          )}
                      </dd>
                    </dl>
                  </button>
                ))}
              </div>

              {result.totalPages > 1 && (
                <div className="admin-pager">
                  <button type="button" className="ghost sm" disabled={result.first || loading}
                          onClick={() => setPage((p) => p - 1)}>← 이전</button>
                  <span className="mono dim">{page + 1} / {result.totalPages}</span>
                  <button type="button" className="ghost sm" disabled={result.last || loading}
                          onClick={() => setPage((p) => p + 1)}>다음 →</button>
                </div>
              )}
            </>
          )}
        </section>
      </main>
    </>
  )
}
