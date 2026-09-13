import { formatDateTime, formatEok, formatPercent, formatWon } from '../utils/format.js'

const MONO = 'DM Mono, Pretendard Variable, Pretendard, monospace'
const GRID_LINE = '#e0ded9'
const MUTED = '#8a8983'
const RED = '#e72d2d'
const EOK = 100_000_000

const REASON_TEXT = {
  BUDGET_EXCEEDED: '예산 안에 드는 대수가 없습니다. 예산을 올리거나 목표를 낮춰 다시 요청해 보세요.',
  THROUGHPUT_SHORT: '예산 안의 대수로는 목표 출고 처리율에 닿지 않습니다. 목표를 낮추거나 예산을 올려야 합니다.',
  UTILIZATION_SHORT: '목표 처리율은 채우지만 그 대수의 AMR 가동률이 목표에 못 미칩니다. 가동률 목표를 조정해 보세요.',
  ALL_FAILED: '모든 대수의 시뮬레이션이 실패해 판정할 결과가 없습니다. 조건을 확인한 뒤 다시 요청해 주세요.',
  LOAD_TOO_LOW: '모든 대수가 처리율 100%를 기록해 대수를 구분할 수 없습니다. 주문량이 너무 적거나 시뮬 실행 조건을 확인해야 합니다.',
}

function isDone(run) {
  return run.status === 'DONE' && run.throughput != null
}

/**
 * 비용 축의 최대값. 처리율 축이 0/25/50/75/100 을 4등분하고 두 축이 격자선을 공유하므로,
 * 비용 축도 4등분이 예쁜 값으로 올려야 눈금이 "0.8 / 1.6 / 2.4" 같이 지저분해지지 않는다.
 */
function niceCostMax(rawMax) {
  const steps = [0.25, 0.5, 1, 1.5, 2, 2.5, 3, 5, 7.5, 10, 15, 20, 25, 50, 100]
  const step = steps.find((s) => 4 * s * EOK >= rawMax) ?? Math.ceil(rawMax / (4 * EOK))
  return 4 * step * EOK
}

/** 대수가 많으면(최대 28) x축 라벨이 겹친다 — 일정 간격만 찍되 강조할 대수는 항상 찍는다. */
function tickIndexes(runs, keepIndex) {
  const every = Math.max(1, Math.ceil(runs.length / 10))
  return runs.map((_, i) => i).filter((i) => i % every === 0 || i === keepIndex)
}

