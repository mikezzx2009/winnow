import { useEffect, useState } from 'react'
import { api } from '../api'

const input = 'w-full mb-4 px-3 py-2 border border-slate-300 rounded-md'

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [cfg, setCfg] = useState({ allow_registration: false, invite_required: false })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [invite, setInvite] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.authConfig().then(setCfg).catch(() => {})
  }, [])

  async function submit(e) {
    e.preventDefault()
    setErr('')
    if (mode === 'register' && password !== confirm) {
      setErr('两次输入的密码不一致')
      return
    }
    setBusy(true)
    try {
      const r =
        mode === 'login'
          ? await api.login(username, password)
          : await api.register(username, password, invite || undefined)
      onLogin(r)
    } catch (e) {
      setErr(e.message || (mode === 'login' ? '登录失败' : '注册失败'))
    } finally {
      setBusy(false)
    }
  }

  function switchMode(m) {
    setMode(m)
    setErr('')
    setPassword('')
    setConfirm('')
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
          className={input}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
        <label className="block text-sm text-slate-600 mb-1">密码</label>
        <input
          className={input}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
        />
        {mode === 'register' && (
          <>
            <label className="block text-sm text-slate-600 mb-1">确认密码</label>
            <input
              className={input}
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
            />
            {cfg.invite_required && (
              <>
                <label className="block text-sm text-slate-600 mb-1">邀请码</label>
                <input className={input} value={invite} onChange={(e) => setInvite(e.target.value)} />
              </>
            )}
            <p className="text-xs text-slate-400 mb-4 -mt-2">
              用户名 3-32 位字母/数字/下划线，密码至少 8 位。
            </p>
          </>
        )}
        {err && <div className="text-sm text-red-600 mb-3">{err}</div>}
        <button
          disabled={busy}
          className="w-full py-2 bg-slate-900 text-white rounded-md disabled:opacity-50"
        >
          {busy ? '处理中…' : mode === 'login' ? '登录' : '注册并登录'}
        </button>

        {cfg.allow_registration && (
          <div className="text-sm text-slate-500 mt-4 text-center">
            {mode === 'login' ? (
              <>
                没有账号？{' '}
                <button type="button" onClick={() => switchMode('register')} className="text-slate-900 underline">
                  注册
                </button>
              </>
            ) : (
              <>
                已有账号？{' '}
                <button type="button" onClick={() => switchMode('login')} className="text-slate-900 underline">
                  返回登录
                </button>
              </>
            )}
          </div>
        )}
      </form>
    </div>
  )
}
