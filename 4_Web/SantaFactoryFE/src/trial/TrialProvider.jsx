import { useEffect, useState } from 'react'
import { getTrialMode } from '../api/config.js'
import { TrialContext } from './trialContext.js'

/**
 * 체험 모드를 앱이 뜰 때 한 번 묻는다 (S15P21A106-283).
 *
 * 로그인 상태와 상관없는 서버 설정이라 AuthProvider 와 따로 둔다 — 로그인·가입 화면에도 안내 배너가
 * 떠야 한다. 못 받으면 평소 화면으로 둔다. 새 요청은 서버가 막으므로 버튼이 보여도 비용은 새지 않고,
 * 누르면 서버의 안내 문구가 뜬다.
 */
export function TrialProvider({ children }) {
  const [trialMode, setTrialMode] = useState(false)

  useEffect(() => {
    getTrialMode()
      .then(setTrialMode)
      .catch((e) => console.error('[config] 체험 모드 설정을 받지 못했습니다', e))
  }, [])

  return <TrialContext.Provider value={trialMode}>{children}</TrialContext.Provider>
}
