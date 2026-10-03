<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getOverview, getBoroughs, getTrendMonths, type OverviewData, type BoroughsData, type TrendMonthsData } from '../api/m6'
import { sessionUser } from '../api/auth'
import AppIcon from '../components/AppIcon.vue'

const start = ref('2025-01-01'), end = ref('2025-12-31'), busy = ref(false), error = ref('')
const overview = ref<OverviewData | null>(null), boroughs = ref<BoroughsData | null>(null), trends = ref<TrendMonthsData | null>(null)
const applied = ref<{ start: string; end: string; revision: string | null } | null>(null)
let sequence = 0
const number = (value: number | null | undefined) => value == null ? '未知' : value.toLocaleString('zh-CN')
const chartMax = computed(() => Math.max(1, ...(trends.value?.months.map(row => row.collision_count ?? 0) ?? [])))
const trendSegments = computed(() => {
  const segments: string[] = []; let current: string[] = []
  const months = trends.value?.months ?? []
  months.forEach((row, i) => {
    if (row.collision_count === null) { if (current.length) segments.push(current.join(' ')); current = []; return }
    current.push(`${30 + i * 620 / Math.max(1, months.length - 1)},${160 - row.collision_count / chartMax.value * 130}`)
  })
  if (current.length) segments.push(current.join(' '))
  return segments
})
const boroughMax = computed(() => Math.max(1, ...(boroughs.value?.items.map(row => row.collision_count) ?? [])))
const names: Record<string, string> = { BRONX: '布朗克斯', BROOKLYN: '布鲁克林', MANHATTAN: '曼哈顿', QUEENS: '皇后区', 'STATEN ISLAND': '斯塔滕岛' }
const metricCards = computed(() => overview.value ? [
  { label: '碰撞事故', value: number(overview.value.collision_count), unit: '起', note: '当前统计区间内的事故记录', icon: 'collisions' as const },
  { label: '已知受伤人数', value: number(overview.value.known_injured_count), unit: '人', note: `${number(overview.value.injured_missing_count)} 起事故伤亡字段缺失`, icon: 'users' as const },
  { label: '已知死亡人数', value: number(overview.value.known_killed_count), unit: '人', note: `${number(overview.value.killed_missing_count)} 起事故死亡字段缺失`, icon: 'shield' as const },
  { label: '有效坐标事故', value: number(overview.value.geocoded_count), unit: '起', note: `${number(overview.value.missing_coordinates_count)} 起事故缺少坐标`, icon: 'map' as const },
] : [])
const link = (path: string) => ({ path, query: applied.value ? { start: applied.value.start, end: applied.value.end } : {} })
const pendingFilters = computed(() => Boolean(applied.value && (start.value !== applied.value.start || end.value !== new Date(Date.parse(applied.value.end) - 86400000).toISOString().slice(0, 10))))
async function load() {
  if (busy.value) return
  if (!start.value || !end.value || start.value > end.value || !/^\d{4}-\d{2}-\d{2}$/.test(start.value + '') || !/^\d{4}-\d{2}-\d{2}$/.test(end.value + '')) { error.value = '请选择有效的日期区间，结束日期不能早于开始日期。'; return }
  const seq = ++sequence
  const query = { start: start.value, endExclusive: new Date(Date.parse(end.value + 'T00:00:00Z') + 86400000).toISOString().slice(0, 10) }
  busy.value = true; error.value = ''
  try {
    const [summary, areas, months] = await Promise.all([getOverview(query), getBoroughs(query), getTrendMonths(query)])
    if (seq !== sequence) return
    if (new Set([summary.revision, areas.revision, months.revision]).size !== 1) throw new Error('查询期间数据版本发生变化，请重新查询。')
    overview.value = summary.data; boroughs.value = areas.data; trends.value = months.data
    applied.value = { start: query.start, end: query.endExclusive, revision: summary.revision }
  } catch (exception) {
    if (seq !== sequence) return
    overview.value = null; boroughs.value = null; trends.value = null; applied.value = null
    error.value = exception instanceof Error ? exception.message : '总览数据加载失败，请重试。'
  } finally { if (seq === sequence) busy.value = false }
}
onMounted(load)
onBeforeUnmount(() => { sequence++ })
</script>

