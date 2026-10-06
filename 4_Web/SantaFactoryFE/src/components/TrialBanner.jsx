import { useTrialMode } from '../trial/trialContext.js'

/**
 * 체험판 안내 (S15P21A106-283) — 모든 화면 맨 위, 헤더보다 위에 둔다.
 *
 * 본선 뒤 공개 링크는 서버 비용 때문에 새 견적·3D 주행 검증을 받지 않는다. 버튼만 숨기면 왜 없는지
 * 모르니 처음부터 데모라는 것과 그 이유를 밝히고 양해를 구한다. 닫기 버튼은 두지 않는다 — 닫고 나면
 * 다음 화면에서 같은 의문이 다시 생긴다.
 */
export default function TrialBanner() {
  const trialMode = useTrialMode()
  if (!trialMode) return null

  return (
    <aside className="trial-banner" aria-label="체험판 안내">
      <span className="trial-tag">DEMO</span>
      <p>
        <b>지금 보시는 화면은 데모입니다.</b>{' '}
        서버 리소스 비용 문제로 실제 견적 요청과 3D 주행 검증 기능은 내려 두었습니다.
        미리 계산해 둔 데모 견적으로 결과 화면을 둘러봐 주세요. 양해 부탁드립니다.
      </p>
    </aside>
  )
}
