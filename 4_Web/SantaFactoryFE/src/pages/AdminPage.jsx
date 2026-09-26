import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ESTIMATE_PAGE_SIZE, getAllEstimates, getMembers } from '../api/admin.js'
import { deleteEstimate } from '../api/estimates.js'
import { useAuth } from '../auth/authContext.js'
import ConfirmDialog from '../components/ConfirmDialog.jsx'

const STATUS_LABEL = {
  QUEUED: '대기 중',
  RUNNING: '진행 중',
  DONE: '완료',
  PARTIAL: '일부 완료',
  CANCELLED: '취소됨',
}

/** 01012345678 → 010-1234-5678. 서버는 하이픈을 떼고 저장한다. */
function formatPhone(phone) {
  if (!phone) return '—'
  const digits = phone.replace(/[^0-9]/g, '')
  if (digits.length === 11) return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`
  if (digits.length === 10) return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`
  return phone
}

/**
 * 접수 시각. "오늘 뭐가 들어왔나"를 보는 화면이라 연도보다 월·일·시각이 중요하다.
 *
 * 서버가 주는 값은 시간대가 없는 LocalDateTime 이다. Date 가 이걸 브라우저 지역시로 읽는데,
 * 서버와 보는 사람이 같은 시간대에 있는 한 그게 맞는 해석이다.
 */
