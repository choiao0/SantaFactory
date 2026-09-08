export const GRID = { width: 24, length: 14 }

export const AMR_MODELS = [
  {
    id: 'iwhub',
    model: 'iw.hub',
    vendor: 'idealworks',
    speedEmpty: 1.2,
    speedLoaded: 1.0,
    capacity: 8,
    battery: 100,
    chargeTime: 3600,
    chargeThreshold: 0.2,
    price: 4500,
    note: '기준 모델 · 스펙 확정',
  },
  {
    id: 'model-b',
    model: 'MODEL B',
    vendor: '미정',
    speedEmpty: 1.6,
    speedLoaded: 1.3,
    capacity: 12,
    battery: 100,
    chargeTime: 2700,
    chargeThreshold: 0.25,
    price: 6200,
    note: '2차 후보 · 스펙 미확정 (목업)',
  },
]

export const AMR_MODEL = AMR_MODELS[0]

export const ESTIMATE = {
  id: 77,
  createdAt: '2026-09-07 14:20',
  status: 'PARTIAL',
  seed: 42,
  targetThroughput: 90,
  budget: 60000,
  baseCost: 8000,
  fleetMin: 3,
  fleetMax: 15,
  fleetStep: 2,
  recommended: 9,
}

export const RUNS = [
  { n: 3, status: 'DONE', throughput: 42.1, utilization: 0.91, leadTime: 480, waitRatio: 0.002, distance: 5200, completed: 50 },
  { n: 5, status: 'DONE', throughput: 66.4, utilization: 0.86, leadTime: 340, waitRatio: 0.004, distance: 8100, completed: 50 },
  { n: 7, status: 'DONE', throughput: 84.0, utilization: 0.79, leadTime: 260, waitRatio: 0.006, distance: 10400, completed: 50 },
  { n: 9, status: 'DONE', throughput: 96.4, utilization: 0.71, leadTime: 210, waitRatio: 0.011, distance: 12480, completed: 50 },
  { n: 11, status: 'DONE', throughput: 104.2, utilization: 0.63, leadTime: 190, waitRatio: 0.019, distance: 13900, completed: 50 },
  { n: 13, status: 'FAILED', error: 'worker timeout (1800s)' },
  { n: 15, status: 'DONE', throughput: 110.1, utilization: 0.48, leadTime: 178, waitRatio: 0.045, distance: 15200, completed: 50 },
]

export const RUN_STATUS_LABEL = {
  QUEUED: '대기',
  RUNNING: '계산 중',
  DONE: '완료',
  FAILED: '실패',
  TIMEOUT: '시간 초과',
}

export const ESTIMATE_STATUS_LABEL = {
  RUNNING: '진행 중',
  DONE: '완료',
  PARTIAL: '일부 실패',
  CANCELLED: '취소됨',
}

export function totalCost(n) {
  return ESTIMATE.baseCost + AMR_MODEL.price * n
}

export function formatWon(man) {
  if (man == null) return '—'
  const eok = Math.floor(man / 10000)
  const rest = man % 10000
  if (eok === 0) return `${rest.toLocaleString()}만원`
  if (rest === 0) return `${eok}억원`
  return `${eok}억 ${rest.toLocaleString()}만원`
}

const EMPTY = 0
export const RACK = 1
export const STATION = 2
export const DOCK = 3

export function buildLayout() {
  const { width: W, length: H } = GRID
  const cells = new Array(W * H).fill(EMPTY)
  for (let y = 2; y < H - 2; y++) {
    if (y % 3 === 1) continue
    for (let x = 4; x < W - 4; x++) {
      if ((x - 4) % 5 === 4) continue
      cells[y * W + x] = RACK
    }
  }
  ;[2, 5, 8, 11].forEach((y) => (cells[y * W + 0] = STATION))
  ;[3, 7, 11].forEach((y) => (cells[y * W + W - 1] = DOCK))
  return cells
}

export const BOTS = [
  { x: 2, y: 4, state: 'carry', path: 'a' },
  { x: 8, y: 1, state: 'move', path: 'b' },
  { x: 13, y: 7, state: 'work', path: 'c' },
  { x: 18, y: 10, state: 'carry', path: 'd' },
  { x: 21, y: 4, state: 'move', path: 'e' },
  { x: 5, y: 12, state: 'free', path: 'f' },
  { x: 11, y: 1, state: 'carry', path: 'g' },
  { x: 16, y: 12, state: 'move', path: 'h' },
  { x: 1, y: 8, state: 'work', path: 'i' },
]

// ─────────────────────────────────────────────────────────────────────────────
// 아래는 백엔드 GET /api/estimates/{id} 응답과 같은 모양이다 (camelize 후).
// 위쪽 ESTIMATE/RUNS 는 다른 단계 컴포넌트가 아직 쓰는 목업이라 그대로 둔다.
//
// 백엔드 의미에 주의:
//   throughput  = 접수 주문 중 완료 비율 [%]  (건/시가 아니다. 판정이 이 값을 쓴다)
//   utilization = AMR 가동률 [%] 0~100       (0~1 이 아니다)
//   outbound    = 일일 출고 건수 [건/일]
//   totalCost   = 대당 단가·설치비까지 합산된 구축비 [원]
// ─────────────────────────────────────────────────────────────────────────────

/** 대당 단가 1,550만 = AMR 1,500만 + 설치 50만 (application.yml estimate.*). */
const UNIT_COST = 15_500_000

const CURVE = [
  //  n  처리율%  가동률%
  [1, 12.0, 98.0], [2, 24.0, 97.0], [3, 35.0, 96.0], [4, 46.0, 94.0],
  [5, 56.0, 92.0], [6, 65.0, 90.0], [7, 73.0, 88.0], [8, 80.0, 86.0],
  [9, 85.0, 85.0], [10, 89.0, 84.0], [11, 92.0, 83.0], [12, 96.0, 82.0],
  [13, 97.0, 80.0], [14, 98.0, 79.0], [15, 98.5, 76.0], [16, 99.0, 73.0],
  [17, null, null], [18, 99.4, 67.0], [19, 99.5, 64.0], [20, 99.6, 61.0],
]

/** 하루 출고 800건 기준으로 처리율에서 환산. */
const dailyOutbound = (throughput) => Math.round((throughput / 100) * 800)

export const MOCK_ESTIMATE = {
  estimateId: 77,
  status: 'PARTIAL',           // n17 이 실패해서 DONE 이 아니다
  amrModel: 'iw.hub',
  targetThroughput: 95.0,
  targetUtilization: 80.0,
  budgetLimit: 300_000_000,
  recommendedCount: 12,        // 96 ≥ 95 · 82 ≥ 80 · 1.86억 ≤ 3억 을 처음 만족
  kneeCount: 13,
  reasonCode: null,
  createdAt: '2026-09-08T14:20:00',
  completedAt: '2026-09-08T14:33:12',
  elapsedSeconds: 792,
  runs: CURVE.map(([n, throughput, utilization]) => ({
    runId: `est_77_n${n}`,
    amrCount: n,
    status: throughput === null ? 'TIMEOUT' : 'DONE',
    throughput,
    utilization,
    outbound: throughput === null ? null : dailyOutbound(throughput),
    totalCost: UNIT_COST * n,
    error: throughput === null ? '결과가 오지 않아 TIMEOUT 처리됨 (30분)' : null,
  })),
}
