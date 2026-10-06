import { Link } from 'react-router-dom'
import Footer from '../components/Footer.jsx'
import Header from '../components/Header.jsx'
import Hero from '../components/Hero.jsx'
import ModelShowcase from '../components/landing/ModelShowcase.jsx'
import MyStats from '../components/landing/MyStats.jsx'
import RecentEstimates from '../components/landing/RecentEstimates.jsx'
import ResumeBanner from '../components/landing/ResumeBanner.jsx'
import StepGuide from '../components/landing/StepGuide.jsx'
import WarehousePicker from '../components/landing/WarehousePicker.jsx'
import { useAuth } from '../auth/authContext.js'
import { useLandingData } from '../hooks/useLandingData.js'
import { useTrialMode } from '../trial/trialContext.js'

/**
 * 로그인 뒤 첫 화면 (S15P21A106-274).
 *
 * <p>주소는 `/estimate` 다 — 로그인 성공·로그아웃·권한 없는 접근이 모두 이리로 오게 되어 있어,
 * 여기를 첫 화면으로 두면 그 길들을 하나도 고치지 않아도 된다.
 *
 * <p>설명은 짧게 둔다. 화면이 하는 일은 단계 다섯 줄과 로봇 단가면 충분히 드러나고, 그 위에
 * 문단을 더 얹으면 읽지 않는 글만 길어진다. 대신 <b>진행 중 알림은 맨 위</b>다 — 읽을거리가
 * 아니라 알림이라 아래로 내려가면 있을 이유가 없다.
 *
 * <p>관리자에게는 내 작업 구역을 그리지 않는다. 목록 API 들이 관리자에게는 전체를 주기 때문에
 * 남의 창고가 "내 조건"으로 보인다.
 */
export default function LandingPage() {
  const { isAdmin } = useAuth()
  const trialMode = useTrialMode()
  const { recent, warehouses, robots } = useLandingData({ mine: !isAdmin })
  const hasMine = recent.total > 0 || warehouses.items.length > 0

  return (
    <>
      <Header />
      <main>
        <ResumeBanner estimate={recent.running} />
        <Hero />
        <StepGuide />
        <ModelShowcase robots={robots} />

        {!isAdmin && hasMine && (
          <section className="step section-dark mywork" id="mine">
            <div className="eyebrow red">
              <span className="live-dot" />
              {trialMode ? '체험판' : '내 작업'}
            </div>
            <h2>{trialMode ? '데모 견적 둘러보기' : '이어서 하기'}</h2>
            <MyStats recent={recent} warehouses={warehouses} />
            {/* 체험판은 새 견적을 받지 않아 저장된 조건으로 다시 요청하는 칸을 감춘다 (S15P21A106-283) */}
            {!trialMode && warehouses.items.length > 0 && <WarehousePicker warehouses={warehouses} robots={robots} />}
            <RecentEstimates recent={recent} />
          </section>
        )}

        {isAdmin && (
          <section className="step section-dark mywork" id="mine">
            <div className="eyebrow red">
              <span className="live-dot" />
              관리자
            </div>
            <h2>전체 현황</h2>
            {/* 관리자 계정에는 회원 전체가 내려와 "내 조건"을 가릴 수 없다 — 그 화면으로 보낸다 */}
            <p className="mono dim lhint">회원별 창고와 견적은 전체 견적 화면에서 확인할 수 있습니다.</p>
            <div className="herocta">
              <Link className="button" to="/admin">전체 견적 보기</Link>
            </div>
          </section>
        )}
      </main>
      <Footer />
    </>
  )
}
