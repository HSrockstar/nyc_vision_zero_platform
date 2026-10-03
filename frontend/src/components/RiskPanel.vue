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
const emit = defineEmits<{ governance: [profile: RiskProfile] }>()
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
  <section class="workflow-panel risk-page" aria-labelledby="risk-heading">
    <header class="page-heading">
      <div>
        <p class="page-eyebrow">风险评估 · 历史批次</p>
        <h2 id="risk-heading">周期与规则</h2>
        <p class="page-lead">按已发布规则查看周期画像、覆盖范围和可追溯的风险分项。</p>
      </div>
      <button class="button-secondary" :disabled="busy || !ruleId" @click="act(reload)">{{ busy ? '刷新中…' : '刷新批次' }}</button>
    </header>

    <div v-if="message" class="inline-message message-success" role="status">{{ message }}</div>
    <div v-if="error" class="inline-message message-error" role="alert">{{ error }}</div>

    <section class="surface-card filter-card" aria-label="画像周期与规则">
      <div class="card-heading"><div><p class="section-kicker">计算范围</p><h3>选择周期和规则</h3></div>
        <span class="quiet-note">结束日期为排他边界</span></div>
      <div class="risk-controls">
        <label>开始日期<input v-model="start" type="date" :disabled="busy" @change="runPage = 1; selected = ''; act(reload)" /></label>
        <label>结束日期（不含）<input v-model="end" type="date" :disabled="busy" @change="runPage = 1; selected = ''; act(reload)" /></label>
        <label class="rule-field">规则<select v-model="ruleId" :disabled="busy" @change="runPage = 1; selected = ''; act(reload)"><option v-for="item in rules" :key="item.rule_id" :value="item.rule_id">{{ item.rule_name }} v{{ item.version_no }}{{ item.status === 'RETIRED' ? '（已停用，仅查历史）' : '' }}</option></select></label>
        <button v-if="canCreate" class="button-primary" :disabled="busy || rule?.status !== 'PUBLISHED' || !start || !end || start >= end" @click="act(submit)">{{ busy ? '处理中…' : '生成本周期画像' }}</button>
      </div>
      <p v-if="rule" class="method-note">S = {{ rule.weight_collision }}×事故数 + {{ rule.weight_injured }}×受伤 + {{ rule.weight_killed }}×死亡 + {{ rule.weight_vru }}×行人及骑行者伤亡。低：小于 {{ rule.threshold_medium }}；中：{{ rule.threshold_medium }} 至小于 {{ rule.threshold_high }}；高：不小于 {{ rule.threshold_high }}。行人和骑行者在受伤/死亡项中已计数，此处有意额外加权。规则未经现实效果验证；不同长度周期的原始分数不宜直接比较。</p>
    </section>

    <section class="surface-card batch-section" aria-label="历史批次">
      <div class="card-heading"><div><p class="section-kicker">计算记录</p><h3>同周期历史批次</h3></div>
        <div class="batch-paging"><button class="button-secondary" :disabled="busy || runPage <= 1" @click="runPage--; selected = ''; act(reload)">较新批次</button><span>第 {{ runPage }} 页 / {{ Math.max(1, Math.ceil(runTotal / 20)) }}</span><button class="button-secondary" :disabled="busy || runPage * 20 >= runTotal" @click="runPage++; selected = ''; act(reload)">较旧批次</button></div>
      </div>
      <div class="batch-picker">
        <label>选择批次<select v-model="selected" :disabled="busy" @change="page = 1; act(loadProfiles)"><option value="">尚无批次</option><option v-for="item in runs" :key="item.run_id" :value="item.run_id">#{{ item.run_id }} · {{ statuses[item.status] }} · 版本 {{ item.input_revision ?? '待读取' }}</option></select></label>
        <div v-if="run" class="selected-run-state">
          <span class="state-badge" :class="'run-' + run.status.toLowerCase()">{{ statuses[run.status] }}</span>
          <span class="quiet-note">批次 #{{ run.run_id }} · 输入版本 {{ run.input_revision ?? '待读取' }}</span>
        </div>
      </div>
      <div v-if="run && run.is_stale" class="inline-message message-warning" role="status">此批次已过期：来源数据或归属有新修订，历史结果仍按版本 {{ run.input_revision }} 保留。</div>
      <div v-if="run?.error_summary" class="inline-message message-error" role="alert">{{ run.error_summary }}</div>

      <template v-if="run">
        <template v-if="run.status === 'SUCCEEDED'">
          <div class="coverage-grid" aria-label="批次覆盖概况">
            <div><span>事故总数</span><strong>{{ run.coverage_summary.total ?? '未知' }}</strong></div>
            <div><span>有坐标 / 缺坐标</span><strong>{{ run.coverage_summary.geocoded ?? '未知' }} / {{ run.coverage_summary.missing_coordinates ?? '未知' }}</strong></div>
            <div><span>纳入 / 未正式归属</span><strong>{{ run.coverage_summary.included ?? '未知' }} / {{ run.coverage_summary.unmatched ?? '未知' }}</strong></div>
            <div><span>覆盖率</span><strong>{{ run.coverage_summary.coverage_ratio == null ? (run.coverage_summary.total === 0 ? '无事故' : '未知') : (run.coverage_summary.coverage_ratio * 100).toFixed(2) + '%' }}</strong></div>
            <div><span>画像路口数</span><strong>{{ run.coverage_summary.profiled_intersections ?? '未知' }}</strong></div>
            <div><span>伤亡不完整事故</span><strong>{{ run.coverage_summary.incomplete_included ?? '未知' }}</strong></div>
          </div>
          <p class="quiet-note">未知等级的伤亡列仅为已知值合计。未正式归属的事故不参与路口排名。</p>

          <div class="card-heading profile-heading"><div><p class="section-kicker">路口结果</p><h3>风险画像</h3></div><span class="quiet-note">共 {{ total }} 个 · 第 {{ page }} 页</span></div>
          <div class="risk-controls profile-filters">
            <label>风险等级<select v-model="level" :disabled="busy" @change="page = 1; act(loadProfiles)"><option value="">全部</option><option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option></select></label>
            <label>排序<select v-model="sort" :disabled="busy" @change="page = 1; act(loadProfiles)"><option value="score">分数降序</option><option value="collision_count">事故数降序</option></select></label>
            <label>路口编号<input v-model="intersection" placeholder="可选" :disabled="busy" /></label><button class="button-secondary" :disabled="busy" @click="page = 1; act(loadProfiles)">应用筛选</button>
          </div>
          <div class="profile-grid">
            <article v-for="item in rows" :key="item.profile_id" class="profile-card">
              <div class="profile-card-heading">
                <div><p class="section-kicker">路口 #{{ item.intersection_id }}</p><h4>{{ item.street_a }} / {{ item.street_b }}</h4></div>
                <span class="risk-badge" :class="'risk-' + item.risk_level.toLowerCase()">{{ labels[item.risk_level] }}</span>
              </div>
              <dl class="profile-metrics">
                <div><dt>事故</dt><dd>{{ item.collision_count }}</dd></div>
                <div><dt>已知受伤</dt><dd>{{ item.injured_count ?? '未知' }}</dd></div>
                <div><dt>已知死亡</dt><dd>{{ item.killed_count ?? '未知' }}</dd></div>
                <div><dt>行人 / 骑行伤亡</dt><dd>{{ item.vulnerable_road_user_count ?? '未知' }}</dd></div>
              </dl>
              <div class="profile-card-footer"><p><span>风险分数</span><strong>{{ item.score ?? '不可评分' }}</strong></p>
                <div class="card-actions"><button class="button-secondary" :disabled="busy" @click="act(async () => { detail = await getProfile(item.profile_id) })">查看分项</button><button v-if="canCreate" class="button-primary" :disabled="busy" @click="emit('governance', item)">建立治理草稿</button></div>
              </div>
            </article>
          </div>
          <p v-if="!rows.length" class="empty-state">该筛选条件下未生成画像；未生成结果不代表低风险。</p>
          <div class="profile-pagination"><button class="button-secondary" :disabled="busy || page <= 1" @click="page--; act(loadProfiles)">上一页</button><span>第 {{ page }} 页 / 共 {{ total }} 条</span><button class="button-secondary" :disabled="busy || page * 20 >= total" @click="page++; act(loadProfiles)">下一页</button></div>
          <p v-if="run.input_manifest.snapshot" class="risk-hash">快照 SHA-256：{{ run.input_manifest.snapshot.sha256 }}</p>
        </template>
        <div v-else class="batch-pending"><span class="state-badge" :class="'run-' + run.status.toLowerCase()">{{ statuses[run.status] }}</span><p>本批次尚未完成，画像不可见。</p></div>
      </template>
      <p v-else class="empty-state">当前周期和规则暂无计算批次。</p>
    </section>

    <section v-if="detail" class="surface-card risk-detail" aria-labelledby="risk-detail-heading">
      <div class="card-heading"><div><p class="section-kicker">画像分项 · 批次 #{{ detail.run_id }}</p><h3 id="risk-detail-heading">{{ detail.street_a }} / {{ detail.street_b }}</h3></div><span class="risk-badge" :class="'risk-' + detail.risk_level.toLowerCase()">{{ labels[detail.risk_level] }}</span></div>
      <div class="detail-contributions"><div><span>事故贡献</span><strong>{{ detail.contributions.collision }}</strong></div><div><span>受伤贡献</span><strong>{{ detail.contributions.injured }}</strong></div><div><span>死亡贡献</span><strong>{{ detail.contributions.killed }}</strong></div><div><span>行人及骑行者贡献</span><strong>{{ detail.contributions.vru }}</strong></div></div>
      <p v-if="detail.incomplete_casualty_collision_count" class="inline-message message-warning">伤亡缺失事故 {{ detail.incomplete_casualty_collision_count }} 起，以上仅为已知值贡献，无法给出有效总分和等级。</p>
      <p class="quiet-note">周期 {{ detail.run.period_start }} 至 {{ detail.run.period_end }}（不含），输入版本 {{ detail.run.input_revision }}；来源批次 {{ detail.run.input_manifest.sources?.length ?? 0 }} 个。{{ detail.is_stale ? '结果已过期，可查看历史或重新计算。' : '对应当前数据版本。' }}</p>
    </section>
  </section>
