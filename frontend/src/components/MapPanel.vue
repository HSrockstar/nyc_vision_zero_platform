<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { sessionUser } from '../api/auth'
import {
  generateCandidates, getIntersection, getIntersections, getLocationAssignment, getMapCollisions,
  getNearby, reviewIntersection, setLocationAssignment,
  type Generation, type Intersection, type IntersectionDetail, type LocationAssignment, type MapCoverage,
} from '../api/m3'

const mapHost = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let collisionLayer: L.LayerGroup | null = null
let intersectionLayer: L.LayerGroup | null = null
let nearbyLayer: L.LayerGroup | null = null
const loading = ref(false)
const error = ref('')
const summary = ref<MapCoverage | null>(null)
const displayed = ref(0)
const truncated = ref(false)
const viewportChanged = ref(false)
const start = ref('2025-01-01')
const end = ref('2026-01-01')
const intersections = ref<Intersection[]>([])
const intersectionTotal = ref(0)
const intersectionPage = ref(1)
const intersectionPages = computed(() => Math.max(1, Math.ceil(intersectionTotal.value / 50)))
const statusFilter = ref<'ALL' | 'CANDIDATE' | 'CONFIRMED' | 'REJECTED'>('ALL')
const selectedIntersection = ref<IntersectionDetail | null>(null)
const selectedLocation = ref<LocationAssignment | null>(null)
const detailError = ref('')
const actionMessage = ref('')
const actionError = ref('')
const actionBusy = ref(false)
const reviewNote = ref('')
const manualStatus = ref<'MANUAL_CONFIRMED' | 'REJECTED' | 'UNMATCHED'>('MANUAL_CONFIRMED')
const manualTargetId = ref('')
const manualReason = ref('')
const boroughId = ref(3)
const radiusM = ref(50)
const maxLocations = ref(100)
const afterLocationId = ref('0')
const lastGeneration = ref<Generation | null>(null)
const nearbyRadius = ref(200)
const nearbyCount = ref<number | null>(null)
const nearbyTruncated = ref(false)
let nearbyCenter: L.LatLng | null = null

const canManage = () => sessionUser.value?.role === 'ADMIN' || sessionUser.value?.role === 'MANAGER'
const message = (value: unknown) => value instanceof Error ? value.message : '请求未完成，请稍后重试。'

function clearLayers() {
  collisionLayer?.clearLayers()
  intersectionLayer?.clearLayers()
  nearbyLayer?.clearLayers()
}

function tooltip(value: string) {
  const node = document.createElement('span')
  node.textContent = value
  return node
}

async function loadMap() {
  if (!map || loading.value) return
  if (start.value >= end.value) {
    error.value = '结束日期必须晚于开始日期。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const bounds = map.getBounds()
    const result = await getMapCollisions({
      start: start.value, end: end.value, west: bounds.getWest(), south: bounds.getSouth(),
      east: bounds.getEast(), north: bounds.getNorth(), limit: 500,
    })
    if (!collisionLayer) return
    collisionLayer.clearLayers()
    for (const point of result.items) {
      const marker = L.circleMarker([point.latitude, point.longitude], {
        radius: 5, color: '#225d9f', weight: 1, fillColor: '#2586c2', fillOpacity: 0.7,
      }).addTo(collisionLayer)
      marker.bindTooltip(tooltip(`${point.crash_date} · 事故 ${point.collision_id}`))
      marker.on('click', () => void openLocation(point.location_id))
    }
    summary.value = result.coverage
    displayed.value = result.returned
    truncated.value = result.truncated
    viewportChanged.value = false
  } catch (reason) {
    error.value = message(reason)
  } finally { loading.value = false }
}

async function loadIntersections() {
  try {
    const result = await getIntersections(statusFilter.value === 'ALL' ? undefined : statusFilter.value, intersectionPage.value)
    intersections.value = result.items
    intersectionTotal.value = result.total
    if (!intersectionLayer) return
    intersectionLayer.clearLayers()
    for (const item of result.items) {
      const color = item.status === 'CONFIRMED' ? '#1f855e' : item.status === 'REJECTED' ? '#8a9298' : '#cd8b17'
      const marker = L.circleMarker([item.latitude, item.longitude], {
        radius: 8, color, fillColor: color, weight: 2, fillOpacity: 0.35,
      }).addTo(intersectionLayer)
      marker.bindTooltip(tooltip(`${item.status === 'CONFIRMED' ? '已确认' : item.status === 'REJECTED' ? '已拒绝' : '候选'} · ${item.street_a} / ${item.street_b}`))
      marker.on('click', () => void openIntersection(item.intersection_id))
    }
  } catch (reason) { detailError.value = message(reason) }
}

