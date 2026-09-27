import { useEffect, useRef } from 'react'

/**
 * 되돌릴 수 없는 일을 묻는 창 (S15P21A106-271).
 *
 * <p>화면 두 곳(내 견적·전체 견적)이 같은 창을 쓴다. 한 곳만 고치면 다른 곳이 조용히 뒤처지므로
 * 모양과 키보드 동작을 여기 모아 둔다.
 *
 * <p>role="dialog" 만 붙여 놓으면 보조기기에는 창이라고 알리면서 정작 키보드로는 빠져나갈 수도,
 * 들어갈 수도 없다. 열릴 때 창 안으로 초점을 옮기고, Esc 로 닫고, 닫힐 때 누르기 전 자리로
 * 초점을 돌려준다.
 */
export default function ConfirmDialog({ title, children, confirmLabel, busy = false, onCancel, onConfirm }) {
  const cancelRef = useRef(null)
  const openerRef = useRef(null)

  useEffect(() => {
    openerRef.current = document.activeElement
    cancelRef.current?.focus()
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && !busy) onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      openerRef.current?.focus?.()
    }
    // busy 가 바뀔 때마다 초점을 다시 옮기지 않는다 — 삭제 중에 초점이 튀면 진행 상황을 놓친다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="modal-back" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel() }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <h4 id="confirm-title">{title}</h4>
        <p>{children}</p>
        <div className="modal-cta">
          <button type="button" className="ghost sm" ref={cancelRef} disabled={busy} onClick={onCancel}>
            취소
          </button>
          <button type="button" className="button danger sm" disabled={busy} onClick={onConfirm}>
            {busy ? `${confirmLabel} 중…` : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
