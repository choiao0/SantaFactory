import Footer from '../components/Footer.jsx'
import Header from '../components/Header.jsx'
import Hero from '../components/Hero.jsx'

/**
 * 로그인 뒤 첫 화면 (S15P21A106-274).
 *
 * 스크롤 한 장이던 때 맨 위에 있던 안내가 제 페이지를 갖는다. 주소는 그대로 `/estimate` 다 —
 * 로그인 성공·로그아웃·권한 없는 접근이 모두 이 주소로 오게 되어 있어, 여기를 첫 화면으로
 * 두면 그 길들을 하나도 고치지 않아도 된다.
 */
export default function LandingPage() {
  return (
    <>
      <Header />
      <main>
        <Hero />
      </main>
      <Footer />
    </>
  )
}