async function openIntersection(id: string) {
  detailError.value = ''
  selectedLocation.value = null
  try {
    const item = await getIntersection(id)
    selectedIntersection.value = item
    map?.panTo([item.latitude, item.longitude])
  } catch (reason) { detailError.value = message(reason) }
}

async function openLocation(id: string) {
  detailError.value = ''
  try {
    selectedLocation.value = await getLocationAssignment(id)
    manualStatus.value = selectedLocation.value.match_status === 'MANUAL_CONFIRMED' ? 'MANUAL_CONFIRMED' : 'UNMATCHED'
    manualTargetId.value = selectedLocation.value.intersection_id ?? ''
  } catch (reason) { detailError.value = message(reason) }
}

async function loadNearby() {
  if (!map || !nearbyLayer) return
  actionError.value = ''
  try {
    const center = nearbyCenter ?? map.getCenter()
    const result = await getNearby(center.lng, center.lat, nearbyRadius.value)
    nearbyLayer.clearLayers()
    L.circle(center, { radius: nearbyRadius.value, color: '#8249a1', weight: 2, fillOpacity: 0.04 }).addTo(nearbyLayer)
    for (const point of result.items) {
      const marker = L.circleMarker([point.latitude, point.longitude], {
        radius: 5, color: '#8249a1', fillOpacity: 0.7,
      }).addTo(nearbyLayer)
      marker.bindTooltip(tooltip(`事故 ${point.collision_id} · ${Math.round(point.distance_m ?? 0)} 米`))
      marker.on('click', () => void openLocation(point.location_id))
    }
    nearbyCount.value = result.items.length
    nearbyTruncated.value = result.truncated
  } catch (reason) { actionError.value = message(reason) }
}

async function runGeneration() {
  if (!canManage() || actionBusy.value) return
  actionBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await generateCandidates(boroughId.value, afterLocationId.value, maxLocations.value, radiusM.value)
    lastGeneration.value = result
    afterLocationId.value = result.last_location_id
    actionMessage.value = `已检查 ${result.processed} 个地点：新增候选 ${result.created_candidates}、自动归属 ${result.auto_matched}；${result.has_more ? '可继续下一批。' : '该区已到末尾。'}`
    intersectionPage.value = 1
    await Promise.all([loadIntersections(), loadMap()])
  } catch (reason) { actionError.value = message(reason) }
  finally { actionBusy.value = false }
}

async function submitReview(confirm: boolean) {
  const item = selectedIntersection.value
  if (!item || !canManage() || actionBusy.value) return
  if (!reviewNote.value.trim()) { actionError.value = '请填写复核依据。'; return }
  if (!window.confirm(confirm ? '确认这个候选交叉口及其依据？' : '拒绝这个候选交叉口？')) return
  actionBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await reviewIntersection(item.intersection_id, item.version, reviewNote.value.trim(), confirm)
    actionMessage.value = `${confirm ? '已确认' : '已拒绝'}；处理 ${result.assignments_changed} 个地点，数据版本 ${result.data_revision}。`
    reviewNote.value = ''
    await Promise.all([loadIntersections(), openIntersection(item.intersection_id), loadMap()])
  } catch (reason) { actionError.value = message(reason) }
  finally { actionBusy.value = false }
}

async function submitAssignment() {
  const item = selectedLocation.value
  if (!item || !canManage() || actionBusy.value) return
  if (!manualReason.value.trim()) { actionError.value = '请填写人工判断依据。'; return }
  if (manualStatus.value === 'MANUAL_CONFIRMED' && !/^\d+$/.test(manualTargetId.value)) {
    actionError.value = '请输入已确认交叉口编号。'; return
  }
  if (!window.confirm('确认修改这个观察地点的归属？')) return
  actionBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await setLocationAssignment(item.location_id, item.version,
      manualStatus.value, manualTargetId.value, manualReason.value.trim())
    actionMessage.value = `地点归属已更新；版本 ${result.version}，数据版本 ${result.data_revision}。`
    manualReason.value = ''
    await Promise.all([openLocation(item.location_id), loadIntersections(), loadMap()])
  } catch (reason) { actionError.value = message(reason) }
  finally { actionBusy.value = false }
}

watch(statusFilter, () => { intersectionPage.value = 1; void loadIntersections() })
watch(intersectionPage, () => void loadIntersections())
watch(boroughId, () => { afterLocationId.value = '0'; lastGeneration.value = null })
watch(radiusM, () => { afterLocationId.value = '0'; lastGeneration.value = null })

