export interface User {
  user_id: string
  username: string
  display_name: string
  role: 'ADMIN' | 'MANAGER' | 'VIEWER'
  is_active: boolean
  version: number
}

let accessToken = ''

export function clearSession() { accessToken = '' }
export function hasSession() { return Boolean(accessToken) }

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Request-ID': crypto.randomUUID() }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  const result = await fetch(`/api/v1${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  })
  const content = await result.json()
  if (!result.ok) {
    if (result.status === 401) clearSession()
    throw new Error(content.error?.message ?? '请求未完成，请稍后重试。')
  }
  return content.data as T
}

export async function login(username: string, password: string): Promise<User> {
  clearSession()
  const result = await api<{ access_token: string; user: User }>('/auth/login', 'POST', { username, password })
  accessToken = result.access_token
  return result.user
}
