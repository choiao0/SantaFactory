import { AMR_MODEL } from '../data/mock.js'
import { useEstimate } from '../hooks/useEstimate.js'

const MONO = 'DM Mono, Pretendard Variable, Pretendard, monospace'
const GRID_LINE = '#e0ded9'
const MUTED = '#8a8983'
const RED = '#e72d2d'

const EOK = 100_000_000

/**
 * 비용 축의 최대값. 처리율 축이 0~100을 4등분(0/25/50/75/100)하고 두 축이 격자선을 공유하므로,
 * 비용 축도 4등분이 예쁜 값으로 올려야 눈금이 `0.8 / 1.6 / 2.4` 같이 지저분해지지 않는다.
 * 예산을 최대값에 포함시키기 때문에, 예산이 실제 비용보다 훨씬 크면 비용 곡선이 아래로 눌린다 —
 * 그 자체가 "예산이 넉넉하다"를 보여주므로 지금은 그대로 둔다.
 */
function niceCostMax(rawMax) {
  // 눈금 한 칸(억)이 될 수 있는 값. 촘촘해야 축을 덜 버린다 — [0.25,0.5,1,2,…] 만 쓰면
  // 4.2억이 8억으로 올라가 축 절반이 빈다.
  const steps = [0.25, 0.5, 1, 1.5, 2, 2.5, 3, 5, 7.5, 10, 15, 20, 25, 50, 100]
  const step = steps.find((s) => 4 * s * EOK >= rawMax) ?? Math.ceil(rawMax / (4 * EOK))
  return 4 * step * EOK
}

/** 백엔드가 원 단위로 주므로 억/만원으로 끊어 읽는다. */
function formatKrw(won) {
  if (won == null) return '—'
  const eok = Math.floor(won / 100_000_000)
  const man = Math.round((won % 100_000_000) / 10_000)
  if (eok === 0) return `${man.toLocaleString()}만원`
  if (man === 0) return `${eok}억원`
  return `${eok}억 ${man.toLocaleString()}만원`
}

const REASON_TEXT = {
  BUDGET_EXCEEDED: '모든 대수가 예산을 넘습니다. 예산을 올리거나 목표를 낮춰야 합니다.',
  THROUGHPUT_SHORT: '예산 안에 드는 대수 중 목표 처리율에 닿는 구성이 없습니다.',
  UTILIZATION_SHORT: '목표 처리율은 채우지만 그 대수의 가동률이 목표에 못 미칩니다.',
}

const STATUS_TEXT = {
  RUNNING: '진행 중',
  DONE: '완료',
  PARTIAL: '일부 실패',
  CANCELLED: '취소됨',
}

const RUN_STATUS_TEXT = {
  QUEUED: '대기',
  RUNNING: '계산 중',
  DONE: '완료',
  FAILED: '실패',
  TIMEOUT: '시간 초과',
}

/**
 * 처리율·구축비 곡선.
 *
 * 왼쪽 축은 출고 처리율 %다. 판정이 이 값을 목표(기본 95 %)와 비교하므로, 목표 점선과
 * 곡선이 만나는 지점이 곧 권장 대수의 근거가 된다. 목업의 "건/시" 축은 판정에 쓰이지
 * 않아 뺐다 — 물량은 표의 일일 출고 열에 있다.
 */
