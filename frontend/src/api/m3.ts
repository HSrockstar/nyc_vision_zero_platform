import { api } from './auth'

export interface MapCollision {
  collision_id: string
  location_id: string
  crash_date: string
  crash_time: string | null
  borough_id: number | null
  longitude: number
  latitude: number
  intersection_id: string | null
  distance_m?: number
}

export interface MapCoverage {
  total: number
  geocoded: number
  missing_coordinates: number
  confirmed_assigned: number
  unmatched: number
}

export interface MapResult {
  items: MapCollision[]
  returned: number
  truncated: boolean
  coverage: MapCoverage
  bounds: [number, number, number, number]
}

export interface Intersection {
  intersection_id: string
  intersection_code: string
  borough_id: string | null
  street_a: string
  street_b: string
  status: 'CANDIDATE' | 'CONFIRMED' | 'REJECTED'
  source_method: string
  is_active: boolean
  version: number
  longitude: number
  latitude: number
}

export interface IntersectionDetail extends Intersection {
  created_at: string
  confirmed_at: string | null
  confirmation_note?: string | null
  location_count: number
  risk_profile_count: number
  locations: Array<{
    location_id: string
    on_street_name: string | null
    cross_street_name: string | null
    longitude: number | null
    latitude: number | null
    match_status: string
    distance_m: number | null
    version: number
  }>
}

export interface LocationAssignment {
  location_id: string
  borough_id: string | null
  on_street_name: string | null
  cross_street_name: string | null
  longitude: number | null
  latitude: number | null
  intersection_id: string | null
  match_status: string
  version: number
  evidence?: Record<string, unknown>
}

export interface Generation {
  processed: number
  created_candidates: number
  candidate_assignments: number
  auto_matched: number
  unchanged: number
  invalid_pair: number
  last_location_id: string
  has_more: boolean
  algorithm_version: string
  radius_m: number
}

function params(values: Record<string, string | number | undefined>) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  return query.toString()
}

export function getMapCollisions(values: {
  start: string; end: string; west: number; south: number; east: number; north: number; limit: number
}) {
  return api<MapResult>('/map/collisions?' + params(values))
}

export function getNearby(longitude: number, latitude: number, radiusM: number, limit = 100) {
  return api<{ items: MapCollision[]; truncated: boolean; radius_m: number }>(
    '/map/nearby?' + params({ longitude, latitude, radius_m: radiusM, limit }),
  )
}

export function getIntersections(status?: Intersection['status'], page = 1) {
  return api<{ items: Intersection[]; total: number }>(
    '/intersections?' + params({ status, page, page_size: 50 }),
  )
}

export function getIntersection(id: string) {
  return api<IntersectionDetail>('/intersections/' + encodeURIComponent(id))
}

export function getLocationAssignment(id: string) {
  return api<LocationAssignment>('/location-assignments/' + encodeURIComponent(id))
}

export function generateCandidates(boroughId: number, afterLocationId: string, maxLocations: number, radiusM: number) {
  return api<Generation>('/intersection-candidates/generate', 'POST', {
    borough_id: boroughId, after_location_id: afterLocationId,
    max_locations: maxLocations, radius_m: radiusM,
  }, { timeoutMs: 60000 })
}

export function reviewIntersection(id: string, version: number, note: string, confirm: boolean) {
  return api<{ intersection_id: string; status: string; assignments_changed: number; data_revision: string }>(
    '/intersections/' + encodeURIComponent(id) + (confirm ? '/confirm' : '/reject'),
    'POST', { version, note },
  )
}

export function setLocationAssignment(id: string, version: number,
  status: 'MANUAL_CONFIRMED' | 'REJECTED' | 'UNMATCHED', intersectionId: string, reason: string) {
  return api<{ location_id: string; match_status: string; version: number; data_revision: string }>(
    '/location-assignments/' + encodeURIComponent(id), 'PATCH',
    { version, status, intersection_id: status === 'MANUAL_CONFIRMED' ? intersectionId : null, reason },
  )
}
