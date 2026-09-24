import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider.jsx'
import RequireAuth from './auth/RequireAuth.jsx'
import AdminPage from './pages/AdminPage.jsx'
import LandingPage from './pages/LandingPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import MyEstimatesPage from './pages/MyEstimatesPage.jsx'
import SignupPage from './pages/SignupPage.jsx'
import EstimateLayout from './pages/estimate/EstimateLayout.jsx'
import FleetPage from './pages/estimate/FleetPage.jsx'
import NewEstimateLayout from './pages/estimate/NewEstimateLayout.jsx'
import QuotePage from './pages/estimate/QuotePage.jsx'
import RunsPage from './pages/estimate/RunsPage.jsx'
import VerifyPage from './pages/estimate/VerifyPage.jsx'
import WarehousePage from './pages/estimate/WarehousePage.jsx'

/**
 * 견적은 다섯 단계가 각자 제 주소를 갖는다 (S15P21A106-274).
 *
 * <p>앞 두 단계는 아직 견적 번호가 없어 `/estimate/new/…` 아래에 모이고, 요청이 성공하면
 * 번호가 붙은 `/estimate/{id}/…` 로 넘어간다. 번호가 주소에 있으므로 새로고침·뒤로가기·링크
 * 공유가 저절로 되고, 예전처럼 sessionStorage 에 번호를 숨겨 둘 필요가 없다.
 *
 * <p>`/estimate/new` 가 `/estimate/:estimateId` 보다 먼저 잡히는 것은 라우터가 고정 조각을
 * 변수 조각보다 앞세우기 때문이다.
 */
/**
 * 단계를 넘길 때 화면 맨 위에서 시작한다.
 *
 * 라우터는 스크롤 위치를 건드리지 않는다 — 아래까지 내려 본 03 에서 다음을 누르면 04 가 같은
 * 높이에서 열려 제목도 없이 중간부터 보였다. 스크롤 한 장이던 때는 다음 자리로 밀어 줬다.
 * 즉시 옮긴다 — html 의 smooth 를 타면 새 화면이 한 번 흐른 뒤에야 자리를 잡는다.
 */
function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
  }, [pathname])
  return null
}

export default function App() {
  return (
    <AuthProvider>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route
          path="/admin"
          element={(
            <RequireAuth role="ADMIN">
              <AdminPage />
            </RequireAuth>
          )}
        />
        <Route
          path="/estimates"
          element={(
            <RequireAuth>
              <MyEstimatesPage />
            </RequireAuth>
          )}
        />
        <Route
          path="/estimate"
          element={(
            <RequireAuth>
              <LandingPage />
            </RequireAuth>
          )}
        />
        <Route
          path="/estimate/new"
          element={(
            <RequireAuth>
              <NewEstimateLayout />
            </RequireAuth>
          )}
        >
          <Route index element={<Navigate to="warehouse" replace />} />
          <Route path="warehouse" element={<WarehousePage />} />
          <Route path="fleet" element={<FleetPage />} />
        </Route>
        <Route
          path="/estimate/:estimateId"
          element={(
            <RequireAuth>
              <EstimateLayout />
            </RequireAuth>
          )}
        >
          {/* 번호만 주고 들어오면 결론을 연다 — 지난 견적을 여는 길이 이쪽이다 */}
          <Route index element={<Navigate to="quote" replace />} />
          <Route path="runs" element={<RunsPage />} />
          <Route path="verify" element={<VerifyPage />} />
          <Route path="quote" element={<QuotePage />} />
        </Route>
        {/* 없는 주소는 첫 화면으로 — 로그인 전이면 RequireAuth 가 다시 로그인으로 보낸다 */}
        <Route path="*" element={<Navigate to="/estimate" replace />} />
      </Routes>
    </AuthProvider>
  )
}
