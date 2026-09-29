<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { sessionUser } from '../api/auth'
import {
  getCollision, listCollisions, listFactors, listPersons, listVehicleTypes, listVehicles,
  type Collision, type CollisionDetail, type DictionaryItem, type PersonItem, type VehicleItem,
} from '../api/m2'

const pageSize = 25
const detailPageSize = 20
const filters = reactive({ start: '', end: '', boroughId: '', street: '', vehicleTypeId: '', factorId: '' })
const collisions = ref<Collision[]>([])
const nextCursor = ref<string | null>(null)
const total = ref<number | null>(null)
const loading = ref(false)
const queryError = ref('')
const vehicleTypes = ref<DictionaryItem[]>([])
const factors = ref<DictionaryItem[]>([])
const dictionaryError = ref('')

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
const collisionCount = computed(() => total.value === null ? '总数暂不可用' : '共 ' + total.value + ' 起')

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

async function loadDictionaryOptions() {
  dictionaryError.value = ''
  const [vehicleResult, factorResult] = await Promise.allSettled([listVehicleTypes(), listFactors()])
  if (vehicleResult.status === 'fulfilled') vehicleTypes.value = vehicleResult.value.items.filter((item) => item.is_active)
  else dictionaryError.value = vehicleResult.reason instanceof Error ? vehicleResult.reason.message : '车型筛选项暂不可用。'
  if (factorResult.status === 'fulfilled') factors.value = factorResult.value.items.filter((item) => item.is_active)
  else dictionaryError.value = factorResult.reason instanceof Error ? factorResult.reason.message : '原因筛选项暂不可用。'
}

function makeFilters(cursor?: string) {
  return {
    start: filters.start || undefined,
    end: filters.end || undefined,
    borough_id: filters.boroughId.trim() || undefined,
    street: filters.street.trim() || undefined,
    vehicle_type_id: filters.vehicleTypeId || undefined,
    factor_id: filters.factorId || undefined,
    page_size: pageSize,
    cursor,
    include_total: true,
  }
}

async function search(reset = true) {
  if (filters.start && filters.end && filters.end <= filters.start) {
    queryError.value = '结束日期必须晚于开始日期；结束日期按排他边界处理。'
    return
  }
  loading.value = true
  queryError.value = ''
  if (reset) {
    collisions.value = []
    nextCursor.value = null
    total.value = null
  }
  try {
    const result = await listCollisions(makeFilters(reset ? undefined : nextCursor.value ?? undefined))
    collisions.value = reset ? result.items : collisions.value.concat(result.items)
    nextCursor.value = result.next_cursor
    total.value = result.total
  } catch (error) {
    queryError.value = error instanceof Error ? error.message : '事故查询暂未完成。'
  } finally {
    loading.value = false
  }
}

function closeDetail() {
  detailSequence += 1
  selectedId.value = ''
  detail.value = null
  persons.value = []
  vehicles.value = []
  detailError.value = ''
  peopleError.value = ''
  vehiclesError.value = ''
}

async function openDetail(id: string) {
  const sequence = ++detailSequence
  selectedId.value = id
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
  void loadDictionaryOptions()
  void search()
})
</script>

