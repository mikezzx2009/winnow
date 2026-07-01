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
  me: () => req('GET', '/auth/me'),
  login: (username, password) => req('POST', '/auth/login', { username, password }),
  logout: () => req('POST', '/auth/logout'),
  account: () => req('GET', '/account'),
  saveBinding: (email, auth_code) => req('PUT', '/account/binding', { email, auth_code }),
  saveConfig: (cfg) => req('PUT', '/account/config', cfg),
  rules: () => req('GET', '/rules'),
  addRule: (pattern, kind) => req('POST', '/rules', { pattern, kind }),
  delRule: (id) => req('DELETE', `/rules/${id}`),
  logs: (params) => req('GET', '/logs' + toQuery(params)),
  stats: () => req('GET', '/stats'),
}
