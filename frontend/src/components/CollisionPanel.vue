<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElButton, ElDrawer, ElTabPane, ElTabs, ElTag } from 'element-plus'
import { sessionUser } from '../api/auth'
import {
  getCollision, listCollisions, listFactors, listPersons, listVehicleTypes, listVehicles,
  type Collision, type CollisionDetail, type CollisionFilters, type DictionaryItem, type PersonItem, type VehicleItem,
} from '../api/m2'

const pageSize = 25
const detailPageSize = 20
const route = useRoute()
const componentReady = ref(false)
const pendingSearch = ref(false)
const boroughs = [
  { id: '1', label: '布朗克斯' },
  { id: '2', label: '布鲁克林' },
  { id: '3', label: '曼哈顿' },
  { id: '4', label: '皇后区' },
  { id: '5', label: '史泰登岛' },
]
const filters = reactive({ start: '', end: '', boroughId: '', street: '', vehicleTypeId: '', factorId: '' })
const collisions = ref<Collision[]>([])
const nextCursor = ref<string | null>(null)
const total = ref<number | null>(null)
const loading = ref(false)
const queryError = ref('')
const vehicleTypes = ref<DictionaryItem[]>([])
const factors = ref<DictionaryItem[]>([])
const dictionaryError = ref('')

const appliedFilters = ref<CollisionFilters | null>(null)
const appliedSignature = ref('')
const currentSignature = computed(() => signature(makeFilters()))
const queryChanged = computed(() => appliedFilters.value !== null && currentSignature.value !== appliedSignature.value)
const canLoadMoreCollisions = computed(() => Boolean(nextCursor.value) && !loading.value && !queryChanged.value)

const drawerOpen = ref(false)
const activeDetailTab = ref<'persons' | 'vehicles'>('persons')
const selectedId = ref('')
const detail = ref<CollisionDetail | null>(null)
const persons = ref<PersonItem[]>([])
const vehicles = ref<VehicleItem[]>([])
const personTotal = ref<number | null>(null)
const vehicleTotal = ref<number | null>(null)
const personPage = ref(1)
const vehiclePage = ref(1)
const detailBusy = ref(false)
const detailError = ref('')
const peopleError = ref('')
const vehiclesError = ref('')
const peopleBusy = ref(false)
const vehiclesBusy = ref(false)
let detailSequence = 0

const canSeePersonDetails = computed(() => sessionUser.value?.role !== 'VIEWER')
const collisionCount = computed(() => total.value === null ? '总数暂不可用' : '共 ' + total.value.toLocaleString() + ' 起')

function display(value: string | number | null | undefined) {
  return value === null || value === undefined || value === '' ? '缺失' : String(value)
}

function casualtyRows(collision: Collision) {
  return [
    ['人员受伤', collision.persons_injured],
    ['人员死亡', collision.persons_killed],
    ['行人受伤', collision.pedestrians_injured],
    ['行人死亡', collision.pedestrians_killed],
    ['骑行者受伤', collision.cyclists_injured],
    ['骑行者死亡', collision.cyclists_killed],
    ['机动车乘员受伤', collision.motorists_injured],
    ['机动车乘员死亡', collision.motorists_killed],
  ] as const
}

function streetSummary(collision: Collision) {
  const parts = [collision.on_street_name, collision.cross_street_name, collision.off_street_name]
    .filter((value): value is string => Boolean(value))
  return parts.length ? parts.join(' · ') : '街道信息缺失'
}

function makeFilters(): CollisionFilters {
  return {
    start: filters.start || undefined,
    end: filters.end || undefined,
    borough_id: filters.boroughId || undefined,
    street: filters.street.trim() || undefined,
    vehicle_type_id: filters.vehicleTypeId || undefined,
    factor_id: filters.factorId || undefined,
    page_size: pageSize,
    include_total: true,
  }
}

function signature(query: CollisionFilters) {
  return JSON.stringify(query)
}

