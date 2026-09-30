import { api } from './auth'

export interface RiskRule {
  rule_id: string; rule_name: string; version_no: number
  status: 'PUBLISHED' | 'RETIRED'
  weight_collision: string; weight_injured: string; weight_killed: string; weight_vru: string
  threshold_medium: string; threshold_high: string; rationale: string
}
export interface Coverage {
  total: number; geocoded: number; missing_coordinates: number; included: number; unmatched: number
  incomplete_included: number; profiled_intersections: number; confirmed_intersections: number
  coverage_ratio: number | null
}
export interface RiskRun {
  run_id: string; rule_id: string; period_start: string; period_end: string
  input_revision: string | null; status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  is_stale: boolean; error_summary: string | null; coverage_summary: Partial<Coverage>
  input_manifest: { snapshot?: { sha256: string; profile_rows: number; mapping_rows: number }; sources?: unknown[] }
}
export interface RiskProfile {
  profile_id: string; intersection_id: string; run_id: string; street_a: string; street_b: string
  collision_count: number; injured_count: number; killed_count: number; vulnerable_road_user_count: number
  incomplete_casualty_collision_count: number; score: string | null
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN'; is_stale: boolean
}
export interface RiskDetail extends RiskProfile {
  contributions: { collision: string; injured: string; killed: string; vru: string }; run: RiskRun
}
export const getRules = () => api<{ items: RiskRule[] }>('/risk-rules')
export const getRuns = (start: string, end: string, rule: string, page = 1, status = '') => {
  const params = new URLSearchParams({ start, end, rule_id: rule, page: String(page) })
  if (status) params.set('status', status)
  return api<{ items: RiskRun[]; total: number }>('/risk-runs?' + params)
}
export const createRiskRun = (start: string, end: string, rule: string, requestId: string) =>
  api<RiskRun>('/risk-runs', 'POST', { period_start: start, period_end: end, rule_id: rule, request_id: requestId })
export const getProfiles = (run: string, level: string, sort: string, page: number, intersection: string) => {
  const params = new URLSearchParams({ run_id: run, sort, page: String(page) })
  if (level) params.set('risk_level', level)
  if (intersection) params.set('intersection_id', intersection)
  return api<{ items: RiskProfile[]; total: number }>('/risk-profiles?' + params)
}
export const getProfile = (id: string) => api<RiskDetail>('/risk-profiles/' + id)
