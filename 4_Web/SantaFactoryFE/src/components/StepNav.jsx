import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { STEPS, stepPath } from '../data/steps.js'

/**
 * 다섯 단계 중 지금 어디인지, 그리고 어디로 갈 수 있는지 (S15P21A106-274).
 *
 * 스크롤 한 장이던 때 헤더의 섹션 앵커가 하던 일을 대신한다. 갈 수 없는 단계는 링크가 아니라
 * 글자로 남긴다 — 눌러도 아무 일이 없는 링크를 두면 어디까지 진행됐는지가 흐려진다.
 */
export default function StepNav({ current, estimateId = null }) {
  const index = STEPS.findIndex((s) => s.key === current)
  const navRef = useRef(null)
  const hereRef = useRef(null)

  useEffect(() => {
    const nav = navRef.current
    const here = hereRef.current
    if (!nav || !here) return
    // 좁은 화면에서는 다섯 칸이 한 줄에 안 들어가 지금 단계가 오른쪽 밖에 있을 수 있다.
    // scrollIntoView 는 세로까지 움직여 방금 맞춘 화면 위치를 흔들므로 가로만 직접 맞춘다
    nav.scrollLeft = Math.max(0, here.offsetLeft - (nav.clientWidth - here.offsetWidth) / 2)
  }, [current])

  return (
    <nav className="stepnav" aria-label="견적 단계" ref={navRef}>
      {STEPS.map((step, i) => {
        const to = step.key === current ? null : stepPath(step, estimateId)
        const state = i === index ? 'on' : i < index ? 'done' : 'todo'
        const inner = (
          <>
            <span className="stepnav-no">{step.no}</span>
            <b>{step.title}</b>
          </>
        )
        return to ? (
          <Link key={step.key} className={`stepnav-item ${state}`} to={to}>{inner}</Link>
        ) : (
          <span key={step.key} className={`stepnav-item ${state}`}
                ref={i === index ? hereRef : undefined}
                aria-current={i === index ? 'step' : undefined}>
            {inner}
          </span>
        )
      })}
    </nav>
  )
}
