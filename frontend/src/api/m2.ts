import { api } from './auth'

export interface Collision {
  collision_id: string
  crash_date: string
  crash_time: string | null
  borough_id: string | null
  borough_name: string | null
  on_street_name: string | null
  cross_street_name: string | null
  off_street_name: string | null
  latitude: number | null
  longitude: number | null
  persons_injured: number | null
  persons_killed: number | null
  pedestrians_injured: number | null
  pedestrians_killed: number | null
  cyclists_injured: number | null
  cyclists_killed: number | null
  motorists_injured: number | null
  motorists_killed: number | null
}

export interface CollisionDetail extends Collision {
  source: { batch_id: string; raw_record_id: string; cleaning_version: string }
}

export interface PersonItem {
  person_id?: string
  person_type?: string | null
  person_injury?: string | null
  person_age?: number | null
  person_sex?: string | null
}

export interface VehicleItem {
  vehicle_id: string
  canonical_name: string | null
  vehicle_year: number | null
  travel_direction: string | null
  pre_crash: string | null
  point_of_impact: string | null
  vehicle_damage: string | null
}

export interface DictionaryItem {
  id: string
  canonical_name: string
  display_name: string | null
  is_active: boolean
}

export interface Page<T> {
  items: T[]
  total: number | null
}

export interface CollisionPage extends Page<Collision> {
  next_cursor: string | null
}

export interface CollisionFilters {
  start?: string
  end?: string
  borough_id?: string
  street?: string
  vehicle_type_id?: string
  factor_id?: string
  page_size?: number
  cursor?: string
  include_total?: boolean
}

export interface ImportFileSummary {
  source_kind: string
  dataset_id: string | null
  sha256: string
  bytes: number
  headers: string[]
  header_mode: string
  row_count: number | null
}

export interface ImportManifest {
  files: ImportFileSummary[]
  validation?: {
    planned?: { inserted: number; updated: number; unchanged: number }
    source_counts?: Record<string, Record<string, number>>
    blocking_issue_count?: number
    coverage?: unknown
  }
  publication?: {
    inserted: number
    updated: number
    unchanged: number
    revision: string | null
  }
}

export interface ImportBatch {
  batch_id: string
  status: string
  cleaning_version: string | null
  requested_start: string | null
  requested_end: string | null
  rows_read: number | null
  rows_accepted: number | null
  rows_rejected: number | null
  rows_skipped: number | null
  published_revision: string | null
  error_summary: string | null
  created_at: string
  input_manifest?: ImportManifest | null
}

export interface ImportDetail extends ImportBatch {
  input_manifest?: ImportManifest | null
}

export interface DataIssue {
  issue_id: string
  issue_code: string
  severity: 'INFO' | 'WARNING' | 'ERROR' | string
  field_name: string | null
  description: string
  status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | string
  row_no?: number | null
  source_kind?: string | null
}

function queryString(values: Record<string, string | number | boolean | undefined>) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return params.toString()
}

export function listCollisions(filters: CollisionFilters) {
  return api<CollisionPage>('/collisions?' + queryString(filters as Record<string, string | number | boolean | undefined>))
}

export function getCollision(id: string) {
  return api<CollisionDetail>('/collisions/' + encodeURIComponent(id))
}

export function listPersons(id: string, page: number, pageSize = 20) {
  return api<Page<PersonItem>>('/collisions/' + encodeURIComponent(id) + '/persons?' + queryString({
    page, page_size: pageSize,
  }))
}

export function listVehicles(id: string, page: number, pageSize = 20) {
  return api<Page<VehicleItem>>('/collisions/' + encodeURIComponent(id) + '/vehicles?' + queryString({
    page, page_size: pageSize,
  }))
}

export async function listVehicleTypes() {
  return api<{ items: DictionaryItem[] }>('/dictionaries/vehicle-types')
}

export async function listFactors() {
  return api<{ items: DictionaryItem[] }>('/dictionaries/factors')
}

export function listImports(page: number, pageSize = 20) {
  return api<Page<ImportBatch>>('/imports?' + queryString({ page, page_size: pageSize }))
}

export function submitImport(body: FormData) {
  return api<ImportBatch>('/imports', 'POST', body, { timeoutMs: 5 * 60 * 1000 })
}
export function getImport(id: string) {
  return api<ImportDetail>('/imports/' + encodeURIComponent(id))
}

export function listImportIssues(id: string, page: number, pageSize = 20) {
  return api<Page<DataIssue>>('/imports/' + encodeURIComponent(id) + '/issues?' + queryString({
    page, page_size: pageSize,
  }))
}

export function publishImport(id: string, requestId: string) {
  return api<ImportBatch>('/imports/' + encodeURIComponent(id) + '/publish', 'POST', {
    request_id: requestId,
  })
}

export function retryImport(id: string, requestId: string) {
  return api<ImportBatch>('/imports/' + encodeURIComponent(id) + '/retry', 'POST', {
    request_id: requestId,
  })
}

export function updateDataIssue(id: string, status: 'ACKNOWLEDGED' | 'RESOLVED', resolutionNote: string) {
  return api<DataIssue>('/data-issues/' + encodeURIComponent(id), 'PATCH', {
    status, resolution_note: resolutionNote,
  })
}