async function loadDictionaryOptions() {
  dictionaryError.value = ''
  const [vehicleResult, factorResult] = await Promise.allSettled([listVehicleTypes(), listFactors()])
  if (vehicleResult.status === 'fulfilled') vehicleTypes.value = vehicleResult.value.items.filter((item) => item.is_active)
  else dictionaryError.value = vehicleResult.reason instanceof Error ? vehicleResult.reason.message : '车型筛选项暂不可用。'
  if (factorResult.status === 'fulfilled') factors.value = factorResult.value.items.filter((item) => item.is_active)
  else dictionaryError.value = factorResult.reason instanceof Error ? factorResult.reason.message : '原因筛选项暂不可用。'
}

async function search(reset = true) {
  if (loading.value) {
    if (reset) pendingSearch.value = true
    return
  }
  if (reset && filters.start && filters.end && filters.end <= filters.start) {
    queryError.value = '结束日期必须晚于开始日期；结束日期按排他边界处理。'
    return
  }

  let requestFilters: CollisionFilters
  if (reset) {
    requestFilters = makeFilters()
    appliedFilters.value = { ...requestFilters }
    appliedSignature.value = signature(requestFilters)
    collisions.value = []
    nextCursor.value = null
    total.value = null
  } else {
    const snapshot = appliedFilters.value
    if (!snapshot || queryChanged.value || !nextCursor.value) {
      queryError.value = '筛选条件已更改或没有后续页，请重新查询后继续浏览。'
      return
    }
    requestFilters = { ...snapshot, cursor: nextCursor.value }
  }

  loading.value = true
  queryError.value = ''
  try {
    const result = await listCollisions(requestFilters)
    collisions.value = reset ? result.items : collisions.value.concat(result.items)
    nextCursor.value = result.next_cursor
    total.value = result.total
  } catch (error) {
    queryError.value = error instanceof Error ? error.message : '事故查询暂未完成。'
  } finally {
    loading.value = false
    if (pendingSearch.value) {
      pendingSearch.value = false
      void search()
    }
  }
}

function clearDetail() {
  detailSequence += 1
  selectedId.value = ''
  detail.value = null
  persons.value = []
  vehicles.value = []
  personTotal.value = null
  vehicleTotal.value = null
  personPage.value = 1
  vehiclePage.value = 1
  detailBusy.value = false
  detailError.value = ''
  peopleError.value = ''
  vehiclesError.value = ''
}

async function openDetail(id: string) {
  const sequence = ++detailSequence
  drawerOpen.value = true
  selectedId.value = id
  activeDetailTab.value = 'persons'
  detail.value = null
  persons.value = []
  vehicles.value = []
  personTotal.value = null
  vehicleTotal.value = null
  personPage.value = 1
  vehiclePage.value = 1
  detailError.value = ''
  peopleError.value = ''
  vehiclesError.value = ''
  detailBusy.value = true
  const results = await Promise.allSettled([
    getCollision(id),
    listPersons(id, 1, detailPageSize),
    listVehicles(id, 1, detailPageSize),
  ])
  if (sequence !== detailSequence) return
  if (results[0].status === 'fulfilled') detail.value = results[0].value
  else detailError.value = results[0].reason instanceof Error ? results[0].reason.message : '事故详情暂不可用。'
  if (results[1].status === 'fulfilled') {
    persons.value = results[1].value.items
    personTotal.value = results[1].value.total
  } else peopleError.value = results[1].reason instanceof Error ? results[1].reason.message : '人员明细暂不可用。'
  if (results[2].status === 'fulfilled') {
    vehicles.value = results[2].value.items
    vehicleTotal.value = results[2].value.total
  } else vehiclesError.value = results[2].reason instanceof Error ? results[2].reason.message : '车辆明细暂不可用。'
  detailBusy.value = false
}

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
    filters.start = range.start
    filters.end = range.end
    if (componentReady.value) void search()
  },
  { immediate: true },
)
function canLoadMore(loaded: number, count: number | null) {
  return count === null ? loaded >= detailPageSize : loaded < count
}

