// 与后端 /api 通信的薄封装。credentials:'include' 让 session Cookie 随请求发送。

function toQuery(params = {}) {
  const q = Object.entries(params)
    .filter(([, v]) => v !== '' && v !== undefined && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return q ? `?${q}` : ''
}

async function req(method, path, body) {
  const opts = { method, headers: {}, credentials: 'include' }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(`/api${path}`, opts)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.detail || `请求失败 (${res.status})`)
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  // 认证
  me: () => req('GET', '/auth/me'),
  login: (username, password) => req('POST', '/auth/login', { username, password }),
  logout: () => req('POST', '/auth/logout'),

  // 账号（多账号）
  accounts: () => req('GET', '/accounts'),
  createAccount: (email) => req('POST', '/accounts', { email }),
  deleteAccount: (id) => req('DELETE', `/accounts/${id}`),

  // 单账号的绑定 / 配置（account_id 缺省用主账号）
  account: (accountId) => req('GET', '/account' + toQuery({ account_id: accountId })),
  saveBinding: (accountId, email, auth_code) =>
    req('PUT', '/account/binding' + toQuery({ account_id: accountId }), { email, auth_code }),
  saveConfig: (accountId, cfg) =>
    req('PUT', '/account/config' + toQuery({ account_id: accountId }), cfg),

  // 规则
  rules: (accountId) => req('GET', '/rules' + toQuery({ account_id: accountId })),
  addRule: (accountId, pattern, kind) =>
    req('POST', '/rules' + toQuery({ account_id: accountId }), { pattern, kind }),
  delRule: (id) => req('DELETE', `/rules/${id}`),

  // 日志 / 复核
  logs: (params) => req('GET', '/logs' + toQuery(params)),
  reviewLog: (id, label) => req('POST', `/logs/${id}/review`, { label }),

  // 统计 / 状态 / 事件
  stats: (accountId) => req('GET', '/stats' + toQuery({ account_id: accountId })),
  status: (accountId) => req('GET', '/status' + toQuery({ account_id: accountId })),
  events: (params) => req('GET', '/events' + toQuery(params)),
  resolveEvent: (id) => req('POST', `/events/${id}/resolve`),

  // 用户（多用户）
  users: () => req('GET', '/users'),
  createUser: (username, password) => req('POST', '/users', { username, password }),
  setUserPassword: (id, password) => req('POST', `/users/${id}/password`, { password }),
  deleteUser: (id) => req('DELETE', `/users/${id}`),
}
