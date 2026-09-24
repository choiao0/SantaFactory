import { Navigate, Outlet, useParams } from 'react-router-dom'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { useEstimateStream } from '../../hooks/useEstimateStream.js'

/**
 * 견적 번호가 붙은 세 단계(03 시뮬레이션 · 04 물리 검증 · 05 견적)를 감싼다 (S15P21A106-274).
 *
 * <p>진행 스트림을 여기 한 곳에만 연다. 페이지마다 열면 단계를 옮길 때마다 EventSource 가 끊기고
 * 다시 붙어, 그 사이에 도착한 run 결과를 놓친다.
 *
 * <p>지난 견적도 같은 길로 열린다 — 서버가 이미 끝난 견적에는 snapshot 과 estimate.done 을 즉시
 * 보내고 닫기 때문에(EstimateEventStream), 진행 중인지 지난 것인지 화면이 나눠 볼 필요가 없다.
 */
export default function EstimateLayout() {
  const { estimateId: raw } = useParams()
  const estimateId = Number(raw)
  const valid = Number.isInteger(estimateId) && estimateId > 0
  // 훅은 조건 앞에서 부른다 — 번호가 null 이면 스트림은 아무것도 열지 않는다
  const stream = useEstimateStream(valid ? estimateId : null)

  // 주소창에 숫자가 아닌 것을 치면 서버에 물어볼 것도 없다
  if (!valid) return <Navigate to="/estimate" replace />

  return (
    <>
      <Header />
      <main>
        <Outlet context={{
          estimateId,
          estimate: stream.estimate,
          verdict: stream.verdict,
          connected: stream.connected,
          error: stream.error,
        }} />
      </main>
      <Footer />
    </>
  )
}
