import { api } from './auth'

export type TaskStatus = 'DRAFT' | 'OPEN' | 'IN_PROGRESS' | 'PENDING_REVIEW' | 'COMPLETED' | 'CANCELLED'
export type TaskAction = 'edit' | 'publish' | 'delete_draft' | 'assign' | 'start' | 'progress' | 'submit' | 'approve' | 'reject' | 'cancel'
export type Measure = 'MARKING_MAINTENANCE' | 'SIGNAL_REVIEW' | 'PEDESTRIAN_FACILITY_REVIEW' | 'FIELD_SURVEY' | 'OTHER'
export type Priority = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT'
export interface GovernanceTask {
  task_id: string; task_code: string; profile_id: string; intersection_id: string
  title: string; description: string; measure_type: Measure; priority: Priority; status: TaskStatus
  created_by: string; assignee_id: string | null; due_date: string | null; effective_on: string | null
  assessment_scope: Record<string, unknown>; is_simulated: boolean; version: number
  deleted_at: string | null; created_at: string; updated_at: string; allowed_actions: TaskAction[]
  creator_name: string; assignee_name: string | null
  risk_level: RiskProfileLevel
  street_a?: string; street_b?: string
}
type RiskProfileLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN'
export interface TaskHistory {
  history_id: string; sequence_no: number; event_type: string; from_status: TaskStatus | null
  to_status: TaskStatus; actor_id: string; actor_name: string; note: string; changed_fields: Record<string, unknown>; created_at: string
}
export interface Assignee { user_id: string; display_name: string; role: 'ADMIN' | 'MANAGER' }
export interface DraftFields {
  title: string; description: string; measure_type: Measure; priority: Priority
  due_date: string | null; effective_on: string | null
}
export const getTasks = (page: number, status: string, mine: boolean) => {
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  if (status) params.set('status', status)
  if (mine) params.set('my_todo', 'true')
  return api<{ items: GovernanceTask[]; total: number }>('/governance-tasks?' + params)
}
export const getTask = (id: string) => api<GovernanceTask>('/governance-tasks/' + id)
export const getHistory = (id: string) => api<{ items: TaskHistory[] }>('/governance-tasks/' + id + '/history')
export const getAssignees = (search: string) => api<{ items: Assignee[]; total: number }>(
  '/governance-tasks/assignees?' + new URLSearchParams({ page_size: '100', search }))
export const createTask = (body: DraftFields & { request_id: string; profile_id: string; radius_m: number; rationale: string | null }) =>
  api<GovernanceTask>('/governance-tasks', 'POST', body)
export const changeTask = (id: string, action: TaskAction, body: Record<string, unknown>) => {
  const method = action === 'edit' ? 'PATCH' : action === 'delete_draft' ? 'DELETE' : 'POST'
  const suffix = ['edit', 'delete_draft'].includes(action) ? '' : ['approve', 'reject'].includes(action) ? '/review' : '/' + action
  return api<GovernanceTask>('/governance-tasks/' + id + suffix, method, body)
}
