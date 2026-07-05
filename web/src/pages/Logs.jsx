import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../accountContext'
import EmptyAccount from '../components/EmptyAccount.jsx'

function extractEmail(from) {
  const m = /<([^>]+)>/.exec(from || '')
  return (m ? m[1] : from || '').trim().toLowerCase()
}

export default function Logs() {
  const { accountId } = useAccount()
  const [data, setData] = useState({ items: [], total: 0 })
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState({})
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')

  async function load() {
    const params = { limit: 100, q, account_id: accountId }
    if (filter.important !== undefined) params.important = filter.important
    if (filter.forwarded !== undefined) params.forwarded = filter.forwarded
    try {
      setData(await api.logs(params))
    } catch (e) {
      setErr(e.message)
    }
  }

  useEffect(() => {
    if (!accountId) return
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, accountId])

  if (!accountId) return <EmptyAccount />

  async function review(id, label) {
    await api.reviewLog(id, label)
    await load()
  }
  async function addRule(from, kind) {
    const pattern = extractEmail(from)
    if (!pattern) return
    await api.addRule(accountId, pattern, kind)
    setNote(`已把 ${pattern} 加入${kind === 'whitelist' ? '白' : '黑'}名单`)
  }

  return (
    <div>
      <div className="flex gap-2 mb-4 items-center">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          placeholder="搜索主题 / 发件人，回车"
          className="px-3 py-2 border border-slate-300 rounded-md flex-1"
        />
        <Chip active={filter.important} onClick={() => setFilter((f) => ({ ...f, important: f.important ? undefined : true }))}>
          仅重要
        </Chip>
        <Chip active={filter.forwarded} onClick={() => setFilter((f) => ({ ...f, forwarded: f.forwarded ? undefined : true }))}>
          仅已转发
        </Chip>
      </div>
      {err && <div className="text-red-600 text-sm mb-3">{err}</div>}
      {note && <div className="text-green-700 text-sm mb-3 bg-green-50 border border-green-200 rounded px-3 py-2">{note}</div>}
      <div className="text-sm text-slate-500 mb-2">共 {data.total} 条</div>
      <div className="space-y-2">
        {data.items.map((it) => (
          <LogRow key={it.id} it={it} onReview={review} onAddRule={addRule} />
        ))}
        {data.items.length === 0 && <div className="text-slate-400 text-sm">无记录</div>}
      </div>
    </div>
  )
}

function Chip({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-md text-sm border ${
        active ? 'bg-slate-900 text-white border-slate-900' : 'border-slate-300 text-slate-600'
      }`}
    >
      {children}
    </button>
  )
}

function Tag({ ok, children }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${ok ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>
      {children}
    </span>
  )
}

function LogRow({ it, onReview, onAddRule }) {
  const reviewText = it.review_label === 'important' ? '已标记：其实重要' : it.review_label === 'not_important' ? '已标记：其实垃圾' : null
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium truncate">{it.subject || '(无主题)'}</div>
        <div className="flex gap-1 shrink-0">
          <Tag ok={it.is_important}>{it.is_important ? '重要' : '非重要'}</Tag>
          <Tag ok={it.forwarded}>{it.forwarded ? '已转发' : '未转发'}</Tag>
          <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600">{it.prefiltered ? '预筛' : 'AI'}</span>
        </div>
      </div>
      <div className="text-xs text-slate-500 mt-1">
        {it.from_addr} · {it.category} · 置信 {Number(it.confidence).toFixed(2)}
      </div>
      <div className="text-sm text-slate-700 mt-2">{it.reason}</div>
      {it.error && <div className="text-xs text-amber-600 mt-1">{it.error}</div>}
      {reviewText && <div className="text-xs text-indigo-600 mt-1">✎ {reviewText}</div>}
      <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-slate-100 text-xs">
        <span className="text-slate-400 self-center">复核纠错：</span>
        <ActionBtn onClick={() => onReview(it.id, 'important')}>其实重要</ActionBtn>
        <ActionBtn onClick={() => onReview(it.id, 'not_important')}>其实垃圾</ActionBtn>
        {it.review_label && <ActionBtn onClick={() => onReview(it.id, 'clear')}>清除标记</ActionBtn>}
        <span className="text-slate-300 self-center">|</span>
        <ActionBtn onClick={() => onAddRule(it.from_addr, 'whitelist')}>发件人加白名单</ActionBtn>
        <ActionBtn onClick={() => onAddRule(it.from_addr, 'blacklist')}>发件人加黑名单</ActionBtn>
      </div>
    </div>
  )
}

function ActionBtn({ onClick, children }) {
  return (
    <button onClick={onClick} className="px-2 py-1 rounded border border-slate-200 text-slate-600 hover:bg-slate-50">
      {children}
    </button>
  )
}
