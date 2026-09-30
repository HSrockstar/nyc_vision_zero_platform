<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { sessionUser } from '../api/auth'
import { createRiskRun, getProfile, getProfiles, getRules, getRuns, type RiskDetail, type RiskProfile, type RiskRule, type RiskRun } from '../api/m4'

const start = ref('2025-01-01'), end = ref('2026-01-01'), ruleId = ref('')
const rules = ref<RiskRule[]>([]), runs = ref<RiskRun[]>([]), selected = ref('')
const rows = ref<RiskProfile[]>([]), total = ref(0), page = ref(1), level = ref(''), sort = ref('score'), intersection = ref('')
const runPage = ref(1), runTotal = ref(0), detail = ref<RiskDetail | null>(null)
const busy = ref(false), message = ref(''), error = ref('')
const rule = computed(() => rules.value.find(item => item.rule_id === ruleId.value))
const run = computed(() => runs.value.find(item => item.run_id === selected.value))
const canCreate = computed(() => ['ADMIN', 'MANAGER'].includes(sessionUser.value?.role ?? ''))
const pendingRequest = ref<{ key: string; id: string } | null>(null)
const labels = { LOW: '低', MEDIUM: '中', HIGH: '高', UNKNOWN: '未知' }
const statuses = { QUEUED: '排队中', RUNNING: '计算中', SUCCEEDED: '已完成', FAILED: '失败' }

async function loadProfiles() {
  detail.value = null; rows.value = []; total.value = 0
  if (!selected.value || run.value?.status !== 'SUCCEEDED') { rows.value = []; total.value = 0; return }
  const result = await getProfiles(selected.value, level.value, sort.value, page.value, intersection.value.trim())
  rows.value = result.items; total.value = result.total
}
async function reload() {
  rows.value = []; total.value = 0; detail.value = null
  runs.value = []; runTotal.value = 0
  const result = await getRuns(start.value, end.value, ruleId.value, runPage.value)
  runs.value = result.items; runTotal.value = result.total
  if (runPage.value === 1 && !selected.value && !runs.value.some(item => item.status === 'SUCCEEDED')) {
    const successful = (await getRuns(start.value, end.value, ruleId.value, 1, 'SUCCEEDED')).items[0]
    if (successful) runs.value.push(successful)
  }
  if (!runs.value.some(item => item.run_id === selected.value))
    selected.value = runs.value.find(item => item.status === 'SUCCEEDED')?.run_id ?? runs.value[0]?.run_id ?? ''
  page.value = 1
  await loadProfiles()
}
async function act(work: () => Promise<void>) {
  busy.value = true; error.value = ''
  try { await work() } catch (err) { error.value = err instanceof Error ? err.message : '请求失败。' }
  finally { busy.value = false }
}
async function submit() {
  const key = [start.value, end.value, ruleId.value].join('|')
  if (pendingRequest.value?.key !== key) pendingRequest.value = { key, id: crypto.randomUUID() }
  const created = await createRiskRun(start.value, end.value, ruleId.value, pendingRequest.value.id)
  pendingRequest.value = null; runPage.value = 1; selected.value = created.run_id
  message.value = `计算批次 ${created.run_id} 已排队，worker 完成后点击刷新。`
  await reload()
}
onMounted(() => act(async () => {
  rules.value = (await getRules()).items
  ruleId.value = rules.value.find(item => item.status === 'PUBLISHED')?.rule_id ?? rules.value[0]?.rule_id ?? ''
  if (ruleId.value) await reload()
}))
</script>

