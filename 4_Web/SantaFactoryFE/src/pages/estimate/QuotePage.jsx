import { useOutletContext } from 'react-router-dom'
import QuoteStep from '../../components/QuoteStep.jsx'
import RunsStep from '../../components/RunsStep.jsx'
import StepFoot from '../../components/StepFoot.jsx'
import StepNav from '../../components/StepNav.jsx'
import VerifyStep from '../../components/VerifyStep.jsx'

/**
 * 05 — 견적 (S15P21A106-274). 지난 견적이 열리는 곳이기도 하다.
 *
 * <p>목록·관리자 화면에서 지난 견적을 누르면 곧장 여기로 온다. 결론 한 장으로 여는 것이
 * 요구지만, 그렇다고 주행 재생과 검증 영상까지 사라지면 안 된다 — 그래서 03·04 페이지를
 * <b>통째로</b> 접어 둔다. 잘라 붙이지 않았으므로 배속·시크·출고 패널·시점 전환·서명 URL
 * 재발급까지 그 안에서 쓰던 것이 전부 그대로 돈다.
 *
 * <p>접힌 채로도 DOM 에 둔다. 열 때 붙이면 그 안의 등장 연출이 이미 지나간 뒤라 펴도 빈 칸이 된다.
 */
export default function QuotePage() {
  const { estimateId, estimate, verdict, connected, error } = useOutletContext()

  return (
    <>
      <StepNav current="quote" estimateId={estimateId} />
      <QuoteStep estimateId={estimateId} estimate={estimate} verdict={verdict} />

      <div className="folds">
        <details className="fold">
          <summary>주행 재생 보기</summary>
          <RunsStep estimateId={estimateId} estimate={estimate} connected={connected} error={error} />
        </details>
        <details className="fold">
          <summary>물리 검증 영상 보기</summary>
          <VerifyStep
            estimateId={estimateId}
            ready={Boolean(verdict)}
            recommendedCount={verdict?.recommended_count}
          />
        </details>
      </div>

      <StepFoot back={`/estimate/${estimateId}/verify`} />
    </>
  )
}
