import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../accountContext'
import EmptyAccount from '../components/EmptyAccount.jsx'

const input = 'px-3 py-2 border border-slate-300 rounded-md'

export default function Rules() {
  const { accountId } = useAccount()
  const [rules, setRules] = useState([])
  const [pattern, setPattern] = useState('')
  const [kind, setKind] = useState('whitelist')
  const [err, setErr] = useState('')

  async function load() {
    setRules(await api.rules(accountId))
  }
  useEffect(() => {
    if (!accountId) return
    load().catch((e) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId])

  if (!accountId) return <EmptyAccount />

  async function add(e) {
    e.preventDefault()
    setErr('')
    if (!pattern.trim()) return
    try {
      await api.addRule(accountId, pattern.trim(), kind)
      setPattern('')
      await load()
    } catch (e) {
      setErr(e.message)
    }
  }

  async function del(id) {
    await api.delRule(id)
    await load()
  }

  const whitelist = rules.filter((r) => r.kind === 'whitelist')
  const blacklist = rules.filter((r) => r.kind === 'blacklist')

  return (
    <div className="max-w-2xl space-y-6">
      {err && <div className="text-sm text-red-700">{err}</div>}
      <form onSubmit={add} className="bg-white border border-slate-200 rounded-xl p-6 flex gap-2 items-end">
        <div className="flex-1">
          <label className="block text-sm text-slate-600 mb-1">发件人匹配（地址子串，如 @company.com）</label>
          <input className={input + ' w-full'} value={pattern} onChange={(e) => setPattern(e.target.value)} />
        </div>
        <select className={input} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="whitelist">白名单(必转发)</option>
          <option value="blacklist">黑名单(必拦截)</option>
        </select>
        <button className="px-4 py-2 bg-slate-900 text-white rounded-md">添加</button>
      </form>
      <div className="grid grid-cols-2 gap-4">
        <RuleList title="白名单 · 必转发" titleClass="text-green-700" items={whitelist} onDel={del} />
        <RuleList title="黑名单 · 必拦截" titleClass="text-red-700" items={blacklist} onDel={del} />
      </div>
    </div>
  )
}

function RuleList({ title, titleClass, items, onDel }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5">
      <div className={`text-sm font-medium mb-3 ${titleClass}`}>{title}</div>
      {items.length === 0 && <div className="text-sm text-slate-400">暂无</div>}
      <ul className="space-y-2">
        {items.map((r) => (
          <li key={r.id} className="flex items-center justify-between text-sm bg-slate-50 rounded-md px-3 py-2">
            <span className="font-mono">{r.pattern}</span>
            <button onClick={() => onDel(r.id)} className="text-slate-400 hover:text-red-600">
              删除
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