function CurveChart({ estimate }) {
  const W = 560
  const H = 300
  const pad = { l: 42, r: 52, t: 20, b: 34 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b

  const runs = estimate.runs
  const done = runs.filter((r) => r.status === 'DONE' && r.throughput != null)
  const xMin = runs[0]?.amrCount ?? 1
  const xMax = runs[runs.length - 1]?.amrCount ?? 1
  const costMax = niceCostMax(Math.max(estimate.budgetLimit, ...runs.map((r) => r.totalCost ?? 0)))

  const x = (n) => (xMax === xMin ? pad.l + iw / 2 : pad.l + ((n - xMin) / (xMax - xMin)) * iw)
  const y = (pct) => pad.t + ih - (pct / 100) * ih
  const yc = (won) => pad.t + ih - (won / costMax) * ih

  const throughputLine = done.map((r) => `${x(r.amrCount)},${y(r.throughput)}`).join(' ')
  const costLine = runs.map((r) => `${x(r.amrCount)},${yc(r.totalCost)}`).join(' ')
  const rec = done.find((r) => r.amrCount === estimate.recommendedCount)
  const knee = done.find((r) => r.amrCount === estimate.kneeCount)
  // 예산 초과 구간 — 대수가 늘면 비용이 단조 증가하므로 첫 초과 대수부터 오른쪽 전부다.
  const overBudget = runs.find((r) => r.totalCost > estimate.budgetLimit)
  // 눈금이 촘촘하면 라벨이 겹친다. 대수 축은 최대 10개만 찍는다.
  const tickEvery = Math.ceil(runs.length / 10)
  // 점 사이 간격의 절반 — 예산 초과 음영을 점 위치가 아니라 반 칸 앞에서 시작시키는 데 쓴다.
  const halfStep = runs.length > 1 ? iw / (runs.length - 1) / 2 : iw / 4

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 출고 처리율과 구축비용 곡선">
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke={GRID_LINE} />
          <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" fontSize="8" fill={MUTED} fontFamily={MONO}>{v}</text>
        </g>
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => {
        const eok = (costMax * f) / EOK
        return (
          <text key={f} x={W - pad.r + 8} y={yc(costMax * f) + 3} fontSize="8" fill={MUTED} fontFamily={MONO}>
            {Number.isInteger(eok) ? eok : eok.toFixed(2).replace(/0$/, '')}억
          </text>
        )
      })}
      {runs.filter((_, i) => i % tickEvery === 0).map((r) => (
        <text key={r.runId} x={x(r.amrCount)} y={H - pad.b + 16} textAnchor="middle" fontSize="8"
              fill={r.status === 'DONE' ? '#4a4a46' : '#b7b5b0'} fontFamily={MONO}>
          n{r.amrCount}
        </text>
      ))}
      <text x={pad.l} y={H - 4} fontSize="7.5" fill={MUTED} fontFamily={MONO}>AMR COUNT →</text>
      <text x={pad.l - 40} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>처리율 %</text>
      <text x={W - pad.r + 8} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>구축비</text>

      {/* 목표선 라벨은 왼쪽에 둔다. 대수가 늘면 곡선이 목표선 바로 위에서 평평해져서,
          오른쪽에 두면 곡선·점과 겹쳐 읽을 수 없다. 왼쪽은 곡선이 낮아 항상 비어 있다. */}
      <line x1={pad.l} x2={W - pad.r} y1={y(estimate.targetThroughput)} y2={y(estimate.targetThroughput)}
            stroke="#111" strokeDasharray="4 4" />
      <text x={pad.l + 4} y={y(estimate.targetThroughput) - 5} fontSize="7.5" fill="#111" fontFamily={MONO}>
        TARGET {estimate.targetThroughput}%
      </text>

      {/* 예산은 두 가지로 보인다. 가로 점선(비용 축)이 "예산이 얼마"를, 세로 음영이 "몇 대부터
          초과"를 답한다. 두 표현은 비용 곡선이 예산을 넘는 그 점에서 만나므로 서로를 설명한다.
          색은 자기가 속한 축·계열을 따른다 — 예산선은 회색(비용), 목표선은 검정(처리율). */}
      {/* 음영은 첫 초과 대수의 반 칸 앞에서 시작한다. 점 위치에서 시작하면, 초과가 마지막
          대수일 때(예산이 딱 맞게 잡힌 흔한 경우) 너비가 0이 되어 아무것도 안 보인다. */}
      {overBudget && (
        <rect x={x(overBudget.amrCount) - halfStep} y={pad.t}
              width={W - pad.r - x(overBudget.amrCount) + halfStep} height={ih}
              fill="#111" opacity=".06" />
      )}
      {estimate.budgetLimit <= costMax && (
        <>
          <line x1={pad.l} x2={W - pad.r} y1={yc(estimate.budgetLimit)} y2={yc(estimate.budgetLimit)}
                stroke={MUTED} strokeDasharray="4 4" />
          <text x={W - pad.r - 4} y={yc(estimate.budgetLimit) - 5} textAnchor="end" fontSize="7.5" fill={MUTED}
                fontFamily={MONO}>
            BUDGET {formatKrw(estimate.budgetLimit)}
          </text>
        </>
      )}

      <polyline points={costLine} fill="none" stroke={MUTED} strokeWidth="1.5" />
      <polyline points={throughputLine} fill="none" stroke={RED} strokeWidth="2.5" />
      {done.map((r) => (
        <circle key={r.runId} cx={x(r.amrCount)} cy={y(r.throughput)} r="4"
                fill={r.amrCount === estimate.recommendedCount ? RED : '#fbfaf8'} stroke={RED} strokeWidth="2" />
      ))}

      {/* 세로선 라벨은 아래쪽에 둔다. 권장 대수는 곡선이 목표선에 닿는 지점이라 위쪽이 항상
          곡선·점으로 붐빈다. 두 라벨이 같은 대수 근처에 설 수 있으니 높이를 나눠 둔다
          (RECOMMENDED ih-10 / KNEE ih-26). 차트 오른쪽 끝에 가까우면 선 왼쪽으로 붙인다. */}
      {knee && knee.amrCount !== estimate.recommendedCount && (
        <>
          <line x1={x(knee.amrCount)} x2={x(knee.amrCount)} y1={pad.t} y2={pad.t + ih} stroke={MUTED}
                strokeDasharray="3 3" />
          <text x={x(knee.amrCount) + 6} y={pad.t + ih - 26} fontSize="8" fill={MUTED} fontFamily={MONO}>
            KNEE n{knee.amrCount}
          </text>
        </>
      )}
      {rec && (
        <>
          <line x1={x(rec.amrCount)} x2={x(rec.amrCount)} y1={pad.t} y2={pad.t + ih} stroke={RED}
                strokeDasharray="3 3" />
          <text x={x(rec.amrCount) + (x(rec.amrCount) > pad.l + iw * 0.7 ? -6 : 6)} y={pad.t + ih - 10}
                textAnchor={x(rec.amrCount) > pad.l + iw * 0.7 ? 'end' : 'start'}
                fontSize="8" fontWeight="600" fill="#b51616" fontFamily={MONO}>
            RECOMMENDED n{rec.amrCount}
          </text>
        </>
      )}
    </svg>
  )
}

