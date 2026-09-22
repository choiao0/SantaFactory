import { useEffect, useState } from 'react'
import { openVerifyStream } from '../api/estimates.js'

const IDLE = { id: null, status: null, videoUrl: null, videoSideUrl: null, error: null }

export function useVerifyStream(estimateId) {
  const [state, setState] = useState(IDLE)

  useEffect(() => {
    if (estimateId == null) return undefined

    const apply = (payload) =>
      setState({
        id: estimateId,
        status: payload.status,
        videoUrl: payload.video_url,
        // 측면 시점은 찍지 않은 회차가 있어 없을 수 있다 — 그때는 화면이 상단만 보여준다
        videoSideUrl: payload.video_side_url ?? null,
        error: payload.error,
      })

    const close = openVerifyStream(estimateId, {
      onSnapshot: apply,
      onDone: apply,
      onError: () => console.error(`[verify] estimateId=${estimateId} 스트림 연결 실패`),
    })
    return close
  }, [estimateId])

  return state.id === estimateId ? state : IDLE
}