<template>
  <section aria-labelledby="collisions-heading" class="m2-section">
    <div class="section-title">
      <h2 id="collisions-heading">事故查询</h2>
      <span class="detail">{{ collisionCount }}</span>
    </div>
    <form class="filter-grid" @submit.prevent="search()">
      <label>开始日期（包含）<input v-model="filters.start" type="date" /></label>
      <label>结束日期（不包含）<input v-model="filters.end" type="date" /></label>
      <label>区域标识<input v-model="filters.boroughId" inputmode="numeric" placeholder="例如：1" /></label>
      <label>街道关键词<input v-model="filters.street" maxlength="120" placeholder="搜索街道名称" /></label>
      <label>车型<select v-model="filters.vehicleTypeId"><option value="">全部车型</option>
        <option v-for="item in vehicleTypes" :key="item.id" :value="item.id">{{ item.display_name || item.canonical_name }}</option>
      </select></label>
      <label>事故因素<select v-model="filters.factorId"><option value="">全部因素</option>
        <option v-for="item in factors" :key="item.id" :value="item.id">{{ item.display_name || item.canonical_name }}</option>
      </select></label>
      <div class="filter-actions"><button :disabled="loading">{{ loading ? '查询中…' : '查询事故' }}</button></div>
    </form>
    <p v-if="dictionaryError" class="error" role="alert">{{ dictionaryError }}</p>
    <p v-if="queryError" class="error" role="alert">{{ queryError }}</p>
    <p v-if="loading && !collisions.length" class="detail" role="status">正在加载事故记录…</p>
    <p v-else-if="!loading && !collisions.length && !queryError" class="empty-state">没有匹配的事故记录。</p>
    <div v-if="collisions.length" class="collision-list">
      <article v-for="collision in collisions" :key="collision.collision_id" class="collision-card">
        <div class="section-title">
          <div>
            <h3>{{ collision.crash_date }} {{ display(collision.crash_time) }}</h3>
            <p class="detail">{{ display(collision.borough_name) }} · {{ streetSummary(collision) }}</p>
          </div>
          <button type="button" class="secondary-button" @click="openDetail(collision.collision_id)">查看详情</button>
        </div>
        <p class="detail">事故编号：{{ collision.collision_id }}</p>
        <div class="casualty-grid">
          <span v-for="row in casualtyRows(collision)" :key="row[0]">{{ row[0] }}：{{ display(row[1]) }}</span>
        </div>
      </article>
    </div>
    <div v-if="nextCursor" class="load-more">
      <button class="secondary-button" :disabled="loading" @click="search(false)">{{ loading ? '加载中…' : '加载更多事故' }}</button>
    </div>

    <section v-if="selectedId" aria-labelledby="collision-detail-heading" class="detail-panel">
      <div class="section-title">
        <h3 id="collision-detail-heading">事故详情 · {{ selectedId }}</h3>
        <button type="button" class="secondary-button" @click="closeDetail">收起详情</button>
      </div>
      <p v-if="detailBusy" class="detail" role="status">正在加载详情和人员、车辆明细…</p>
      <p v-if="detailError" class="error" role="alert">{{ detailError }}</p>
      <template v-if="detail">
        <dl class="facts-grid">
          <div><dt>日期与时间</dt><dd>{{ detail.crash_date }} {{ display(detail.crash_time) }}</dd></div>
          <div><dt>区域</dt><dd>{{ display(detail.borough_name) }}（{{ display(detail.borough_id) }}）</dd></div>
          <div><dt>街道</dt><dd>{{ streetSummary(detail) }}</dd></div>
          <div><dt>坐标</dt><dd>{{ display(detail.latitude) }}，{{ display(detail.longitude) }}</dd></div>
        </dl>
        <h4>伤亡统计</h4>
        <div class="casualty-grid">
          <span v-for="row in casualtyRows(detail)" :key="row[0]">{{ row[0] }}：{{ display(row[1]) }}</span>
        </div>
      </template>

      <div class="detail-columns">
        <section class="detail-panel">
          <h4>人员明细 <span class="detail">（{{ personTotal === null ? persons.length + ' 条已加载' : '共 ' + personTotal + ' 条' }}）</span></h4>
          <p v-if="peopleError" class="error" role="alert">{{ peopleError }}</p>
          <p v-else-if="!persons.length && !detailBusy" class="empty-state">没有可显示的人员明细。</p>
          <div v-if="persons.length" class="table-wrap">
            <table>
              <thead><tr><th>人员类别</th><th>伤亡状态</th><th v-if="canSeePersonDetails">年龄</th><th v-if="canSeePersonDetails">性别</th></tr></thead>
              <tbody><tr v-for="(person, index) in persons" :key="person.person_id || index">
                <td>{{ display(person.person_type) }}</td><td>{{ display(person.person_injury) }}</td>
                <td v-if="canSeePersonDetails">{{ display(person.person_age) }}</td>
                <td v-if="canSeePersonDetails">{{ display(person.person_sex) }}</td>
              </tr></tbody>
            </table>
          </div>
          <button v-if="canLoadMore(persons.length, personTotal)" class="secondary-button" :disabled="peopleBusy" @click="loadMorePeople">
            {{ peopleBusy ? '加载中…' : '加载更多人员' }}
          </button>
        </section>
        <section class="detail-panel">
          <h4>车辆明细 <span class="detail">（{{ vehicleTotal === null ? vehicles.length + ' 条已加载' : '共 ' + vehicleTotal + ' 条' }}）</span></h4>
          <p v-if="vehiclesError" class="error" role="alert">{{ vehiclesError }}</p>
          <p v-else-if="!vehicles.length && !detailBusy" class="empty-state">没有可显示的车辆明细。</p>
          <div v-if="vehicles.length" class="table-wrap">
            <table>
              <thead><tr><th>车型</th><th>年份</th><th>方向</th><th>事故前动作</th><th>撞击位置</th><th>车辆损坏</th></tr></thead>
              <tbody><tr v-for="vehicle in vehicles" :key="vehicle.vehicle_id">
                <td>{{ display(vehicle.canonical_name) }}</td><td>{{ display(vehicle.vehicle_year) }}</td>
                <td>{{ display(vehicle.travel_direction) }}</td><td>{{ display(vehicle.pre_crash) }}</td>
                <td>{{ display(vehicle.point_of_impact) }}</td><td>{{ display(vehicle.vehicle_damage) }}</td>
              </tr></tbody>
            </table>
          </div>
          <button v-if="canLoadMore(vehicles.length, vehicleTotal)" class="secondary-button" :disabled="vehiclesBusy" @click="loadMoreVehicles">
            {{ vehiclesBusy ? '加载中…' : '加载更多车辆' }}
          </button>
        </section>
      </div>
    </section>
  </section>
</template>