async function loadMorePeople() {
  if (!selectedId.value || peopleBusy.value) return
  const id = selectedId.value
  const sequence = detailSequence
  const page = personPage.value + 1
  peopleBusy.value = true
  peopleError.value = ''
  try {
    const result = await listPersons(id, page, detailPageSize)
    if (sequence === detailSequence) {
      persons.value = persons.value.concat(result.items)
      personTotal.value = result.total
      personPage.value = page
    }
  } catch (error) {
    if (sequence === detailSequence) peopleError.value = error instanceof Error ? error.message : '人员明细暂不可用。'
  } finally {
    if (sequence === detailSequence) peopleBusy.value = false
  }
}

async function loadMoreVehicles() {
  if (!selectedId.value || vehiclesBusy.value) return
  const id = selectedId.value
  const sequence = detailSequence
  const page = vehiclePage.value + 1
  vehiclesBusy.value = true
  vehiclesError.value = ''
  try {
    const result = await listVehicles(id, page, detailPageSize)
    if (sequence === detailSequence) {
      vehicles.value = vehicles.value.concat(result.items)
      vehicleTotal.value = result.total
      vehiclePage.value = page
    }
  } catch (error) {
    if (sequence === detailSequence) vehiclesError.value = error instanceof Error ? error.message : '车辆明细暂不可用。'
  } finally {
    if (sequence === detailSequence) vehiclesBusy.value = false
  }
}

onMounted(() => {
  componentReady.value = true
  void loadDictionaryOptions()
  void search()
})
</script>

