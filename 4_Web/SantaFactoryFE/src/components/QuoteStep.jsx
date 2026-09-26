import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FIRST_STEP_PATH } from '../data/steps.js'
import { downloadQuotePdf, emailQuote } from '../api/estimates.js'
import { formatDateTime, formatEok, formatPercent, formatWon } from '../utils/format.js'

const MONO = 'DM Mono, Pretendard Variable, Pretendard, monospace'
const GRID_LINE = '#e0ded9'
const MUTED = '#8a8983'
const RED = '#e72d2d'
/** 최소 구성 표식 — 권장(빨강)과 다른 축이라 색도 다르게 둔다. 종이 바탕에서 읽히는 노랑이다 */
const AMBER = '#d99a00'
const AMBER_DARK = '#8f6503'
/** 표식 글자 폭 어림값 — 어느 쪽에 쓸지, 두 글자가 겹치는지 판단할 때만 쓴다 */
const MIN_LABEL_W = 92
const REC_LABEL_W = 62
const FULL_LABEL_W = 78
/** 가동률 막대 기본색 — 권장 구성만 RED 로 덮어 칠한다 */
const BAR = '#3f3f3d'
/** 차트 배경(종이) — 점 안쪽을 채워 선 위에 띄울 때 쓴다 */
const PAPER = '#fbfaf8'
/** 권장 대수 표식의 바깥 링 반지름 — RECOMMENDED 점선이 여기서 끊긴다 */
const MARK_R = 13

/**
 * 표식 반지름 — 대수 한 칸 간격에 맞춰 줄인다. 대수 범위가 넓으면 칸 간격이 좁아져, 고정 크기로는
 * 권장과 최소 구성이 나란히 있을 때 두 원이 겹쳐 하나처럼 보인다.
 *
 * <p>최소 구성은 한 치수 더 작게 둔다. 주된 답은 권장이라 둘 중 양보할 쪽은 이쪽이고, 크기가
 * 다르면 겹치기 직전까지 가도 어느 쪽이 권장인지 헷갈리지 않는다.
 *
 * @param gap 대수 한 칸의 가로 간격(px)
 */
function markRadius(gap) {
  const outer = Math.max(7, Math.min(MARK_R, gap * 0.55))
  return { rec: outer, min: outer - 4 }
}
const EOK = 100_000_000

const REASON_TEXT = {
  BUDGET_EXCEEDED: '예산 안에 드는 대수가 없습니다. 예산을 올리거나 목표를 낮춰 다시 요청해 보세요.',
  THROUGHPUT_SHORT: '예산 안의 대수로는 목표 출고 처리율에 닿지 않습니다. 목표를 낮추거나 예산을 올려야 합니다.',
  UTILIZATION_SHORT: '목표 처리율은 채우지만 그 대수의 AMR 가동률이 목표에 못 미칩니다. 가동률 목표를 조정해 보세요.',
  LEAD_TIME_LONG: '주문은 목표만큼 나가지만 한 건이 끝나기까지 걸리는 시간이 상한을 넘습니다. 대수를 늘리거나 리드타임 상한을 완화해야 합니다.',
  ALL_FAILED: '모든 대수의 시뮬레이션이 실패해 판정할 결과가 없습니다. 조건을 확인한 뒤 다시 요청해 주세요.',
  // 더 이상 만들어지지 않는 사유 — 예전에 판정한 견적을 열었을 때를 위해 남겨 둔다
  LOAD_TOO_LOW: '모든 대수가 처리율 100%를 기록해 대수를 구분할 수 없습니다. 주문량이 너무 적거나 시뮬 실행 조건을 확인해야 합니다.',
}

function isDone(run) {
  return run.status === 'DONE' && run.throughput != null
}

/**
 * 이 대수가 목표를 통과했나 — 처리율·가동률·예산을 모두 본다. 표의 목표 칸과 같은 판정이라
 * 그래프에서 색이 찬 점 = 표에서 달성인 행이 된다.
 *
 * <p>리드타임 상한은 화면이 모른다(서버 설정). 지금은 미설정이라 판정에 쓰이지 않지만, 켜지면
 * 최소 구성이 여기서 고른 것보다 오른쪽일 수 있다 — 표식은 서버가 준 값을 그대로 쓴다.
 */
