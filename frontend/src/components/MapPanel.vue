<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { ElButton, ElTag } from 'element-plus'
import { sessionUser } from '../api/auth'
import {
  generateCandidates, getIntersection, getIntersections, getLocationAssignment, getMapCollisions,
  getNearby, reviewIntersection, setLocationAssignment,
  type Generation, type Intersection, type IntersectionDetail, type LocationAssignment, type MapCoverage,
} from '../api/m3'

const route = useRoute()
const mapHost = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let collisionLayer: L.LayerGroup | null = null
let intersectionLayer: L.LayerGroup | null = null
let nearbyLayer: L.LayerGroup | null = null
let mapResizeObserver: ResizeObserver | null = null
let resizeFrame = 0
let intersectionSequence = 0
const componentReady = ref(false)
const pendingMapLoad = ref(false)
const mobileView = ref<'map' | 'list'>('map')
function switchMobilePanel(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  mobileView.value = event.key === 'Home' ? 'map' : event.key === 'End' ? 'list' : mobileView.value === 'map' ? 'list' : 'map'
  const index = mobileView.value === 'map' ? 0 : 1
  ;(event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role=tab]')[index]?.focus()
}
const loading = ref(false)
const intersectionLoading = ref(false)
const error = ref('')
const archiveError = ref('')
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
const locationCoordinateMessage = ref('')
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
const boroughs = [
  { id: 1, label: '布朗克斯' },
  { id: 2, label: '布鲁克林' },
  { id: 3, label: '曼哈顿' },
  { id: 4, label: '皇后区' },
  { id: 5, label: '史泰登岛' },
]
let nearbyCenter: L.LatLng | null = null

const canManage = computed(() => sessionUser.value?.role === 'ADMIN' || sessionUser.value?.role === 'MANAGER')
const message = (value: unknown) => value instanceof Error ? value.message : '请求未完成，请稍后重试。'

function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(value + 'T00:00:00Z')
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value
}

function routeDateRange(startValue: unknown, endValue: unknown) {
  if (!validDate(startValue) || !validDate(endValue) || endValue <= startValue) return null
  return { start: startValue, end: endValue }
}

watch(
  () => [route.query.start, route.query.end],
  ([startValue, endValue]) => {
    const range = routeDateRange(startValue, endValue)
    if (!range) return
    start.value = range.start
    end.value = range.end
    if (componentReady.value) void loadMap()
  },
  { immediate: true },
)

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

function boroughLabel(value: number | string | null | undefined) {
  const id = value === null || value === undefined ? '' : Number(value)
  return boroughs.find((borough) => borough.id === id)?.label ?? '行政区未知'
}

function statusLabel(status: Intersection['status']) {
  if (status === 'CONFIRMED') return '已确认'
  if (status === 'REJECTED') return '已拒绝'
  return '待复核候选'
}

function statusTone(status: Intersection['status']) {
  if (status === 'CONFIRMED') return 'success'
  if (status === 'REJECTED') return 'info'
  return 'warning'
}

async function loadMap() {
  if (!map) return
  if (loading.value) {
    pendingMapLoad.value = true
    return
  }
  if (start.value >= end.value) {
    error.value = '结束日期必须晚于开始日期；结束日期按排他边界处理。'
    return
  }
  loading.value = true
  error.value = ''
  const queryBounds = map.getBounds()
  try {
    const result = await getMapCollisions({
      start: start.value, end: end.value, west: queryBounds.getWest(), south: queryBounds.getSouth(),
      east: queryBounds.getEast(), north: queryBounds.getNorth(), limit: 500,
    })
    if (!collisionLayer || !map) return
    collisionLayer.clearLayers()
    for (const point of result.items) {
      const marker = L.circleMarker([point.latitude, point.longitude], {
        radius: 5, color: '#083da6', weight: 1, fillColor: '#3478e5', fillOpacity: 0.74,
      }).addTo(collisionLayer)
      marker.bindTooltip(tooltip(point.crash_date + ' · 事故 ' + point.collision_id))
      marker.on('click', () => void openLocation(point.location_id))
    }
    summary.value = result.coverage
    displayed.value = result.returned
    truncated.value = result.truncated
    const latestBounds = map.getBounds()
    viewportChanged.value = Math.abs(latestBounds.getWest() - queryBounds.getWest()) > 0.000001
      || Math.abs(latestBounds.getSouth() - queryBounds.getSouth()) > 0.000001
      || Math.abs(latestBounds.getEast() - queryBounds.getEast()) > 0.000001
      || Math.abs(latestBounds.getNorth() - queryBounds.getNorth()) > 0.000001
  } catch (reason) {
    error.value = message(reason)
  } finally {
    loading.value = false
    if (pendingMapLoad.value) {
      pendingMapLoad.value = false
      void loadMap()
    }
  }
}

