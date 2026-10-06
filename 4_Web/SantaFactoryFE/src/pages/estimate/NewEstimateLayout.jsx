import { useEffect, useState } from 'react'
import { Navigate, Outlet, useNavigate } from 'react-router-dom'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { reusableWarehouseId, useEstimateDraft } from '../../hooks/useEstimateDraft.js'
import { createEstimate, createWarehouse, getRobots } from '../../api/estimates.js'
import { useTrialMode } from '../../trial/trialContext.js'

/**
 * 새 견적을 만드는 두 단계(01 운영 조건 · 02 대수 범위)를 감싼다 (S15P21A106-274).
 *
 * 입력값과 모델 목록을 여기서 들고 있는 이유는, 이 레이아웃이 두 단계 사이를 오가는 동안
 * 살아 있기 때문이다. 페이지마다 들고 있으면 01 에서 친 값이 02 로 넘어가지 못하고, 모델
 * 목록도 단계를 옮길 때마다 다시 받는다.
 */
export default function NewEstimateLayout() {
  const navigate = useNavigate()
  const trialMode = useTrialMode()
  const draft = useEstimateDraft()
  const [models, setModels] = useState([])
  const [modelsError, setModelsError] = useState(null)
  const [requesting, setRequesting] = useState(false)
  const [requestError, setRequestError] = useState(null)

  useEffect(() => {
    getRobots()
      .then((list) => {
        setModels(list)
        // 자동으로 고르지 않는다 — 화면이 먼저 묻는다 (S15P21A106-271)
      })
      .catch((e) => setModelsError(e.message))
  }, [])

  const selectedModel = models.find((m) => m.model === draft.model) ?? null

  /**
   * 창고를 만들고 그 창고로 견적을 연다. 둘은 한 번의 제출이다 — 창고만 만들고 끝나면 쓰이지 않는
   * 창고가 남는다.
   *
   * <p>랜딩에서 저장된 조건을 골라 왔고 한 칸도 안 고쳤으면 창고를 새로 만들지 않고 그 번호를
   * 그대로 쓴다. 견적 생성 API 가 원래 창고 번호를 받으므로(EstimateService.create) 서버는 그대로다.
   */
  const requestEstimate = async () => {
    setRequesting(true)
    setRequestError(null)
    try {
      const reusedId = reusableWarehouseId(draft)
      const warehouseId = reusedId
        ?? (await createWarehouse({ ...draft.form, budgetLimit: draft.form.budgetMan * 10000 })).warehouse_id
      const estimate = await createEstimate({
        warehouseId,
        amrModel: draft.model,
        fleetMin: draft.fleet.min,
        fleetMax: draft.fleet.max,
      })
      // 입력값은 지우지 않는다 — 견적서에서 "조건 바꿔 다시 요청"으로 돌아왔을 때 방금 친 값이
      // 그대로 있어야 한다. 스크롤 한 장이던 때도 입력칸은 건드려지지 않았다
      navigate(`/estimate/${estimate.estimate_id}/runs`)
    } catch (e) {
      setRequestError(e.message)
    } finally {
      setRequesting(false)
    }
  }

  // 체험판은 새 견적을 받지 않는다 — 주소로 바로 들어와도 데모 견적 목록으로 보낸다 (S15P21A106-283)
  if (trialMode) return <Navigate to="/estimates" replace />

  return (
    <>
      <Header />
      <main>
        <Outlet context={{ ...draft, models, modelsError, selectedModel, requesting, requestError, requestEstimate }} />
      </main>
      <Footer />
    </>
  )
}