<template>
  <div class="overview-page">
    <section class="overview-welcome"><div><p class="eyebrow">CITY SAFETY AT A GLANCE</p><h2>每一条数据，都关乎安全。</h2><p>你好，{{ sessionUser?.display_name }}。从事故分布出发，识别值得关注的交叉口。</p><div class="welcome-actions"><RouterLink class="button-link" :to="link('/map')">探索事故地图<AppIcon name="arrow" /></RouterLink><RouterLink class="text-link" to="/risks">查看风险画像 →</RouterLink></div></div><div class="overview-map-art" aria-hidden="true"><svg viewBox="0 0 280 150" fill="none"><path d="m-20 123 100-35 67 13 158-75 M25-15l49 107 65 76 M178-10l-34 103 23 75" stroke="#d9e5f5" stroke-width="24"/><path d="m-20 123 100-35 67 13 158-75 M25-15l49 107 65 76 M178-10l-34 103 23 75" stroke="white" stroke-width="12"/><circle cx="145" cy="101" r="28" fill="#083da6" opacity=".08"/><circle cx="145" cy="101" r="9" fill="#083da6" stroke="white" stroke-width="4"/><circle cx="80" cy="88" r="6" fill="#2c9381" stroke="white" stroke-width="3"/></svg><span><span class="status-dot healthy" />数据洞察 · 空间分析</span></div></section>
    <form class="overview-filter" @submit.prevent="load"><div><h2>事故数据概览</h2><p class="detail">默认展示 2025 年；可调整日期查看已有数据。</p></div><div class="overview-date-fields"><label>开始日期<input v-model="start" type="date" required /></label><span class="date-separator">—</span><label>结束日期（含当天）<input v-model="end" type="date" required /></label><button :disabled="busy">{{ busy ? '加载中…' : '更新概览' }}</button></div></form>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="pendingFilters" class="notice" role="status">日期尚未应用，下方展示上次成功查询的结果。</p>
    <div v-if="busy && !overview" class="metric-grid" aria-label="正在加载概览" role="status"><div v-for="i in 4" :key="i" class="metric-card skeleton-card"><span class="skeleton-line"/><span class="skeleton-line wide"/><span class="skeleton-line"/></div></div>
    <template v-if="overview && applied">
      <div class="metric-grid"><article v-for="card in metricCards" :key="card.label" class="metric-card"><div class="metric-label"><span>{{ card.label }}</span><span class="metric-icon"><AppIcon :name="card.icon" /></span></div><div class="metric-value">{{ card.value }}<small>{{ card.unit }}</small></div><p>{{ card.note }}</p></article></div>
      <div class="overview-charts"><section class="trend-panel"><div class="section-title"><div><h2>事故月度趋势</h2><p class="detail">按月份观察碰撞事故数量</p></div><RouterLink class="text-link" :to="link('/statistics')">完整报表 →</RouterLink></div><div class="overview-trend"><svg viewBox="0 0 680 195" role="img" aria-label="事故月度数量趋势，详细数值可在下方展开"><path d="M30 30h620 M30 95h620 M30 160h620" stroke="#e8edf4" stroke-dasharray="4 4"/><text x="30" y="20">{{ number(chartMax) }}</text><polyline v-for="(segment, i) in trendSegments" :key="i" :points="segment" fill="none" stroke="#083da6" stroke-width="2.5" stroke-linejoin="round"/><template v-for="(month, i) in trends?.months" :key="month.month"><circle v-if="month.collision_count !== null" :cx="30 + i * 620 / Math.max(1, (trends?.months.length ?? 1) - 1)" :cy="160 - month.collision_count / chartMax * 130" r="3.5" fill="#083da6"><title>{{ month.month }}：{{ month.collision_count }} 起</title></circle><text v-if="(trends?.months.length ?? 0) <= 12 || i % Math.ceil((trends?.months.length ?? 1) / 8) === 0" :x="30 + i * 620 / Math.max(1, (trends?.months.length ?? 1) - 1)" y="187" text-anchor="middle">{{ month.month.slice(2) }}</text></template></svg></div><p class="detail">无记录月份保留为空，不能据此认定为零事故。</p><details class="data-disclosure"><summary>查看月度明细与覆盖说明</summary><p class="detail">{{ trends?.coverage_note }}</p><div class="table-wrap"><table><thead><tr><th>月份</th><th>事故数</th><th>覆盖状态</th></tr></thead><tbody><tr v-for="month in trends?.months" :key="month.month"><td>{{ month.month }}</td><td>{{ month.collision_count === null ? '无记录' : number(month.collision_count) }}</td><td>{{ month.coverage === 'WITH_DATA' ? '有记录' : month.coverage === 'OUTSIDE_DECLARED_RANGES' ? '不在声明覆盖范围' : '覆盖未确认' }}</td></tr></tbody></table></div></details></section>
      <section class="borough-panel"><div class="section-title"><div><h2>行政区分布</h2><p class="detail">当前日期范围内的事故数量</p></div></div><div class="borough-bars"><div v-for="area in boroughs?.items" :key="area.borough_id ?? 'unknown'" class="borough-bar"><div><span>{{ names[area.borough_name] ?? area.borough_name ?? '未知行政区' }}</span><strong>{{ number(area.collision_count) }}</strong></div><div class="bar-track"><span :style="{ width: `${area.collision_count / boroughMax * 100}%` }" /></div></div></div><RouterLink class="text-link" :to="link('/collisions')">查询事故记录 →</RouterLink></section></div>
      <div class="overview-data-note"><AppIcon name="shield" /><p>统计范围 [{{ applied.start }}, {{ applied.end }}) · 数据版本 {{ applied.revision ?? '未知' }}。{{ overview.casualty_note }}<br />{{ overview.filters.collision_scope }}</p></div>
    </template>
    <div v-else-if="!busy" class="empty-state overview-empty">概览暂不可用。你仍可通过导航进入各业务页面。</div>
    <section class="workflow-links"><div><h2>从发现到行动</h2><p class="detail">沿着数据、风险与治理，建立完整的工作记录。</p></div><div class="workflow-grid"><RouterLink :to="link('/collisions')"><span class="workflow-number">01</span><div><strong>查阅事故</strong><p>定位记录，核对人车明细</p></div><AppIcon name="arrow" /></RouterLink><RouterLink to="/risks"><span class="workflow-number">02</span><div><strong>识别风险</strong><p>查看周期画像与计算依据</p></div><AppIcon name="arrow" /></RouterLink><RouterLink v-if="sessionUser?.role !== 'VIEWER'" to="/governance"><span class="workflow-number">03</span><div><strong>跟踪治理</strong><p>管理课程模拟任务与复核</p></div><AppIcon name="arrow" /></RouterLink><RouterLink v-else :to="link('/statistics')"><span class="workflow-number">03</span><div><strong>分析趋势</strong><p>阅读统计与输出事故记录</p></div><AppIcon name="arrow" /></RouterLink></div></section>
  </div>
</template>
