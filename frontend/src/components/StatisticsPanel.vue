<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'
import { useRoute } from 'vue-router'
import { sessionUser } from '../api/auth'
import { listFactors, listVehicleTypes, type DictionaryItem } from '../api/m2'
import {
  downloadCsv, getBoroughs, getFactors, getGovernance, getOverview, getPersons, getTrendHours,
  getTrendMonths, getVehicleTypes,
  type BoroughsData, type FactorsData, type GovernanceData, type OverviewData, type PersonsData,
  type TrendHoursData, type TrendMonthsData, type VehicleTypesData,
} from '../api/m6'

// 只注册本页实际使用的图表和渲染器，保持路由资源体积可控。
echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

// borough_id与数据库种子一致：1=BRONX、2=BROOKLYN、3=MANHATTAN、4=QUEENS、5=STATEN ISLAND。
const boroughOptions = [
  { id: '1', name: '布朗克斯 Bronx' }, { id: '2', name: '布鲁克林 Brooklyn' },
  { id: '3', name: '曼哈顿 Manhattan' }, { id: '4', name: '皇后区 Queens' },
  { id: '5', name: '斯塔滕岛 Staten Island' },
]
const vehicleTypes = ref<DictionaryItem[]>([]), factors = ref<DictionaryItem[]>([])

const route = useRoute()
const defaultDateRange = { start: '2025-01-01', end: '2025-12-31' }
function validQueryDate(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const date = new Date(value + 'T00:00:00.000Z')
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value ? value : null
}
function dateRangeFromRoute() {
  const start = validQueryDate(route.query.start)
  const endExclusive = validQueryDate(route.query.end)
  if (!start || !endExclusive || start >= endExclusive) return null
  return { start, end: addDays(endExclusive, -1) }
}
const initialDateRange = dateRangeFromRoute() ?? defaultDateRange

// 默认2025全年：结束日为"包含当天"语义，2025-12-31提交后即[2025-01-01, 2026-01-01)。
const filters = reactive({ start: initialDateRange.start, end: initialDateRange.end, boroughId: '', street: '', vehicleTypeId: '', factorId: '' })

const overview = ref<OverviewData | null>(null)
const boroughs = ref<BoroughsData | null>(null)
const months = ref<TrendMonthsData | null>(null)
const hours = ref<TrendHoursData | null>(null)
const factorStats = ref<FactorsData | null>(null)
const vehicleStats = ref<VehicleTypesData | null>(null)
const personStats = ref<PersonsData | null>(null)
const governance = ref<GovernanceData | null>(null)

const busy = ref(false), loadError = ref(''), revisionWarning = ref('')
const exportError = ref(''), exporting = ref('')
let sequence = 0

// 已应用筛选：最近一次成功且一致的查询条件；打印与CSV只绑定它，不读正在编辑的表单。
interface AppliedFilters {
  start: string
  endExclusive: string
  boroughId: string
  boroughName: string
  street: string
  vehicleTypeId: string
  vehicleTypeName: string
  factorId: string
  factorName: string
  revision: string
  scopeNote: string
}
const applied = ref<AppliedFilters | null>(null)
// stale：本次查询各接口revision不一致——结果未应用，保留上次一致渲染，输出停用。
const stale = ref(false)
// formInvalid：出现无效条件后，须完成新的成功查询才能恢复输出。
const formInvalid = ref(false)
const dateError = computed(() => {
  if (!filters.start || !filters.end) return '请先选择开始与结束日期。'
  if (filters.start > filters.end) return '结束日期（含当天）必须不早于开始日期。'
  return ''
})
const invalidFilters = computed(() => formInvalid.value || Boolean(dateError.value))
watch(dateError, error => { if (error) formInvalid.value = true }, { flush: 'sync' })

const canSeePersonDetails = computed(() => sessionUser.value?.role === 'ADMIN' || sessionUser.value?.role === 'MANAGER')
const outputDisabled = computed(() => busy.value || stale.value || invalidFilters.value || !applied.value)
// reportValid：当前是否存在可打印的单一版本有效报表；打印媒体下据此隐藏无效内容。
const reportValid = computed(() => !outputDisabled.value && Boolean(overview.value))
const printBlockReason = computed(() => {
  if (busy.value) return '正在查询统计，报表尚未形成，当前不可打印；请稍后重试或等待查询完成。'
  if (stale.value) return '本次查询读取到不同的数据版本，结果未应用；为避免输出混合版本的报表，打印与导出已停用，请重新查询。'
  if (invalidFilters.value) return '筛选条件无效或尚未重新完成成功查询，上次成功查询结果仅供查看，不可打印；请恢复有效条件并重新查询。'
  return '尚未形成有效报表（无已应用筛选或上次查询失败），当前不可打印；请完成一次成功查询后再打印。'
})
const FACTOR_TOP_N = 10
const factorTop = computed(() => (factorStats.value?.items ?? []).slice(0, FACTOR_TOP_N))

