import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../accountContext'
import EmptyAccount from '../components/EmptyAccount.jsx'

const input = 'w-full px-3 py-2 border border-slate-300 rounded-md'

export default function Binding() {
  const { accountId, reloadAccounts } = useAccount()
  const [acc, setAcc] = useState(null)
  const [email, setEmail] = useState('')
  const [authCode, setAuthCode] = useState('')
  const [cfg, setCfg] = useState({})
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  async function load() {
    const a = await api.account(accountId)
    setAcc(a)
    setEmail(a.email || '')
    setCfg({
      forward_to: a.forward_to,
      subject_prefix: a.subject_prefix,
      importance_threshold: a.importance_threshold,
      forward_interval_seconds: a.forward_interval_seconds,
      daily_forward_limit: a.daily_forward_limit,
      enabled: a.enabled,
    })
  }

  useEffect(() => {
    if (!accountId) return
    load().catch((e) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId])

  async function saveBinding(e) {
    e.preventDefault()
    setErr('')
    setMsg('')
    try {
      await api.saveBinding(accountId, email, authCode)
      setAuthCode('')
      setMsg('已保存，授权码已加密入库。')
      await load()
      await reloadAccounts()
    } catch (e) {
      setErr(e.message)
    }
  }

  async function saveConfig(e) {
    e.preventDefault()
    setErr('')
    setMsg('')
    try {
      await api.saveConfig(accountId, {
        forward_to: cfg.forward_to,
        subject_prefix: cfg.subject_prefix,
        importance_threshold: Number(cfg.importance_threshold),
        forward_interval_seconds: Number(cfg.forward_interval_seconds),
        daily_forward_limit: Number(cfg.daily_forward_limit),
        enabled: !!cfg.enabled,
      })
      setMsg('配置已保存，常驻服务下一轮生效。')
      await reloadAccounts()
    } catch (e) {
      setErr(e.message)
    }
  }

  if (!accountId) return <EmptyAccount />
  if (!acc) return <div className="text-slate-500">加载中…</div>

  return (
    <div className="space-y-6 max-w-2xl">
      {msg && (
        <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">
          {msg}
        </div>
      )}
      {err && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
          {err}
        </div>
      )}

      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="font-semibold mb-1">126 邮箱绑定</h2>
        <p className="text-xs text-slate-500 mb-4">
          授权码是「客户端授权码」（非登录密码），在 mail.126.com → 设置 → IMAP/SMTP 处获取。
          提交后 Fernet 加密入库。当前：{acc.bound ? '已绑定授权码' : '未绑定（回退使用 .env）'}。
        </p>
        <form onSubmit={saveBinding} className="space-y-3">
          <div>
            <label className="block text-sm text-slate-600 mb-1">126 邮箱地址</label>
            <input className={input} value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm text-slate-600 mb-1">授权码</label>
            <input
              className={input}
              type="password"
              placeholder="填入以更新（留空则不修改绑定）"
              value={authCode}
              onChange={(e) => setAuthCode(e.target.value)}
            />
          </div>
          <button className="px-4 py-2 bg-slate-900 text-white rounded-md">保存绑定</button>
        </form>
      </section>

      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="font-semibold mb-4">转发配置</h2>
        <form onSubmit={saveConfig} className="space-y-3">
          <div>
            <label className="block text-sm text-slate-600 mb-1">目标邮箱</label>
            <input
              className={input}
              value={cfg.forward_to || ''}
              onChange={(e) => setCfg({ ...cfg, forward_to: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-sm text-slate-600 mb-1">标题前缀</label>
            <input
              className={input}
              value={cfg.subject_prefix || ''}
              onChange={(e) => setCfg({ ...cfg, subject_prefix: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-sm text-slate-600 mb-1">重要性阈值</label>
              <input
                className={input}
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={cfg.importance_threshold ?? ''}
                onChange={(e) => setCfg({ ...cfg, importance_threshold: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm text-slate-600 mb-1">转发间隔(秒)</label>
              <input
                className={input}
                type="number"
                value={cfg.forward_interval_seconds ?? ''}
                onChange={(e) => setCfg({ ...cfg, forward_interval_seconds: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm text-slate-600 mb-1">每日上限</label>
              <input
                className={input}
                type="number"
                value={cfg.daily_forward_limit ?? ''}
                onChange={(e) => setCfg({ ...cfg, daily_forward_limit: e.target.value })}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={!!cfg.enabled}
              onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
            />
            启用该账号的收信处理
          </label>
          <button className="px-4 py-2 bg-slate-900 text-white rounded-md">保存配置</button>
        </form>
      </section>
    </div>
  )
}