function meetsGoal(run, estimate) {
  return isDone(run)
    && run.utilization != null
    && run.throughput >= estimate.target_throughput
    && run.utilization >= estimate.target_utilization
    && run.total_cost != null && run.total_cost <= estimate.budget_limit
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

/**
 * 효율 점수 = 처리율 × 가동률 (둘 다 0~100 이라 결과도 같은 축에 얹힌다).
 *
 * <p>대수가 적으면 처리율이 낮아 점수가 낮고, 많으면 가동률이 떨어져 다시 낮아진다 — 그래서 곡선에
 * 봉우리가 생기고, 그 꼭대기가 백엔드가 고른 권장 대수와 같은 자리다. 처리율만 그리면 포화한 뒤
 * 평평해서 "어디까지 사면 되는가"가 그림에 나타나지 않는다.
 *
 * <p>권장 대수 자체는 백엔드가 준 값을 그대로 쓴다 — 화면에서 다시 계산하지 않는다.
 */
function efficiencyScore(run) {
  if (!isDone(run) || run.utilization == null) return null
  return (run.throughput * run.utilization) / 100
}

/** 대수가 많으면(최대 28) x축 라벨이 겹친다 — 일정 간격만 찍되 강조할 대수는 항상 찍는다. */
function tickIndexes(runs, keepIndex) {
  const every = Math.max(1, Math.ceil(runs.length / 10))
  return runs.map((_, i) => i).filter((i) => i % every === 0 || i === keepIndex)
}

function CurveChart({ runs, estimate, budget, recommended, minimal, knee }) {
  const W = 560
  const H = 300
  const pad = { l: 42, r: 66, t: 20, b: 34 }   // r 은 구축비 눈금 + (BUDGET) 라벨 자리
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

  const scored = done.filter((r) => efficiencyScore(r) != null)
  const recMark = scored.find((r) => r.amr_count === recommended) != null
    ? efficiencyScore(scored.find((r) => r.amr_count === recommended))
    : null
  const { rec: markR, min: minMarkR } = markRadius(iw / span)
  const minRun = scored.find((r) => r.amr_count === minimal) ?? null
  // 최소 구성은 목표를 만족하는 가장 적은 대수라 언제나 권장보다 왼쪽이거나 같다
  const showMin = minimal != null && minimal !== recommended && minRun != null
  const recRight = recommended != null && x(recommended) > pad.l + iw * 0.7
  const minLeft = showMin && x(minimal) - 6 - MIN_LABEL_W >= pad.l
  /**
   * 두 표식 글자는 같은 줄에 앉혀 높이를 맞춘다. 다만 둘 다 제 점선 왼쪽에 쓰는데 대수가 붙어
   * 있으면 권장 글자가 최소 구성 글자를 덮는다 — 그때만 최소 구성을 한 줄 올린다.
   */
  const minRow = minLeft && recRight && x(recommended) - x(minimal) < REC_LABEL_W + 8 ? 1 : 0
  const labelY = (row) => pad.t + ih - 8 - row * 18
  const ep = scored.map((r) => `${x(r.amr_count)},${y(efficiencyScore(r))}`).join(' ')
  const cp = runs.filter((r) => r.total_cost != null).map((r) => `${x(r.amr_count)},${yc(r.total_cost)}`).join(' ')
  const recIndex = runs.findIndex((r) => r.amr_count === recommended)
  const visible = new Set(tickIndexes(runs, recIndex))

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 효율 점수와 구축비용 곡선">
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
      <text x={pad.l} y={H - 4} fontSize="7.5" fill={MUTED} fontFamily={MONO}>AMR 대수 →</text>
      <text x={pad.l - 40} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>효율</text>
      <text x={W - pad.r + 8} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>구축비</text>

      {budget <= costMax && (
        <>
          <line x1={pad.l} x2={W - pad.r} y1={yc(budget)} y2={yc(budget)} stroke={MUTED} strokeDasharray="2 4" />
          {/* 그래프 안에 적으면 구축비 선이 지나가 글자가 뭉갠다 — 구축비 눈금 오른쪽에 붙인다.
              금액은 같은 높이의 눈금이 말해 주므로 여기선 이름만 */}
          <text x={W - pad.r + 24} y={yc(budget) + 3} fontSize="7" fill={MUTED} fontFamily={MONO}>(예산)</text>
        </>
      )}

      <polyline points={cp} fill="none" stroke={MUTED} strokeWidth="1.5" />
      {runs.filter((r) => r.total_cost != null).map((r) => (
        <circle key={r.run_id} cx={x(r.amr_count)} cy={yc(r.total_cost)} r="3" fill={PAPER} stroke={MUTED} strokeWidth="1.5" />
      ))}

      {/* 효율 점수 = 처리율 × 가동률. 처리율만 그리면 포화 뒤 평평해서 "어디까지 사면 되는가"가
          그림에 안 나타난다 — 점수는 봉우리를 만들고 그 꼭대기가 곧 권장 대수다 */}
      <polyline points={ep} fill="none" stroke={RED} strokeWidth="2.5" />
      {/* 목표를 못 넘은 대수는 회색 빈 점 — 처리율 곡선과 같은 판정, 같은 표시다. 효율 점수가
          높아도 목표에 걸려 후보에서 빠진 대수가 있어, 색이 없으면 봉우리 왼쪽이 다 후보처럼 보인다 */}
      {scored.filter((r) => r.amr_count !== recommended && !(showMin && r.amr_count === minimal)).map((r) => (
        <circle key={r.run_id} cx={x(r.amr_count)} cy={y(efficiencyScore(r))} r="4"
                fill={PAPER} stroke={meetsGoal(r, estimate) ? RED : '#b7b5b0'} strokeWidth="2" />
      ))}
      {/* 최소 구성 표식 — 권장과 같은 모양, 색만 다르다. 모양까지 다르면 둘이 같은 종류의
          표식이라는 게 안 보이고, 색이 같으면 어느 쪽이 권장인지 헷갈린다 */}
      {showMin && (
        <g>
          <circle cx={x(minimal)} cy={y(efficiencyScore(minRun))} r={minMarkR} fill={PAPER} />
          <circle cx={x(minimal)} cy={y(efficiencyScore(minRun))} r={minMarkR} fill="none" stroke={AMBER} strokeWidth="2.2" />
          <circle cx={x(minimal)} cy={y(efficiencyScore(minRun))} r={minMarkR * 0.45} fill={PAPER} stroke={AMBER} strokeWidth="2" />
        </g>
      )}
      {/* 권장 대수 표식 — 흰 원반으로 곡선을 끊어 점을 띄우고, 그 위에 링과 가운데 점을 겹친다.
          같은 색 점을 키우기만 하면 선에 묻혀서 어느 대수인지 눈에 안 들어온다 */}
      {scored.filter((r) => r.amr_count === recommended).map((r) => {
        // markR 은 아래 RECOMMENDED 점선이 어디서 끊길지도 정한다
        const cy = y(efficiencyScore(r))
        const cx = x(r.amr_count)
        return (
          <g key={`${r.run_id}-mark`}>
            <circle cx={cx} cy={cy} r={markR} fill={PAPER} />
            <circle cx={cx} cy={cy} r={markR} fill="none" stroke={RED} strokeWidth="2.5" />
            <circle cx={cx} cy={cy} r={markR * 0.46} fill={PAPER} stroke={RED} strokeWidth="2" />
          </g>
        )
      })}

      {knee != null && knee !== recommended && (
        <>
          <line x1={x(knee)} x2={x(knee)} y1={pad.t} y2={pad.t + ih} stroke={MUTED} strokeDasharray="3 3" />
          <text x={x(knee) + 6} y={pad.t + ih - 20} fontSize="7.5" fill={MUTED} fontFamily={MONO}>변곡 {knee}대</text>
        </>
      )}
      {showMin && (
        <>
          <line x1={x(minimal)} x2={x(minimal)} y1={y(efficiencyScore(minRun)) + minMarkR} y2={pad.t + ih}
                stroke={AMBER} strokeDasharray="3 3" />
          {/* 제 점선의 왼쪽에 붙인다 — 최소 구성은 언제나 권장보다 왼쪽이라, 오른쪽에 쓰면 글자가
              두 점선 사이로 들어가 권장 쪽으로 밀려 보인다. 왼쪽에 자리가 없을 때만 넘긴다 */}
          <text x={x(minimal) + (minLeft ? -6 : 6)} y={labelY(minRow)}
                textAnchor={minLeft ? 'end' : 'start'}
                fontSize="11" fontWeight="700" fill={AMBER_DARK} fontFamily={MONO}>
            최소 구성 {minimal}대
          </text>
        </>
      )}
      {recommended != null && (
        <>
          {/* 표식을 관통하지 않도록 바깥 링 아래에서 시작한다 — 점이 어느 대수인지 끌어 주기만 하면 된다 */}
          <line x1={x(recommended)} x2={x(recommended)}
                y1={recMark != null ? y(recMark) + markR : pad.t} y2={pad.t + ih}
                stroke={RED} strokeDasharray="3 3" />
          <text x={x(recommended) + (recRight ? -6 : 6)} y={labelY(0)}
                textAnchor={recRight ? 'end' : 'start'}
                fontSize="11" fontWeight="700" fill="#b51616" fontFamily={MONO}>
            권장 {recommended}대
          </text>
        </>
      )}
    </svg>
  )
}

