import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../accountContext'

function fmtAgo(seconds) {
  if (seconds == null) return '从未'
  if (seconds < 60) return `${seconds} 秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  return `${Math.floor(seconds / 3600)} 小时前`
}

export default function Status() {
  const { accountId } = useAccount()
  const [st, setSt] = useState(null)
  const [events, setEvents] = useState([])
  const [err, setErr] = useState('')

  async function load() {
    try {
      setSt(await api.status(accountId))
      setEvents(await api.events({ limit: 50, account_id: accountId }))
    } catch (e) {
      setErr(e.message)
    }
  }
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId])

  async function resolve(id) {
    await api.resolveEvent(id)
    await load()
  }

  if (err) return <div className="text-red-600">{err}</div>
  if (!st) return <div className="text-slate-500">加载中…</div>

  return (
    <div className="space-y-6">
      <section className={`rounded-xl border p-5 ${st.healthy ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${st.healthy ? 'bg-green-500' : 'bg-amber-500'}`}></span>
          <span className="font-semibold">{st.healthy ? '收信服务运行正常' : '收信服务可能离线或有未处理告警'}</span>
        </div>
        <div className="text-sm text-slate-600 mt-3 grid grid-cols-2 gap-y-1 max-w-md">
          <span className="text-slate-400">上次心跳</span>
          <span>{fmtAgo(st.seconds_since_poll)}</span>
          <span className="text-slate-400">未处理错误</span>
          <span>{st.unresolved.error}</span>
          <span className="text-slate-400">未处理警告</span>
          <span>{st.unresolved.warning}</span>
          <span className="text-slate-400">授权码绑定</span>
          <span>{st.bound ? '已绑定 (DB 加密)' : '回退 .env'}</span>
          <span className="text-slate-400">账号启用</span>
          <span>{st.enabled ? '是' : '否'}</span>
        </div>
        {st.seconds_since_poll == null && (
          <div className="text-sm text-amber-700 mt-3">
            尚无心跳：请确认收信服务 <code>winnow run</code> 已启动。
          </div>
        )}
      </section>

      <section>
        <h2 className="font-semibold mb-3">事件 / 告警</h2>
        <div className="space-y-2">
          {events.length === 0 && <div className="text-slate-400 text-sm">暂无事件</div>}
          {events.map((e) => (
            <div
              key={e.id}
              className={`bg-white border border-slate-200 rounded-lg p-3 flex items-start justify-between gap-3 ${
                e.resolved ? 'opacity-50' : ''
              }`}
            >
              <div>
                <div className="flex items-center gap-2 text-xs">
                  <LevelTag level={e.level} />
                  <span className="text-slate-400">{e.kind}</span>
                  <span className="text-slate-400">{e.created_at?.replace('T', ' ').slice(0, 19)}</span>
                </div>
                <div className="text-sm text-slate-700 mt-1">{e.message}</div>
              </div>
              {!e.resolved && (
                <button onClick={() => resolve(e.id)} className="text-xs text-slate-500 hover:text-slate-900 shrink-0">
                  标记已处理
                </button>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function LevelTag({ level }) {
  const cls =
    level === 'error'
      ? 'bg-red-100 text-red-700'
      : level === 'warning'
        ? 'bg-amber-100 text-amber-700'
        : 'bg-slate-100 text-slate-600'
  return <span className={`px-2 py-0.5 rounded ${cls}`}>{level}</span>
}
