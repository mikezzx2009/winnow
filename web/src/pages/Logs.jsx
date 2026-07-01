import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Logs() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState({})
  const [err, setErr] = useState('')

  async function load() {
    const params = { limit: 100, q }
    if (filter.important !== undefined) params.important = filter.important
    if (filter.forwarded !== undefined) params.forwarded = filter.forwarded
    try {
      setData(await api.logs(params))
    } catch (e) {
      setErr(e.message)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

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
        <Chip
          active={filter.important}
          onClick={() => setFilter((f) => ({ ...f, important: f.important ? undefined : true }))}
        >
          仅重要
        </Chip>
        <Chip
          active={filter.forwarded}
          onClick={() => setFilter((f) => ({ ...f, forwarded: f.forwarded ? undefined : true }))}
        >
          仅已转发
        </Chip>
      </div>
      {err && <div className="text-red-600 text-sm mb-3">{err}</div>}
      <div className="text-sm text-slate-500 mb-2">共 {data.total} 条</div>
      <div className="space-y-2">
        {data.items.map((it) => (
          <LogRow key={it.id} it={it} />
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
    <span
      className={`text-xs px-2 py-0.5 rounded ${
        ok ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'
      }`}
    >
      {children}
    </span>
  )
}

function LogRow({ it }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium truncate">{it.subject || '(无主题)'}</div>
        <div className="flex gap-1 shrink-0">
          <Tag ok={it.is_important}>{it.is_important ? '重要' : '非重要'}</Tag>
          <Tag ok={it.forwarded}>{it.forwarded ? '已转发' : '未转发'}</Tag>
          <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600">
            {it.prefiltered ? '预筛' : 'AI'}
          </span>
        </div>
      </div>
      <div className="text-xs text-slate-500 mt-1">
        {it.from_addr} · {it.category} · 置信 {Number(it.confidence).toFixed(2)}
      </div>
      <div className="text-sm text-slate-700 mt-2">{it.reason}</div>
      {it.error && <div className="text-xs text-amber-600 mt-1">{it.error}</div>}
    </div>
  )
}
