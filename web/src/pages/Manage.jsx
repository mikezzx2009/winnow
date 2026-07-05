import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../accountContext'

const input = 'px-3 py-2 border border-slate-300 rounded-md'

export default function Manage() {
  const { accounts, reloadAccounts, user } = useAccount()
  const isAdmin = !!user?.is_admin
  const [users, setUsers] = useState([])
  const [newEmail, setNewEmail] = useState('')
  const [newUser, setNewUser] = useState('')
  const [newPass, setNewPass] = useState('')
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  async function loadUsers() {
    if (!isAdmin) return
    setUsers(await api.users())
  }
  useEffect(() => {
    loadUsers().catch((e) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin])

  function ok(m) {
    setMsg(m)
    setErr('')
  }
  function fail(e) {
    setErr(e.message || String(e))
    setMsg('')
  }

  async function addAccount(e) {
    e.preventDefault()
    if (!newEmail.trim()) return
    try {
      await api.createAccount(newEmail.trim())
      setNewEmail('')
      await reloadAccounts()
      ok('已添加账号（去「邮箱绑定」页填授权码后启用）')
    } catch (e) {
      fail(e)
    }
  }
  async function removeAccount(id) {
    try {
      await api.deleteAccount(id)
      await reloadAccounts()
      ok('已删除账号')
    } catch (e) {
      fail(e)
    }
  }

  async function changeMyPassword(e) {
    e.preventDefault()
    try {
      await api.changeOwnPassword(oldPw, newPw)
      setOldPw('')
      setNewPw('')
      ok('已修改我的登录密码')
    } catch (e) {
      fail(e)
    }
  }

  async function addUser(e) {
    e.preventDefault()
    if (!newUser.trim() || !newPass) return
    try {
      await api.createUser(newUser.trim(), newPass)
      setNewUser('')
      setNewPass('')
      await loadUsers()
      ok('已添加用户')
    } catch (e) {
      fail(e)
    }
  }
  async function resetPassword(id, username) {
    const pw = window.prompt(`为用户「${username}」设置新密码（至少 8 位）：`)
    if (!pw) return
    try {
      await api.setUserPassword(id, pw)
      ok('已更新密码')
    } catch (e) {
      fail(e)
    }
  }
  async function removeUser(id) {
    try {
      await api.deleteUser(id)
      await loadUsers()
      await reloadAccounts() // 被删用户的账号会归给当前管理员
      ok('已删除用户（其名下账号已归给你）')
    } catch (e) {
      fail(e)
    }
  }

  return (
    <div className="space-y-8 max-w-3xl">
      {msg && <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">{msg}</div>}
      {err && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">{err}</div>}

      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="font-semibold mb-1">我的邮箱账号</h2>
        <p className="text-xs text-slate-500 mb-4">
          添加账号后，到顶部切换到该账号，在「邮箱绑定」页填入其 126 授权码并启用；
          收信服务会为每个已启用且已绑定的账号各起一个连接。
        </p>
        <form onSubmit={addAccount} className="flex gap-2 mb-4">
          <input
            className={input + ' flex-1'}
            placeholder="新增 126 邮箱地址，如 someone@126.com"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
          <button className="px-4 py-2 bg-slate-900 text-white rounded-md">添加账号</button>
        </form>
        <ul className="divide-y divide-slate-100">
          {accounts.length === 0 && <li className="text-sm text-slate-400 py-2">暂无账号</li>}
          {accounts.map((a) => (
            <li key={a.id} className="flex items-center justify-between py-2 text-sm">
              <div>
                <span className="font-mono">{a.email}</span>
                <span className="ml-2 text-xs text-slate-500">
                  {a.bound ? '已绑定授权码' : '未绑定'} · {a.enabled ? '已启用' : '已停用'}
                </span>
              </div>
              <button onClick={() => removeAccount(a.id)} className="text-slate-400 hover:text-red-600">
                删除
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="font-semibold mb-4">修改我的登录密码</h2>
        <form onSubmit={changeMyPassword} className="flex gap-2">
          <input
            className={input}
            type="password"
            placeholder="原密码"
            value={oldPw}
            onChange={(e) => setOldPw(e.target.value)}
            autoComplete="current-password"
          />
          <input
            className={input + ' flex-1'}
            type="password"
            placeholder="新密码（至少 8 位）"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            autoComplete="new-password"
          />
          <button className="px-4 py-2 bg-slate-900 text-white rounded-md">修改</button>
        </form>
      </section>

      {isAdmin && (
        <section className="bg-white border border-slate-200 rounded-xl p-6">
          <h2 className="font-semibold mb-1">用户管理（管理员）</h2>
          <p className="text-xs text-slate-500 mb-4">
            这里管理控制台登录用户。删除用户时，其名下邮箱账号会归给你，不会丢数据。
          </p>
          <form onSubmit={addUser} className="flex gap-2 mb-4">
            <input className={input} placeholder="用户名" value={newUser} onChange={(e) => setNewUser(e.target.value)} />
            <input
              className={input + ' flex-1'}
              type="password"
              placeholder="密码（至少 8 位）"
              value={newPass}
              onChange={(e) => setNewPass(e.target.value)}
            />
            <button className="px-4 py-2 bg-slate-900 text-white rounded-md">添加用户</button>
          </form>
          <ul className="divide-y divide-slate-100">
            {users.map((u) => (
              <li key={u.id} className="flex items-center justify-between py-2 text-sm">
                <span className="font-mono">
                  {u.username}
                  {u.is_admin && <span className="ml-2 text-xs text-indigo-600">管理员</span>}
                </span>
                <div className="flex gap-3">
                  <button onClick={() => resetPassword(u.id, u.username)} className="text-slate-500 hover:text-slate-900">
                    改密码
                  </button>
                  <button onClick={() => removeUser(u.id)} className="text-slate-400 hover:text-red-600">
                    删除
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