async function loadIntersections() {
  const sequence = ++intersectionSequence
  intersectionLoading.value = true
  archiveError.value = ''
  try {
    const result = await getIntersections(statusFilter.value === 'ALL' ? undefined : statusFilter.value, intersectionPage.value)
    if (sequence !== intersectionSequence) return
    intersections.value = result.items
    intersectionTotal.value = result.total
    if (!intersectionLayer) return
    intersectionLayer.clearLayers()
    for (const item of result.items) {
      const color = item.status === 'CONFIRMED' ? '#1f855e' : item.status === 'REJECTED' ? '#8a9298' : '#d69213'
      const marker = L.circleMarker([item.latitude, item.longitude], {
        radius: 8, color, fillColor: color, weight: 2, fillOpacity: 0.4,
      }).addTo(intersectionLayer)
      marker.bindTooltip(tooltip(statusLabel(item.status) + ' · ' + item.street_a + ' / ' + item.street_b))
      marker.on('click', () => void openIntersection(item.intersection_id))
    }
  } catch (reason) {
    if (sequence === intersectionSequence) archiveError.value = message(reason)
  } finally {
    if (sequence === intersectionSequence) intersectionLoading.value = false
  }
}

async function openIntersection(id: string) {
  detailError.value = ''
  selectedLocation.value = null
  locationCoordinateMessage.value = ''
  mobileView.value = 'list'
  try {
    const item = await getIntersection(id)
    selectedIntersection.value = item
    map?.panTo([item.latitude, item.longitude])
  } catch (reason) { detailError.value = message(reason) }
}

async function openLocation(id: string) {
  detailError.value = ''
  locationCoordinateMessage.value = ''
  mobileView.value = 'list'
  try {
    const item = await getLocationAssignment(id)
    selectedLocation.value = item
    manualStatus.value = item.match_status === 'MANUAL_CONFIRMED' ? 'MANUAL_CONFIRMED' : 'UNMATCHED'
    manualTargetId.value = item.intersection_id ?? ''
    if (item.latitude !== null && item.longitude !== null) map?.panTo([item.latitude, item.longitude])
    else locationCoordinateMessage.value = '该观察地点缺少坐标，仍可查看其归属并进行人工判断。'
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
        radius: 5, color: '#8249a1', fillColor: '#a46bc2', fillOpacity: 0.74,
      }).addTo(nearbyLayer)
      marker.bindTooltip(tooltip('事故 ' + point.collision_id + ' · ' + Math.round(point.distance_m ?? 0) + ' 米'))
      marker.on('click', () => void openLocation(point.location_id))
    }
    nearbyCount.value = result.items.length
    nearbyTruncated.value = result.truncated
  } catch (reason) { actionError.value = message(reason) }
}

async function runGeneration() {
  if (!canManage.value || actionBusy.value) return
  actionBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await generateCandidates(boroughId.value, afterLocationId.value, maxLocations.value, radiusM.value)
    lastGeneration.value = result
    afterLocationId.value = result.last_location_id
    actionMessage.value = '已检查 ' + result.processed + ' 个地点：新增候选 ' + result.created_candidates + '、自动归属 ' + result.auto_matched + '；' + (result.has_more ? '可继续下一批。' : '该区已到末尾。')
    intersectionPage.value = 1
    await Promise.all([loadIntersections(), loadMap()])
  } catch (reason) { actionError.value = message(reason) }
  finally { actionBusy.value = false }
}

