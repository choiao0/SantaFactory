import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/authContext.js'

export default function Header() {
  const navigate = useNavigate()
  const { member, isAdmin, logout } = useAuth()

  // 로고는 홈으로 가는 자리다. 단계마다 페이지가 갈린 뒤로는 어느 화면에서 눌러도 같은 곳으로
  // 간다 — 예전의 #top 앵커는 견적 화면에만 있어 다른 화면에서는 눌러도 아무 일이 없었다
  const goHome = (e) => {
    e.preventDefault()
    navigate('/estimate')
  }

  const handleLogout = async () => {
    await logout()
    navigate('/', { replace: true })
  }

  return (
    <header className="header">
      <a className="brand" href="/estimate" onClick={goHome}>
        <img className="brand-mark" src="/santafactory-logo.png" alt="Santa Factory" width={30} height={30} />
        {/* 좁은 화면에서 이 글자만 접으려면 요소여야 한다 — 텍스트 노드는 CSS 로 못 가린다 */}
        <span className="brand-text">SANTA FACTORY</span>
      </a>
      <div className="header-account">
        {/* 창고·견적이 회원별로 갈리므로 지금 누구로 보고 있는지가 화면에 있어야 한다 */}
        {member && <span className="mono dim">{member.company} · {member.name}</span>}
        <button type="button" className="ghost sm" onClick={() => navigate('/estimates')}>내 견적</button>
        {isAdmin && (
          // 역할이 아니라 갈 곳을 쓴다 — 바로 왼쪽이 회원 이름이라 "관리자"면 두 번 겹치고,
          // 도착하는 화면이 무엇인지도 알려주지 못한다
          <button type="button" className="ghost sm" onClick={() => navigate('/admin')}>전체 견적</button>
        )}
        <button type="button" className="ghost sm" onClick={handleLogout}>로그아웃</button>
      </div>
    </header>
  )
}
