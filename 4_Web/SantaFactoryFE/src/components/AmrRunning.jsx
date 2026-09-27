/**
 * 계산·검증이 돌고 있다는 표식 — AMR 이 앞으로 나아가는 선화. 돌아가는 원보다 "시뮬이 주행을
 * 돌리고 있다"는 뜻에 가깝다. 뒤쪽 세 줄은 주행선이고, 차체가 앞으로 밀리는 동안 반대로 흘러
 * 속도감을 만든다. 크기는 쓰는 쪽에서 CSS 로 정한다.
 */
export default function AmrRunning() {
  return (
    <span className="amr-run" aria-hidden="true">
      <svg viewBox="0 0 34 22" width="52" height="34" fill="none" stroke="currentColor"
           strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        {/* 주행선 — 차체 뒤쪽 */}
        <path className="dash" d="M4.5 10.5h3M2 13h3.5M4.5 15.5h3" />
        {/* 적재 상자 */}
        <rect x="13" y="2" width="11" height="7" rx="1" />
        <path d="M18.5 2v2.4" />
        {/* 차체 · 바퀴 */}
        <rect x="9" y="9" width="19" height="6.5" rx="2" />
        <circle cx="14" cy="18.2" r="2.3" />
        <circle cx="23" cy="18.2" r="2.3" />
      </svg>
    </span>
  )
}
