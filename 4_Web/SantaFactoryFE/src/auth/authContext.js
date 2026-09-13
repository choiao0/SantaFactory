import { createContext, useContext } from 'react'

/**
 * 로그인 상태를 담는 컨텍스트. 값을 채우는 쪽은 {@link ../auth/AuthProvider.jsx}.
 *
 * 컴포넌트와 파일을 나눈 이유는 Fast Refresh 다 — 한 파일이 컴포넌트와 훅을 같이
 * 내보내면 HMR 이 그 파일을 통째로 다시 평가해 편집할 때마다 로그인 상태가 날아간다.
 */
export const AuthContext = createContext(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth 는 AuthProvider 안에서만 쓸 수 있습니다')
  }
  return context
}
