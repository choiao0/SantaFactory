/**
 * 견적 흐름의 다섯 단계 (S15P21A106-274).
 *
 * 한 화면을 스크롤하던 구조를 단계마다 별개 페이지로 나누면서, "몇 번째 무엇인가"를 랜딩 안내와
 * 단계 내비가 각자 들고 있으면 언젠가 어긋난다. 한 곳에서 읽는다.
 *
 * 앞 둘은 아직 견적 번호가 없어 `/estimate/new/…`, 뒤 셋은 번호가 붙어 `/estimate/{id}/…` 로 간다.
 */
export const STEPS = [
  {
    key: 'warehouse', no: '01', title: '운영 조건', desc: '창고 조건과 예산', phase: 'new',
    what: '하루 출고량과 출고 시간대, 목표 처리율과 예산을 넣고 쓸 AMR 모델을 고릅니다.',
  },
  {
    key: 'fleet', no: '02', title: '대수 범위', desc: '비교할 AMR 대수', phase: 'new',
    what: '몇 대부터 몇 대까지 견줄지 정합니다. 정한 범위만큼 시뮬레이션이 따로따로 돌아갑니다.',
  },
  {
    key: 'runs', no: '03', title: '시뮬레이션', desc: '대수별 실행 결과', phase: 'run',
    what: '대수마다 하루치 주문을 실제로 돌립니다. 결과가 오는 대로 카드가 채워지고, 그 대수의 주행을 재생해 볼 수 있습니다.',
  },
  {
    key: 'verify', no: '04', title: '물리 검증', desc: '로봇 물리로 재현', phase: 'run',
    what: '권장 대수를 물리 엔진으로 한 번 더 돌려 로봇이 실제로 부딪히지 않고 도는지 확인하고, 그 장면을 영상으로 남깁니다.',
  },
  {
    key: 'quote', no: '05', title: '견적', desc: '적정 대수와 비용', phase: 'run',
    what: '권장 대수와 최소 구성, 대수별 비용 곡선을 한 장에 담습니다. 견적서는 PDF로 받거나 메일로 보낼 수 있습니다.',
  },
]

/** 견적 요청이 시작되는 곳. 랜딩·견적서에서 같은 자리로 보낸다. */
export const FIRST_STEP_PATH = '/estimate/new/warehouse'

/**
 * 그 단계로 가는 주소 — 갈 수 없으면 null.
 *
 * 번호가 없는 동안에는 뒤 세 단계로 갈 수 없다(보여줄 결과가 없다). 번호가 생긴 뒤에는 앞 두
 * 단계로 돌아갈 수 없다(이미 만들어진 견적이라 조건을 되돌릴 대상이 없다) — 그때 조건을 바꾸는
 * 길은 견적서의 "조건 바꿔 다시 요청"이고, 그것은 새 견적을 만든다.
 */
export function stepPath(step, estimateId) {
  if (step.phase === 'new') {
    return estimateId == null ? `/estimate/new/${step.key}` : null
  }
  return estimateId == null ? null : `/estimate/${estimateId}/${step.key}`
}
