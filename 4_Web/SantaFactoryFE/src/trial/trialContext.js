import { createContext, useContext } from 'react'

/**
 * 체험 모드 여부 (S15P21A106-283). 값을 채우는 쪽은 {@link ./TrialProvider.jsx}.
 *
 * 기본값이 false 라 프로바이더 밖이나 설정을 받기 전에는 평소 화면 그대로다.
 * 컴포넌트와 파일을 나눈 이유는 authContext.js 와 같다(Fast Refresh).
 */
export const TrialContext = createContext(false)

export function useTrialMode() {
  return useContext(TrialContext)
}