</template>

<style scoped>
.workflow-panel { --panel-ink:#17324d; --panel-muted:#61758c; --panel-line:#dbe5f0; --panel-blue:#083da6; --panel-blue-soft:#eaf0ff; min-width:0; margin:0; padding:0; border:0; border-radius:0; background:transparent; box-shadow:none; color:var(--panel-ink); }
.page-heading,.card-heading,.profile-card-heading,.profile-card-footer { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.page-heading { margin-bottom:22px; }
.page-heading h2 { color:var(--panel-ink); font-size:18px; letter-spacing:-.01em; }
.page-eyebrow,.section-kicker { margin:0 0 6px; color:var(--panel-blue); font-size:11px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.page-lead,.quiet-note { color:var(--panel-muted); font-size:13px; line-height:1.65; }
.page-lead { margin:7px 0 0; }
.surface-card { min-width:0; margin:16px 0 0; padding:20px; border:1px solid var(--panel-line); border-radius:12px; background:#fff; box-shadow:0 5px 18px rgb(29 55 89 / 5%); }
.surface-card h3,.surface-card h4 { margin:0; color:var(--panel-ink); }
.card-heading { margin-bottom:16px; }
.card-heading .section-kicker { margin-bottom:3px; }
.quiet-note { margin:0; }
.risk-controls { display:flex; flex-wrap:wrap; gap:12px; align-items:end; margin:16px 0 0; }
label { display:flex; flex:1 1 170px; flex-direction:column; gap:7px; max-width:100%; color:var(--panel-muted); font-size:12px; font-weight:650; }
input,select { width:100%; min-width:0; max-width:100%; min-height:42px; padding:9px 11px; border:1px solid #cbd7e7; border-radius:8px; box-sizing:border-box; background:#fff; color:var(--panel-ink); font:inherit; }
input:focus,select:focus { border-color:var(--panel-blue); outline:3px solid rgb(8 61 166 / 12%); }
button { min-height:40px; padding:9px 14px; border:1px solid transparent; border-radius:8px; background:var(--panel-blue); color:#fff; font:inherit; font-size:13px; font-weight:700; cursor:pointer; transition:background .15s ease,transform .15s ease; }
button:hover:not(:disabled) { background:#062f83; transform:translateY(-1px); }
button:disabled { opacity:.52; cursor:not-allowed; }
.button-secondary { border-color:#d4deec; background:#f4f7fc; color:var(--panel-blue); }
.button-secondary:hover:not(:disabled) { background:#eaf0ff; }
.method-note { margin:18px 0 0; padding:13px 15px; border-radius:9px; background:#f5f7fb; color:var(--panel-muted); font-size:12px; line-height:1.75; }
.inline-message { margin:12px 0; padding:12px 14px; border:1px solid transparent; border-radius:9px; font-size:13px; line-height:1.6; }
.message-success { border-color:#cae8db; background:#eff9f4; color:#176b51; }
.message-error { border-color:#f1d0d0; background:#fff4f3; color:#9f3333; }
.message-warning { border-color:#f1ddb9; background:#fff8eb; color:#805711; }
.batch-paging,.selected-run-state,.profile-pagination { display:flex; align-items:center; flex-wrap:wrap; gap:10px; color:var(--panel-muted); font-size:12px; }
.batch-paging button,.profile-pagination button { min-height:36px; }
.batch-picker { display:flex; align-items:end; flex-wrap:wrap; gap:18px; padding:14px; border-radius:10px; background:#f6f8fc; }
.batch-picker label { flex:1 1 260px; }
.selected-run-state { padding-bottom:9px; }
.state-badge,.risk-badge { display:inline-flex; align-items:center; justify-content:center; min-height:27px; padding:5px 10px; border-radius:999px; font-size:11px; font-weight:800; white-space:nowrap; }
.run-succeeded { background:#e8f6ef; color:#15704d; }.run-running,.run-queued { background:#eaf0ff; color:#17499c; }.run-failed { background:#fff0ee; color:#a33730; }
.coverage-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:10px; margin-top:18px; }
.coverage-grid > div,.detail-contributions > div { min-width:0; padding:13px 14px; border:1px solid #e5ebf3; border-radius:10px; background:#fff; }
.coverage-grid span,.detail-contributions span { display:block; color:var(--panel-muted); font-size:11px; line-height:1.4; }
.coverage-grid strong,.detail-contributions strong { display:block; margin-top:7px; color:var(--panel-ink); font-size:20px; line-height:1.2; overflow-wrap:anywhere; }
.profile-heading { margin:25px 0 12px; padding-top:20px; border-top:1px solid var(--panel-line); }
.profile-filters { margin:0 0 14px; }
.profile-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr)); gap:12px; }
.profile-card { min-width:0; padding:17px; border:1px solid #dfe7f2; border-radius:11px; background:#fff; }
.profile-card-heading { align-items:flex-start; }
.profile-card-heading h4 { font-size:16px; line-height:1.45; overflow-wrap:anywhere; }
.risk-low { background:#e8f5ee; color:#146c48; }.risk-medium { background:#fff5db; color:#825400; }.risk-high { background:#fff0ee; color:#a4302e; }.risk-unknown { background:#edf0f5; color:#58677b; }
.profile-metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; margin:16px 0; }
.profile-metrics > div { min-width:0; padding:10px; border-radius:8px; background:#f6f8fc; }
.profile-metrics dt { color:var(--panel-muted); font-size:11px; }
.profile-metrics dd { margin:5px 0 0; color:var(--panel-ink); font-size:16px; font-weight:750; overflow-wrap:anywhere; }
.profile-card-footer { align-items:flex-end; padding-top:12px; border-top:1px solid #e9eef5; }
.profile-card-footer p { margin:0; color:var(--panel-muted); font-size:11px; }
.profile-card-footer p strong { display:block; margin-top:3px; color:var(--panel-blue); font-size:19px; }
.card-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:7px; }
.card-actions button { min-height:36px; padding:8px 10px; }
.profile-pagination { justify-content:center; margin-top:16px; }
.risk-hash { margin:18px 0 0; padding-top:12px; border-top:1px solid var(--panel-line); color:var(--panel-muted); font-size:11px; overflow-wrap:anywhere; }
.batch-pending { display:flex; align-items:center; gap:12px; margin-top:16px; padding:14px; border-radius:9px; background:#f6f8fc; color:var(--panel-muted); }
.batch-pending p { margin:0; }
.risk-detail { border-color:#cbd8f1; }
.detail-contributions { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:16px 0; }
.empty-state { padding:16px; border-radius:9px; background:#f6f8fc; color:var(--panel-muted); }
@media(max-width:700px) {
  .workflow-panel { padding:0; border-radius:0; }
  .page-heading { align-items:flex-start; flex-direction:column; }
  .page-heading > button { width:100%; }
  .card-heading { align-items:flex-start; flex-direction:column; }
  .batch-paging { width:100%; justify-content:space-between; }
  .batch-paging button { padding-inline:9px; }
  .selected-run-state { padding:0; }
  .coverage-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .profile-card-footer { align-items:flex-start; flex-direction:column; }
  .card-actions { width:100%; justify-content:stretch; }
  .card-actions button { flex:1 1 130px; }
  .risk-controls > button { width:100%; }
}
</style>