/**
 * 처리율 곡선 — 최소 구성이 왜 그 대수인지 보여 주는 그림. 효율 곡선은 봉우리로 권장을 설명하지만
 * 최소 구성은 설명하지 못한다. 여기서는 목표선을 처음 넘는(그리고 색이 찬) 점이 곧 최소 구성이다.
 *
 * <p>점이 목표선 위에 있어도 가동률이나 예산에서 떨어질 수 있다 — 그런 대수는 회색 빈 점으로
 * 둔다. 처리율만 보고 "목표선 넘은 첫 점 = 최소 구성"으로 읽으면 가동률이 발목을 잡는 견적에서
 * 틀린다 (전 대수 처리율 100 % 인데 가동률 미달로 권장이 없던 견적이 있었다).
 */
function ThroughputChart({ runs, estimate, budget, minimal, recommended }) {
  const W = 560
  const H = 300
  const pad = { l: 42, r: 66, t: 20, b: 34 }
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
  const minRun = done.find((r) => r.amr_count === minimal) ?? null
  /**
   * 빨간 표식 하나 — 하루 주문을 다 빼는 첫 대수(전량 처리). 어느 대수도 100 %에 닿지 않는 견적에는
   * 그 점이 없으므로 대신 권장을 찍는다. 처리율 그림에 표식이 최소 구성 하나뿐이면 그 대수가 왜
   * 최소인지(오른쪽이 무엇인지)를 견줄 데가 없다.
   */
  const { rec: markR, min: minMarkR } = markRadius(iw / span)
  const fullRun = done.find((r) => r.throughput >= 99.95) ?? null
  const peak = fullRun ?? done.find((r) => r.amr_count === recommended) ?? null
  const peakLabel = fullRun != null ? '전량 처리' : '권장'
  const showFull = peak != null
  const full = peak
  /**
   * 빨간 표식과 같은 대수면 최소 구성 표식은 그리지 않는다 — 한 자리에 표식이 둘이면 어느 기준으로
   * 고른 대수인지가 흐려진다. 표의 칩과 같은 규칙이다.
   */
  const showMin = minRun != null && (peak == null || peak.amr_count !== minRun.amr_count)
  const minLeft = showMin && x(minimal) - 6 - MIN_LABEL_W >= pad.l
  const fullLeft = showFull && x(full.amr_count) - 6 - FULL_LABEL_W >= pad.l
  const labelY = (row) => pad.t + ih - 8 - row * 18
  // 둘 다 제 점선 왼쪽에 쓰므로, 대수가 붙어 있으면 전량 처리 글자가 최소 구성 글자를 덮는다
  const fullRow = showFull && minLeft && fullLeft
    && x(full.amr_count) - x(minimal) < FULL_LABEL_W + 8 ? 1 : 0
  const visible = new Set(tickIndexes(runs, runs.findIndex((r) => r.amr_count === minimal)))

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AMR 대수별 주문 처리율 곡선">
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke={GRID_LINE} />
          <text x={pad.l - 8} y={y(v) + 3} textAnchor="end" fontSize="8" fill={MUTED} fontFamily={MONO}>{v}</text>
        </g>
      ))}
      {runs.filter((_, i) => visible.has(i)).map((r) => (
        <text key={r.run_id} x={x(r.amr_count)} y={H - pad.b + 16} textAnchor="middle" fontSize="8"
              fill={isDone(r) ? '#4a4a46' : '#b7b5b0'} fontFamily={MONO}>
          {r.amr_count}
        </text>
      ))}
      <text x={pad.l} y={H - 4} fontSize="7.5" fill={MUTED} fontFamily={MONO}>AMR 대수 →</text>
      <text x={pad.l - 40} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>처리율</text>
      <text x={W - pad.r + 8} y={pad.t - 6} fontSize="7.5" fill={MUTED} fontFamily={MONO}>구축비</text>

      {/* 효율 곡선과 같은 비용 축·예산선을 쓴다 — 두 화면을 오가며 같은 금액을 읽게 된다 */}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <text key={f} x={W - pad.r + 8} y={yc(costMax * f) + 3} fontSize="8" fill={MUTED} fontFamily={MONO}>
          {formatEok(costMax * f)}
        </text>
      ))}
      {budget <= costMax && (
        <>
          <line x1={pad.l} x2={W - pad.r} y1={yc(budget)} y2={yc(budget)} stroke={MUTED} strokeDasharray="2 4" />
          <text x={W - pad.r + 24} y={yc(budget) + 3} fontSize="7" fill={MUTED} fontFamily={MONO}>(예산)</text>
        </>
      )}

      <polyline points={cp} fill="none" stroke={MUTED} strokeWidth="1.5" />
      {runs.filter((r) => r.total_cost != null).map((r) => (
        <circle key={r.run_id} cx={x(r.amr_count)} cy={yc(r.total_cost)} r="3" fill={PAPER} stroke={MUTED} strokeWidth="1.5" />
      ))}

      <polyline points={tp} fill="none" stroke={RED} strokeWidth="2.5" />
      {done.filter((r) => !(showMin && r.amr_count === minimal) && !(showFull && r.amr_count === full.amr_count)).map((r) => {
        const ok = meetsGoal(r, estimate)
        return (
          <circle key={r.run_id} cx={x(r.amr_count)} cy={y(r.throughput)} r="4"
                  fill={PAPER} stroke={ok ? RED : '#b7b5b0'} strokeWidth="2" />
        )
      })}

      {showFull && (
        <g>
          <circle cx={x(full.amr_count)} cy={y(full.throughput)} r={markR} fill={PAPER} />
          <circle cx={x(full.amr_count)} cy={y(full.throughput)} r={markR} fill="none" stroke={RED} strokeWidth="2.5" />
          <circle cx={x(full.amr_count)} cy={y(full.throughput)} r={markR * 0.46} fill={PAPER} stroke={RED} strokeWidth="2" />
        </g>
      )}
      {showMin && (
        <g>
          <circle cx={x(minimal)} cy={y(minRun.throughput)} r={minMarkR} fill={PAPER} />
          <circle cx={x(minimal)} cy={y(minRun.throughput)} r={minMarkR} fill="none" stroke={AMBER} strokeWidth="2.2" />
          <circle cx={x(minimal)} cy={y(minRun.throughput)} r={minMarkR * 0.45} fill={PAPER} stroke={AMBER} strokeWidth="2" />
        </g>
      )}

      {showFull && (
        <>
          <line x1={x(full.amr_count)} x2={x(full.amr_count)} y1={y(full.throughput) + markR} y2={pad.t + ih}
                stroke={RED} strokeDasharray="3 3" />
          <text x={x(full.amr_count) + (fullLeft ? -6 : 6)} y={labelY(fullRow)}
                textAnchor={fullLeft ? 'end' : 'start'}
                fontSize="11" fontWeight="700" fill="#b51616" fontFamily={MONO}>
            {peakLabel} {full.amr_count}대
          </text>
        </>
      )}
      {showMin && (
        <>
          <line x1={x(minimal)} x2={x(minimal)} y1={y(minRun.throughput) + minMarkR} y2={pad.t + ih}
                stroke={AMBER} strokeDasharray="3 3" />
          <text x={x(minimal) + (minLeft ? -6 : 6)} y={labelY(0)} textAnchor={minLeft ? 'end' : 'start'}
                fontSize="11" fontWeight="700" fill={AMBER_DARK} fontFamily={MONO}>
            최소 구성 {minimal}대
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
            <rect x={cx - bw * 0.3} y={pad.t + ih - uh} width={bw * 0.6} height={uh} fill={hl ? RED : BAR} />
            {hl && (
              <text x={cx} y={pad.t + ih - uh - 6} textAnchor="middle" fontSize="8" fontWeight="600" fill="#b51616" fontFamily={MONO}>
                {Math.round(r.utilization)}
              </text>
            )}
            {label}
          </g>
        )
      })}
    </svg>
  )
}

