import { AMR_MODEL, ESTIMATE, RUNS, WAREHOUSE, formatWon, totalCost } from '../data/mock.js'

const DONE = RUNS.filter((r) => r.status === 'DONE')
const REC = DONE.find((r) => r.n === ESTIMATE.recommended)

function CurveChart() {
  const W = 560
  const H = 300
  const pad = { l: 42, r: 50, t: 20, b: 34 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const xMin = ESTIMATE.fleetMin
  const xMax = ESTIMATE.fleetMax
  const yMax = 120
  const cMax = 80000
  const x = (n) => pad.l + ((n - xMin) / (xMax - xMin)) * iw
  const y = (v) => pad.t + ih - (v / yMax) * ih
  const yc = (v) => pad.t + ih - (v / cMax) * ih

  const tp = DONE.map((r) => `${x(r.n)},${y(r.throughput)}`).join(' ')
  const cp = DONE.map((r) => `${x(r.n)},${yc(totalCost(r.n))}`).join(' ')
  const budgetN = (ESTIMATE.budget - ESTIMATE.baseCost) / AMR_MODEL.price

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 처리량과 구축비용 곡선">
      {[0, 30, 60, 90, 120].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="#e0ded9" />
          <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" fontSize="8" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">{v}</text>
        </g>
      ))}
      {[0, 2, 4, 6, 8].map((v) => (
        <text key={v} x={W - pad.r + 8} y={yc(v * 10000) + 3} fontSize="8" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">{v}억</text>
      ))}
      {RUNS.map((r) => (
        <text key={r.n} x={x(r.n)} y={H - pad.b + 16} textAnchor="middle" fontSize="8" fill={r.status === 'DONE' ? '#4a4a46' : '#b7b5b0'} fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">
          n{r.n}
        </text>
      ))}
      <text x={pad.l} y={H - 4} fontSize="7.5" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">AMR COUNT →</text>
      <text x={pad.l - 40} y={pad.t - 6} fontSize="7.5" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">건/시</text>
      <text x={W - pad.r + 8} y={pad.t - 6} fontSize="7.5" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">구축비</text>

      <line x1={pad.l} x2={W - pad.r} y1={y(ESTIMATE.targetThroughput)} y2={y(ESTIMATE.targetThroughput)} stroke="#111" strokeDasharray="4 4" />
      <text x={W - pad.r - 4} y={y(ESTIMATE.targetThroughput) - 5} textAnchor="end" fontSize="7.5" fill="#111" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">
        TARGET {ESTIMATE.targetThroughput}/h
      </text>
      <rect x={x(budgetN)} y={pad.t} width={W - pad.r - x(budgetN)} height={ih} fill="#111" opacity=".05" />
      <line x1={x(budgetN)} x2={x(budgetN)} y1={pad.t} y2={pad.t + ih} stroke="#8a8983" strokeDasharray="2 4" />
      <text x={x(budgetN) + 5} y={pad.t + ih - 8} fontSize="7.5" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">
        BUDGET {formatWon(ESTIMATE.budget)}
      </text>

      <polyline points={cp} fill="none" stroke="#8a8983" strokeWidth="1.5" />
      {DONE.map((r) => <circle key={r.n} cx={x(r.n)} cy={yc(totalCost(r.n))} r="3" fill="#fbfaf8" stroke="#8a8983" strokeWidth="1.5" />)}

      <polyline points={tp} fill="none" stroke="#e72d2d" strokeWidth="2.5" />
      {DONE.map((r) => <circle key={r.n} cx={x(r.n)} cy={y(r.throughput)} r="4" fill={r.n === ESTIMATE.recommended ? '#e72d2d' : '#fbfaf8'} stroke="#e72d2d" strokeWidth="2" />)}

      {REC && (
        <>
          <line x1={x(REC.n)} x2={x(REC.n)} y1={pad.t} y2={pad.t + ih} stroke="#e72d2d" strokeDasharray="3 3" />
          <text x={x(REC.n) + 6} y={pad.t + 12} fontSize="8" fontWeight="600" fill="#b51616" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">
            RECOMMENDED n{REC.n}
          </text>
        </>
      )}
    </svg>
  )
}

