export interface HealthState {
  live: boolean
  ready: boolean
  detail: string
}

const reasons: Record<string, string> = {
  configuration_invalid: '数据库配置无效，请检查项目本地配置。',
  database_version_mismatch: '数据库版本与项目锁定基线不一致。',
  migration_pending: '数据库迁移尚未完成。',
  database_unavailable: '暂时无法连接开发数据库。',
}

export async function loadHealth(): Promise<HealthState> {
  const timeout = AbortSignal.timeout(8000)
  try {
    const live = await fetch('/health/live', { signal: timeout })
    if (!live.ok) return { live: false, ready: false, detail: '后端尚未启动或不可访问。' }
    const ready = await fetch('/health/ready', { signal: timeout })
    const data = await ready.json()
    return {
      live: true,
      ready: ready.ok && data.status === 'ready',
      detail: ready.ok ? '数据库连接、迁移版本和 PostGIS 检查通过。' : reasons[data.reason] ?? '后端尚未就绪。',
    }
  } catch {
    return { live: false, ready: false, detail: '后端暂不可访问，请确认启动状态后重试。' }
  }
}
