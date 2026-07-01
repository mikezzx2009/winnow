import { NavLink } from 'react-router-dom'
import { api } from '../api'
import { useAccount } from '../accountContext'

const tabs = [
  { to: '/', label: '统计面板', end: true },
  { to: '/binding', label: '邮箱绑定' },
  { to: '/rules', label: '转发规则' },
  { to: '/logs', label: '处理日志' },
  { to: '/status', label: '系统状态' },
  { to: '/manage', label: '管理' },
]

export default function Layout({ user, onLogout, children }) {
  const { accountId, accounts, setAccountId } = useAccount()
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
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-5 min-w-0">
            <span className="font-semibold text-slate-900 shrink-0">🌾 Winnow</span>
            <nav className="flex gap-1 flex-wrap">
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
          <div className="flex items-center gap-3 text-sm shrink-0">
            {accounts.length > 0 && (
              <select
                value={accountId ?? ''}
                onChange={(e) => setAccountId(Number(e.target.value))}
                className="px-2 py-1 border border-slate-300 rounded-md text-sm max-w-[180px]"
                title="当前账号"
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.email}
                    {a.enabled ? '' : '（停用）'}
                  </option>
                ))}
              </select>
            )}
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