onMounted(async () => {
  if (!mapHost.value) return
  map = L.map(mapHost.value, { preferCanvas: true }).setView([40.73, -73.95], 11)
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map)
  collisionLayer = L.layerGroup().addTo(map)
  intersectionLayer = L.layerGroup().addTo(map)
  nearbyLayer = L.layerGroup().addTo(map)
  map.on('moveend', () => { viewportChanged.value = true })
  map.on('click', event => { nearbyCenter = event.latlng; nearbyCount.value = null })
  await Promise.all([loadMap(), loadIntersections()])
})

onUnmounted(() => {
  clearLayers()
  map?.remove()
  map = null
})
</script>

<template>
  <section aria-labelledby="map-heading">
    <div class="section-title">
      <h2 id="map-heading">事故观察点与交叉口地图</h2>
      <button :disabled="loading" @click="loadMap">{{ loading ? '加载中…' : '查询当前地图范围' }}</button>
    </div>
    <p class="detail">蓝色为事故观察点，橙色为候选交叉口，绿色为已确认交叉口；候选不等于官方道路节点。点击地图可设置附近查询中心。</p>
    <div class="map-controls">
      <label>开始日期（包含）<input v-model="start" type="date" /></label>
      <label>结束日期（不包含）<input v-model="end" type="date" /></label>
      <label>交叉口状态
        <select v-model="statusFilter"><option value="ALL">全部状态</option><option value="CANDIDATE">候选</option><option value="CONFIRMED">已确认</option><option value="REJECTED">已拒绝</option></select>
      </label>
    </div>
    <p v-if="viewportChanged" class="detail">地图已移动；点击“查询当前地图范围”刷新事故点。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div ref="mapHost" class="map-canvas" aria-label="纽约事故观察点与交叉口地图"></div>
    <p v-if="summary" class="detail" aria-live="polite">
      查询期共 {{ summary.total }} 起事故；有坐标 {{ summary.geocoded }}、缺坐标 {{ summary.missing_coordinates }}、已归属确认交叉口 {{ summary.confirmed_assigned }}、尚无正式归属 {{ summary.unmatched }}。
      当前范围显示 {{ displayed }} 个点。<strong v-if="truncated">点数超过 500 上限，当前显示只是部分结果；请放大或缩小范围。</strong>
    </p>
    <p class="detail">没有坐标的事故仍保留在事故列表和上面的总数中，不会显示成地图点。底图需要网络；底图不可用时事故点和交叉口数据仍可查询。</p>
    <div class="map-controls">
      <label>附近半径（米）<input v-model.number="nearbyRadius" type="number" min="1" max="1000" /></label>
      <button class="secondary-button" @click="loadNearby">查询点击位置附近事故</button>
      <span v-if="nearbyCount !== null" class="detail">附近返回 {{ nearbyCount }} 起{{ nearbyTruncated ? '（达到上限，需缩小半径）' : '' }}</span>
    </div>

    <section class="map-subsection" aria-labelledby="intersection-list-heading">
      <div class="section-title"><h3 id="intersection-list-heading">交叉口档案</h3><span class="detail">共 {{ intersectionTotal }} 条；本页 {{ intersections.length }} 条</span></div>
      <p class="detail">列表按编号倒序分页，每页最多50条；地图标记也只绘制当前页档案。</p>
      <div class="map-controls">
        <button class="secondary-button" :disabled="intersectionPage <= 1" @click="intersectionPage--">上一页</button>
        <span class="detail">第 {{ intersectionPage }} / {{ intersectionPages }} 页</span>
        <button class="secondary-button" :disabled="intersectionPage >= intersectionPages" @click="intersectionPage++">下一页</button>
      </div>
      <div v-if="intersections.length" class="intersection-list">
        <button v-for="item in intersections" :key="item.intersection_id" class="secondary-button intersection-item" @click="openIntersection(item.intersection_id)">
          {{ item.intersection_code }} · {{ item.street_a }} / {{ item.street_b }} · {{ item.status === 'CONFIRMED' ? '已确认' : item.status === 'REJECTED' ? '已拒绝' : '候选' }}
        </button>
      </div>
      <p v-else class="empty-state">当前状态尚无交叉口档案。</p>
    </section>

    <section v-if="canManage()" class="map-subsection" aria-labelledby="candidate-heading">
      <h3 id="candidate-heading">按行政区生成候选</h3>
      <p class="detail">仅处理有坐标、主街与横街不同的地点；按地点编号逐批推进，50 米为待人工复核的课程参数。</p>
      <div class="map-controls">
        <label>行政区<select v-model.number="boroughId"><option :value="1">BRONX</option><option :value="2">BROOKLYN</option><option :value="3">MANHATTAN</option><option :value="4">QUEENS</option><option :value="5">STATEN ISLAND</option></select></label>
        <label>半径（米）<input v-model.number="radiusM" type="number" min="20" max="80" /></label>
        <label>每批地点数<input v-model.number="maxLocations" type="number" min="1" max="100" /></label>
        <button :disabled="actionBusy" @click="runGeneration">{{ actionBusy ? '执行中…' : '生成下一批候选' }}</button>
        <button class="secondary-button" @click="afterLocationId = '0'; lastGeneration = null">从本区开头重新检查</button>
      </div>
      <p v-if="lastGeneration" class="detail">上次处理至地点 {{ lastGeneration.last_location_id }}；{{ lastGeneration.has_more ? '还有后续地点' : '已到当前末尾' }}。重复检查不会覆盖人工判断。</p>
    </section>

    <section v-if="selectedIntersection" class="map-subsection" aria-labelledby="intersection-detail-heading">
      <div class="section-title"><h3 id="intersection-detail-heading">交叉口 {{ selectedIntersection.intersection_code }}</h3><button class="secondary-button" @click="selectedIntersection = null">收起</button></div>
      <p class="detail">{{ selectedIntersection.street_a }} / {{ selectedIntersection.street_b }} · {{ selectedIntersection.status }} · 来源 {{ selectedIntersection.source_method }} · 版本 {{ selectedIntersection.version }}</p>
      <p class="detail">关联地点 {{ selectedIntersection.location_count }} 个；已有风险画像 {{ selectedIntersection.risk_profile_count }} 个。系统推导候选中心是第一个观察点，不代表官方路口坐标。</p>
      <p v-if="selectedIntersection.confirmation_note" class="detail">复核依据：{{ selectedIntersection.confirmation_note }}</p>
      <div v-if="selectedIntersection.locations.length" class="intersection-list">
        <button v-for="location in selectedIntersection.locations" :key="location.location_id" class="secondary-button intersection-item" @click="openLocation(location.location_id)">
          地点 {{ location.location_id }} · {{ location.on_street_name || '街名缺失' }} / {{ location.cross_street_name || '横街缺失' }} · {{ location.match_status }}
        </button>
      </div>
      <div v-if="canManage() && selectedIntersection.status === 'CANDIDATE'" class="map-controls">
        <label class="wide-input">复核依据<textarea v-model="reviewNote" rows="2" maxlength="2000" placeholder="记录现场或地图核查依据"></textarea></label>
        <button :disabled="actionBusy" @click="submitReview(true)">确认候选</button>
        <button :disabled="actionBusy" class="secondary-button" @click="submitReview(false)">拒绝候选</button>
      </div>
    </section>

    <section v-if="selectedLocation" class="map-subsection" aria-labelledby="assignment-heading">
      <div class="section-title"><h3 id="assignment-heading">观察地点 {{ selectedLocation.location_id }}</h3><button class="secondary-button" @click="selectedLocation = null">收起</button></div>
      <p class="detail">{{ selectedLocation.on_street_name || '主街未知' }} / {{ selectedLocation.cross_street_name || '横街未知' }} · {{ selectedLocation.match_status }} · 当前版本 {{ selectedLocation.version }}</p>
      <p class="detail">归属交叉口：{{ selectedLocation.intersection_id || '尚无正式归属' }}。人工改派会记录审计并使分析数据版本增加。</p>
      <div v-if="canManage()" class="map-controls">
        <label>人工状态<select v-model="manualStatus"><option value="MANUAL_CONFIRMED">人工确认归属</option><option value="REJECTED">拒绝归属</option><option value="UNMATCHED">解除归属</option></select></label>
        <label v-if="manualStatus === 'MANUAL_CONFIRMED'">已确认交叉口编号<input v-model="manualTargetId" inputmode="numeric" /></label>
        <label class="wide-input">理由<textarea v-model="manualReason" rows="2" maxlength="2000"></textarea></label>
        <button :disabled="actionBusy" @click="submitAssignment">保存人工判断</button>
      </div>
    </section>
    <p v-if="detailError" class="error" role="alert">{{ detailError }}</p>
    <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
    <p v-if="actionMessage" class="notice" role="status">{{ actionMessage }}</p>
  </section>
</template>