function CurveChart({ runs, target, budget, recommended, knee }) {
  const W = 560
  const H = 300
  const pad = { l: 42, r: 50, t: 20, b: 34 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const counts = runs.map((r) => r.amr_count)
  const xMin = Math.min(...counts)
  const xMax = Math.max(...counts)
  const span = Math.max(1, xMax - xMin)
  const done = runs.filter(isDone)
  const costMax = niceCostMax(Math.max(budget, ...runs.map((r) => r.total_cost ?? 0)) * 1.15)
  const x = (n) => pad.l + ((n - xMin) / span) * iw
  const y = (v) => pad.t + ih - (v / 100) * ih
  const yc = (v) => pad.t + ih - (v / costMax) * ih

  const tp = done.map((r) => `${x(r.amr_count)},${y(r.throughput)}`).join(' ')
  const cp = runs.filter((r) => r.total_cost != null).map((r) => `${x(r.amr_count)},${yc(r.total_cost)}`).join(' ')
  const recIndex = runs.findIndex((r) => r.amr_count === recommended)
  const visible = new Set(tickIndexes(runs, recIndex))

  // 예산 초과 구간 음영 — 대수가 늘면 비용이 단조 증가하므로 첫 초과 대수부터 오른쪽 전부다.
  const overBudget = runs.find((r) => r.total_cost > budget)
  const halfStep = runs.length > 1 ? iw / (runs.length - 1) / 2 : iw / 4

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 처리율과 구축비용 곡선">
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke={GRID_LINE} />
          <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" fontSize="8" fill={MUTED} fontFamily={MONO}>{v}</text>
        </g>
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <text key={f} x={W - pad.r + 8} y={yc(costMax * f) + 3} fontSize="8" fill={MUTED} fontFamily={MONO}>
          {formatEok(costMax * f)}
        </text>
      ))}
      {runs.filter((_, i) => visible.has(i)).map((r) => (
        <text key={r.run_id} x={x(r.amr_count)} y={H - pad.b + 16} textAnchor="middle" fontSize="8" fill={isDone(r) ? '#4a4a46' : '#b7b5b0'} fontFamily={MONO}>
          {r.amr_count}
        </text>
      ))}
      <text x={pad.l} y={H - 4} fontSize="7.5" fill={MUTED} fontFamily={MONO}>AMR COUNT →</text>
      <text x={pad.l - 40} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>처리율</text>
      <text x={W - pad.r + 8} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>구축비</text>

      <line x1={pad.l} x2={W - pad.r} y1={y(target)} y2={y(target)} stroke="#111" strokeDasharray="4 4" />
      <text x={pad.l + 4} y={y(target) - 5} fontSize="7.5" fill="#111" fontFamily={MONO}>TARGET {target}%</text>

      {overBudget && (
        <rect x={x(overBudget.amr_count) - halfStep} y={pad.t}
              width={W - pad.r - x(overBudget.amr_count) + halfStep} height={ih}
              fill="#111" opacity=".06" />
      )}
      {budget <= costMax && (
        <>
          <line x1={pad.l} x2={W - pad.r} y1={yc(budget)} y2={yc(budget)} stroke={MUTED} strokeDasharray="2 4" />
          <text x={W - pad.r - 4} y={yc(budget) + 11} textAnchor="end" fontSize="7.5" fill={MUTED} fontFamily={MONO}>
            BUDGET {formatWon(budget)}
          </text>
        </>
      )}

      <polyline points={cp} fill="none" stroke={MUTED} strokeWidth="1.5" />
      {runs.filter((r) => r.total_cost != null).map((r) => (
        <circle key={r.run_id} cx={x(r.amr_count)} cy={yc(r.total_cost)} r="3" fill="#fbfaf8" stroke={MUTED} strokeWidth="1.5" />
      ))}

      <polyline points={tp} fill="none" stroke={RED} strokeWidth="2.5" />
      {done.map((r) => (
        <circle key={r.run_id} cx={x(r.amr_count)} cy={y(r.throughput)} r="4" fill={r.amr_count === recommended ? RED : '#fbfaf8'} stroke={RED} strokeWidth="2" />
      ))}

      {knee != null && knee !== recommended && (
        <>
          <line x1={x(knee)} x2={x(knee)} y1={pad.t} y2={pad.t + ih} stroke={MUTED} strokeDasharray="3 3" />
          <text x={x(knee) + 6} y={pad.t + ih - 20} fontSize="7.5" fill={MUTED} fontFamily={MONO}>KNEE {knee}</text>
        </>
      )}
      {recommended != null && (
        <>
          <line x1={x(recommended)} x2={x(recommended)} y1={pad.t} y2={pad.t + ih} stroke={RED} strokeDasharray="3 3" />
          <text x={x(recommended) + (x(recommended) > pad.l + iw * 0.7 ? -6 : 6)} y={pad.t + ih - 8}
                textAnchor={x(recommended) > pad.l + iw * 0.7 ? 'end' : 'start'}
                fontSize="8" fontWeight="600" fill="#b51616" fontFamily={MONO}>
            RECOMMENDED {recommended}
          </text>
        </>
      )}
    </svg>
  )
}

function UtilChart({ runs, target, recommended }) {
  const W = 400
  const H = 300
  const pad = { l: 40, r: 16, t: 20, b: 34 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const bw = iw / Math.max(1, runs.length)
  const recIndex = runs.findIndex((r) => r.amr_count === recommended)
  const visible = new Set(tickIndexes(runs, recIndex))

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 가동률">
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={pad.t + ih - (v / 100) * ih} y2={pad.t + ih - (v / 100) * ih} stroke={GRID_LINE} />
          <text x={pad.l - 8} y={pad.t + ih - (v / 100) * ih + 3} textAnchor="end" fontSize="8" fill={MUTED} fontFamily={MONO}>{v}%</text>
        </g>
      ))}
      {target != null && (
        <line x1={pad.l} x2={W - pad.r} y1={pad.t + ih - (target / 100) * ih} y2={pad.t + ih - (target / 100) * ih} stroke="#111" strokeDasharray="4 4" />
      )}
      {runs.map((r, i) => {
        const cx = pad.l + bw * i + bw / 2
        const hl = r.amr_count === recommended
        const label = visible.has(i) && (
          <text x={cx} y={H - pad.b + 16} textAnchor="middle" fontSize="8" fontWeight={hl ? '600' : '400'}
                fill={hl ? '#b51616' : isDone(r) ? '#4a4a46' : '#b7b5b0'} fontFamily={MONO}>
            {r.amr_count}
          </text>
        )
        if (!isDone(r) || r.utilization == null) {
          return (
            <g key={r.run_id}>
              <rect x={cx - bw * 0.3} y={pad.t} width={bw * 0.6} height={ih} fill={GRID_LINE} opacity=".5" />
              {label}
            </g>
          )
        }
        const uh = (Math.min(100, r.utilization) / 100) * ih
        return (
          <g key={r.run_id}>
            <rect x={cx - bw * 0.3} y={pad.t + ih - uh} width={bw * 0.6} height={uh} fill={hl ? RED : '#3f3f3d'} />
            {hl && (
              <text x={cx} y={pad.t + ih - uh - 6} textAnchor="middle" fontSize="8" fontWeight="600" fill="#b51616" fontFamily={MONO}>
                {Math.round(r.utilization)}
              </text>
            )}
            {label}
          </g>
        )
      })}
      <text x={pad.l} y={H - 4} fontSize="7.5" fill={MUTED} fontFamily={MONO}>검은 막대 가동률 · 빨간 막대 권장 구성 · 회색 막대 결과 없는 run</text>
    </svg>
  )
}

