import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ESTIMATE_PAGE_SIZE, getAllEstimates, getMembers } from '../api/admin.js'
import { useAuth } from '../auth/authContext.js'

const STATUS_LABEL = {
  QUEUED: '대기 중',
  RUNNING: '진행 중',
  DONE: '완료',
  PARTIAL: '일부 실패',
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

  // 요청한 페이지와 받아둔 페이지가 다르면 아직 오는 중이다. 별도 상태를 두지 않고 파생한다
  const loading = loadedPage !== page

  useEffect(() => {
    getMembers().then(setMembers).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    let cancelled = false
    getAllEstimates(page)
      .then((result) => { if (!cancelled) setEstimatePage(result) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoadedPage(page) })
    // 빠르게 두 번 넘기면 먼저 보낸 요청의 응답이 나중에 도착할 수 있다.
    // 그대로 두면 화면이 방금 지나온 페이지로 되돌아간다
    return () => { cancelled = true }
  }, [page])

  // 기존 견적 화면(estimateId 기반 로딩)을 그대로 재사용 — App.jsx 와 같은 패턴.
  const openEstimate = (estimateId) => {
    sessionStorage.setItem('estimateId', String(estimateId))
    navigate('/estimate')
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
          <small>ADMIN</small>
        </a>
        <button type="button" className="ghost sm" onClick={handleLogout}>로그아웃</button>
      </header>
      <main>
        <section className="step paper">
          <div className="eyebrow red">
            <span className="live-dot" />
            <span>ALL ESTIMATES</span>
          </div>
          <h2>회원별 견적 현황.</h2>
          <p className="desc">회원마다 등록한 창고와 최근 견적을 한눈에 봅니다. 카드를 누르면 그 견적 화면으로 이동합니다.</p>

          {error && <p className="form-error">현황을 불러오지 못했습니다. {error}</p>}

          {!error && (
            <>
              <h3 className="admin-subhead">회원 {members.length}명</h3>
              <div className="admin-grid">
                {members.map((m) => (
                  <div key={m.member_id} className="spec admin-card">
                    {m.role === 'ADMIN' && <span className="admin-badge">관리자</span>}
                    <h4>{m.company}</h4>
                    <div className="sub">{m.name} · {formatPhone(m.phone)}</div>
                    <dl>
                      <dt>등록 창고</dt>
                      <dd>{m.warehouse_count}개</dd>
                      <dt>요청 견적</dt>
                      <dd>{m.estimate_count}건</dd>
                    </dl>
                  </div>
                ))}
              </div>

              <h3 className="admin-subhead">
                견적
                {/* 서버가 페이지 단위로 자르므로 총 건수를 같이 보여준다 — 안 보여주면
                    다음 페이지에 남은 견적이 아예 없는 것처럼 읽힌다 */}
                <span className="admin-count">
                  {total === 0 ? '0건' : `전체 ${total}건 중 ${firstRow}–${lastRow}`}
                </span>
              </h3>

              {loading && <p className="mono dim">불러오는 중…</p>}
              {!loading && total === 0 && <p className="mono dim">아직 요청된 견적이 없습니다.</p>}

              <div className="admin-grid">
                {estimates.map((item) => (
                  <button
                    key={item.estimate_id}
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
      </main>
    </>
  )
}
