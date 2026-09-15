import { Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider.jsx'
import RequireAuth from './auth/RequireAuth.jsx'
import EstimatePage from './pages/EstimatePage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import SignupPage from './pages/SignupPage.jsx'
import AdminPage from './pages/AdminPage.jsx'
import MyEstimatesPage from './pages/MyEstimatesPage.jsx'

export default function App() {
  return (
    <AuthProvider>
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
          path="/estimate"
          element={(
            <RequireAuth>
              <EstimatePage />
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
      </Routes>
    </AuthProvider>
  )
}