async function submitReview(confirm: boolean) {
  const item = selectedIntersection.value
  if (!item || !canManage.value || actionBusy.value) return
  if (!reviewNote.value.trim()) { actionError.value = '请填写复核依据。'; return }
  if (!window.confirm(confirm ? '确认这个候选交叉口及其依据？' : '拒绝这个候选交叉口？')) return
  actionBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await reviewIntersection(item.intersection_id, item.version, reviewNote.value.trim(), confirm)
    actionMessage.value = (confirm ? '已确认' : '已拒绝') + '；处理 ' + result.assignments_changed + ' 个地点，数据版本 ' + result.data_revision + '。'
    reviewNote.value = ''
    await Promise.all([loadIntersections(), openIntersection(item.intersection_id), loadMap()])
  } catch (reason) { actionError.value = message(reason) }
  finally { actionBusy.value = false }
}

async function submitAssignment() {
  const item = selectedLocation.value
  if (!item || !canManage.value || actionBusy.value) return
  if (!manualReason.value.trim()) { actionError.value = '请填写人工判断依据。'; return }
  if (manualStatus.value === 'MANUAL_CONFIRMED' && !/^\d+$/.test(manualTargetId.value)) {
    actionError.value = '请输入已确认交叉口编号。'
    return
  }
  if (!window.confirm('确认修改这个观察地点的归属？')) return
  actionBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await setLocationAssignment(item.location_id, item.version,
      manualStatus.value, manualTargetId.value, manualReason.value.trim())
    actionMessage.value = '地点归属已更新；版本 ' + result.version + '，数据版本 ' + result.data_revision + '。'
    manualReason.value = ''
    await Promise.all([openLocation(item.location_id), loadIntersections(), loadMap()])
  } catch (reason) { actionError.value = message(reason) }
  finally { actionBusy.value = false }
}

watch(statusFilter, () => { intersectionPage.value = 1; void loadIntersections() })
watch(intersectionPage, () => void loadIntersections())
watch([boroughId, radiusM], () => { afterLocationId.value = '0'; lastGeneration.value = null })

onMounted(async () => {
  if (!mapHost.value) return
  map = L.map(mapHost.value, { preferCanvas: true }).setView([40.73, -73.95], 11)
  map.zoomControl.setPosition('topright')
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map)
  collisionLayer = L.layerGroup().addTo(map)
  intersectionLayer = L.layerGroup().addTo(map)
  nearbyLayer = L.layerGroup().addTo(map)
  map.on('moveend', () => { viewportChanged.value = true })
  map.on('click', event => { nearbyCenter = event.latlng; nearbyCount.value = null })
  mapResizeObserver = new ResizeObserver(() => {
    if (resizeFrame) cancelAnimationFrame(resizeFrame)
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = 0
      map?.invalidateSize({ pan: false })
    })
  })
  mapResizeObserver.observe(mapHost.value)
  componentReady.value = true
  await Promise.all([loadMap(), loadIntersections()])
})

onUnmounted(() => {
  componentReady.value = false
  intersectionSequence += 1
  mapResizeObserver?.disconnect()
  mapResizeObserver = null
  if (resizeFrame) cancelAnimationFrame(resizeFrame)
  resizeFrame = 0
  clearLayers()
  map?.remove()
  map = null
})
</script>