/** 대수별 가동률 막대. 백엔드가 %(0~100)로 주므로 그대로 쓴다. */
function UtilChart({ estimate }) {
  const W = 400
  const H = 300
  const pad = { l: 40, r: 16, t: 20, b: 34 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const runs = estimate.runs
  const bw = iw / runs.length
  const labelEvery = Math.ceil(runs.length / 10)
  const targetY = pad.t + ih - (estimate.targetUtilization / 100) * ih

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 가동률">
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={pad.t + ih - (v / 100) * ih} y2={pad.t + ih - (v / 100) * ih}
                stroke={GRID_LINE} />
          <text x={pad.l - 8} y={pad.t + ih - (v / 100) * ih + 3} textAnchor="end" fontSize="8" fill={MUTED}
                fontFamily={MONO}>{v}%</text>
        </g>
      ))}
      <line x1={pad.l} x2={W - pad.r} y1={targetY} y2={targetY} stroke="#111" strokeDasharray="4 4" />
      <text x={W - pad.r} y={targetY - 5} textAnchor="end" fontSize="7.5" fill="#111" fontFamily={MONO}>
        TARGET {estimate.targetUtilization}%
      </text>

      {runs.map((r, i) => {
        const cx = pad.l + bw * i + bw / 2
        const hl = r.amrCount === estimate.recommendedCount
        // 라벨은 촘촘함을 피해 건너뛰지만 권장 대수는 반드시 찍는다 — 빨간 막대가 몇 대인지
        // 모르면 강조가 무의미하다 (권장이 짝수면 건너뛰기에 걸려 라벨이 없었다).
        const label = i % labelEvery === 0 || hl
          ? (
            <text x={cx} y={H - pad.b + 16} textAnchor="middle" fontSize="8" fontWeight={hl ? '600' : '400'}
                  fill={hl ? '#b51616' : r.status === 'DONE' ? '#4a4a46' : '#b7b5b0'}
                  fontFamily={MONO}>n{r.amrCount}</text>
          )
          : null
        if (r.status !== 'DONE' || r.utilization == null) {
          return (
            <g key={r.runId}>
              <rect x={cx - bw * 0.3} y={pad.t} width={bw * 0.6} height={ih} fill={GRID_LINE} opacity=".5" />
              {label}
            </g>
          )
        }
        const uh = (r.utilization / 100) * ih
        return (
          <g key={r.runId}>
            <rect x={cx - bw * 0.3} y={pad.t + ih - uh} width={bw * 0.6} height={uh} fill={hl ? RED : '#3f3f3d'} />
            {hl && (
              <text x={cx} y={pad.t + ih - uh - 6} textAnchor="middle" fontSize="8" fontWeight="600" fill="#b51616"
                    fontFamily={MONO}>
                {Math.round(r.utilization)}
              </text>
            )}
            {label}
          </g>
        )
      })}
      {/* 범례는 SVG 밖 .chart-cap 에만 둔다 — 왼쪽 곡선 차트와 같은 방식. */}
    </svg>
  )
}

