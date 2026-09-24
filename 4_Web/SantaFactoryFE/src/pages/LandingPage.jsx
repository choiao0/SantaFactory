import { Link } from 'react-router-dom'
import Footer from '../components/Footer.jsx'
import Header from '../components/Header.jsx'
import Hero from '../components/Hero.jsx'
import ModelShowcase from '../components/landing/ModelShowcase.jsx'
import MyStats from '../components/landing/MyStats.jsx'
import RecentEstimates from '../components/landing/RecentEstimates.jsx'
import ResumeBanner from '../components/landing/ResumeBanner.jsx'
import ServiceIntro from '../components/landing/ServiceIntro.jsx'
import StepGuide from '../components/landing/StepGuide.jsx'
import WarehousePicker from '../components/landing/WarehousePicker.jsx'
import { useAuth } from '../auth/authContext.js'
import { useLandingData } from '../hooks/useLandingData.js'

/**
 * 로그인 뒤 첫 화면 (S15P21A106-274).
 *
 * <p>주소는 `/estimate` 다 — 로그인 성공·로그아웃·권한 없는 접근이 모두 이리로 오게 되어 있어,
 * 여기를 첫 화면으로 두면 그 길들을 하나도 고치지 않아도 된다.
 *
 * <p>소개를 위에, 내 작업을 아래에 둔다. 처음 온 사람은 스크롤 없이 시작할 수 있고, 다시 온
 * 사람은 한 번 내리면 자기 일이 나온다. 다만 <b>진행 중 알림만은 맨 위</b>다 — 그건 읽을거리가
 * 아니라 알림이라 아래로 내려가면 있을 이유가 없다.
 *
 * <p>관리자에게는 내 작업 구역을 그리지 않는다. 목록 API 들이 관리자에게는 전체를 주기 때문에
 * 남의 창고가 "내 조건"으로 보인다.
 */
export default function LandingPage() {
  const { isAdmin } = useAuth()
  const { recent, warehouses, robots } = useLandingData({ mine: !isAdmin })
  const hasMine = recent.total > 0 || warehouses.items.length > 0

  return (
    <>
      <Header />
      <main>
        <ResumeBanner estimate={recent.running} />
        <Hero />
        <ServiceIntro />
        <StepGuide />
        <ModelShowcase robots={robots} />

        {!isAdmin && hasMine && (
          <section className="step section-dark mywork" id="mine">
            <div className="eyebrow red">
              <span className="live-dot" />
              내 작업
            </div>
            <h2>Pick up where you left off.</h2>
            <MyStats recent={recent} warehouses={warehouses} />
            {warehouses.items.length > 0 && <WarehousePicker warehouses={warehouses} robots={robots} />}
            <RecentEstimates recent={recent} />
          </section>
        )}

        {isAdmin && (
          <section className="step section-dark mywork" id="mine">
            <div className="eyebrow red">
              <span className="live-dot" />
              관리자
            </div>
            <h2>See everyone&apos;s.</h2>
            <p className="desc">
              관리자 계정에는 회원 전체의 창고와 견적이 내려옵니다. 내 것만 골라 보여줄 수 없어
              이 자리에는 두지 않습니다 — 전체 현황 화면에서 회원별로 보세요.
            </p>
            <div className="herocta">
              <Link className="button" to="/admin">전체 견적 보기 ↗</Link>
            </div>
          </section>
        )}
      </main>
      <Footer />
    </>
  )
}
