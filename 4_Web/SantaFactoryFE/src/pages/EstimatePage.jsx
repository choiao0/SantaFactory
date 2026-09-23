import { useEffect, useState } from 'react'
import Header from '../components/Header.jsx'
import Hero from '../components/Hero.jsx'
import WarehouseStep from '../components/WarehouseStep.jsx'
import FleetStep from '../components/FleetStep.jsx'
import RunsStep from '../components/RunsStep.jsx'
import QuoteStep from '../components/QuoteStep.jsx'
import VerifyStep from '../components/VerifyStep.jsx'
import Footer from '../components/Footer.jsx'
import { useReveal } from '../hooks/useReveal.js'
import { useEstimateStream } from '../hooks/useEstimateStream.js'
import { createEstimate, createWarehouse, getRobots } from '../api/estimates.js'

/** 견적을 내려면 사용자가 채워야 하는 값. 기본값이 0 이라 빈 채로 요청하면 서버 검증에서 막힌다. */
const REQUIRED_FIELDS = [
  ['inboundAvg', '일 평균 입고'],
  ['outboundAvg', '일 평균 출고 주문'],
  ['targetThroughput', '목표 출고 처리율'],
  ['targetUtilization', '목표 가동률'],
  ['budgetMan', '최대 구축 예산'],
]

const DEFAULT_FORM = {
  // 화면에서는 받지 않는다 — 시뮬 엔진이 아직 이 값을 쓰지 않는다
  // (FMS API 계약 문서: worker_count = 피커 작업 시간 모델, "로드맵 확정, 미구현").
  // 다만 창고 생성 API 가 여전히 필수(@NotNull)라 보내긴 해야 해서 기본값으로 남긴다.
  // 엔진이 실제로 반영하기 시작하면 입력 항목을 되살려야 한다.
  workerCount: 4,
  inboundStart: '01:00',
  inboundEnd: '09:00',
  outboundStart: '13:00',
  outboundEnd: '18:00',
  // 실제 창고 조건은 사용자가 넣어야 하는 값이다 — 그럴듯한 기본값이 박혀 있으면 그대로 두고
  // 요청해 버려서, 나온 견적이 자기 창고 이야기가 아니게 된다
  inboundAvg: 0,
  outboundAvg: 0,
  targetThroughput: 0,
  targetUtilization: 0,
  budgetMan: 0,
}

const DEFAULT_FLEET = { min: 3, max: 15 }

export default function EstimatePage() {
  useReveal()

  const [form, setForm] = useState(DEFAULT_FORM)
  const [models, setModels] = useState([])
  const [modelsError, setModelsError] = useState(null)
  const [model, setModel] = useState(null)
  const [fleet, setFleet] = useState(DEFAULT_FLEET)
  const [requesting, setRequesting] = useState(false)
  const [requestError, setRequestError] = useState(null)
  const [estimateId, setEstimateId] = useState(() => {
    const saved = sessionStorage.getItem('estimateId')
    return saved ? Number(saved) : null
  })
  const stream = useEstimateStream(estimateId)

  useEffect(() => {
    getRobots()
      .then((list) => {
        setModels(list)
        setModel((current) => current ?? list[0]?.model ?? null)
      })
      .catch((e) => setModelsError(e.message))
  }, [])

  const selectedModel = models.find((m) => m.model === model) ?? null

  const requestEstimate = async () => {
    setRequesting(true)
    setRequestError(null)
    try {
      const warehouse = await createWarehouse({ ...form, budgetLimit: form.budgetMan * 10000 })
      const estimate = await createEstimate({
        warehouseId: warehouse.warehouse_id,
        amrModel: model,
        fleetMin: fleet.min,
        fleetMax: fleet.max,
      })
      setEstimateId(estimate.estimate_id)
      sessionStorage.setItem('estimateId', String(estimate.estimate_id))
      document.getElementById('s3')?.scrollIntoView({ behavior: 'smooth' })
    } catch (e) {
      setRequestError(e.message)
    } finally {
      setRequesting(false)
    }
  }

  return (
    <>
      <Header />
      <main>
        <Hero />
        <WarehouseStep
          form={form}
          onChange={(patch) => setForm((f) => ({ ...f, ...patch }))}
          models={models}
          modelsError={modelsError}
          model={model}
          onSelectModel={setModel}
        />
        <FleetStep
          fleet={fleet}
          onChange={setFleet}
          model={selectedModel}
          requesting={requesting}
          error={requestError}
          missing={REQUIRED_FIELDS.filter(([key]) => !(Number(form[key]) > 0)).map(([, label]) => label)}
          onRequest={requestEstimate}
        />
        <RunsStep estimateId={estimateId} estimate={stream.estimate} connected={stream.connected} error={stream.error} />
        <VerifyStep
          estimateId={estimateId}
          ready={Boolean(stream.verdict)}
          recommendedCount={stream.verdict?.recommended_count}
        />
        <QuoteStep
          estimateId={estimateId}
          estimate={stream.estimate}
          verdict={stream.verdict}
        />
      </main>
      <Footer />
    </>
  )
}