function UtilChart() {
  const W = 400
  const H = 300
  const pad = { l: 40, r: 16, t: 20, b: 34 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const bw = iw / RUNS.length

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 가동률과 통로 대기 비율">
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={pad.t + ih - (v / 100) * ih} y2={pad.t + ih - (v / 100) * ih} stroke="#e0ded9" />
          <text x={pad.l - 8} y={pad.t + ih - (v / 100) * ih + 3} textAnchor="end" fontSize="8" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">{v}%</text>
        </g>
      ))}
      {RUNS.map((r, i) => {
        const cx = pad.l + bw * i + bw / 2
        if (r.status !== 'DONE') {
          return (
            <g key={r.n}>
              <rect x={cx - bw * 0.3} y={pad.t} width={bw * 0.6} height={ih} fill="#e0ded9" opacity=".5" />
              <text x={cx} y={H - pad.b + 16} textAnchor="middle" fontSize="8" fill="#b7b5b0" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">n{r.n}</text>
            </g>
          )
        }
        const uh = r.utilization * ih
        const wh = Math.max(2, r.waitRatio * 10 * ih)
        const hl = r.n === ESTIMATE.recommended
        return (
          <g key={r.n}>
            <rect x={cx - bw * 0.3} y={pad.t + ih - uh} width={bw * 0.6} height={uh} fill={hl ? '#e72d2d' : '#3f3f3d'} />
            <rect x={cx - bw * 0.3} y={pad.t + ih - wh} width={bw * 0.6} height={wh} fill="#e0a01e" />
            <text x={cx} y={pad.t + ih - uh - 6} textAnchor="middle" fontSize="8" fontWeight="600" fill={hl ? '#b51616' : '#4a4a46'} fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">
              {Math.round(r.utilization * 100)}
            </text>
            <text x={cx} y={H - pad.b + 16} textAnchor="middle" fontSize="8" fill="#4a4a46" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">n{r.n}</text>
          </g>
        )
      })}
      <text x={pad.l} y={H - 4} fontSize="7.5" fill="#8a8983" fontFamily="DM Mono, Pretendard Variable, Pretendard, monospace">■ 가동률 &nbsp; ■ 통로 대기 비율 (×10)</text>
    </svg>
  )
}

function congestion(ratio) {
  if (ratio < 0.01) return ['ok', '원활']
  if (ratio < 0.03) return ['mid', '주의']
  return ['bad', '정체']
}

