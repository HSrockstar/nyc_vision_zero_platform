import { apiWithMeta, authHeaders, clearSession } from './auth'

export type Revisioned<T> = { data: T; revision: string | null }

export interface StatFilters {
  start: string
  end: string
  end_exclusive: boolean
  borough_id: string | null
  street_filter: boolean
  vehicle_type_id: string | null
  factor_id: string | null
  collision_scope: string
}

export interface OverviewData {
  collision_count: number
  known_injured_count: number | null
  injured_missing_count: number
  known_killed_count: number | null
  killed_missing_count: number
  person_records: number
  vehicle_records: number
  geocoded_count: number
  missing_coordinates_count: number
  confirmed_assigned_count: number
  assignment_coverage_ratio: string | null
  casualty_note: string
  filters: StatFilters
}

export interface BoroughRow {
  borough_id: string | null
  borough_name: string
  collision_count: number
  known_injured_count: number | null
  injured_missing_count: number
  known_killed_count: number | null
  killed_missing_count: number
}

export interface BoroughsData {
  items: BoroughRow[]
  casualty_note: string
  filters: StatFilters
}

export interface MonthRow {
  month: string
  collision_count: number | null
  known_injured_count: number | null
  injured_missing_count: number | null
  known_killed_count: number | null
  killed_missing_count: number | null
  coverage: 'WITH_DATA' | 'NO_RECORDS_COVERAGE_UNCONFIRMED' | 'OUTSIDE_DECLARED_RANGES'
}

export interface TrendMonthsData {
  months: MonthRow[]
  zero_fill: boolean
  coverage_note: string
  granularity: 'month'
  filters: StatFilters
}

export interface TrendHoursData {
  hours: { hour: number; collision_count: number }[]
  unknown_time_collision_count: number
  note: string
  granularity: 'hours'
  filters: StatFilters
}

export interface FactorsData {
  items: { factor_id: string; canonical_name: string; display_name: string | null; collision_count: number }[]
  no_factor_collision_count: number
  overlap_note: string
  filters: StatFilters
}

export interface VehicleTypesData {
  items: { vehicle_type_id: string | null; canonical_name: string | null; display_name: string | null; vehicle_records: number; collision_count: number }[]
  overlap_note: string
  filters: StatFilters
}

export interface PersonsData {
  items: { person_type: string | null; person_injury: string | null; record_count: number }[]
  note: string
  filters: StatFilters
}

export interface GovernanceData {
  total_tasks: number
  by_status: { status: string; label: string; task_count: number }[]
  by_assignee: { assignee_id: string | null; assignee_name: string; task_count: number }[]
  by_measure_type: { measure_type: string; task_count: number }[]
  by_priority: { priority: string; task_count: number }[]
  handling: { completed: number; cancelled: number; in_execution: number; draft: number }
  note: string
  filter_basis: string
  filters: Record<string, unknown>
}

export interface StatisticsQuery {
  start: string
  endExclusive: string
  boroughId?: string
  street?: string
  vehicleTypeId?: string
  factorId?: string
}

function query(q: StatisticsQuery) {
  const params = new URLSearchParams()
  params.set('start', q.start)
  params.set('end', q.endExclusive)
  if (q.boroughId) params.set('borough_id', q.boroughId)
  if (q.street && q.street.trim()) params.set('street', q.street.trim())
  if (q.vehicleTypeId) params.set('vehicle_type_id', q.vehicleTypeId)
  if (q.factorId) params.set('factor_id', q.factorId)
  return params.toString()
}

export function getOverview(q: StatisticsQuery) {
  return apiWithMeta<OverviewData>('/statistics/overview?' + query(q))
}
export function getBoroughs(q: StatisticsQuery) {
  return apiWithMeta<BoroughsData>('/statistics/boroughs?' + query(q))
}
export function getTrendMonths(q: StatisticsQuery) {
  return apiWithMeta<TrendMonthsData>('/statistics/trends?' + query(q))
}
export function getTrendHours(q: StatisticsQuery) {
  return apiWithMeta<TrendHoursData>('/statistics/trends?' + query(q) + '&granularity=hours')
}
export function getFactors(q: StatisticsQuery) {
  return apiWithMeta<FactorsData>('/statistics/factors?' + query(q))
}
export function getVehicleTypes(q: StatisticsQuery) {
  return apiWithMeta<VehicleTypesData>('/statistics/vehicle-types?' + query(q))
}
export function getPersons(q: StatisticsQuery) {
  return apiWithMeta<PersonsData>('/statistics/persons?' + query(q))
}
export function getGovernance() {
  return apiWithMeta<GovernanceData>('/statistics/governance')
}

export async function downloadCsv(path: string, params: string): Promise<Blob> {
  // 复用认证请求头；失败时读取JSON错误消息（如超限、无权限）。
  const response = await fetch('/api/v1' + path + (params ? '?' + params : ''), {
    headers: authHeaders(),
    signal: AbortSignal.timeout(120000),
  })
  if (!response.ok) {
    let message = '导出未完成，请稍后重试。'
    try { message = (await response.json())?.error?.message ?? message } catch { /* 保留默认消息 */ }
    if (response.status === 401) clearSession()
    throw new Error(message)
  }
  return response.blob()
}
