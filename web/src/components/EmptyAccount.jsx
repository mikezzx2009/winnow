import { Link } from 'react-router-dom'

// 新注册用户名下还没有邮箱账号时的占位提示
export default function EmptyAccount() {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-8 text-center max-w-lg mx-auto">
      <div className="text-3xl mb-3">📮</div>
      <div className="font-semibold mb-2">还没有邮箱账号</div>
      <p className="text-sm text-slate-500 mb-4">
        先到「管理」页添加你的 126 邮箱，再到「邮箱绑定」页填入授权码并启用，
        收信服务就会开始为你工作。
      </p>
      <Link to="/manage" className="inline-block px-4 py-2 bg-slate-900 text-white rounded-md text-sm">
        去添加账号
      </Link>
    </div>
  )
}
