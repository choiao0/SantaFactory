import { useEffect, useState } from 'react'
import Header from './components/Header.jsx'
import Hero from './components/Hero.jsx'
import WarehouseStep from './components/WarehouseStep.jsx'
import FleetStep from './components/FleetStep.jsx'
import RunsStep from './components/RunsStep.jsx'
import QuoteStep from './components/QuoteStep.jsx'
import VerifyStep from './components/VerifyStep.jsx'
import Footer from './components/Footer.jsx'
import { useReveal } from './hooks/useReveal.js'
import { useEstimateStream } from './hooks/useEstimateStream.js'
import { createEstimate, createWarehouse, getRobots } from './api/estimates.js'

const DEFAULT_FORM = {
  workerCount: 4,
  inboundStart: '01:00',
  inboundEnd: '09:00',
  outboundStart: '13:00',
  outboundEnd: '18:00',
  inboundAvg: 480,
  outboundAvg: 500,
  targetThroughput: 95,
  budgetMan: 30000,
}

const DEFAULT_FLEET = { min: 3, max: 15 }

export default function App() {
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
          estimateId={estimateId}
          onRequest={requestEstimate}
        />
        <RunsStep estimateId={estimateId} estimate={stream.estimate} connected={stream.connected} error={stream.error} />
        <VerifyStep estimateId={estimateId} ready={Boolean(stream.verdict)} />
        <QuoteStep
          estimateId={estimateId}
          estimate={stream.estimate}
          verdict={stream.verdict}
          model={selectedModel}
          form={form}
        />
      </main>
      <Footer />
    </>
  )
}
