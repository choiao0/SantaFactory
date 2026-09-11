import { Route, Routes } from 'react-router-dom'
import EstimatePage from './pages/EstimatePage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import AdminPage from './pages/AdminPage.jsx'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/estimate" element={<EstimatePage />} />
    </Routes>
  )
}