<template>
  <section aria-labelledby="collisions-heading" class="collision-panel">
    <header class="panel-heading">
      <div>
        <p class="panel-kicker">数据检索</p>
        <h2 id="collisions-heading">事故查询</h2>
      </div>
      <ElTag effect="plain" round>{{ collisionCount }}</ElTag>
    </header>

    <form class="filter-panel" @submit.prevent="search()">
      <div class="filter-group">
        <div class="filter-group-heading">
          <h3>常用筛选</h3>
          <span>日期、行政区与街道</span>
        </div>
        <div class="filter-grid">
          <label>开始日期（包含）<input v-model="filters.start" type="date" /></label>
          <label>结束日期（不包含）<input v-model="filters.end" type="date" /></label>
          <label>行政区
            <select v-model="filters.boroughId">
              <option value="">全部行政区</option>
              <option v-for="borough in boroughs" :key="borough.id" :value="borough.id">{{ borough.label }}</option>
            </select>
          </label>
          <label class="street-field">街道关键词<input v-model="filters.street" maxlength="120" placeholder="输入街道名称" /></label>
        </div>
      </div>

      <details class="advanced-filters">
        <summary>高级筛选 <span>车型、事故因素</span></summary>
        <div class="filter-grid advanced-grid">
          <label>车型<select v-model="filters.vehicleTypeId"><option value="">全部车型</option>
            <option v-for="item in vehicleTypes" :key="item.id" :value="item.id">{{ item.display_name || item.canonical_name }}</option>
          </select></label>
          <label>事故因素<select v-model="filters.factorId"><option value="">全部因素</option>
            <option v-for="item in factors" :key="item.id" :value="item.id">{{ item.display_name || item.canonical_name }}</option>
          </select></label>
        </div>
      </details>

      <div class="filter-footer">
        <div class="filter-status" aria-live="polite">
          <span v-if="queryChanged" class="query-warning">筛选条件已更改，当前结果仍对应上次查询；请重新查询后加载更多。</span>
          <span v-else-if="appliedFilters">结果按已提交的筛选条件分页。</span>
          <span v-if="dictionaryError" class="query-warning">{{ dictionaryError }}</span>
        </div>
        <ElButton type="primary" native-type="submit" :loading="loading">{{ loading ? '查询中…' : '查询事故' }}</ElButton>
      </div>
    </form>

    <p v-if="queryError" class="query-error" role="alert">{{ queryError }}</p>
    <p v-if="loading && !collisions.length" class="quiet-message" role="status">正在加载事故记录…</p>
    <p v-else-if="!loading && !collisions.length && !queryError" class="empty-state">没有匹配的事故记录。</p>

    <div v-if="collisions.length" class="results-frame">
      <div class="results-heading">
        <h3>查询结果</h3>
        <span>{{ collisions.length.toLocaleString() }} 条已加载<span v-if="total !== null"> / 共 {{ total.toLocaleString() }} 条</span></span>
      </div>

      <div class="desktop-table-wrap">
        <table class="collision-table">
          <thead>
            <tr><th>日期时间</th><th>行政区</th><th>事故街道</th><th>伤亡统计</th><th><span class="sr-only">操作</span></th></tr>
          </thead>
          <tbody>
            <tr v-for="collision in collisions" :key="collision.collision_id">
              <td class="date-cell"><strong>{{ collision.crash_date }}</strong><span>{{ display(collision.crash_time) }}</span></td>
              <td>{{ display(collision.borough_name) }}</td>
              <td class="street-cell">{{ streetSummary(collision) }}</td>
              <td>
                <div class="casualty-inline">
                  <span v-for="row in casualtyRows(collision)" :key="row[0]" :title="row[0]">{{ row[0].replace('人员', '').replace('机动车乘员', '乘员') }} <b>{{ display(row[1]) }}</b></span>
                </div>
              </td>
              <td><ElButton type="primary" plain size="small" @click="openDetail(collision.collision_id)">查看详情</ElButton></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mobile-collision-list">
        <article v-for="collision in collisions" :key="collision.collision_id" class="mobile-collision">
          <div class="mobile-card-heading">
            <div><strong>{{ collision.crash_date }} · {{ display(collision.crash_time) }}</strong><span>{{ display(collision.borough_name) }}</span></div>
            <ElButton type="primary" plain size="small" @click="openDetail(collision.collision_id)">详情</ElButton>
          </div>
          <p class="mobile-street">{{ streetSummary(collision) }}</p>
          <div class="mobile-casualties">
            <span>受伤 <b>{{ display(collision.persons_injured) }}</b></span>
            <span>死亡 <b>{{ display(collision.persons_killed) }}</b></span>
            <span>行人 <b>{{ display(collision.pedestrians_injured) }}</b> 伤 · <b>{{ display(collision.pedestrians_killed) }}</b> 死</span>
            <span>骑行者 <b>{{ display(collision.cyclists_injured) }}</b> 伤 · <b>{{ display(collision.cyclists_killed) }}</b> 死</span>
            <span>机动车乘员 <b>{{ display(collision.motorists_injured) }}</b> 伤 · <b>{{ display(collision.motorists_killed) }}</b> 死</span>
          </div>
        </article>
      </div>

      <div v-if="nextCursor" class="load-more-row">
        <ElButton type="primary" plain :disabled="!canLoadMoreCollisions" :loading="loading" @click="search(false)">
          {{ queryChanged ? '重新查询后继续' : loading ? '加载中…' : '加载更多事故' }}
        </ElButton>
      </div>
    </div>

    <ElDrawer v-model="drawerOpen" direction="rtl" size="min(980px, 100vw)" :with-header="false" :append-to-body="true" class="collision-drawer" @closed="clearDetail">
      <div class="drawer-shell">
        <header class="drawer-heading">
          <div><p class="panel-kicker">事故档案</p><h2 id="collision-detail-heading">事故详情 <span v-if="selectedId">· {{ selectedId }}</span></h2></div>
          <ElButton circle aria-label="关闭事故详情" @click="drawerOpen = false">×</ElButton>
        </header>
        <div class="drawer-content">
          <p v-if="detailBusy" class="quiet-message" role="status">正在加载详情和人员、车辆明细…</p>
          <p v-if="detailError" class="query-error" role="alert">{{ detailError }}</p>
          <template v-if="detail">
            <dl class="facts-grid">
              <div><dt>日期与时间</dt><dd>{{ detail.crash_date }} {{ display(detail.crash_time) }}</dd></div>
              <div><dt>行政区</dt><dd>{{ display(detail.borough_name) }}（{{ display(detail.borough_id) }}）</dd></div>
              <div><dt>街道</dt><dd>{{ streetSummary(detail) }}</dd></div>
              <div><dt>坐标</dt><dd>{{ display(detail.latitude) }}，{{ display(detail.longitude) }}</dd></div>
            </dl>
            <section class="detail-block" aria-labelledby="casualty-heading">
              <h3 id="casualty-heading">伤亡统计</h3>
              <div class="casualty-detail-grid">
                <span v-for="row in casualtyRows(detail)" :key="row[0]"><span>{{ row[0] }}</span><strong>{{ display(row[1]) }}</strong></span>
              </div>
            </section>
          </template>

          <ElTabs v-model="activeDetailTab" class="detail-tabs">
            <ElTabPane label="人员明细" name="persons">
              <section class="detail-block detail-list-block" aria-label="人员明细">
                <div class="detail-list-heading"><h3>人员明细</h3><ElTag effect="plain">{{ personTotal === null ? persons.length + ' 条已加载' : '共 ' + personTotal + ' 条' }}</ElTag></div>
                <p v-if="peopleError" class="query-error" role="alert">{{ peopleError }}</p>
                <p v-else-if="!persons.length && !detailBusy" class="empty-state">没有可显示的人员明细。</p>
                <div v-if="persons.length" class="table-wrap">
                  <table class="detail-table">
                    <thead><tr><th>人员类别</th><th>伤亡状态</th><th v-if="canSeePersonDetails">年龄</th><th v-if="canSeePersonDetails">性别</th></tr></thead>
                    <tbody><tr v-for="(person, index) in persons" :key="person.person_id || index">
                      <td><ElTag effect="plain" size="small">{{ display(person.person_type) }}</ElTag></td>
                      <td>{{ display(person.person_injury) }}</td>
                      <td v-if="canSeePersonDetails">{{ display(person.person_age) }}</td>
                      <td v-if="canSeePersonDetails">{{ display(person.person_sex) }}</td>
                    </tr></tbody>
                  </table>
                </div>
                <ElButton v-if="canLoadMore(persons.length, personTotal)" type="primary" plain :loading="peopleBusy" @click="loadMorePeople">
                  {{ peopleBusy ? '加载中…' : '加载更多人员' }}
                </ElButton>
              </section>
            </ElTabPane>
            <ElTabPane label="车辆明细" name="vehicles">
              <section class="detail-block detail-list-block" aria-label="车辆明细">
                <div class="detail-list-heading"><h3>车辆明细</h3><ElTag effect="plain">{{ vehicleTotal === null ? vehicles.length + ' 条已加载' : '共 ' + vehicleTotal + ' 条' }}</ElTag></div>
                <p v-if="vehiclesError" class="query-error" role="alert">{{ vehiclesError }}</p>
                <p v-else-if="!vehicles.length && !detailBusy" class="empty-state">没有可显示的车辆明细。</p>
                <div v-if="vehicles.length" class="table-wrap">
                  <table class="detail-table vehicle-table">
                    <thead><tr><th>车型</th><th>年份</th><th>方向</th><th>事故前动作</th><th>撞击位置</th><th>车辆损坏</th></tr></thead>
                    <tbody><tr v-for="vehicle in vehicles" :key="vehicle.vehicle_id">
                      <td><ElTag effect="plain" size="small">{{ display(vehicle.canonical_name) }}</ElTag></td>
                      <td>{{ display(vehicle.vehicle_year) }}</td><td>{{ display(vehicle.travel_direction) }}</td>
                      <td>{{ display(vehicle.pre_crash) }}</td><td>{{ display(vehicle.point_of_impact) }}</td><td>{{ display(vehicle.vehicle_damage) }}</td>
                    </tr></tbody>
                  </table>
                </div>
                <ElButton v-if="canLoadMore(vehicles.length, vehicleTotal)" type="primary" plain :loading="vehiclesBusy" @click="loadMoreVehicles">
                  {{ vehiclesBusy ? '加载中…' : '加载更多车辆' }}
                </ElButton>
              </section>
            </ElTabPane>
          </ElTabs>
          <p v-if="!canSeePersonDetails" class="privacy-note">当前角色不显示人员年龄与性别。</p>
        </div>
      </div>
    </ElDrawer>
  </section>
