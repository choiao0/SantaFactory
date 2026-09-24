import { useOutletContext } from 'react-router-dom'
import FleetStep from '../../components/FleetStep.jsx'
import StepFoot from '../../components/StepFoot.jsx'
import StepNav from '../../components/StepNav.jsx'
import { missingFields } from '../../hooks/useEstimateDraft.js'
import { useReveal } from '../../hooks/useReveal.js'

/**
 * 02 — 대수 범위 (S15P21A106-274).
 *
 * 다음으로 넘기는 버튼을 따로 두지 않는다. 이 단계의 "다음"은 곧 견적 요청이고, 그 버튼은
 * 몇 회를 돌리는지까지 적혀 있어 섹션 안에 있어야 말이 된다 — 성공하면 03 으로 데려간다.
 */
export default function FleetPage() {
  const { form, model, fleet, setFleet, selectedModel, requesting, requestError, requestEstimate } = useOutletContext()
  useReveal()

  return (
    <>
      <StepNav current="fleet" />
      <FleetStep
        fleet={fleet}
        onChange={setFleet}
        model={selectedModel}
        requesting={requesting}
        error={requestError}
        missing={missingFields(form, model)}
        onRequest={requestEstimate}
      />
      <StepFoot back="/estimate/new/warehouse" />
    </>
  )
}
