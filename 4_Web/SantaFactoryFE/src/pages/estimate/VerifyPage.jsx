import { useOutletContext } from 'react-router-dom'
import StepFoot from '../../components/StepFoot.jsx'
import StepNav from '../../components/StepNav.jsx'
import VerifyStep from '../../components/VerifyStep.jsx'

/** 04 — 물리 검증 (S15P21A106-274). 시작 버튼은 섹션 안에 있다 — 사람이 정해서 누른다. */
export default function VerifyPage() {
  const { estimateId, verdict } = useOutletContext()

  return (
    <>
      <StepNav current="verify" estimateId={estimateId} />
      <VerifyStep
        estimateId={estimateId}
        ready={Boolean(verdict)}
        recommendedCount={verdict?.recommended_count}
      />
      <StepFoot back={`/estimate/${estimateId}/runs`} next={`/estimate/${estimateId}/quote`} />
    </>
  )
}
