import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../accountContext'

function Card({ label, value }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="text-3xl font-semibold mt-1">{value}</div>
    </div>
  )
}

export default function Dashboard() {
  const { accountId } = useAccount()
  const [s, setS] = useState(null)
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api.stats(accountId).then(setS).catch((e) => setErr(e.message))
    api.status(accountId).then(setSt).catch(() => {})
  }, [accountId])

  if (err) return <div className="text-red-600">{err}</div>
  if (!s) return <div className="text-slate-500">加载中…</div>

  return (
    <div>
      {st && (
        <div
          className={`mb-6 rounded-lg border px-4 py-2 text-sm flex items-center gap-2 ${
            st.healthy ? 'bg-green-50 border-green-200 text-green-800' : 'bg-amber-50 border-amber-200 text-amber-800'
          }`}
        >
          <span className={`w-2 h-2 rounded-full ${st.healthy ? 'bg-green-500' : 'bg-amber-500'}`}></span>
          {st.healthy
            ? '收信服务运行正常'
            : `收信服务可能离线或有告警（未处理错误 ${st.unresolved.error}）— 详见「系统状态」`}
        </div>
      )}
      <h1 className="text-lg font-semibold mb-4">今日</h1>
      <div className="grid grid-cols-3 gap-4 mb-8">
        <Card label="今日收到" value={s.today.received} />
        <Card label="判为重要" value={s.today.important} />
        <Card label="已转发" value={s.today.forwarded} />
      </div>
      <h1 className="text-lg font-semibold mb-4">累计</h1>
      <div className="grid grid-cols-3 gap-4">
        <Card label="累计收到" value={s.total.received} />
        <Card label="累计重要" value={s.total.important} />
        <Card label="累计转发" value={s.total.forwarded} />
      </div>
    </div>
  )
}