function Placeholder({ estimateId, estimate }) {
  if (estimateId == null) {
    return <div className="q-empty">견적을 요청하면 리포트가 여기에 표시됩니다.</div>
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

/**
 * 견적서 PDF 저장·메일 전송 (S15P21A106-236). 둘 다 백엔드가 만든 같은 문서다 — 저장은 파일로 받고,
 * 메일은 로그인 계정 이메일로 간다. 계산이 끝나기 전엔 서버가 409 를 주므로 버튼을 막아 둔다.
 */
function QuoteActions({ estimateId, finished }) {
  const [busy, setBusy] = useState(null) // null | 'pdf' | 'mail'
  const [message, setMessage] = useState(null)

  const run = async (kind, action, doneText) => {
    setBusy(kind)
    setMessage(null)
    try {
      await action()
      setMessage({ ok: true, text: doneText })
    } catch (e) {
      setMessage({ ok: false, text: e.message ?? '요청에 실패했습니다.' })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="printrow">
      <button
        type="button"
        className="button"
        disabled={!finished || busy !== null}
        onClick={() => run('pdf', () => downloadQuotePdf(estimateId), '견적서를 저장했습니다.')}
      >
        {busy === 'pdf' ? '견적서 만드는 중…' : '견적서 PDF 저장 ↗'}
      </button>
      <button
        type="button"
        className="ghost"
        disabled={!finished || busy !== null}
        onClick={() => run('mail', () => emailQuote(estimateId), '가입한 이메일로 견적서를 보냈습니다. 잠시 후 메일함을 확인하세요.')}
      >
        {busy === 'mail' ? '보내는 중…' : '메일로 받기'}
      </button>
      <Link className="ghost" to={FIRST_STEP_PATH}>조건 바꿔 다시 요청</Link>
      {message && (
        <span className="mono" style={{ fontSize: 13, color: message.ok ? '#1c7c4f' : '#b51616' }}>{message.text}</span>
      )}
    </div>
  )
}

/** 권장을 고르는 점수와 같은 식 — 표에도 같은 값을 보여야 그래프의 봉우리를 표에서 확인할 수 있다. */
function efficiency(r) {
  return (r.throughput * r.utilization) / 100
}

/**
 * 목표 칸 — 처리율과 가동률을 <b>둘 다</b> 넘어야 달성이다. 예전에는 처리율만 보고 찍었는데, 칸 이름이
 * 그냥 '목표' 라 가동률이 한참 모자란 구성도 달성으로 읽혔다. 못 넘은 쪽을 이름으로 적어 어디가 모자란지
 * 바로 보이게 한다. 칸은 머리글까지 통째로 가운데 정렬이라, 길이가 다른 '달성' 도 같은 축에 선다.
 */
function GoalCell({ run, estimate }) {
  const slow = run.throughput < estimate.target_throughput
  const idle = run.utilization < estimate.target_utilization
  if (!slow && !idle) {
    return <td className="goal met">달성</td>
  }
  const short = [slow && '처리율', idle && '가동률'].filter(Boolean).join('·')
  return <td className="goal"><span>{short} 미달</span></td>
}

export default function QuoteStep({ estimateId, estimate, verdict }) {
  const [curveView, setCurveView] = useState('eff')
  const ready = Boolean(estimate && verdict)
  const runs = estimate?.runs ?? []
  const recommended = verdict?.recommended_count ?? null
  const rec = runs.find((r) => r.amr_count === recommended) ?? null
  // 최소 구성 — 권장과 같은 조건을 통과한 것 중 가장 적은 대수. 권장과 같으면 표식을 하나로 합친다
  const minimal = verdict?.minimal_count ?? null
  const min = runs.find((r) => r.amr_count === minimal) ?? null
  // 하루 주문을 다 빼는 첫 대수 — 권장과 같은 대수면 표식을 따로 달지 않는다
  const fullCount = runs.find((r) => isDone(r) && r.throughput >= 99.95)?.amr_count ?? null
  const saving = rec && min && minimal !== recommended ? rec.total_cost - min.total_cost : null
  const effLoss = saving == null ? null : efficiency(rec) - efficiency(min)
  const cancelled = verdict?.status === 'CANCELLED'

  return (
    <section className="step paper" id="quote">
      <div className="eyebrow red">
        <span className="live-dot" />
        05 — 견적
      </div>
      {!ready && <Placeholder estimateId={estimateId} estimate={estimate} />}

      {ready && (
        <>
          <div className="q-head">
            <h3>SANTA FACTORY · 견적서</h3>
            <span className="mono">
              {formatDateTime(estimate.created_at)} · AMR : {estimate.amr_model}
            </span>
          </div>

          {cancelled && <div className="notice">이 견적은 취소되었습니다. 조건을 바꿔 다시 요청해 주세요.</div>}

          {!cancelled && rec && (
            <>
              <p className="q-sum">
                목표 출고 처리율 <b>{estimate.target_throughput}%</b>를 만족하면서 효율(처리율 × 가동률)이
                가장 높은 구성은 <b className="rd">{estimate.amr_model} {rec.amr_count}대</b>입니다.
                예상 구축비용은 <b>{formatWon(rec.total_cost)}</b>으로 예산{' '}
                {formatWon(estimate.budget_limit)} 이내입니다.
                {verdict.knee_count != null && verdict.knee_count !== rec.amr_count && (
                  <> {verdict.knee_count}대부터는 대수를 늘려도 처리율이 거의 오르지 않습니다.</>
                )}
              </p>

              <div className="kpi">
                <div>
                  <span className="k-label">권장 대수</span>
                  <strong>{rec.amr_count}<span>대</span></strong>
                  <em className="ok">목표 달성 · 예산 이내 · 효율 최고</em>
                </div>
                <div>
                  <span className="k-label">처리율</span>
                  <strong>{formatPercent(rec.throughput)}<span>%</span></strong>
                  <em>목표 {estimate.target_throughput}% 대비 +{formatPercent(rec.throughput - estimate.target_throughput)}p</em>
                </div>
                <div>
                  <span className="k-label">구축비용</span>
                  <strong>{formatWon(rec.total_cost)}</strong>
                  <em>예산 {formatWon(estimate.budget_limit)} 중 {Math.round((rec.total_cost / estimate.budget_limit) * 100)}%</em>
                </div>
                <div>
                  <span className="k-label">가동률</span>
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
                  {/* 두 그림이 각자 다른 표식을 설명한다 — 효율 곡선의 봉우리가 권장, 처리율
                      곡선에서 목표선을 처음 넘는(색이 찬) 점이 최소 구성이다 */}
                  <div className="chart-head">
                    <h5>{curveView === 'eff' ? '효율–비용 곡선' : '처리율 곡선'}</h5>
                    <div className="chart-toggle" role="group" aria-label="곡선 기준">
                      {[['eff', '효율'], ['thr', '처리율']].map(([key, text]) => (
                        <button key={key} type="button" className={curveView === key ? 'on' : ''}
                                aria-pressed={curveView === key} onClick={() => setCurveView(key)}>
                          {text}
                        </button>
                      ))}
                    </div>
                  </div>
                  {curveView === 'eff' ? (
                    <CurveChart
                      runs={runs}
                      estimate={estimate}
                      budget={estimate.budget_limit}
                      recommended={recommended}
                      minimal={minimal}
                      knee={verdict.knee_count}
                    />
                  ) : (
                    <ThroughputChart runs={runs} estimate={estimate} budget={estimate.budget_limit}
                                     minimal={minimal} recommended={recommended} />
                  )}
                  <p className="chart-cap">
                    {/* 선 색을 말로 적으면 어느 선인지 짚기 어렵다 — 실제 칠하는 색을 그대로 보여준다 */}
                    {curveView === 'eff' ? (
                      <>
                        <i style={{ background: RED }} />효율 (처리율 × 가동률)
                        <i style={{ background: MUTED }} />구축비용
                        <i style={{ background: '#b7b5b0' }} />목표 미달
                        <br />
                        효율이 가장 높은 대수를 권장 구성으로{minimal != null && minimal !== recommended
                          ? ', 목표를 만족하는 가장 적은 대수를 최소 구성으로' : ''} 표시합니다
                      </>
                    ) : (
                      <>
                        <i style={{ background: RED }} />주문 처리율
                        <i style={{ background: MUTED }} />구축비용
                        <i style={{ background: '#b7b5b0' }} />목표 미달
                        <br />
                        목표를 만족하는 가장 적은 대수를 최소 구성으로 표시합니다. 회색 점은 처리율·가동률·예산 중
                        하나라도 못 넘은 대수입니다
                      </>
                    )}
                  </p>
                </div>
                <div>
                  <h5>가동률</h5>
                  <UtilChart runs={runs} target={estimate.target_utilization} recommended={recommended} />
                  <p className="chart-cap">
                    {/* 막대 색을 말로 적으면 어느 막대인지 짚기 어렵다 — 실제 칠하는 색을 그대로 보여준다 */}
                    <i style={{ background: BAR }} />가동률
                    <i style={{ background: RED }} />권장 구성
                    <i style={{ background: GRID_LINE, border: '1px solid #c9c7c2' }} />측정값 없음
                    <br />
                    대수가 많으면 x축 라벨은 일부만 표시됩니다
                  </p>
                </div>
              </div>

              <div className="tablewrap">
                <table className="q-table">
                  <thead>
                    <tr>
                      <th>구성</th>
                      <th>처리율</th>
                      <th>가동률</th>
                      <th className="goal">목표</th>
                      <th>효율 <span>처리율 × 가동률</span></th>
                      <th>처리 완료 <span>건/일</span></th>
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
                            <td colSpan={5}>{r.status} · 결과 없음{r.error ? ` · ${r.error}` : ''}</td>
                            <td>{formatWon(r.total_cost)}</td>
                            <td>{inBudget ? '이내' : '초과'}</td>
                          </tr>
                        )
                      }
                      return (
                        <tr key={r.run_id} className={r.amr_count === recommended ? 'hl' : ''}>
                          {/* 표식이 겹치면 권장만 남긴다 — 한 행에 이름이 둘 이상 붙으면 어느 기준으로
                              고른 대수인지가 흐려진다 */}
                          <td>
                            {r.amr_count}대
                            {r.amr_count === recommended && <span className="rec-chip">권장</span>}
                            {r.amr_count !== recommended && r.amr_count === minimal && (
                              <span className="rec-chip min">최소 구성</span>
                            )}
                            {r.amr_count !== recommended && r.amr_count === fullCount && (
                              <span className="rec-chip min">전량 처리</span>
                            )}
                          </td>
                          <td>{formatPercent(r.throughput)}%</td>
                          <td>{formatPercent(r.utilization)}%</td>
                          <GoalCell run={r} estimate={estimate} />
                          <td>{formatPercent(efficiency(r))}</td>
                          <td>{r.outbound != null ? r.outbound.toLocaleString() : '—'}</td>
                          <td>{formatWon(r.total_cost)}</td>
                          <td>{inBudget ? '이내' : <span>초과</span>}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* 표에 대수를 두 개 표시했으면, 그 둘을 왜 나눠 놓았는지 한 줄로 말한다 */}
              {saving != null && (
                <p className="table-note">
                  <b>최소 구성</b>은 목표를 만족하는 가장 적은 대수로, {minimal}대({formatWon(min.total_cost)})는
                  권장보다 {formatWon(saving)} 적지만 효율 {formatPercent(efficiency(min))}%로
                  권장보다 {formatPercent(effLoss)}%p 안 좋습니다.
                </p>
              )}
              {saving == null && minimal != null && (
                <p className="table-note">
                  목표를 만족하는 가장 적은 대수가 권장 구성과 같습니다 — 더 줄일 여지가 없습니다.
                </p>
              )}
            </>
          )}

          <div className="q-two">
            <div>
              <h4>구축비용</h4>
              <div className="notice">
                (단가 + 설치비) × 대수 + 충전기(4대당 1기)로 계산합니다.
                유지보수비와 자재 관리비는 포함되지 않습니다.
              </div>
            </div>
          </div>

          <QuoteActions estimateId={estimateId} finished={verdict.status === 'DONE' || verdict.status === 'PARTIAL'} />
        </>
      )}
    </section>
  )
}