function dictionaryLabel(items: DictionaryItem[], id?: string) {
  if (!id) return '全部'
  const item = items.find(entry => entry.id === id)
  return item ? (item.display_name || item.canonical_name) : `编号${id}`
}

function boroughLabel(id?: string) {
  if (!id) return '全部'
  const option = boroughOptions.find(entry => entry.id === id)
  return option ? option.name : `编号${id}`
}

function addDays(value: string, days: number) {
  const date = new Date(value + 'T00:00:00Z')
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function buildQuery() {
  loadError.value = ''
  if (dateError.value) {
    loadError.value = dateError.value
    formInvalid.value = true
    return null
  }
  const endExclusive = addDays(filters.end, 1)
  return {
    start: filters.start,
    endExclusive,
    boroughId: filters.boroughId || undefined,
    street: filters.street || undefined,
    vehicleTypeId: filters.vehicleTypeId || undefined,
    factorId: filters.factorId || undefined,
  }
}

function clearResults() {
  overview.value = null; boroughs.value = null; months.value = null; hours.value = null
  factorStats.value = null; vehicleStats.value = null; personStats.value = null; governance.value = null
  applied.value = null; stale.value = false
}

async function reload() {
  const query = buildQuery()
  if (!query) return
  const seq = ++sequence
  busy.value = true; loadError.value = ''; revisionWarning.value = ''; exportError.value = ''
  try {
    const basePromise = Promise.all([getOverview(query), getBoroughs(query), getTrendMonths(query),
                                     getTrendHours(query), getFactors(query), getVehicleTypes(query)] as const)
    const detailPromise = canSeePersonDetails.value
      ? Promise.all([getPersons(query), getGovernance()] as const)
      : Promise.resolve(null)
    const [base, detail] = await Promise.all([basePromise, detailPromise])
    if (seq !== sequence) return
    const revisions = new Set([...base, ...(detail ?? [])].map(item => item.revision))
    if (revisions.size > 1) {
      // 未形成一致报表：不写入数据、图表与applied，保留上一次一致渲染，输出停用。
      stale.value = true
      revisionWarning.value = '本次查询读取到不同的数据版本（可能有新数据发布），结果未应用；已展示报表为上次成功查询结果，打印与导出已停用，请重新查询。'
      return
    }
    stale.value = false
    formInvalid.value = false
    revisionWarning.value = ''
    overview.value = base[0].data; boroughs.value = base[1].data; months.value = base[2].data
    hours.value = base[3].data; factorStats.value = base[4].data; vehicleStats.value = base[5].data
    if (detail) { personStats.value = detail[0].data; governance.value = detail[1].data }
    applied.value = {
      start: query.start, endExclusive: query.endExclusive,
      boroughId: query.boroughId ?? '', boroughName: boroughLabel(query.boroughId),
      street: (query.street ?? '').trim(),
      vehicleTypeId: query.vehicleTypeId ?? '', vehicleTypeName: dictionaryLabel(vehicleTypes.value, query.vehicleTypeId),
      factorId: query.factorId ?? '', factorName: dictionaryLabel(factors.value, query.factorId),
      revision: base[0].revision ?? '',
      scopeNote: base[0].data.filters.collision_scope,
    }
    await nextTick()
    renderCharts()
  } catch (error) {
    if (seq !== sequence) return
    clearResults()
    loadError.value = error instanceof Error ? error.message : '统计查询失败，请稍后重试。'
  } finally {
    if (seq === sequence) busy.value = false
  }
}

function appliedQueryParams(): string | null {
  const current = applied.value
  if (!current) return null
  const params = new URLSearchParams()
  params.set('start', current.start)
  params.set('end', current.endExclusive)
  if (current.boroughId) params.set('borough_id', current.boroughId)
  if (current.street) params.set('street', current.street)
  if (current.vehicleTypeId) params.set('vehicle_type_id', current.vehicleTypeId)
  if (current.factorId) params.set('factor_id', current.factorId)
  return params.toString()
}

async function warnIfRevisionDiffers(blob: Blob) {
  const current = applied.value
  if (!current?.revision) return
  try {
    const head = await blob.slice(0, 2048).text()
    const match = head.match(/数据版本 revision: (\d+)/)
    if (match && match[1] !== current.revision) {
      exportError.value = `导出文件的数据版本（revision ${match[1]}）与当前报表版本（revision ${current.revision}）不同：文件按数据库实际快照生成，请重新查询后再导出以保持一致。`
    }
  } catch { /* 说明行解析失败不影响已下载的文件。 */ }
}

async function saveCsv(kind: 'collisions' | 'statistics') {
  if (outputDisabled.value) return
  const params = appliedQueryParams()
  if (!params) { exportError.value = '当前没有可导出的有效报表，请先完成一次查询。'; return }
  exporting.value = kind; exportError.value = ''
  try {
    const blob = await downloadCsv(kind === 'collisions' ? '/exports/collisions.csv' : '/exports/statistics.csv', params)
    await warnIfRevisionDiffers(blob)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = kind === 'collisions' ? 'vision-zero-collisions.csv' : 'vision-zero-statistics.csv'
    link.click()
    // 延迟释放对象URL：立即revoke可能在浏览器开始读取前取消下载。
    setTimeout(() => URL.revokeObjectURL(url), 15000)
  } catch (error) {
    exportError.value = error instanceof Error ? error.message : '导出失败，请稍后重试。'
  } finally { exporting.value = '' }
}

function printReport() {
  if (outputDisabled.value) return
  window.print()
}

const boroughChartEl = ref<HTMLDivElement | null>(null)
const monthChartEl = ref<HTMLDivElement | null>(null)
const hourChartEl = ref<HTMLDivElement | null>(null)
const factorChartEl = ref<HTMLDivElement | null>(null)
const statisticsPanelEl = ref<HTMLElement | null>(null)
let charts: echarts.ECharts[] = []
let resizeObserver: ResizeObserver | null = null
let resizeFrame = 0
let isMounted = false

const chartColors = {
  blue: '#083da6',
  blueSoft: '#5177c4',
  teal: '#218a83',
  amber: '#c38a2d',
  coral: '#bc5550',
  slate: '#71829a',
}

function disposeCharts() {
  charts.forEach(chart => chart.dispose())
  charts = []
}

function mountChart(element: HTMLDivElement | null, option: EChartsOption) {
  if (!element) return
  const chart = echarts.init(element)
  chart.setOption(option)
  charts.push(chart)
}

const COVERAGE_LABELS: Record<string, string> = {
  WITH_DATA: '有记录',
  NO_RECORDS_COVERAGE_UNCONFIRMED: '无记录（覆盖未确认）',
  OUTSIDE_DECLARED_RANGES: '无记录（来源未覆盖）',
}

function renderCharts() {
  disposeCharts()
  if (boroughs.value?.items.length) {
    mountChart(boroughChartEl.value, {
      tooltip: { trigger: 'axis' },
      legend: { top: 0 },
      grid: { left: 40, right: 16, top: 34, bottom: 46 },
      xAxis: { type: 'category', data: boroughs.value.items.map(item => item.borough_name), axisLabel: { interval: 0, rotate: 24 } },
      yAxis: { type: 'value' },
      series: [
        { name: '事故数', type: 'bar', data: boroughs.value.items.map(item => item.collision_count), itemStyle: { color: chartColors.blue } },
        { name: '已知受伤', type: 'bar', data: boroughs.value.items.map(item => item.known_injured_count), itemStyle: { color: chartColors.teal } },
      ],
    })
  }
  if (months.value?.months.length) {
    mountChart(monthChartEl.value, {
      tooltip: { trigger: 'axis' },
      legend: { top: 0 },
      grid: { left: 52, right: 16, top: 34, bottom: 40 },
      xAxis: { type: 'category', data: months.value.months.map(item => item.month) },
      yAxis: { type: 'value' },
      series: [
        { name: '事故数', type: 'line', connectNulls: false,
          data: months.value.months.map(item => item.collision_count), itemStyle: { color: chartColors.blue }, lineStyle: { color: chartColors.blue, width: 3 } },
        { name: '已知受伤', type: 'line', connectNulls: false,
          data: months.value.months.map(item => item.known_injured_count), itemStyle: { color: chartColors.coral }, lineStyle: { color: chartColors.coral, width: 2 } },
      ],
    })
  }
  if (hours.value) {
    mountChart(hourChartEl.value, {
      tooltip: { trigger: 'axis' },
      grid: { left: 44, right: 16, top: 20, bottom: 46 },
      xAxis: { type: 'category', data: [...hours.value.hours.map(item => String(item.hour) + '时'), '未知'] ,
               axisLabel: { interval: 2, rotate: 40 } },
      yAxis: { type: 'value' },
      series: [{ name: '事故数', type: 'bar',
        data: [...hours.value.hours.map(item => item.collision_count),
                { value: hours.value.unknown_time_collision_count, itemStyle: { color: chartColors.slate } }],
        itemStyle: { color: chartColors.blueSoft } }],
    })
  }
  if (factorTop.value.length) {
    mountChart(factorChartEl.value, {
      tooltip: { trigger: 'axis' },
      grid: { left: 190, right: 30, top: 10, bottom: 30 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', inverse: true,
               data: factorTop.value.map(item => item.display_name || item.canonical_name),
               axisLabel: { width: 176, overflow: 'truncate' } },
      series: [{ name: '涉及事故数', type: 'bar',
                  data: factorTop.value.map(item => item.collision_count), itemStyle: { color: chartColors.teal } }],
    })
  }
}

function resizeCharts() { charts.forEach(chart => chart.resize()) }
function scheduleResizeCharts() {
  if (resizeFrame) cancelAnimationFrame(resizeFrame)
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = 0
    resizeCharts()
  })
}
// 打印预览或媒体切换结束后，等待屏幕布局恢复再调整图表。
const printMedia = window.matchMedia('print')
function onPrintMediaChange() { scheduleResizeCharts() }

