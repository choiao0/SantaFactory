import { useEffect, useRef, useState } from 'react'

/**
 * 시각 입력 (S15P21A106-263).
 *
 * <p>브라우저 기본 <input type="time"> 을 쓰지 않는다. 그 피커는 페이지 밖에 그려지는 브라우저
 * UI라 칸과 위치가 어긋나도 못 맞추고, 편집 중인 조각(오전/오후)에 칠해지는 파란 블록도 작성자
 * CSS로 못 지운다. 값은 그대로 "HH:MM"(24시간) 문자열로 주고받는다 — 바깥 코드는 안 바뀐다.
 */

const MERIDIEMS = ['오전', '오후']
const HOURS = Array.from({ length: 12 }, (_, i) => i + 1)
const MINUTES = Array.from({ length: 60 }, (_, i) => i)

const pad = (n) => String(n).padStart(2, '0')

/** "13:05" → { meridiem: '오후', hour: 1, minute: 5 }. 자정은 "오전 12시"다. */
function parse(value) {
  const [h, m] = String(value ?? '').split(':')
  const hour24 = Number.isFinite(Number(h)) ? Number(h) : 0
  const minute = Number.isFinite(Number(m)) ? Number(m) : 0
  return {
    meridiem: hour24 < 12 ? '오전' : '오후',
    hour: hour24 % 12 === 0 ? 12 : hour24 % 12,
    minute,
  }
}

function toValue({ meridiem, hour, minute }) {
  const base = hour % 12
  return `${pad(meridiem === '오전' ? base : base + 12)}:${pad(minute)}`
}

/**
 * 고른 항목을 그 열 맨 위로 올린다 — 브라우저 기본 피커와 같은 방식이다. 가운데에 두면 위아래로
 * 잘린 항목이 같이 보여 지금 무엇이 골라졌는지 한눈에 안 들어온다.
 *
 * <p>offsetTop 은 위치 지정된 조상(.tf-pop) 기준이라 열 기준으로 다시 잰다. scrollIntoView 는
 * 페이지까지 같이 밀어서 쓰지 않는다.
 */
function alignSelectedToTop(column) {
  const selected = column?.querySelector('.tf-opt.on')
  if (!selected) return
  const gap = selected.getBoundingClientRect().top - column.getBoundingClientRect().top
  column.scrollTop += gap - parseFloat(getComputedStyle(column).paddingTop || 0)
}

export default function TimeField({ id, value, onChange, label }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const columnsRef = useRef([])
  const parts = parse(value)

  // 바깥을 누르거나 Esc 면 닫는다. pointerdown 으로 잡아야 항목을 고르는 클릭보다 먼저 판정된다
  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false)
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  useEffect(() => {
    if (open) columnsRef.current.forEach(alignSelectedToTop)
  }, [open])

  const pick = (patch) => onChange(toValue({ ...parts, ...patch }))

  const column = (index, items, render, isOn, onPick, columnLabel) => (
    <ul
      className="tf-col"
      role="listbox"
      aria-label={columnLabel}
      ref={(el) => { columnsRef.current[index] = el }}
    >
      {items.map((item) => {
        const on = isOn(item)
        return (
          <li key={item}>
            <button
              type="button"
              className={`tf-opt${on ? ' on' : ''}`}
              role="option"
              aria-selected={on}
              onClick={() => onPick(item)}
            >
              {render(item)}
            </button>
          </li>
        )
      })}
    </ul>
  )

  return (
    <div className="tf" ref={rootRef}>
      <button
        type="button"
        id={id}
        className="tf-value"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{parts.meridiem} {pad(parts.hour)}:{pad(parts.minute)}</span>
        {/* 시계 아이콘 — 기본 입력에서 쓰던 표시를 그대로 남긴다 */}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" strokeLinecap="round" />
        </svg>
      </button>

      {open && (
        <div className="tf-pop">
          {column(0, MERIDIEMS, (m) => m, (m) => m === parts.meridiem,
            (m) => pick({ meridiem: m }), '오전 오후')}
          {column(1, HOURS, (h) => pad(h), (h) => h === parts.hour,
            (h) => pick({ hour: h }), '시')}
          {column(2, MINUTES, (m) => pad(m), (m) => m === parts.minute,
            (m) => pick({ minute: m }), '분')}
        </div>
      )}
    </div>
  )
}
