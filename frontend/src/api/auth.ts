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

export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'X-Request-ID': crypto.randomUUID() }
  if (accessToken) headers.Authorization = 'Bearer ' + accessToken
  return headers
}

async function request<T>(
  path: string,
  method: string,
  body?: unknown,
  options: { timeoutMs?: number } = {},
): Promise<{ data: T; revision: string | null }> {
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
  let content: { data?: T; error?: { message?: string }; meta?: { data_revision?: string } } = {}
  try { content = await result.json() as typeof content }
  catch { /* 错误响应可能没有 JSON 正文。 */ }
  if (!result.ok) {
    if (result.status === 401) clearSession()
    throw new Error(content.error?.message ?? '请求未完成，请稍后重试。')
  }
  return { data: content.data as T, revision: content.meta?.data_revision ?? null }
}

export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  return (await request<T>(path, method, body, options)).data
}

export function apiWithMeta<T>(
  path: string,
  options: { timeoutMs?: number } = {},
): Promise<{ data: T; revision: string | null }> {
  return request<T>(path, 'GET', undefined, options)
}

export async function login(username: string, password: string): Promise<User> {
  clearSession()
  const result = await api<{ access_token: string; user: User }>('/auth/login', 'POST', { username, password })
  accessToken = result.access_token
  sessionUser.value = result.user
  return result.user
}