function formatDateTime(value) {
  if (!value) return '—'
  const at = new Date(value)
  if (Number.isNaN(at.getTime())) return value
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(at.getMonth() + 1)}.${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`
}

export default function AdminPage() {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const [members, setMembers] = useState([])
  const [estimatePage, setEstimatePage] = useState(null)
  const [page, setPage] = useState(0)
  const [loadedPage, setLoadedPage] = useState(null)
  const [error, setError] = useState(null)
  /** 지우려는 견적. 되돌릴 수 없는 일이라 카드에서 바로 지우지 않고 한 번 더 묻는다 */
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [reload, setReload] = useState(0)
  /** 회원 카드를 눌러 그 회원 것만 볼 때. null 이면 전체 */
  const [member, setMember] = useState(null)
  const [order, setOrder] = useState('desc')

  // 요청한 페이지와 받아둔 페이지가 다르면 아직 오는 중이다. 별도 상태를 두지 않고 파생한다
  const loading = loadedPage !== page

  useEffect(() => {
    getMembers().then(setMembers).catch((e) => {
      console.error('[admin] 회원 목록 조회 실패', e)
      setError('회원 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
    })
  }, [])

  useEffect(() => {
    let cancelled = false
    getAllEstimates(page, { memberId: member?.member_id ?? null, order })
      .then((result) => { if (!cancelled) setEstimatePage(result) })
      .catch((e) => {
        console.error(`[admin] page=${page} 견적 목록 조회 실패`, e)
        if (!cancelled) setError('견적 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
      })
      .finally(() => { if (!cancelled) setLoadedPage(page) })
    // 빠르게 두 번 넘기면 먼저 보낸 요청의 응답이 나중에 도착할 수 있다.
    // 그대로 두면 화면이 방금 지나온 페이지로 되돌아간다
    return () => { cancelled = true }
  }, [page, reload, member, order])

  // 견적 결론 화면을 그대로 재사용 — 내 견적 목록과 같은 길이다 (S15P21A106-274).
  const openEstimate = (estimateId) => {
    navigate(`/estimate/${estimateId}/quote`)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    try {
      await deleteEstimate(pendingDelete.estimate_id)
      // 마지막 한 건을 지워 페이지가 비면 앞 페이지로 물러난다
      setPage((p) => (estimates.length === 1 && p > 0 ? p - 1 : p))
      setReload((n) => n + 1)
      setPendingDelete(null)
    } catch (e) {
      console.error(`[admin] estimateId=${pendingDelete.estimate_id} 삭제 실패`, e)
      setError('견적을 삭제하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      setPendingDelete(null)
    } finally {
      setDeleting(false)
    }
  }

  const handleLogout = async () => {
    await logout()
    navigate('/', { replace: true })
  }

  const estimates = estimatePage?.content ?? []
  const total = estimatePage?.totalElements ?? 0
  const firstRow = total === 0 ? 0 : page * ESTIMATE_PAGE_SIZE + 1
  const lastRow = page * ESTIMATE_PAGE_SIZE + estimates.length

  return (
    <>
      <header className="header">
        <a className="brand" href="/estimate" onClick={(e) => { e.preventDefault(); navigate('/estimate') }}>
          <img className="brand-mark" src="/santafactory-logo.png" alt="Santa Factory" width={30} height={30} />
          <span>SANTA FACTORY</span>
          <small>관리자</small>
        </a>
        <button type="button" className="ghost sm" onClick={handleLogout}>로그아웃</button>
      </header>
      <main>
        <section className="step paper">
          <div className="eyebrow red">
            <span className="live-dot" />
            <span>전체 견적</span>
          </div>
          <h2>회원별 견적 현황</h2>
          <p className="desc">회원별 등록 창고와 견적을 확인합니다. 견적 카드를 누르면 해당 견적 화면으로 이동합니다.</p>

          {error && <p className="form-error">{error}</p>}

          {!error && (
            <>
              <h3 className="admin-subhead">회원 {members.length}명</h3>
              <div className="admin-grid">
                {members.map((m) => (
                  // 누르면 그 회원의 견적만 — 다시 누르면 전체로 돌아온다
                  <button
                    key={m.member_id}
                    type="button"
                    className={`spec selectable admin-card${member?.member_id === m.member_id ? ' on' : ''}`}
                    aria-pressed={member?.member_id === m.member_id}
                    onClick={() => {
                      setPage(0)
                      setMember((cur) => (cur?.member_id === m.member_id ? null : m))
                    }}
                  >
                    {m.role === 'ADMIN' && <span className="admin-badge">관리자</span>}
                    <h4>{m.company}</h4>
                    <div className="sub">{m.name} · {formatPhone(m.phone)}</div>
                    <dl>
                      <dt>등록 창고</dt>
                      <dd>{m.warehouse_count}개</dd>
                      <dt>요청 견적</dt>
                      <dd>{m.estimate_count}건</dd>
                    </dl>
                  </button>
                ))}
              </div>

              <h3 className="admin-subhead">
                {member ? `${member.company} 견적` : '견적'}
                {/* 서버가 페이지 단위로 자르므로 총 건수를 같이 보여준다 — 안 보여주면
                    다음 페이지에 남은 견적이 아예 없는 것처럼 읽힌다 */}
                <span className="admin-count">
                  {total === 0 ? '0건' : `전체 ${total}건 중 ${firstRow}–${lastRow}`}
                </span>
                {member && (
                  <button type="button" className="ghost sm"
                          onClick={() => { setPage(0); setMember(null) }}>전체 보기</button>
                )}
                <div className="sortpick" role="group" aria-label="정렬">
                  {[['desc', '최신순'], ['asc', '오래된순']].map(([key, text]) => (
                    <button key={key} type="button" className={order === key ? 'on' : ''}
                            aria-pressed={order === key}
                            onClick={() => { setPage(0); setOrder(key) }}>
                      {text}
                    </button>
                  ))}
                </div>
              </h3>

              {loading && <p className="mono dim">불러오는 중…</p>}
              {!loading && total === 0 && <p className="mono dim">아직 요청된 견적이 없습니다.</p>}

              <div className="admin-grid">
                {estimates.map((item) => (
                  // 카드가 버튼이라 삭제 버튼을 안에 둘 수 없다 — 나란히 놓고 카드 위에 겹친다
                  <div className="card-slot" key={item.estimate_id}>
                  <button
                    type="button"
                    className="spec selectable admin-card"
                    onClick={() => openEstimate(item.estimate_id)}
                  >
                    <span className={`status ${item.status}`}>{STATUS_LABEL[item.status] ?? item.status}</span>
                    <h4>{item.company ?? '—'}</h4>
                    <div className="sub">{item.member_name ?? '담당자 없음'} · {item.warehouse_name ?? '창고 없음'}</div>
                    <dl>
                      <dt>접수</dt>
                      <dd className="admin-plain">{formatDateTime(item.created_at)}</dd>
                      <dt>견적 번호</dt>
                      <dd>#{item.estimate_id}</dd>
                      <dt>모델</dt>
                      <dd>{item.amr_model ?? '—'}</dd>
                      <dt>권장 대수</dt>
                      <dd>{item.recommended_count != null ? `${item.recommended_count}대` : '—'}</dd>
                      <dt>연락처</dt>
                      <dd className="admin-plain">{formatPhone(item.phone)}</dd>
                    </dl>
                  </button>
                  <button
                    type="button"
                    className="card-del"
                    aria-label={`견적 #${item.estimate_id} 삭제`}
                    title="삭제"
                    onClick={() => setPendingDelete(item)}
                  >
                    ×
                  </button>
                  </div>
                ))}
              </div>

              {estimatePage && estimatePage.totalPages > 1 && (
                <div className="admin-pager">
                  <button
                    type="button"
                    className="ghost sm"
                    disabled={estimatePage.first || loading}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    ← 이전
                  </button>
                  <span className="mono dim">{page + 1} / {estimatePage.totalPages}</span>
                  <button
                    type="button"
                    className="ghost sm"
                    disabled={estimatePage.last || loading}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    다음 →
                  </button>
                </div>
              )}
            </>
          )}
        </section>

        {pendingDelete && (
          <ConfirmDialog
            title={`견적 #${pendingDelete.estimate_id} 삭제`}
            confirmLabel="삭제"
            busy={deleting}
            onCancel={() => setPendingDelete(null)}
            onConfirm={confirmDelete}
          >
            {pendingDelete.company ?? '회원'}의 견적입니다. 대수별 시뮬레이션 결과, 주행 재생, 3D 주행 검증
            결과가 함께 삭제됩니다.<b> 삭제한 견적은 복구할 수 없습니다.</b>
          </ConfirmDialog>
        )}
      </main>
    </>
  )
}
