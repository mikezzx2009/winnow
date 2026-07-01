import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Binding from './pages/Binding.jsx'
import Rules from './pages/Rules.jsx'
import Logs from './pages/Logs.jsx'
import Status from './pages/Status.jsx'

export default function App() {
  // null=检查中, false=未登录, {username}=已登录
  const [auth, setAuth] = useState(null)

  useEffect(() => {
    api.me().then(setAuth).catch(() => setAuth(false))
  }, [])

  if (auth === null) {
    return <div className="min-h-screen flex items-center justify-center text-slate-500">加载中…</div>
  }

  if (!auth) {
    return (
      <Routes>
        <Route path="*" element={<Login onLogin={setAuth} />} />
      </Routes>
    )
  }

  return (
    <Layout user={auth} onLogout={() => setAuth(false)}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/binding" element={<Binding />} />
        <Route path="/rules" element={<Rules />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/status" element={<Status />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