/** 입력 플로우가 붙기 전까지는 쿼리스트링으로 견적을 지정한다. 없으면 목업. */
function estimateIdFromQuery() {
  if (typeof window === 'undefined') return null
  const raw = new URLSearchParams(window.location.search).get('estimate')
  const id = Number(raw)
  return raw && Number.isFinite(id) ? id : null
}

export default function QuoteStep() {
  const { estimate, error, live } = useEstimate(estimateIdFromQuery())

  // 데이터가 있으면 그대로 그린다 — 진행 스트림이 끊긴 건 화면을 비울 이유가 아니다.
  // 그 경우 아래 "읽는 법"에 안내만 띄우고, 값은 마지막으로 받은 것을 유지한다.
  if (!estimate) {
    return (
      <section className="step paper" id="quote">
        <div className="eyebrow red"><span className="live-dot" />04 — QUOTE</div>
        <h2>Choose on the curve.</h2>
        <p className="desc">
          {error ? `견적을 불러오지 못했습니다 — ${error.message} (${error.code})` : '견적을 불러오는 중입니다…'}
        </p>
      </section>
    )
  }

  const runs = estimate.runs ?? []
  const doneRuns = runs.filter((r) => r.status === 'DONE')
  const unfinished = runs.filter((r) => r.status === 'QUEUED' || r.status === 'RUNNING')
  const failed = runs.filter((r) => r.status === 'FAILED' || r.status === 'TIMEOUT')
  const rec = doneRuns.find((r) => r.amrCount === estimate.recommendedCount)
  const running = estimate.status === 'RUNNING'

  return (
    <section className="step paper" id="quote">
      <div className="eyebrow red">
        <span className="live-dot" />
        04 — QUOTE
      </div>
      <h2>Choose on the curve.</h2>
      <p className="desc">목표 처리율과 가동률을 만족하고 예산 안에 드는 최소 대수를 권장 구성으로 표시합니다.</p>

      <div className="q-head">
        <h3>SANTA FACTORY · QUOTATION</h3>
        <span className="mono">
          EST #{estimate.estimateId} · {STATUS_TEXT[estimate.status] ?? estimate.status} · {estimate.amrModel}
          {estimate.elapsedSeconds != null && ` · ${estimate.elapsedSeconds}s`}
          {!live && ' · 목업 데이터'}
        </span>
      </div>

      {running ? (
        <p className="q-sum">
          대수별 시뮬을 돌리는 중입니다 — <b>{doneRuns.length + failed.length} / {runs.length}</b> 완료.
          모든 run 이 끝나면 권장 대수가 확정됩니다.
        </p>
      ) : rec ? (
        <p className="q-sum">
          출고 주문의 <b>{estimate.targetThroughput}%</b> 이상을 처리하려면{' '}
          <b className="rd">{estimate.amrModel} {rec.amrCount}대</b>가 필요합니다. 예상 구축비용은{' '}
          <b>{formatKrw(rec.totalCost)}</b>으로 예산 {formatKrw(estimate.budgetLimit)} 이내입니다.
        </p>
      ) : (
        <p className="q-sum">
          목표를 만족하는 구성을 찾지 못했습니다. {REASON_TEXT[estimate.reasonCode] ?? estimate.reasonCode ?? ''}
        </p>
      )}

      <div className="kpi">
        <div>
          <span className="k-label">RECOMMENDED FLEET</span>
          <strong>{rec ? rec.amrCount : '—'}<span>대</span></strong>
          <em className={rec ? 'ok' : ''}>
            {rec ? '목표 충족 · 예산 이내 최소 구성' : (estimate.reasonCode ?? '판정 전')}
          </em>
        </div>
        <div>
          <span className="k-label">EST. THROUGHPUT</span>
          <strong>{rec ? rec.throughput.toFixed(1) : '—'}<span>%</span></strong>
          <em>
            {rec
              ? `목표 ${estimate.targetThroughput}% 대비 +${(rec.throughput - estimate.targetThroughput).toFixed(1)}`
              : '완료된 run 없음'}
          </em>
        </div>
        <div>
          <span className="k-label">EST. CAPEX</span>
          <strong>{formatKrw(rec?.totalCost)}</strong>
          <em>예산 {formatKrw(estimate.budgetLimit)}</em>
        </div>
        <div>
          <span className="k-label">UTILIZATION · 일일 출고</span>
          <strong>{rec ? Math.round(rec.utilization) : '—'}<span>%</span></strong>
          <em>
            {rec?.outbound != null ? `${rec.outbound.toLocaleString()}건/일` : `목표 ${estimate.targetUtilization}%`}
          </em>
        </div>
      </div>

      <div className="charts">
        <div>
          <h5>THROUGHPUT–COST CURVE</h5>
          <CurveChart estimate={estimate} />
          <p className="chart-cap">빨간 선 처리율 · 회색 선 구축비용 · 채워진 점 권장 구성</p>
        </div>
        <div>
          <h5>UTILIZATION</h5>
          <UtilChart estimate={estimate} />
          <p className="chart-cap">검은 막대 가동률 · 빨간 막대 권장 구성 · 회색 막대 결과 없는 run</p>
        </div>
      </div>

      <div className="tablewrap">
        <table className="q-table">
          <thead>
            <tr>
              <th>구성</th>
              <th>처리율 <span>%</span></th>
              <th>목표</th>
              <th>가동률 <span>%</span></th>
              <th>일일 출고 <span>건/일</span></th>
              <th>구축비용</th>
              <th>예산</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const inBudget = r.totalCost <= estimate.budgetLimit
              if (r.status !== 'DONE') {
                return (
                  <tr key={r.runId} className="fail">
                    <td>{r.amrCount}대</td>
                    <td colSpan={4}>
                      {RUN_STATUS_TEXT[r.status] ?? r.status}
                      {r.error && ` · ${r.error}`}
                    </td>
                    <td>{formatKrw(r.totalCost)}</td>
                    <td>{inBudget ? '이내' : '초과'}</td>
                  </tr>
                )
              }
              return (
                <tr key={r.runId} className={r.amrCount === estimate.recommendedCount ? 'hl' : ''}>
                  <td>{r.amrCount}대{r.amrCount === estimate.recommendedCount && <span> · 권장</span>}</td>
                  <td>{r.throughput.toFixed(1)}</td>
                  <td>{r.throughput >= estimate.targetThroughput ? '충족' : <span>미달</span>}</td>
                  <td>{Math.round(r.utilization)}</td>
                  <td>{r.outbound?.toLocaleString() ?? '—'}</td>
                  <td>{formatKrw(r.totalCost)}</td>
                  <td>{inBudget ? '이내' : <span>초과</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="q-two">
        <div>
          <h4>가정 명세 — 이 숫자가 나온 조건 전부</h4>
          <details className="assume">
            <summary>입력 조건과 고정값</summary>
            <ul>
              <li>창고 운영조건(작업 시간·입출고 물량)은 견적 요청 시점의 창고 정보를 씁니다</li>
              <li>처리율 = 접수한 출고 주문 중 완료 비율. 시뮬을 고정 시간으로 돌려 그 안의 완료 수로 셉니다</li>
              <li>일일 출고 = 시뮬 출고 구간 실측을 실제 출고 작업창 기준으로 환산한 값</li>
              <li>구축비용 = 대당 단가 × 대수 + 설치비. 유지보수·자재 관리비 제외</li>
              <li>재고는 항상 충분하다고 가정. 입고 검수·포장·배송 과정은 범위 외</li>
              <li>경로 계획 PIBT · 1칸 = 1 m · 회전 포함 이동 모델 · AMR {AMR_MODEL.model}</li>
            </ul>
          </details>
        </div>
        <div>
          <h4>읽는 법</h4>
          <div className="notice">
            확정 견적이 아닌 도입 전 검토 자료입니다. 피크 여유가 필요하면 한 단계 위 구성도 함께 보십시오.
            {estimate.kneeCount != null && (
              <>
                <br /><br />
                {estimate.kneeCount}대부터는 대수를 늘려도 처리율이 거의 오르지 않습니다.
              </>
            )}
            {failed.length > 0 && (
              <>
                <br /><br />
                {failed.map((r) => `n${r.amrCount}`).join(', ')} run 은 결과가 없어 곡선에서 빠져 있습니다.
              </>
            )}
            {unfinished.length > 0 && (
              <>
                <br /><br />
                {unfinished.length}개 run 이 아직 진행 중입니다.
              </>
            )}
            {error && (
              <>
                <br /><br />
                진행 스트림이 끊겨 자동 갱신이 멈췄습니다 ({error.message}). 새로고침하면 최신 상태를 받습니다.
              </>
            )}
          </div>
        </div>
      </div>

      <div className="printrow">
        <button type="button" className="button">견적서 PDF 저장 ↗</button>
        <button type="button" className="ghost">조건 바꿔 다시 요청</button>
      </div>
    </section>
  )
}