<template>
  <section aria-labelledby="risk-heading">
    <div class="section-title"><h2 id="risk-heading">风险画像与历史批次</h2><button :disabled="busy || !ruleId" @click="act(reload)">刷新批次</button></div>
    <p>分数表示所选周期内的历史碰撞指标。当前首批路口只覆盖部分事故；未归属事故不参与排名。</p>
    <div class="risk-controls">
      <label>开始日期<input v-model="start" type="date" :disabled="busy" @change="runPage = 1; selected = ''; act(reload)" /></label>
      <label>结束日期（不含）<input v-model="end" type="date" :disabled="busy" @change="runPage = 1; selected = ''; act(reload)" /></label>
      <label>规则<select v-model="ruleId" :disabled="busy" @change="runPage = 1; selected = ''; act(reload)"><option v-for="item in rules" :key="item.rule_id" :value="item.rule_id">{{ item.rule_name }} v{{ item.version_no }}{{ item.status === 'RETIRED' ? '（已停用，仅查历史）' : '' }}</option></select></label>
      <button v-if="canCreate" :disabled="busy || rule?.status !== 'PUBLISHED' || !start || !end || start >= end" @click="act(submit)">生成本周期画像</button>
    </div>
    <p v-if="rule" class="detail">S = {{ rule.weight_collision }}×事故数 + {{ rule.weight_injured }}×受伤 + {{ rule.weight_killed }}×死亡 + {{ rule.weight_vru }}×行人及骑行者伤亡。低：小于 {{ rule.threshold_medium }}；中：{{ rule.threshold_medium }} 至小于 {{ rule.threshold_high }}；高：不小于 {{ rule.threshold_high }}。行人和骑行者在受伤/死亡项中已计数，此处有意额外加权。规则未经现实效果验证；不同长度周期的原始分数不宜直接比较。</p>
    <p v-if="message" role="status">{{ message }}</p><p v-if="error" role="alert">{{ error }}</p>
    <div class="risk-controls">
      <label>同周期历史批次<select v-model="selected" :disabled="busy" @change="page = 1; act(loadProfiles)"><option value="">尚无批次</option><option v-for="item in runs" :key="item.run_id" :value="item.run_id">#{{ item.run_id }} · {{ statuses[item.status] }} · 版本 {{ item.input_revision ?? '待读取' }}</option></select></label>
      <button :disabled="busy || runPage <= 1" @click="runPage--; selected = ''; act(reload)">较新批次</button>
      <span>批次页 {{ runPage }} / {{ Math.max(1, Math.ceil(runTotal / 20)) }}</span>
      <button :disabled="busy || runPage * 20 >= runTotal" @click="runPage++; selected = ''; act(reload)">较旧批次</button>
    </div>
    <template v-if="run">
      <p v-if="run.is_stale" role="status">此批次已过期：来源数据或归属有新修订，历史结果仍按版本 {{ run.input_revision }} 保留。</p>
      <p v-if="run.error_summary" role="alert">{{ run.error_summary }}</p>
      <template v-if="run.status === 'SUCCEEDED'">
        <p>事故总数 {{ run.coverage_summary.total }}，有坐标 {{ run.coverage_summary.geocoded }}，缺坐标 {{ run.coverage_summary.missing_coordinates }}；纳入 {{ run.coverage_summary.included }}，未正式归属 {{ run.coverage_summary.unmatched }}；覆盖率 {{ run.coverage_summary.coverage_ratio == null ? '无事故' : (run.coverage_summary.coverage_ratio * 100).toFixed(2) + '%' }}；画像 {{ run.coverage_summary.profiled_intersections }} 个，纳入事故中伤亡不完整 {{ run.coverage_summary.incomplete_included }} 起。未知等级的伤亡列仅为已知值合计。</p>
        <div class="risk-controls">
          <label>等级<select v-model="level" :disabled="busy" @change="page = 1; act(loadProfiles)"><option value="">全部</option><option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option></select></label>
          <label>排序<select v-model="sort" :disabled="busy" @change="page = 1; act(loadProfiles)"><option value="score">分数降序</option><option value="collision_count">事故数降序</option></select></label>
          <label>路口编号<input v-model="intersection" placeholder="可选" :disabled="busy" /></label><button :disabled="busy" @click="page = 1; act(loadProfiles)">筛选</button>
        </div>
        <div class="risk-table"><table><thead><tr><th>交叉口</th><th>事故</th><th>受伤</th><th>死亡</th><th>行人/骑行伤亡</th><th>分数</th><th>等级</th><th>详情</th></tr></thead><tbody><tr v-for="item in rows" :key="item.profile_id"><td>{{ item.street_a }} / {{ item.street_b }}<br />#{{ item.intersection_id }}</td><td>{{ item.collision_count }}</td><td>{{ item.injured_count }}</td><td>{{ item.killed_count }}</td><td>{{ item.vulnerable_road_user_count }}</td><td>{{ item.score ?? '不可评分' }}</td><td>{{ labels[item.risk_level] }}</td><td><button :disabled="busy" @click="act(async () => { detail = await getProfile(item.profile_id) })">查看分项</button></td></tr></tbody></table></div>
        <p v-if="!rows.length">该筛选条件下未生成画像；未生成结果不代表低风险。</p>
        <div class="risk-controls"><button :disabled="busy || page <= 1" @click="page--; act(loadProfiles)">上一页</button><span>第 {{ page }} 页 / 共 {{ total }} 条</span><button :disabled="busy || page * 20 >= total" @click="page++; act(loadProfiles)">下一页</button></div>
        <p v-if="run.input_manifest.snapshot" class="risk-hash">快照 SHA-256：{{ run.input_manifest.snapshot.sha256 }}</p>
      </template>
      <p v-else>本批次尚未完成，画像不可见。</p>
    </template>
    <p v-else>当前周期和规则暂无计算批次。</p>
    <div v-if="detail" class="risk-detail">
      <h3>{{ detail.street_a }} / {{ detail.street_b }} · 批次 #{{ detail.run_id }}</h3>
      <p>贡献：事故 {{ detail.contributions.collision }}，受伤 {{ detail.contributions.injured }}，死亡 {{ detail.contributions.killed }}，行人及骑行者 {{ detail.contributions.vru }}。</p>
      <p v-if="detail.incomplete_casualty_collision_count">伤亡缺失事故 {{ detail.incomplete_casualty_collision_count }} 起，以上仅为已知值贡献，无法给出有效总分和等级。</p>
      <p>周期 {{ detail.run.period_start }} 至 {{ detail.run.period_end }}（不含），输入版本 {{ detail.run.input_revision }}；来源批次 {{ detail.run.input_manifest.sources?.length ?? 0 }} 个。{{ detail.is_stale ? '结果已过期，可查看历史或重新计算。' : '对应当前数据版本。' }}</p>
    </div>
  </section>
</template>

<style scoped>
.risk-controls { display:flex; flex-wrap:wrap; gap:12px; align-items:end; margin:16px 0; }
label { display:flex; flex-direction:column; gap:6px; max-width:100%; }
input,select { padding:8px; min-width:140px; max-width:100%; box-sizing:border-box; }
.risk-table { overflow-x:auto; } table { border-collapse:collapse; width:100%; min-width:780px; }
th { white-space:nowrap; }
th,td { text-align:left; padding:10px; border-bottom:1px solid #d6dfe7; }
.risk-hash { overflow-wrap:anywhere; font-size:12px; } .risk-detail { padding:16px; background:#f0f5f8; }
</style>