watch([boroughs, months, hours, factorStats], renderCharts)
watch(() => sessionUser.value?.user_id, () => {
  sequence += 1
  clearResults()
  if (sessionUser.value) reload()
})

watch(() => [route.query.start, route.query.end], () => {
  const range = dateRangeFromRoute() ?? defaultDateRange
  filters.start = range.start
  filters.end = range.end
  if (isMounted) reload()
})

onMounted(async () => {
  isMounted = true
  window.addEventListener('resize', scheduleResizeCharts)
  window.addEventListener('beforeprint', resizeCharts)
  // 打印后恢复图表尺寸，避免画布停留在打印布局宽度。
  window.addEventListener('afterprint', resizeCharts)
  printMedia.addEventListener('change', onPrintMediaChange)
  if (typeof ResizeObserver !== 'undefined' && statisticsPanelEl.value) {
    resizeObserver = new ResizeObserver(scheduleResizeCharts)
    resizeObserver.observe(statisticsPanelEl.value)
  }
  try {
    const [types, factorItems] = await Promise.all([listVehicleTypes(), listFactors()])
    if (!isMounted) return
    vehicleTypes.value = types.items; factors.value = factorItems.items
  } catch { /* 字典加载失败不阻塞统计；下拉筛选暂不可用。 */ }
  if (isMounted) reload()
})

