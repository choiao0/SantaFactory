import { Link } from 'react-router-dom'

/**
 * 단계 아래 붙는 이동 줄 (S15P21A106-274). 스크롤이 아니라 이 버튼이 흐름을 넘긴다.
 *
 * 단계마다 문구를 새로 짓지 않는다 — 어디서든 같은 자리에 같은 모양으로 있어야 "다음"이
 * 흐름을 넘긴다는 규칙이 화면 전체에서 하나로 읽힌다. 그 단계만의 행동(견적 요청 등)은
 * 자기 섹션 안에 그대로 두고, 여기에는 오가는 길만 둔다.
 *
 * @param back 이전 단계 주소. 되돌아갈 곳이 없으면 생략한다
 * @param next 다음 단계 주소. 그 단계의 버튼이 대신 넘길 때는 생략한다
 */
export default function StepFoot({ back, next, nextLabel = '다음 →', children }) {
  if (!back && !next && !children) return null

  return (
    <div className="stepfoot">
      {back && <Link className="ghost" to={back}>← 이전</Link>}
      <div className="stepfoot-end">
        {children}
        {next && <Link className="button" to={next}>{nextLabel}</Link>}
      </div>
    </div>
  )
}
