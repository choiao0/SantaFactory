import { useOutletContext } from 'react-router-dom'
import StepFoot from '../../components/StepFoot.jsx'
import StepNav from '../../components/StepNav.jsx'
import WarehouseStep from '../../components/WarehouseStep.jsx'
import { useReveal } from '../../hooks/useReveal.js'

/** 01 — 운영 조건 (S15P21A106-274). 값은 레이아웃이 들고 있고 여기서는 보여 주기만 한다. */
export default function WarehousePage() {
  const { form, patchForm, models, modelsError, model, setModel } = useOutletContext()
  // 이 페이지가 뜰 때 돌아야 한다 — 섹션이 .reveal 이라 관찰자가 붙기 전에는 투명하다
  useReveal()

  return (
    <>
      <StepNav current="warehouse" />
      <WarehouseStep
        form={form}
        onChange={patchForm}
        models={models}
        modelsError={modelsError}
        model={model}
        onSelectModel={setModel}
      />
      <StepFoot back="/estimate" next="/estimate/new/fleet" />
    </>
  )
}
