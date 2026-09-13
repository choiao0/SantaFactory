import { Navigate } from 'react-router-dom'
import { useAuth } from './authContext.js'

/**
 * 로그인(과 필요하면 역할)을 확인하고 통과시킨다.
 *
 * 이건 화면 편의일 뿐 보안 장치가 아니다 — 실제 차단은 서버가 한다. 관리자 API 는
 * ADMIN 만 받고, 남의 창고·견적은 애초에 404 로 응답한다. 여기서 막는 이유는 권한 없는
 * 화면을 열어 401·403 만 잔뜩 보게 두지 않으려는 것뿐이다.
 */
export default function RequireAuth({ role, children }) {
  const { member, loading } = useAuth()

  if (loading) {
    return null   // 아직 판단할 근거가 없다. 이때 로그인으로 보내면 새로고침마다 튕긴다
  }
  if (!member) {
    return <Navigate to="/" replace />
  }
  if (role && member.role !== role) {
    return <Navigate to="/estimate" replace />
  }
  return children
}
