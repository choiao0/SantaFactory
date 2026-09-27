import { formatDateTime } from '../../utils/format.js'

/** 지금까지 쌓인 것을 네 칸으로 (S15P21A106-274). 값이 없는 칸은 칸 자체를 빼 자리를 비우지 않는다. */
export default function MyStats({ recent, warehouses }) {
  const last = recent.items[0] ?? null
  const cells = [
    ['요청한 견적', recent.total, '건'],
    ['저장된 조건', warehouses.items.length, '개'],
    recent.lastDone && ['최근 권장 대수', recent.lastDone.recommended_count, '대'],
    // 연도는 뺀다 — 큰 숫자 칸이라 'YYYY-MM-DD' 는 두 줄로 깨진다
    last && ['마지막 요청', formatDateTime(last.created_at).slice(5, 10).replace('-', '.'), ''],
  ].filter(Boolean)

  return (
    <div className="kpi lstats">
      {cells.map(([label, value, unit]) => (
        <div key={label}>
          <span className="k-label">{label}</span>
          <strong>{value}{unit && <span>{unit}</span>}</strong>
        </div>
      ))}
    </div>
  )
}