<template>
  <section aria-labelledby="map-heading" class="map-panel">
    <header class="panel-heading">
      <div>
        <p class="panel-kicker">空间分析</p>
        <h2 id="map-heading">事故观察点与交叉口地图</h2>
      </div>
      <ElTag effect="plain" round>候选点需人工复核</ElTag>
    </header>

    <form class="map-toolbar" @submit.prevent="loadMap">
      <label>开始日期（包含）<input v-model="start" type="date" /></label>
      <label>结束日期（不包含）<input v-model="end" type="date" /></label>
      <label>交叉口状态
        <select v-model="statusFilter">
          <option value="ALL">全部状态</option><option value="CANDIDATE">待复核候选</option><option value="CONFIRMED">已确认</option><option value="REJECTED">已拒绝</option>
        </select>
      </label>
      <ElButton type="primary" native-type="submit" :loading="loading">{{ loading ? '加载中…' : '查询当前地图范围' }}</ElButton>
    </form>

    <div class="mobile-switch" role="tablist" aria-label="地图和结果切换" @keydown="switchMobilePanel">
      <ElButton id="map-view-tab" :type="mobileView === 'map' ? 'primary' : 'default'" role="tab" :aria-selected="mobileView === 'map'" :tabindex="mobileView === 'map' ? 0 : -1" aria-controls="map-view-panel" @click="mobileView = 'map'">地图</ElButton>
      <ElButton id="map-results-tab" :type="mobileView === 'list' ? 'primary' : 'default'" role="tab" :aria-selected="mobileView === 'list'" :tabindex="mobileView === 'list' ? 0 : -1" aria-controls="map-results-panel" @click="mobileView = 'list'">结果与操作</ElButton>
    </div>

    <p v-if="error" class="feedback-error" role="alert">{{ error }}</p>
    <div class="workspace-layout">
      <div id="map-view-panel" class="map-column" role="tabpanel" aria-labelledby="map-view-tab" :class="{ 'mobile-hidden': mobileView !== 'map' }">
        <div class="map-stage">
          <div ref="mapHost" class="map-canvas" aria-label="纽约事故观察点与交叉口地图"></div>
          <div class="map-legend" aria-label="地图图例">
            <strong>图例</strong>
            <span><i class="legend-dot collision-dot"></i>事故观察点</span>
            <span><i class="legend-dot candidate-dot"></i>待复核候选</span>
            <span><i class="legend-dot confirmed-dot"></i>已确认交叉口</span>
            <span><i class="legend-dot nearby-dot"></i>附近查询结果</span>
          </div>
        </div>
        <p v-if="viewportChanged" class="map-guidance" role="status">地图范围或中心已变化；点击“查询当前地图范围”刷新事故点。</p>
        <p class="map-guidance">点击地图可设置附近查询中心。没有坐标的事故仍保留在查询总数中，不会显示成地图点；底图需要网络，底图不可用时事故点与交叉口数据仍可查询。</p>
      </div>

      <aside id="map-results-panel" class="result-sidebar" role="tabpanel" aria-labelledby="map-results-tab" :class="{ 'mobile-hidden': mobileView !== 'list' }" aria-label="地图结果与操作">
        <section v-if="summary" class="sidebar-card coverage-card" aria-labelledby="coverage-heading">
          <div class="sidebar-card-heading"><h3 id="coverage-heading">查询覆盖</h3><ElTag effect="plain">{{ displayed }} 个地图点</ElTag></div>
          <div class="coverage-grid">
            <div><strong>{{ summary.total.toLocaleString() }}</strong><span>查询期事故</span></div>
            <div><strong>{{ summary.geocoded.toLocaleString() }}</strong><span>有坐标</span></div>
            <div><strong>{{ summary.missing_coordinates.toLocaleString() }}</strong><span>缺少坐标</span></div>
            <div><strong>{{ summary.confirmed_assigned.toLocaleString() }}</strong><span>已归属确认路口</span></div>
            <div><strong>{{ summary.unmatched.toLocaleString() }}</strong><span>尚无正式归属</span></div>
          </div>
          <p v-if="truncated" class="coverage-warning"><strong>地图点数超过 500 上限，当前显示只是部分结果。请放大范围后重新查询。</strong></p>
        </section>
        <p v-else class="sidebar-hint">调整日期后查询当前地图范围。覆盖总数包含缺少坐标的事故。</p>

        <section class="sidebar-card" aria-labelledby="archive-heading">
          <div class="sidebar-card-heading"><h3 id="archive-heading">交叉口档案</h3><ElTag effect="plain">共 {{ intersectionTotal.toLocaleString() }} 条</ElTag></div>
          <p class="sidebar-hint">按编号倒序分页，每页最多 50 条；地图标记只绘制当前页档案。</p>
          <p v-if="archiveError" class="feedback-error" role="alert">{{ archiveError }}</p>
          <p v-if="intersectionLoading" class="sidebar-hint" role="status">正在加载交叉口档案…</p>
          <div v-if="intersections.length" class="intersection-list">
            <ElButton
              v-for="item in intersections"
              :key="item.intersection_id"
              class="intersection-item"
              :class="{ selected: selectedIntersection?.intersection_id === item.intersection_id }"
              plain
              @click="openIntersection(item.intersection_id)"
            >
              <span class="intersection-item-text"><strong>{{ item.street_a }} / {{ item.street_b }}</strong><small>{{ item.intersection_code }} · {{ boroughLabel(item.borough_id) }}</small></span>
              <ElTag :type="statusTone(item.status)" effect="plain" size="small">{{ statusLabel(item.status) }}</ElTag>
            </ElButton>
          </div>
          <p v-else-if="!intersectionLoading && !archiveError" class="sidebar-hint">当前状态尚无交叉口档案。</p>
          <div class="archive-pagination">
            <ElButton plain size="small" :disabled="intersectionPage <= 1 || intersectionLoading" @click="intersectionPage--">上一页</ElButton>
            <span>第 {{ intersectionPage }} / {{ intersectionPages }} 页</span>
            <ElButton plain size="small" :disabled="intersectionPage >= intersectionPages || intersectionLoading" @click="intersectionPage++">下一页</ElButton>
          </div>
        </section>

        <details v-if="canManage" class="sidebar-card action-disclosure">
          <summary><span><strong>按行政区生成候选</strong><small>按批次扫描可定位的事故观察点</small></span></summary>
          <div class="action-content">
            <p class="sidebar-hint">仅处理有坐标、主街与横街不同的地点；50 米是待人工复核的课程参数，系统推导候选中心不代表官方道路节点。</p>
            <label>行政区
              <select v-model.number="boroughId">
                <option v-for="borough in boroughs" :key="borough.id" :value="borough.id">{{ borough.label }}</option>
              </select>
            </label>
            <div class="compact-fields">
              <label>半径（米）<input v-model.number="radiusM" type="number" min="20" max="80" /></label>
              <label>每批地点数<input v-model.number="maxLocations" type="number" min="1" max="100" /></label>
            </div>
            <div class="action-buttons">
              <ElButton type="primary" :disabled="actionBusy" @click="runGeneration">{{ actionBusy ? '执行中…' : '生成下一批候选' }}</ElButton>
              <ElButton plain :disabled="actionBusy" @click="afterLocationId = '0'; lastGeneration = null">从本区开头重新检查</ElButton>
            </div>
            <p v-if="lastGeneration" class="sidebar-hint">上次处理至地点 {{ lastGeneration.last_location_id }}；{{ lastGeneration.has_more ? '还有后续地点' : '已到当前末尾' }}。重复检查不会覆盖人工判断。</p>
          </div>
        </details>

        <section class="sidebar-card nearby-card" aria-labelledby="nearby-heading">
          <div class="sidebar-card-heading"><h3 id="nearby-heading">附近事故查询</h3><ElTag effect="plain">半径 {{ nearbyRadius }} 米</ElTag></div>
          <p class="sidebar-hint">点击地图设置中心；未设置时使用当前地图中心。</p>
          <label>附近半径（米）<input v-model.number="nearbyRadius" type="number" min="1" max="1000" /></label>
          <ElButton type="primary" plain :disabled="loading" @click="loadNearby">查询点击位置附近事故</ElButton>
          <p v-if="nearbyCount !== null" class="nearby-result" role="status">附近返回 {{ nearbyCount }} 起{{ nearbyTruncated ? '（达到上限，需缩小半径）' : '' }}</p>
        </section>

        <section v-if="selectedIntersection" class="sidebar-card selected-card" aria-labelledby="intersection-detail-heading">
          <div class="sidebar-card-heading">
            <div><p class="panel-kicker">交叉口档案</p><h3 id="intersection-detail-heading">{{ selectedIntersection.intersection_code }}</h3></div>
            <ElButton text @click="selectedIntersection = null">收起</ElButton>
          </div>
          <p class="selected-street">{{ selectedIntersection.street_a }} / {{ selectedIntersection.street_b }}</p>
          <div class="tag-row">
            <ElTag :type="statusTone(selectedIntersection.status)" effect="plain">{{ statusLabel(selectedIntersection.status) }}</ElTag>
            <ElTag effect="plain">{{ boroughLabel(selectedIntersection.borough_id) }}</ElTag>
            <ElTag effect="plain">版本 {{ selectedIntersection.version }}</ElTag>
          </div>
          <p class="sidebar-hint">来源 {{ selectedIntersection.source_method }} · 关联地点 {{ selectedIntersection.location_count }} 个 · 已有风险画像 {{ selectedIntersection.risk_profile_count }} 个</p>
          <p v-if="selectedIntersection.confirmation_note" class="sidebar-hint">复核依据：{{ selectedIntersection.confirmation_note }}</p>
          <div v-if="selectedIntersection.locations.length" class="related-location-list">
            <strong>关联观察地点</strong>
            <ElButton v-for="location in selectedIntersection.locations" :key="location.location_id" plain @click="openLocation(location.location_id)">
              地点 {{ location.location_id }} · {{ location.on_street_name || '街名缺失' }} / {{ location.cross_street_name || '横街缺失' }} · {{ location.match_status }}
            </ElButton>
          </div>
          <div v-if="canManage && selectedIntersection.status === 'CANDIDATE'" class="review-form">
            <label>复核依据<textarea v-model="reviewNote" rows="2" maxlength="2000" placeholder="记录现场或地图核查依据"></textarea></label>
            <div class="action-buttons">
              <ElButton type="primary" :disabled="actionBusy" @click="submitReview(true)">确认候选</ElButton>
              <ElButton type="danger" plain :disabled="actionBusy" @click="submitReview(false)">拒绝候选</ElButton>
            </div>
          </div>
        </section>

        <section v-if="selectedLocation" class="sidebar-card selected-card" aria-labelledby="assignment-heading">
          <div class="sidebar-card-heading">
            <div><p class="panel-kicker">观察地点归属</p><h3 id="assignment-heading">地点 {{ selectedLocation.location_id }}</h3></div>
            <ElButton text @click="selectedLocation = null; locationCoordinateMessage = ''">收起</ElButton>
          </div>
          <p class="selected-street">{{ selectedLocation.on_street_name || '主街未知' }} / {{ selectedLocation.cross_street_name || '横街未知' }}</p>
          <div class="tag-row"><ElTag effect="plain">{{ selectedLocation.match_status }}</ElTag><ElTag effect="plain">版本 {{ selectedLocation.version }}</ElTag></div>
          <p class="sidebar-hint">归属交叉口：{{ selectedLocation.intersection_id || '尚无正式归属' }}。人工改派会记录审计并使分析数据版本增加。</p>
          <p v-if="locationCoordinateMessage" class="coverage-warning" role="status">{{ locationCoordinateMessage }}</p>
          <div v-if="canManage" class="review-form">
            <label>人工状态<select v-model="manualStatus"><option value="MANUAL_CONFIRMED">人工确认归属</option><option value="REJECTED">拒绝归属</option><option value="UNMATCHED">解除归属</option></select></label>
            <label v-if="manualStatus === 'MANUAL_CONFIRMED'">已确认交叉口编号<input v-model="manualTargetId" inputmode="numeric" /></label>
            <label>理由<textarea v-model="manualReason" rows="2" maxlength="2000"></textarea></label>
            <ElButton type="primary" :disabled="actionBusy" @click="submitAssignment">保存人工判断</ElButton>
          </div>
        </section>
      </aside>
    </div>

    <p v-if="detailError" class="feedback-error" role="alert">{{ detailError }}</p>
    <p v-if="actionError" class="feedback-error" role="alert">{{ actionError }}</p>
    <p v-if="actionMessage" class="feedback-success" role="status">{{ actionMessage }}</p>
  </section>
