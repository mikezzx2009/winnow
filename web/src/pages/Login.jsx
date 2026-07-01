import { useState } from 'react'
import { api } from '../api'

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      const r = await api.login(username, password)
      onLogin(r)
    } catch (e) {
      setErr(e.message || '登录失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <form
        onSubmit={submit}
        className="bg-white p-8 rounded-xl shadow-sm border border-slate-200 w-80"
      >
        <div className="text-xl font-semibold mb-1">🌾 Winnow 控制台</div>
        <div className="text-sm text-slate-500 mb-6">126 邮箱 AI 智能转发服务</div>
        <label className="block text-sm text-slate-600 mb-1">用户名</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="w-full mb-4 px-3 py-2 border border-slate-300 rounded-md"
        />
        <label className="block text-sm text-slate-600 mb-1">密码</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full mb-4 px-3 py-2 border border-slate-300 rounded-md"
        />
        {err && <div className="text-sm text-red-600 mb-3">{err}</div>}
        <button
          disabled={busy}
          className="w-full py-2 bg-slate-900 text-white rounded-md disabled:opacity-50"
        >
          {busy ? '登录中…' : '登录'}
        </button>
      </form>
    </div>
  )
}