export default function QuoteStep() {
  const failed = RUNS.filter((r) => r.status !== 'DONE')
  return (
    <section className="step paper" id="quote">
      <div className="eyebrow red">
        <span className="live-dot" />
        04 — QUOTE
      </div>
      <h2>Choose on the curve.</h2>
      <p className="desc">목표 처리량을 만족하고 예산 안에 드는 최소 대수를 권장 구성으로 표시합니다.</p>

      <div className="q-head">
        <h3>SANTA FACTORY · QUOTATION</h3>
        <span className="mono">
          EST #{ESTIMATE.id} · {ESTIMATE.createdAt} · {WAREHOUSE.name} · {AMR_MODEL.model} · SEED {ESTIMATE.seed}
        </span>
      </div>

      <p className="q-sum">
        출고 피크 기준 시간당 <b>{ESTIMATE.targetThroughput}건</b>을 처리하려면{' '}
        <b className="rd">{AMR_MODEL.model} {REC.n}대</b>가 필요합니다. 예상 구축비용은{' '}
        <b>{formatWon(totalCost(REC.n))}</b>으로 예산 {formatWon(ESTIMATE.budget)} 이내입니다.
      </p>

      <div className="kpi">
        <div>
          <span className="k-label">RECOMMENDED FLEET</span>
          <strong>{REC.n}<span>대</span></strong>
          <em className="ok">목표 충족 · 예산 이내 최소 구성</em>
        </div>
        <div>
          <span className="k-label">EST. THROUGHPUT</span>
          <strong>{REC.throughput.toFixed(1)}<span>건/시</span></strong>
          <em>목표 {ESTIMATE.targetThroughput}건/시 대비 +{(REC.throughput - ESTIMATE.targetThroughput).toFixed(1)}</em>
        </div>
        <div>
          <span className="k-label">EST. CAPEX</span>
          <strong>{formatWon(totalCost(REC.n))}</strong>
          <em>단가 {formatWon(AMR_MODEL.price)} × {REC.n} + 구축비 {formatWon(ESTIMATE.baseCost)}</em>
        </div>
        <div>
          <span className="k-label">UTILIZATION · LEAD TIME</span>
          <strong>{Math.round(REC.utilization * 100)}<span>%</span></strong>
          <em>평균 주문 처리시간 {Math.floor(REC.leadTime / 60)}분 {REC.leadTime % 60}초</em>
        </div>
      </div>

      <div className="charts">
        <div>
          <h5>THROUGHPUT–COST CURVE</h5>
          <CurveChart />
          <p className="chart-cap">빨간 선 처리량 · 회색 선 구축비용 · 채워진 점 권장 구성</p>
        </div>
        <div>
          <h5>UTILIZATION · AISLE WAIT</h5>
          <UtilChart />
          <p className="chart-cap">회색 막대 = 결과 없는 run</p>
        </div>
      </div>

      <div className="tablewrap">
        <table className="q-table">
          <thead>
            <tr>
              <th>구성</th>
              <th>처리량 <span>건/시</span></th>
              <th>목표</th>
              <th>가동률</th>
              <th>평균 처리시간</th>
              <th>통로 혼잡</th>
              <th>이동거리 <span>m</span></th>
              <th>구축비용</th>
              <th>예산</th>
            </tr>
          </thead>
          <tbody>
            {RUNS.map((r) => {
              if (r.status !== 'DONE') {
                return (
                  <tr key={r.n} className="fail">
                    <td>{r.n}대</td>
                    <td colSpan={6}>결과 없음 · {r.error} <span>— RUNS 섹션에서 재실행</span></td>
                    <td>{formatWon(totalCost(r.n))}</td>
                    <td>{totalCost(r.n) <= ESTIMATE.budget ? '이내' : '초과'}</td>
                  </tr>
                )
              }
              const [cls, label] = congestion(r.waitRatio)
              const inBudget = totalCost(r.n) <= ESTIMATE.budget
              return (
                <tr key={r.n} className={r.n === ESTIMATE.recommended ? 'hl' : ''}>
                  <td>{r.n}대{r.n === ESTIMATE.recommended && <span> · 권장</span>}</td>
                  <td>{r.throughput.toFixed(1)}</td>
                  <td>{r.throughput >= ESTIMATE.targetThroughput ? '충족' : <span>미달</span>}</td>
                  <td>{Math.round(r.utilization * 100)}%</td>
                  <td>{Math.floor(r.leadTime / 60)}분 {r.leadTime % 60}초</td>
                  <td><i className={`cong ${cls}`} />{label} <span>{(r.waitRatio * 100).toFixed(1)}%</span></td>
                  <td>{r.distance.toLocaleString()}</td>
                  <td>{formatWon(totalCost(r.n))}</td>
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
              <li>창고 {WAREHOUSE.name} · {WAREHOUSE.width}×{WAREHOUSE.length} m · 랙 {WAREHOUSE.rackCount} · 스테이션 {WAREHOUSE.stationCount} · 도크 {WAREHOUSE.dockCount}</li>
              <li>작업자 4명 · 입고 01:00–09:00 (480건) · 출고 13:00–18:00 (500건) · 시드 {ESTIMATE.seed}</li>
              <li>AMR {AMR_MODEL.model} 단일 모델 · 속도 {AMR_MODEL.speedEmpty}/{AMR_MODEL.speedLoaded} m/s · 적재 {AMR_MODEL.capacity} · 충전 임계 {AMR_MODEL.chargeThreshold * 100}%</li>
              <li>구축비용 = 대당 {formatWon(AMR_MODEL.price)} × 대수 + 기본 구축비 {formatWon(ESTIMATE.baseCost)}. 유지보수·자재 관리비 제외</li>
              <li>재고는 항상 충분하다고 가정. 입고 검수·포장·배송 과정은 범위 외</li>
              <li>경로 계획 PIBT + 가중 다익스트라 · 1칸 = 1 m · 회전 포함 이동 모델</li>
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
                {failed.map((r) => `n${r.n}`).join(', ')} run은 결과가 없어 곡선에서 빠져 있습니다.
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