function Placeholder({ estimateId, estimate }) {
  if (estimateId == null) {
    return <div className="q-empty">02 단계에서 견적을 요청하면 리포트가 여기에 표시됩니다.</div>
  }
  const runs = estimate?.runs ?? []
  const finished = runs.filter((r) => r.status !== 'QUEUED' && r.status !== 'RUNNING').length
  return (
    <div className="q-empty">
      <span className="live-dot pulse" /> 시뮬레이션 진행 중 · {finished} / {runs.length} 완료
      <br />
      마지막 run 이 끝나면 권장 대수와 비용 곡선이 자동으로 표시됩니다.
    </div>
  )
}

export default function QuoteStep({ estimateId, estimate, verdict, model, form }) {
  const ready = Boolean(estimate && verdict)
  const runs = estimate?.runs ?? []
  const recommended = verdict?.recommended_count ?? null
  const rec = runs.find((r) => r.amr_count === recommended) ?? null
  const failed = runs.filter((r) => !isDone(r))
  const cancelled = verdict?.status === 'CANCELLED'

  return (
    <section className="step paper" id="quote">
      <div className="eyebrow red">
        <span className="live-dot" />
        05 — QUOTE
      </div>
      <h2>Choose on the curve.</h2>
      <p className="desc">목표 출고 처리율과 가동률을 만족하면서 예산 안에 드는 최소 대수를 권장 구성으로 표시합니다.</p>

      {!ready && <Placeholder estimateId={estimateId} estimate={estimate} />}

      {ready && (
        <>
          <div className="q-head">
            <h3>SANTA FACTORY · QUOTATION</h3>
            <span className="mono">
              EST #{estimate.estimate_id} · {formatDateTime(estimate.created_at)} · {estimate.amr_model} · SEED 101
            </span>
          </div>

          {cancelled && <div className="notice">이 견적은 취소되었습니다. 조건을 바꿔 다시 요청해 주세요.</div>}

          {!cancelled && rec && (
            <>
              <p className="q-sum">
                목표 출고 처리율 <b>{estimate.target_throughput}%</b>를 만족하는 최소 구성은{' '}
                <b className="rd">{estimate.amr_model} {rec.amr_count}대</b>입니다. 예상 구축비용은{' '}
                <b>{formatWon(rec.total_cost)}</b>으로 예산 {formatWon(estimate.budget_limit)} 이내입니다.
                {verdict.knee_count != null && verdict.knee_count !== rec.amr_count && (
                  <> {verdict.knee_count}대부터는 대수를 늘려도 처리율이 거의 오르지 않습니다.</>
                )}
              </p>

              <div className="kpi">
                <div>
                  <span className="k-label">RECOMMENDED FLEET</span>
                  <strong>{rec.amr_count}<span>대</span></strong>
                  <em className="ok">목표 충족 · 예산 이내 최소 구성</em>
                </div>
                <div>
                  <span className="k-label">THROUGHPUT</span>
                  <strong>{formatPercent(rec.throughput)}<span>%</span></strong>
                  <em>목표 {estimate.target_throughput}% 대비 +{formatPercent(rec.throughput - estimate.target_throughput)}p</em>
                </div>
                <div>
                  <span className="k-label">EST. CAPEX</span>
                  <strong>{formatWon(rec.total_cost)}</strong>
                  <em>예산 {formatWon(estimate.budget_limit)} 중 {Math.round((rec.total_cost / estimate.budget_limit) * 100)}%</em>
                </div>
                <div>
                  <span className="k-label">UTILIZATION</span>
                  <strong>{formatPercent(rec.utilization)}<span>%</span></strong>
                  <em>목표 가동률 {estimate.target_utilization}%</em>
                </div>
              </div>
            </>
          )}

          {!cancelled && !rec && (
            <div className="notice">
              <b>권장 대수를 내지 못했습니다.</b>
              <br />
              {REASON_TEXT[verdict.reason_code] ?? `사유 코드 ${verdict.reason_code}`}
            </div>
          )}

          {runs.length > 0 && (
            <>
              <div className="charts">
                <div>
                  <h5>THROUGHPUT–COST CURVE</h5>
                  <CurveChart
                    runs={runs}
                    target={estimate.target_throughput}
                    budget={estimate.budget_limit}
                    recommended={recommended}
                    knee={verdict.knee_count}
                  />
                  <p className="chart-cap">빨간 선 처리율 · 회색 선 구축비용 · 채워진 점 권장 구성</p>
                </div>
                <div>
                  <h5>UTILIZATION</h5>
                  <UtilChart runs={runs} target={estimate.target_utilization} recommended={recommended} />
                  <p className="chart-cap">대수가 많으면 x축 라벨은 일부만 표시됩니다</p>
                </div>
              </div>

              <div className="tablewrap">
                <table className="q-table">
                  <thead>
                    <tr>
                      <th>구성</th>
                      <th>상태</th>
                      <th>처리율</th>
                      <th>목표</th>
                      <th>가동률</th>
                      <th>출고 <span>건/일</span></th>
                      <th>구축비용</th>
                      <th>예산</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => {
                      const inBudget = r.total_cost != null && r.total_cost <= estimate.budget_limit
                      if (!isDone(r)) {
                        return (
                          <tr key={r.run_id} className="fail">
                            <td>{r.amr_count}대</td>
                            <td>{r.status}</td>
                            <td colSpan={4}>결과 없음{r.error ? ` · ${r.error}` : ''}</td>
                            <td>{formatWon(r.total_cost)}</td>
                            <td>{inBudget ? '이내' : '초과'}</td>
                          </tr>
                        )
                      }
                      return (
                        <tr key={r.run_id} className={r.amr_count === recommended ? 'hl' : ''}>
                          <td>{r.amr_count}대{r.amr_count === recommended && <span className="rec-chip">권장</span>}</td>
                          <td>완료</td>
                          <td>{formatPercent(r.throughput)}%</td>
                          <td>{r.throughput >= estimate.target_throughput ? '충족' : <span>미달</span>}</td>
                          <td>{formatPercent(r.utilization)}%</td>
                          <td>{r.outbound != null ? r.outbound.toLocaleString() : '—'}</td>
                          <td>{formatWon(r.total_cost)}</td>
                          <td>{inBudget ? '이내' : <span>초과</span>}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div className="q-two">
            <div>
              <h4>가정 명세 — 이 숫자가 나온 조건 전부</h4>
              <details className="assume">
                <summary>입력 조건과 고정값</summary>
                <ul>
                  <li>목표 출고 처리율 {estimate.target_throughput}% · 목표 가동률 {estimate.target_utilization}% · 예산 {formatWon(estimate.budget_limit)}</li>
                  <li>입고 {form.inboundStart}–{form.inboundEnd} ({form.inboundAvg}건/일) · 출고 {form.outboundStart}–{form.outboundEnd} ({form.outboundAvg}건/일)</li>
                  {model && (
                    <li>AMR {model.model} · 속도 {model.speed} m/s · 적재 {model.capacity} · 대당 단가 {formatWon(model.price)} + 설치비 {formatWon(model.cost)}</li>
                  )}
                  <li>구축비용 = (단가 + 설치비) × 대수 + 충전기(4대당 1기). 유지보수·자재 관리비 제외</li>
                  <li>시뮬레이션 고정 시간 6시간(입고 2h + 출고 4h) · 시드 101 · 재고 항상 충분 가정</li>
                  <li>경로 계획 PIBT + 가중 다익스트라 · 1칸 = 1 m · 고정 창고 레이아웃</li>
                </ul>
              </details>
            </div>
            <div>
              <h4>읽는 법</h4>
              <div className="notice">
                확정 견적이 아닌 도입 전 검토 자료입니다. 피크 여유가 필요하면 한 단계 위 구성도 함께 보십시오.
                {failed.length > 0 && (
                  <>
                    <br />
                    <br />
                    {failed.map((r) => `${r.amr_count}대`).join(', ')} run은 결과가 없어 곡선에서 빠져 있습니다.
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="printrow">
            <button type="button" className="button">견적서 PDF 저장 ↗</button>
            <a className="ghost" href="#s1">조건 바꿔 다시 요청</a>
          </div>
        </>
      )}
    </section>
  )
}
