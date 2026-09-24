import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import Header from '../components/Header.jsx'
import { ESTIMATE_PAGE_SIZE, deleteEstimate, getMyEstimates } from '../api/estimates.js'
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
  LEAD_TIME_LONG: '리드타임 초과',
  ALL_FAILED: '전부 실패',
  LOAD_TOO_LOW: '부하 부족',   // 더 이상 만들어지지 않는다 — 옛 견적용
}

export default function MyEstimatesPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(0)
  const [result, setResult] = useState(null)
  const [loadedPage, setLoadedPage] = useState(null)
  const [error, setError] = useState(null)
  /** 삭제하려는 견적. 되돌릴 수 없는 일이라 카드에서 바로 지우지 않고 한 번 더 묻는다 */
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [reload, setReload] = useState(0)

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
  }, [page, reload])

  /** 견적 화면은 번호를 sessionStorage 에서 읽는다 — 그 약속을 그대로 쓴다 (관리자 화면과 같은 방식). */
  const open = (estimateId) => {
    sessionStorage.setItem('estimateId', String(estimateId))
    navigate('/estimate')
  }

  const confirmDelete = async () => {
    setDeleting(true)
    try {
      await deleteEstimate(pendingDelete.estimate_id)
      // 마지막 한 건을 지워 페이지가 비면 앞 페이지로 물러난다
      setPage((p) => (items.length === 1 && p > 0 ? p - 1 : p))
      setReload((n) => n + 1)
      setPendingDelete(null)
    } catch (e) {
      setError(`삭제하지 못했습니다. ${e.message}`)
      setPendingDelete(null)
    } finally {
      setDeleting(false)
    }
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
            <span>내 견적</span>
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
                  // 카드가 버튼이라 삭제 버튼을 안에 둘 수 없다 — 나란히 놓고 카드 위에 겹친다
                  <div className="card-slot" key={e.estimate_id}>
                  <button
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
                  <button
                    type="button"
                    className="card-del"
                    aria-label={`견적 #${e.estimate_id} 삭제`}
                    title="삭제"
                    onClick={() => setPendingDelete(e)}
                  >
                    ×
                  </button>
                  </div>
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

        {pendingDelete && (
          <ConfirmDialog
            title={`견적 #${pendingDelete.estimate_id}을 삭제할까요?`}
            confirmLabel="삭제"
            busy={deleting}
            onCancel={() => setPendingDelete(null)}
            onConfirm={confirmDelete}
          >
            대수별 결과와 주행 리플레이, 물리 검증 결과까지 함께 지워집니다.
            <b> 삭제한 견적은 되돌릴 수 없습니다.</b>
          </ConfirmDialog>
        )}
      </main>
    </>
  )
}
