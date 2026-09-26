import { Link } from 'react-router-dom'

/**
 * 지금 돌고 있는 견적이 있으면 맨 위에서 이어가게 한다 (S15P21A106-274).
 *
 * 소개보다 위에 둔다. 이건 읽을거리가 아니라 알림이라, 아래로 내려가면 있을 이유가 없다.
 */
export default function ResumeBanner({ estimate }) {
  if (!estimate) return null

  return (
    <div className="resume">
      <span className="live-dot pulse" />
      <span>
        견적 <b>#{estimate.estimate_id}</b> 계산이 진행 중입니다
      </span>
      <Link className="ghost sm" to={`/estimate/${estimate.estimate_id}/runs`}>
        진행 상황 보기 →
      </Link>
    </div>
  )
}
