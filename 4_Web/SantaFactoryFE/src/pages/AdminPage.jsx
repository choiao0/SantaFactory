import { useNavigate } from 'react-router-dom'
import { MOCK_ADMIN_ESTIMATES } from '../data/adminMock.js'

const STATUS_LABEL = {
  RUNNING: '진행 중',
  DONE: '완료',
  PARTIAL: '일부 실패',
  CANCELLED: '취소됨',
}

export default function AdminPage() {
  const navigate = useNavigate()

  // 기존 견적 화면(estimateId 기반 로딩)을 그대로 재사용 — App.jsx 와 같은 패턴.
  const openEstimate = (estimateId) => {
    sessionStorage.setItem('estimateId', String(estimateId))
    navigate('/estimate')
  }

  return (
    <>
      <header className="header">
        <a className="brand" href="/admin">
          <img className="brand-mark" src="/santafactory-logo.png" alt="Santa Factory" width={30} height={30} />
          SANTA FACTORY
          <small>ADMIN</small>
        </a>
        <button type="button" className="ghost sm" onClick={() => navigate('/')}>로그아웃</button>
      </header>
      <main>
        <section className="step paper">
          <div className="eyebrow red">
            <span className="live-dot" />
            ALL ESTIMATES
          </div>
          <h2>회원별 견적 현황.</h2>
          <p className="desc">회원마다 등록한 창고와 최근 견적을 한눈에 봅니다. 카드를 누르면 그 견적 화면으로 이동합니다.</p>

          <div className="admin-grid">
            {MOCK_ADMIN_ESTIMATES.map((item) => (
              <button
                key={item.id}
                type="button"
                className="spec selectable admin-card"
                onClick={() => openEstimate(item.estimateId)}
              >
                <span className={`status ${item.status}`}>{STATUS_LABEL[item.status] ?? item.status}</span>
                <h4>{item.userName}</h4>
                <div className="sub">{item.warehouseName}</div>
                <dl>
                  <dt>견적 번호</dt>
                  <dd>#{item.estimateId}</dd>
                  <dt>권장 대수</dt>
                  <dd>{item.recommendedCount != null ? `${item.recommendedCount}대` : '—'}</dd>
                </dl>
              </button>
            ))}
          </div>
        </section>
      </main>
    </>
  )
}
