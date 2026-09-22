import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/authContext.js'

const LINKS = [
  ['#s1', '운영 조건'],
  ['#s2', '대수 범위'],
  ['#s3', '시뮬레이션'],
  ['#verify', '물리 검증'],
  ['#quote', '견적'],
]

/**
 * @param sections 견적 화면의 섹션 앵커(WAREHOUSE·FLEET…)를 보일지. 그 앵커가 없는 화면에서는
 *                 눌러도 아무 일이 없으므로 끈다.
 */
export default function Header({ sections = true }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { member, isAdmin, logout } = useAuth()

  // 로고는 홈으로 가는 자리다. #top 앵커는 견적 화면에만 있어서 다른 화면에서는 눌러도
  // 아무 일이 없었다 (S15P21A106-263). 견적 화면에서는 예전처럼 맨 위로 올린다
  const goHome = (e) => {
    e.preventDefault()
    if (pathname === '/estimate') {
      document.getElementById('top')?.scrollIntoView({ behavior: 'smooth' })
    } else {
      navigate('/estimate')
    }
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
      {sections && (
        <nav className="header-links">
          {LINKS.map(([href, label]) => (
            <a key={href} href={href}>{label}</a>
          ))}
        </nav>
      )}
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
