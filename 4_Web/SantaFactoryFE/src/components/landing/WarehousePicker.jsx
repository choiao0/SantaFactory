import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FIRST_STEP_PATH } from '../../data/steps.js'
import { startFresh, startFromWarehouse } from '../../hooks/useEstimateDraft.js'
import { formatWon } from '../../utils/format.js'

/**
 * 저장된 조건으로 다시 견적을 낸다 (S15P21A106-274).
 *
 * <p>견적을 낼 때마다 창고 조건이 하나씩 저장되는데, 지금껏 그것을 다시 쓸 길이 없어 두 번째
 * 견적부터도 여섯 칸을 처음부터 다시 쳐야 했다. 저장된 조건을 고르면 그 창고 번호로 바로 견적을
 * 열 수 있다 — 견적 생성 API 가 이미 창고 번호를 받기 때문에 백엔드는 그대로다.
 *
 * <p>모델은 여기서 고른다. 자동으로 정하지 않는 규칙(S15P21A106-271)은 그대로 두되, 고르고 나면
 * 01 단계에 더 넣을 것이 없으므로 대수 범위로 바로 간다.
 */
export default function WarehousePicker({ warehouses, robots }) {
  const navigate = useNavigate()
  const [model, setModel] = useState(null)

  const go = (start) => {
    start()
    // 모델까지 골랐으면 01 에 남은 일이 없다. 안 골랐으면 01 에서 고르게 둔다
    navigate(model ? '/estimate/new/fleet' : FIRST_STEP_PATH)
  }

  return (
    <>
      <h3 className="admin-subhead">
        저장된 조건으로 견적 요청
        <span className="admin-count">{warehouses.items.length}개</span>
      </h3>
      <p className="mono dim lhint">조건을 선택하면 해당 조건으로 바로 견적을 시작합니다.</p>

      {robots.items.length > 0 && (
        <div className="mdlpick" role="group" aria-label="AMR 모델">
          <span className="mono dim">AMR 모델</span>
          {robots.items.map((m) => (
            <button
              key={m.model}
              type="button"
              className={`ghost sm${model === m.model ? ' on' : ''}`}
              aria-pressed={model === m.model}
              onClick={() => setModel((cur) => (cur === m.model ? null : m.model))}
            >
              {m.model}
            </button>
          ))}
          {/* 안 고르면 01 로 간다는 사실을 미리 알린다 — 눌러 봐야 아는 것보다 낫다 */}
          {model == null && <span className="mono dim">선택하지 않으면 01 단계에서 선택합니다.</span>}
        </div>
      )}

      {warehouses.error && <p className="form-error">저장된 조건을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>}

      <div className="admin-grid">
        {warehouses.items.map((w) => (
          <button
            type="button"
            key={w.warehouse_id}
            className="spec selectable admin-card"
            onClick={() => go(() => startFromWarehouse(w, model))}
          >
            <h4>{w.name || `조건 #${w.warehouse_id}`}</h4>
            <div className="sub">{w.area != null ? `${Math.round(w.area).toLocaleString()} ㎡` : '면적 미기재'}</div>
            <dl>
              <dt>일 출고</dt>
              <dd>{(w.outbound_avg ?? 0).toLocaleString()}<span>건</span></dd>
              <dt>목표 처리율</dt>
              <dd>{w.target_throughput ?? '—'}<span>%</span></dd>
              <dt>출고 시간대</dt>
              <dd className="admin-plain">{String(w.outbound_start ?? '').slice(0, 5)}–{String(w.outbound_end ?? '').slice(0, 5)}</dd>
              <dt>예산</dt>
              <dd className="admin-plain">{formatWon(w.budget_limit)}</dd>
            </dl>
          </button>
        ))}

        <button type="button" className="spec selectable admin-card newcond"
                onClick={() => go(() => startFresh(model))}>
          <h4>+ 새 조건</h4>
          <div className="sub">처음부터 입력</div>
        </button>
      </div>
    </>
  )
}
