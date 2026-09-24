import { useCallback, useEffect, useState } from 'react'

/** 입력 중인 조건을 담아 두는 자리. 회원이 바뀌면 AuthProvider 가 지운다. */
const KEY = 'estimateDraft'

const DEFAULT_FORM = {
  // 화면에서는 받지 않는다 — 시뮬 엔진이 아직 이 값을 쓰지 않는다
  // (FMS API 계약 문서: worker_count = 피커 작업 시간 모델, "로드맵 확정, 미구현").
  // 다만 창고 생성 API 가 여전히 필수(@NotNull)라 보내긴 해야 해서 기본값으로 남긴다.
  // 엔진이 실제로 반영하기 시작하면 입력 항목을 되살려야 한다.
  workerCount: 4,
  outboundStart: '13:00',
  outboundEnd: '18:00',
  // 실제 창고 조건은 사용자가 넣어야 하는 값이다 — 그럴듯한 기본값이 박혀 있으면 그대로 두고
  // 요청해 버려서, 나온 견적이 자기 창고 이야기가 아니게 된다
  outboundAvg: 0,
  targetThroughput: 0,
  targetUtilization: 0,
  budgetMan: 0,
}

const DEFAULT_FLEET = { min: 3, max: 15 }

/** 견적을 내려면 사용자가 채워야 하는 값. 기본값이 0 이라 빈 채로 요청하면 서버 검증에서 막힌다. */
const REQUIRED_FIELDS = [
  ['outboundAvg', '일 평균 출고 주문'],
  ['targetThroughput', '목표 출고 처리율'],
  ['targetUtilization', '목표 가동률'],
  ['budgetMan', '최대 구축 예산'],
]

const EMPTY = { form: DEFAULT_FORM, model: null, fleet: DEFAULT_FLEET }

/**
 * 저장해 둔 값을 읽되, 모양은 기본값으로 메운다 — 항목이 늘어난 뒤에 열린 옛 드래프트가
 * 빈 칸을 들고 오면 입력칸이 undefined 로 렌더돼 React 가 비제어 입력으로 바꿔 버린다.
 */
function load() {
  try {
    const saved = sessionStorage.getItem(KEY)
    if (!saved) return EMPTY
    const parsed = JSON.parse(saved)
    return {
      form: { ...DEFAULT_FORM, ...parsed.form },
      model: parsed.model ?? null,
      fleet: { ...DEFAULT_FLEET, ...parsed.fleet },
    }
  } catch {
    // 저장된 값이 깨졌으면 버린다 — 입력 한 번 다시 받는 편이 빈 화면보다 낫다
    return EMPTY
  }
}

export function clearEstimateDraft() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // 저장이 막힌 브라우저 — 지울 것도 없다
  }
}

/**
 * 입력 중인 견적 조건 (S15P21A106-274).
 *
 * 단계가 페이지로 갈리면서 01 에서 친 값이 02 로 넘어가야 하고, 새로고침해도 남아야 한다 —
 * 스크롤 한 장이던 때는 컴포넌트가 안 죽어서 저절로 되던 일이다.
 */
export function useEstimateDraft() {
  const [draft, setDraft] = useState(load)

  useEffect(() => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(draft))
    } catch {
      // 시크릿 모드 등 저장이 막힌 경우. 화면은 그대로 돌고 새로고침에만 약해진다
    }
  }, [draft])

  const patchForm = useCallback((patch) => setDraft((d) => ({ ...d, form: { ...d.form, ...patch } })), [])
  const setModel = useCallback((model) => setDraft((d) => ({ ...d, model })), [])
  const setFleet = useCallback((fleet) => setDraft((d) => ({ ...d, fleet })), [])

  return { ...draft, patchForm, setModel, setFleet }
}

/**
 * 아직 안 채운 필수 항목의 이름들.
 *
 * 모델도 입력값이다 — 안 고르면 견적을 낼 수 없으니 다른 미입력과 같이 막는다.
 */
export function missingFields(form, model) {
  return [
    ...REQUIRED_FIELDS.filter(([key]) => !(Number(form[key]) > 0)).map(([, label]) => label),
    ...(model == null ? ['AMR 모델'] : []),
  ]
}