</template>

<style scoped>
.map-panel {
  --panel-line: var(--line, #dce3ed);
  --panel-muted: var(--muted, #65748a);
  --panel-surface: var(--surface, #fff);
  min-width: 0;
  padding: 22px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel-surface);
  box-shadow: 0 8px 24px rgb(20 42 82 / 4%);
}
.panel-heading, .sidebar-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.panel-heading { margin-bottom: 18px; }
.panel-heading h2 { margin: 0; color: #16365d; font-size: 21px; }
.panel-kicker { margin: 0 0 5px; color: var(--muted, #65748a); font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.map-toolbar {
  display: grid;
  grid-template-columns: repeat(3, minmax(150px, 1fr)) auto;
  align-items: end;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line, #dce3ed);
  border-radius: 9px;
  background: #f9fbfe;
}
.map-toolbar label, .result-sidebar label, .review-form label {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: #394b64;
  font-size: 13px;
  font-weight: 600;
}
.map-toolbar input, .map-toolbar select, .result-sidebar input, .result-sidebar select, .result-sidebar textarea {
  width: 100%;
  min-width: 0;
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid var(--line, #dce3ed);
  border-radius: 7px;
  background: #fff;
  color: #263a55;
  font: inherit;
}
.result-sidebar textarea { resize: vertical; }
.mobile-switch { display: none; }
.feedback-error { margin: 12px 0; color: #b42318; line-height: 1.55; }
.feedback-success { margin: 12px 0; color: #167054; line-height: 1.55; }
.workspace-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(310px, 360px);
  align-items: start;
  gap: 14px;
  margin-top: 14px;
}
.map-column, .result-sidebar { min-width: 0; }
.map-stage { position: relative; min-width: 0; overflow: hidden; border: 1px solid #c8d4e5; border-radius: 10px; background: #e7edf6; }
.map-canvas { width: 100%; height: clamp(440px, 72vh, 760px); min-height: 360px; }
.map-legend {
  position: absolute;
  z-index: 500;
  top: 14px;
  left: 14px;
  display: grid;
  gap: 7px;
  min-width: 170px;
  padding: 11px 12px;
  border: 1px solid rgb(196 207 224 / 85%);
  border-radius: 8px;
  background: rgb(255 255 255 / 95%);
  box-shadow: 0 3px 12px rgb(24 47 82 / 12%);
  color: #334760;
  font-size: 12px;
}
.map-legend strong { color: #17365e; }
.map-legend span { display: flex; align-items: center; gap: 8px; }
.legend-dot { width: 10px; height: 10px; border: 2px solid #fff; border-radius: 50%; box-shadow: 0 0 0 1px rgb(31 47 72 / 25%); }
.collision-dot { background: #3478e5; }
.candidate-dot { background: #d69213; }
.confirmed-dot { background: #1f855e; }
.nearby-dot { background: #a46bc2; }
.map-guidance, .sidebar-hint { margin: 9px 0; color: var(--muted, #65748a); font-size: 12px; line-height: 1.55; }
.result-sidebar {
  position: sticky;
  top: 14px;
  display: grid;
  gap: 11px;
  max-height: min(82vh, 790px);
  overflow-y: auto;
  padding-right: 2px;
}
.sidebar-card {
  margin: 0;
  padding: 14px;
  border: 1px solid var(--line, #dce3ed);
  border-radius: 9px;
  background: #fff;
}
.sidebar-card h3 { margin: 0; color: #18365e; font-size: 15px; }
.coverage-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.coverage-grid > div { display: grid; gap: 3px; padding: 9px; border-radius: 7px; background: #f5f7fb; }
.coverage-grid strong { color: #173f7f; font-size: 16px; }
.coverage-grid span { color: #617187; font-size: 11px; }
.coverage-warning { margin: 9px 0 0; color: #8b5b0a; font-size: 12px; line-height: 1.5; }
.intersection-list { display: grid; gap: 6px; max-height: 300px; overflow: auto; }
.intersection-item { display: flex; width: 100%; height: auto; justify-content: space-between; gap: 8px; padding: 8px; text-align: left; white-space: normal; }
.intersection-item-text { display: grid; min-width: 0; gap: 3px; }
.intersection-item-text strong { color: #203c61; overflow-wrap: anywhere; }
.intersection-item-text small { color: var(--muted, #65748a); font-size: 11px; }
.intersection-item.selected { border-color: var(--primary, #083da6); background: #f1f5ff; }
.archive-pagination { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: 10px; }
.archive-pagination span { color: var(--muted, #65748a); font-size: 11px; white-space: nowrap; }
.action-disclosure { padding: 0; }
.action-disclosure > summary { display: flex; cursor: pointer; align-items: center; padding: 14px; list-style-position: inside; }
.action-disclosure > summary span { display: grid; gap: 4px; }
.action-disclosure > summary strong { color: #18365e; font-size: 14px; }
.action-disclosure > summary small { color: var(--muted, #65748a); font-size: 11px; }
.action-content { display: grid; gap: 10px; padding: 0 14px 14px; }
.compact-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.action-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
.nearby-card { display: grid; gap: 9px; }
.nearby-card .sidebar-hint { margin: 0; }
.nearby-result { margin: 0; color: #394b64; font-size: 12px; }
.selected-card { display: grid; gap: 8px; }
.selected-card .sidebar-card-heading { align-items: flex-start; }
.selected-street { margin: 0; color: #334760; font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.selected-card .sidebar-hint { margin: 0; }
.related-location-list { display: grid; gap: 7px; }
.related-location-list > strong { color: #394b64; font-size: 12px; }
.related-location-list .el-button { height: auto; min-height: 32px; justify-content: flex-start; white-space: normal; text-align: left; overflow-wrap: anywhere; }
.review-form { display: grid; gap: 10px; padding-top: 10px; border-top: 1px solid var(--line, #dce3ed); }
.review-form .action-buttons { align-items: center; }
@media (max-width: 1040px) {
  .map-panel { padding: 17px; }
  .workspace-layout { grid-template-columns: minmax(0, 1fr) 310px; gap: 10px; }
  .map-toolbar { grid-template-columns: repeat(2, minmax(150px, 1fr)); }
  .map-toolbar .el-button { justify-self: start; }
}
@media (max-width: 760px) {
  .panel-heading { align-items: flex-start; flex-direction: column; gap: 10px; }
  .map-panel { padding: 14px; }
  .panel-heading h2 { font-size: 19px; }
  .map-toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 11px; }
  .map-toolbar .el-button { grid-column: 1 / -1; justify-self: stretch; }
  .mobile-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
  .mobile-switch .el-button { margin: 0; }
  .workspace-layout { display: block; }
  .map-column.mobile-hidden, .result-sidebar.mobile-hidden { display: none; }
  .result-sidebar { position: static; max-height: none; overflow: visible; margin-top: 12px; padding: 0; }
  .map-canvas { height: min(66vh, 560px); min-height: 340px; }
  .map-legend { top: 9px; left: 9px; min-width: 150px; padding: 9px; font-size: 11px; }
  .intersection-list { max-height: 42vh; }
}
@media (max-width: 460px) {
  .map-toolbar { grid-template-columns: 1fr; }
  .map-toolbar .el-button { grid-column: auto; }
  .map-legend { min-width: 0; }
  .coverage-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .compact-fields { grid-template-columns: 1fr; }
}
</style>
