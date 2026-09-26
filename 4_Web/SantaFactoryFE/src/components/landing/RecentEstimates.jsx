import { Link, useNavigate } from 'react-router-dom'
import { ESTIMATE_STATUS_LABEL } from '../../data/replay.js'
import { formatDateTime } from '../../utils/format.js'

/** 랜딩에 올릴 견적 수. 전부는 내 견적 화면이 보여준다. */
const SHOWN = 3

/** 최근 견적 몇 건 — 누르면 결론 한 장으로 간다 (S15P21A106-274). */
export default function RecentEstimates({ recent }) {
  const navigate = useNavigate()
  const items = recent.items.slice(0, SHOWN)

  return (
    <>
      <h3 className="admin-subhead">
        최근 견적
        <span className="admin-count">전체 {recent.total}건</span>
        <Link className="ghost sm" to="/estimates">전체 보기 →</Link>
      </h3>

      {recent.error && <p className="form-error">견적 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>}

      <div className="admin-grid">
        {items.map((e) => (
          <button
            type="button"
            key={e.estimate_id}
            className="spec selectable admin-card"
            onClick={() => navigate(`/estimate/${e.estimate_id}/quote`)}
          >
            <span className={`status ${e.status}`}>{ESTIMATE_STATUS_LABEL[e.status] ?? e.status}</span>
            <h4>#{e.estimate_id}</h4>
            <div className="sub">{e.amr_model ?? '—'}</div>
            <dl>
              <dt>요청</dt>
              <dd className="admin-plain">{formatDateTime(e.created_at)}</dd>
              <dt>권장 대수</dt>
              <dd>
                {e.recommended_count != null
                  ? <>{e.recommended_count}<span>대</span></>
                  : <span className="admin-plain">{e.reason_code ? '조건 미달' : '계산 중'}</span>}
              </dd>
            </dl>
          </button>
        ))}
      </div>
    </>
  )
}
