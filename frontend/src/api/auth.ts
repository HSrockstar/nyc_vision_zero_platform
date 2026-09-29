import { ref } from 'vue'

export interface User {
  user_id: string
  username: string
  display_name: string
  role: 'ADMIN' | 'MANAGER' | 'VIEWER'
  is_active: boolean
  version: number
}

export const sessionUser = ref<User | null>(null)
let accessToken = ''

export function clearSession() {
  accessToken = ''
  sessionUser.value = null
}

export function hasSession() { return Boolean(accessToken) }

export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  const headers: Record<string, string> = { 'X-Request-ID': crypto.randomUUID() }
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData
  if (body !== undefined && !isFormData) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = 'Bearer ' + accessToken
  const result = await fetch('/api/v1' + path, {
    method,
    headers,
    body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
    signal: AbortSignal.timeout(options.timeoutMs ?? 10000),
  })
  let content: { data?: T; error?: { message?: string } } = {}
  try { content = await result.json() as typeof content }
  catch { /* 错误响应可能没有 JSON 正文。 */ }
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
  sessionUser.value = result.user
  return result.user
}
