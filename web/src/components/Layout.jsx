import { NavLink } from 'react-router-dom'
import { api } from '../api'

const tabs = [
  { to: '/', label: '统计面板', end: true },
  { to: '/binding', label: '邮箱绑定' },
  { to: '/rules', label: '转发规则' },
  { to: '/logs', label: '处理日志' },
  { to: '/status', label: '系统状态' },
]

export default function Layout({ user, onLogout, children }) {
  async function logout() {
    try {
      await api.logout()
    } finally {
      onLogout()
    }
  }
  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <span className="font-semibold text-slate-900">🌾 Winnow</span>
            <nav className="flex gap-1">
              {tabs.map((t) => (
                <NavLink
                  key={t.to}
                  to={t.to}
                  end={t.end}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded-md text-sm ${
                      isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
                    }`
                  }
                >
                  {t.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-500">{user.username}</span>
            <button onClick={logout} className="text-slate-600 hover:text-slate-900">
              退出
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
    </div>
  )
}