</template>

<style scoped>
.collision-panel {
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
.panel-heading, .drawer-heading, .results-heading, .filter-footer, .filter-group-heading, .mobile-card-heading, .detail-list-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.panel-kicker {
  margin: 0 0 5px;
  color: var(--muted, #65748a);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .08em;
}
.panel-heading h2, .drawer-heading h2 { margin: 0; color: #16365d; font-size: 21px; }
.filter-panel {
  display: grid;
  gap: 16px;
  margin: 20px 0;
  padding: 16px;
  border: 1px solid var(--line, #dce3ed);
  border-radius: 10px;
  background: #f9fbfe;
}
.filter-group-heading { justify-content: flex-start; margin-bottom: 12px; }
.filter-group-heading h3, .results-heading h3, .detail-block h3, .detail-list-heading h3 { margin: 0; color: #18365e; font-size: 15px; }
.filter-group-heading span, .results-heading > span { color: var(--muted, #65748a); font-size: 13px; }
.filter-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(130px, 1fr));
  align-items: end;
  gap: 12px;
}
.filter-grid label {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: #394b64;
  font-size: 13px;
  font-weight: 600;
}
.filter-grid input, .filter-grid select {
  width: 100%;
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid var(--line, #dce3ed);
  border-radius: 7px;
  background: #fff;
  color: #263a55;
  font: inherit;
}
.street-field { grid-column: span 1; }
.advanced-filters {
  border-top: 1px solid var(--line, #dce3ed);
  padding-top: 12px;
}
.advanced-filters summary {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  color: #1c3b67;
  font-size: 13px;
  font-weight: 700;
}
.advanced-filters summary span { color: var(--muted, #65748a); font-size: 12px; font-weight: 400; }
.advanced-grid { margin-top: 12px; grid-template-columns: repeat(2, minmax(180px, 1fr)); }
.filter-footer { align-items: flex-end; }
.filter-status { display: grid; gap: 5px; min-width: 0; color: var(--muted, #65748a); font-size: 12px; }
.query-warning { color: #8b5b0a; }
.query-error { margin: 12px 0; color: #b42318; line-height: 1.55; }
.quiet-message, .empty-state { margin: 12px 0; color: var(--muted, #65748a); line-height: 1.55; }
.results-frame { min-width: 0; border: 1px solid var(--line, #dce3ed); border-radius: 10px; overflow: hidden; }
.results-heading { padding: 13px 16px; border-bottom: 1px solid var(--line, #dce3ed); background: #fbfcff; }
.desktop-table-wrap { overflow-x: auto; }
.collision-table, .detail-table {
  width: 100%;
  border-collapse: collapse;
  color: #273950;
  font-size: 13px;
}
.collision-table th, .collision-table td, .detail-table th, .detail-table td {
  padding: 10px 11px;
  border-bottom: 1px solid #e8edf4;
  text-align: left;
  vertical-align: middle;
}
.collision-table th, .detail-table th { color: #586b83; background: #fafbfd; font-size: 12px; font-weight: 700; }
.collision-table tbody tr:hover, .detail-table tbody tr:hover { background: #f8faff; }
.date-cell { white-space: nowrap; }
.date-cell strong, .date-cell span { display: block; }
.date-cell span { margin-top: 3px; color: var(--muted, #65748a); font-size: 12px; }
.street-cell { min-width: 170px; max-width: 280px; overflow-wrap: anywhere; }
.casualty-inline { display: grid; grid-template-columns: repeat(4, max-content); gap: 4px 8px; min-width: 340px; }
.casualty-inline span { color: #52637a; white-space: nowrap; font-size: 11px; }
.casualty-inline b { color: #18365e; font-size: 12px; }
.mobile-collision-list { display: none; }
.load-more-row { display: flex; justify-content: center; padding: 14px; border-top: 1px solid var(--line, #dce3ed); }
.drawer-shell { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.drawer-heading { position: sticky; top: 0; z-index: 1; padding: 18px 22px; border-bottom: 1px solid var(--line, #dce3ed); background: #fff; }
.drawer-heading h2 { font-size: 19px; }
.drawer-heading h2 span { color: var(--muted, #65748a); font-size: 15px; font-weight: 500; overflow-wrap: anywhere; }
.drawer-content { overflow: auto; padding: 18px 22px 28px; }
.facts-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 0 0 16px;
}
.facts-grid > div { padding: 12px; border: 1px solid var(--line, #dce3ed); border-radius: 8px; background: #fafbfd; }
.facts-grid dt { color: var(--muted, #65748a); font-size: 12px; }
.facts-grid dd { margin: 5px 0 0; color: #263a55; font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.detail-block { margin: 12px 0; padding: 15px; border: 1px solid var(--line, #dce3ed); border-radius: 9px; background: #fff; }
.casualty-detail-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.casualty-detail-grid > span { display: flex; justify-content: space-between; gap: 8px; padding: 9px; border-radius: 7px; background: #f6f8fc; color: #596b82; font-size: 12px; }
.casualty-detail-grid strong { color: #173f7f; font-size: 14px; }
.detail-tabs { margin-top: 16px; }
.detail-list-block { margin: 0; }
.detail-list-heading { margin-bottom: 10px; }
.detail-table { min-width: 540px; margin: 8px 0 12px; }
.vehicle-table { min-width: 760px; }
.privacy-note { color: var(--muted, #65748a); font-size: 12px; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (max-width: 920px) {
  .collision-panel { padding: 16px; }
  .filter-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
  .casualty-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 680px) {
  .collision-panel { padding: 14px; }
  .filter-panel { padding: 12px; }
  .panel-heading h2 { font-size: 19px; }
  .filter-group-heading, .filter-footer { align-items: flex-start; flex-direction: column; }
  .filter-grid, .advanced-grid { grid-template-columns: 1fr; }
  .desktop-table-wrap { display: none; }
  .mobile-collision-list { display: grid; }
  .mobile-collision { padding: 13px; border-bottom: 1px solid var(--line, #dce3ed); }
  .mobile-card-heading { align-items: flex-start; }
  .mobile-card-heading div { display: grid; gap: 4px; }
  .mobile-card-heading strong { color: #18365e; font-size: 13px; }
  .mobile-card-heading span, .mobile-street { color: var(--muted, #65748a); font-size: 12px; }
  .mobile-street { margin: 8px 0; overflow-wrap: anywhere; }
  .mobile-casualties { display: flex; flex-wrap: wrap; gap: 6px; }
  .mobile-casualties span { padding: 5px 7px; border-radius: 6px; background: #f5f7fb; color: #52637a; font-size: 11px; }
  .mobile-casualties b { color: #173f7f; }
  .drawer-heading { padding: 14px; }
  .drawer-content { padding: 14px; }
  .facts-grid { grid-template-columns: 1fr; }
  .casualty-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .detail-block { padding: 12px; }
  .detail-table { min-width: 540px; }
  .vehicle-table { min-width: 760px; }
}
</style>