onBeforeUnmount(() => {
  isMounted = false
  sequence += 1
  resizeObserver?.disconnect()
  resizeObserver = null
  if (resizeFrame) cancelAnimationFrame(resizeFrame)
  resizeFrame = 0
  window.removeEventListener('resize', scheduleResizeCharts)
  window.removeEventListener('beforeprint', resizeCharts)
  window.removeEventListener('afterprint', resizeCharts)
  printMedia.removeEventListener('change', onPrintMediaChange)
  disposeCharts()
})
</script>

<template>
  <section ref="statisticsPanelEl" :class="['statistics-panel', 'workflow-panel', 'statistics-page', { 'report-invalid': !reportValid }]" aria-labelledby="statistics-heading">
    <div class="print-header" aria-hidden="true">
      <h2>统计报表</h2>
      <p v-if="applied">
        统计区间 [{{ applied.start }}, {{ applied.endExclusive }})（结束日期为排他上界，不含当天）；数据版本 revision {{ applied.revision }}。
        行政区：{{ applied.boroughName }}；街道条件：{{ applied.street ? applied.street : '无' }}；
        车型：{{ applied.vehicleTypeName }}；原因：{{ applied.factorName }}。
        {{ applied.scopeNote }}。
        伤亡为Crashes汇总口径（casualty_stat），人员明细不完整不代表没有伤亡；月度空月份不补零；原因/车型组别之间存在重叠，各组计数之和可能大于事故总数。
        模拟治理工单统计独立于事故日期范围，属课程模拟业务。
      </p>
    </div>
    <div class="print-unavailable" aria-hidden="true">
      <h2>统计报表（当前不可打印）</h2>
      <p>{{ printBlockReason }}</p>
    </div>
    <header class="page-heading no-print">
      <div><p class="page-eyebrow">碰撞数据 · 统计分析</p><h2 id="statistics-heading">筛选与输出</h2><p class="page-lead">筛选事故范围，查看全量分析并生成版本一致的 CSV 或打印报表。</p></div>
      <div class="report-actions">
        <button class="button-primary" :disabled="busy" @click="reload">{{ busy ? '查询中…' : '查询统计' }}</button>
        <button class="button-secondary" :disabled="outputDisabled || exporting !== ''" @click="saveCsv('collisions')">
          {{ exporting === 'collisions' ? '导出中…' : '下载事故 CSV' }}</button>
        <button v-if="canSeePersonDetails" class="button-secondary" :disabled="outputDisabled || exporting !== ''" @click="saveCsv('statistics')">
          {{ exporting === 'statistics' ? '导出中…' : '下载统计报表 CSV' }}</button>
        <button class="button-secondary" :disabled="outputDisabled" @click="printReport">打印报表</button>
      </div>
    </header>
    <p v-if="!canSeePersonDetails" class="role-note no-print">人员明细细分与模拟工单统计仅向管理角色开放。</p>

    <section class="surface-card filter-card no-print" aria-label="统计筛选条件">
      <div class="card-heading"><div><p class="section-kicker">查询条件</p><h3>选择统计范围</h3></div><span class="quiet-note">结束日期包含当天</span></div>
      <div class="filter-grid">
      <label>开始日期（含）<input v-model="filters.start" type="date" :disabled="busy" @change="reload" /></label>
      <label>结束日期（含当天，提交时转为次日排他上界）<input v-model="filters.end" type="date" :disabled="busy" @change="reload" /></label>
      <label>行政区<select v-model="filters.boroughId" :disabled="busy" @change="reload">
        <option value="">全部</option>
        <option v-for="item in boroughOptions" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select></label>
      <label>街道（模糊匹配）<input v-model="filters.street" maxlength="160" :disabled="busy" placeholder="如 Main St" @change="reload" /></label>
      <label>车型筛选（选出涉及该车型的事故）<select v-model="filters.vehicleTypeId" :disabled="busy" @change="reload">
        <option value="">全部</option>
        <option v-for="item in vehicleTypes" :key="item.id" :value="item.id">{{ item.display_name || item.canonical_name }}</option>
      </select></label>
      <label>原因筛选（选出涉及该原因的事故）<select v-model="filters.factorId" :disabled="busy" @change="reload">
        <option value="">全部</option>
        <option v-for="item in factors" :key="item.id" :value="item.id">{{ item.display_name || item.canonical_name }}</option>
      </select></label>
      </div>

      <p v-if="dateError || loadError" class="inline-message message-error" role="alert">{{ dateError || loadError }}</p>
      <p v-if="revisionWarning" class="inline-message message-error" role="alert">{{ revisionWarning }}</p>
      <p v-if="exportError" class="inline-message message-error" role="alert">{{ exportError }}</p>
      <p v-if="busy && !overview" class="loading-state" role="status">正在查询统计…</p>
      <p v-if="invalidFilters && applied" class="inline-message message-warning" role="status">
        已展示报表为上次成功查询结果；当前筛选尚未形成有效报表，打印与 CSV 导出已停用。恢复有效条件并成功查询后恢复输出。
      </p>
    </section>

    <div class="report-body" v-if="overview && applied">
      <div class="report-scope">
        <span class="scope-badge">数据版本 {{ applied.revision }}</span>
        <p class="detail">
        统计区间 [{{ applied.start }}, {{ applied.endExclusive }})（结束日期为排他上界，不含当天）；
        数据版本 revision {{ applied.revision }}。
        {{ applied.scopeNote }}。
        行政区：{{ applied.boroughName }}；街道条件：{{ applied.street ? applied.street : '无' }}。
        </p>
      </div>
      <section class="surface-card overview-card">
      <div class="card-heading"><div><p class="section-kicker">事故概况</p><h3>当前范围总览</h3></div><span class="quiet-note">{{ applied.start }} 至 {{ applied.endExclusive }}（不含）</span></div>
      <dl class="facts-grid summary-metrics">
        <div><dt>不同事故数</dt><dd>{{ overview.collision_count }}</dd></div>
        <div><dt>已知受伤合计（缺失 {{ overview.injured_missing_count }} 起事故）</dt>
          <dd>{{ overview.known_injured_count ?? '无已知值' }}</dd></div>
        <div><dt>已知死亡合计（缺失 {{ overview.killed_missing_count }} 起事故）</dt>
          <dd>{{ overview.known_killed_count ?? '无已知值' }}</dd></div>
        <div><dt>人员明细记录数</dt><dd>{{ overview.person_records }}</dd></div>
        <div><dt>车辆明细记录数</dt><dd>{{ overview.vehicle_records }}</dd></div>
        <div><dt>有坐标 / 缺坐标事故</dt><dd>{{ overview.geocoded_count }} / {{ overview.missing_coordinates_count }}</dd></div>
        <div><dt>正式归属已确认交叉口的事故</dt><dd>{{ overview.confirmed_assigned_count }}</dd></div>
        <div><dt>归属覆盖率（分母为当前事故数）</dt><dd>{{ overview.assignment_coverage_ratio ?? '—' }}</dd></div>
      </dl>
      <p class="detail">{{ overview.casualty_note }} 人员明细不完整不代表没有伤亡；覆盖率为正式归属事故数除以当前筛选事故总数。</p>
      </section>

      <template v-if="overview.collision_count === 0">
        <p class="empty-state">当前筛选范围内没有事故记录；请调整日期或筛选条件。各分组表格与图表为空。</p>
      </template>

      <section class="analysis-card print-block">
        <div class="analysis-heading"><div><p class="section-kicker">空间分布</p><h3>行政区分布</h3></div></div>
        <div v-if="boroughs?.items.length" ref="boroughChartEl" class="chart-box"></div>
        <div v-if="boroughs?.items.length" class="table-wrap">
          <table>
            <thead><tr><th>行政区</th><th>事故数</th><th>已知受伤</th><th>受伤缺失事故</th><th>已知死亡</th><th>死亡缺失事故</th></tr></thead>
            <tbody>
              <tr v-for="item in boroughs.items" :key="String(item.borough_id)">
                <td>{{ item.borough_name }}{{ item.borough_id === null ? '（行政区字段缺失）' : '' }}</td>
                <td>{{ item.collision_count }}</td>
                <td>{{ item.known_injured_count ?? '无已知值' }}</td>
                <td>{{ item.injured_missing_count }}</td>
                <td>{{ item.known_killed_count ?? '无已知值' }}</td>
                <td>{{ item.killed_missing_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="analysis-card print-block">
        <div class="analysis-heading"><div><p class="section-kicker">时间变化</p><h3>月度趋势</h3></div></div>
        <p class="detail">{{ months?.coverage_note }} 空月份在图中显示为断点，不计为0。</p>
        <div v-if="months?.months.length" ref="monthChartEl" class="chart-box"></div>
        <div v-if="months" class="table-wrap">
          <table>
            <thead><tr><th>月份</th><th>事故数</th><th>已知受伤</th><th>受伤缺失事故</th><th>已知死亡</th><th>死亡缺失事故</th><th>覆盖状态</th></tr></thead>
            <tbody>
              <tr v-for="item in months.months" :key="item.month">
                <td>{{ item.month }}</td>
                <td>{{ item.collision_count ?? '无记录' }}</td>
                <td>{{ item.known_injured_count ?? '—' }}</td>
                <td>{{ item.injured_missing_count ?? '—' }}</td>
                <td>{{ item.known_killed_count ?? '—' }}</td>
                <td>{{ item.killed_missing_count ?? '—' }}</td>
                <td>{{ COVERAGE_LABELS[item.coverage] }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="analysis-card print-block">
        <div class="analysis-heading"><div><p class="section-kicker">发生时段</p><h3>事故小时分布</h3></div></div>
        <p class="detail">{{ hours?.note }}</p>
        <div v-if="hours && overview.collision_count > 0" ref="hourChartEl" class="chart-box"></div>
      </section>

      <section class="analysis-card print-block">
        <div class="analysis-heading"><div><p class="section-kicker">事故因素</p><h3>事故原因分析（前{{ FACTOR_TOP_N }}项）</h3></div></div>
        <p class="detail">{{ factorStats?.overlap_note }} 无原因记录的事故单独计数，不与来源中的 Unspecified 混同。</p>
        <div v-if="factorTop.length" ref="factorChartEl" class="chart-box chart-tall"></div>
        <div v-if="factorStats" class="table-wrap">
          <table>
            <thead><tr><th>原因</th><th>涉及不同事故数</th></tr></thead>
            <tbody>
              <tr v-for="item in factorStats.items" :key="item.factor_id">
                <td>{{ item.display_name || item.canonical_name }}</td>
                <td>{{ item.collision_count }}</td>
              </tr>
              <tr><td>无原因记录的事故</td><td>{{ factorStats.no_factor_collision_count }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="analysis-card print-block">
        <div class="analysis-heading"><div><p class="section-kicker">车辆构成</p><h3>车辆类型分析</h3></div></div>
        <p class="detail">{{ vehicleStats?.overlap_note }}</p>
        <div v-if="vehicleStats" class="table-wrap">
          <table>
            <thead><tr><th>车型</th><th>车辆记录数</th><th>涉及不同事故数</th></tr></thead>
            <tbody>
              <tr v-for="item in vehicleStats.items" :key="String(item.vehicle_type_id)">
                <td>{{ item.canonical_name ?? '未知车型' }}</td>
                <td>{{ item.vehicle_records }}</td>
                <td>{{ item.collision_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="personStats" class="analysis-card print-block">
        <div class="analysis-heading"><div><p class="section-kicker">人员明细</p><h3>人员类别与伤亡状态（人员明细口径）</h3></div></div>
        <p class="detail">{{ personStats.note }}</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>人员类别</th><th>伤亡状态</th><th>记录数</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in personStats.items" :key="index">
                <td>{{ item.person_type ?? '未知类别' }}</td>
                <td>{{ item.person_injury ?? '未知状态' }}</td>
                <td>{{ item.record_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="governance" class="analysis-card print-block governance-summary">
        <div class="analysis-heading"><div><p class="section-kicker">课程模拟业务</p><h3>模拟治理工单统计</h3></div><span class="scope-badge">独立于事故日期范围</span></div>
        <p class="detail">{{ governance.note }} {{ governance.filter_basis }}</p>
        <p v-if="governance.total_tasks === 0" class="empty-state">当前没有未软删除的模拟工单。</p>
        <template v-else>
          <p class="detail">当前未软删除工单总数：{{ governance.total_tasks }}。</p>
          <div class="stat-columns">
            <div class="table-wrap">
              <table>
                <thead><tr><th>状态</th><th>工单数</th></tr></thead>
                <tbody>
                  <tr v-for="item in governance.by_status" :key="item.status">
                    <td>{{ item.label }}（{{ item.status }}）</td><td>{{ item.task_count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="table-wrap">
              <table>
                <thead><tr><th>执行人</th><th>工单数</th></tr></thead>
                <tbody>
                  <tr v-for="item in governance.by_assignee" :key="String(item.assignee_id)">
                    <td>{{ item.assignee_name }}{{ item.assignee_id ? '' : '（未分配）' }}</td><td>{{ item.task_count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <p class="detail">
            处理情况：已完成 {{ governance.handling.completed }}、执行中（待执行/执行中/待复核）{{ governance.handling.in_execution }}、
            草稿 {{ governance.handling.draft }}、已取消 {{ governance.handling.cancelled }}。
          </p>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.workflow-panel { --panel-ink:#17324d; --panel-muted:#61758c; --panel-line:#dbe5f0; --panel-blue:#083da6; min-width:0; margin:0; padding:0; border:0; border-radius:0; background:transparent; box-shadow:none; color:var(--panel-ink); }
.page-heading,.card-heading,.analysis-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.page-heading { margin-bottom:18px; }.page-heading h2 { color:var(--panel-ink); font-size:18px; letter-spacing:-.01em; }
.page-eyebrow,.section-kicker { margin:0 0 6px; color:var(--panel-blue); font-size:11px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.page-lead,.quiet-note { color:var(--panel-muted); font-size:13px; line-height:1.65; }.page-lead { margin:7px 0 0; }.quiet-note { margin:0; }
.report-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
.surface-card { min-width:0; margin:16px 0 0; padding:20px; border:1px solid var(--panel-line); border-radius:12px; background:#fff; box-shadow:0 5px 18px rgb(29 55 89 / 5%); }
.surface-card h3,.analysis-card h3 { margin:0; color:var(--panel-ink); }.card-heading { margin-bottom:15px; }.card-heading .section-kicker,.analysis-heading .section-kicker { margin-bottom:3px; }
.button-primary,.button-secondary { min-height:39px; padding:9px 13px; border:1px solid transparent; border-radius:8px; font:inherit; font-size:12px; font-weight:750; cursor:pointer; transition:background .15s ease,transform .15s ease; }
.button-primary { background:var(--panel-blue); color:#fff; }.button-secondary { border-color:#d4deec; background:#f4f7fc; color:var(--panel-blue); }
.button-primary:hover:not(:disabled) { background:#062f83; transform:translateY(-1px); }.button-secondary:hover:not(:disabled) { background:#eaf0ff; }
button:disabled { opacity:.52; cursor:not-allowed; }
.role-note { margin:0 0 12px; color:var(--panel-muted); font-size:12px; }
.filter-card { margin-top:0; }.filter-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:0; align-items:end; }
label { display:flex; min-width:0; flex-direction:column; gap:7px; color:var(--panel-muted); font-size:12px; font-weight:650; }
input,select { width:100%; min-width:0; max-width:100%; min-height:41px; padding:9px 10px; border:1px solid #cbd7e7; border-radius:8px; background:#fff; color:var(--panel-ink); font:inherit; }
input:focus,select:focus { border-color:var(--panel-blue); outline:3px solid rgb(8 61 166 / 12%); }
.inline-message { margin:12px 0; padding:12px 14px; border:1px solid transparent; border-radius:9px; font-size:13px; line-height:1.6; }
.message-error { border-color:#f1d0d0; background:#fff4f3; color:#9f3333; }.message-warning { border-color:#f1ddb9; background:#fff8eb; color:#805711; }
.loading-state,.empty-state { margin:14px 0; padding:16px; border-radius:9px; background:#f6f8fc; color:var(--panel-muted); font-size:13px; }
.report-body { min-width:0; }.report-scope { display:flex; align-items:flex-start; gap:12px; margin:16px 0 12px; padding:12px 14px; border:1px solid var(--panel-line); border-radius:10px; background:#fff; }
.report-scope .detail { margin:0; color:var(--panel-muted); font-size:11px; }
.scope-badge { display:inline-flex; flex:none; align-items:center; padding:6px 9px; border-radius:999px; background:#eaf0ff; color:var(--panel-blue); font-size:10px; font-weight:800; white-space:nowrap; }
.overview-card { margin-top:0; }.summary-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:0; }
.summary-metrics > div { min-width:0; padding:13px; border:1px solid #e6ecf4; border-radius:9px; background:#fbfcfe; }
.summary-metrics dt { color:var(--panel-muted); font-size:11px; line-height:1.5; }.summary-metrics dd { margin:7px 0 0; color:var(--panel-blue); font-size:clamp(18px,2vw,25px); font-weight:800; line-height:1.2; overflow-wrap:anywhere; }
.overview-card > .detail { margin:14px 0 0; padding-top:12px; border-top:1px solid #e9eef5; font-size:12px; }
.analysis-card { min-width:0; margin:14px 0 0; padding:19px; border:1px solid var(--panel-line); border-radius:12px; background:#fff; box-shadow:0 4px 14px rgb(29 55 89 / 4%); }
.analysis-heading { margin-bottom:8px; }.analysis-heading h3 { font-size:15px; }.analysis-card > .detail { margin:8px 0; font-size:12px; }
.statistics-page .chart-box { min-width:0; width:100%; height:280px; margin:12px 0; }
.statistics-page .chart-tall { height:330px; }
.table-wrap { min-width:0; overflow-x:auto; border:1px solid #e5ebf2; border-radius:9px; }
table { width:100%; min-width:520px; margin:0; border-collapse:collapse; font-size:11px; }
th { background:#f6f8fc; color:var(--panel-muted); font-size:10px; text-align:left; white-space:nowrap; }.table-wrap th,.table-wrap td { padding:9px; border-bottom:1px solid #e9eef5; text-align:left; vertical-align:top; }
.stat-columns { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }.governance-summary { border-color:#d7e2f4; }
.governance-summary .analysis-heading { align-items:flex-start; }
@media(max-width:900px) { .summary-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }.filter-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:700px) {
  .workflow-panel { padding:0; border-radius:0; }.page-heading { align-items:flex-start; flex-direction:column; }.report-actions { width:100%; justify-content:stretch; }
  .report-actions button { flex:1 1 145px; }.card-heading,.analysis-heading { align-items:flex-start; flex-direction:column; }
  .report-scope { flex-direction:column; }.summary-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }.stat-columns { grid-template-columns:1fr; }
  .analysis-card { padding:14px; }.statistics-page .chart-box { height:250px; }.statistics-page .chart-tall { height:300px; }
}
@media(max-width:440px) { .filter-grid { grid-template-columns:1fr; }.summary-metrics { grid-template-columns:1fr 1fr; }.scope-badge { white-space:normal; } }
</style>
