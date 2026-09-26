import { useOutletContext } from 'react-router-dom'
import RunsStep from '../../components/RunsStep.jsx'
import StepFoot from '../../components/StepFoot.jsx'
import StepNav from '../../components/StepNav.jsx'
import { useReveal } from '../../hooks/useReveal.js'

/**
 * 03 — 시뮬레이션 (S15P21A106-274).
 *
 * 계산이 끝나기를 기다리지 않고 다음으로 넘어갈 수 있다. 04 는 판정이 아직이면 "계산 중"으로
 * 기다리는 화면을 스스로 그리므로, 여기서 버튼을 잠그면 같은 기다림을 두 번 막는 셈이 된다.
 */
export default function RunsPage() {
  const { estimateId, estimate, connected, error } = useOutletContext()
  useReveal()

  return (
    <>
      <StepNav current="runs" estimateId={estimateId} />
      <RunsStep estimateId={estimateId} estimate={estimate} connected={connected} error={error} />
      <StepFoot next={`/estimate/${estimateId}/verify`} />
    </>
  )
}
