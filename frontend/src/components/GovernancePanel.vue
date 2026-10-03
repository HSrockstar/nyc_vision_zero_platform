<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { RiskProfile } from '../api/m4'
import { changeTask, createTask, getAssignees, getHistory, getTask, getTasks,
  type Assignee, type DraftFields, type GovernanceTask, type TaskAction, type TaskHistory } from '../api/m5'

const props = defineProps<{ profile: RiskProfile | null }>()
const statuses = { DRAFT: '草稿', OPEN: '待执行', IN_PROGRESS: '执行中', PENDING_REVIEW: '待复核', COMPLETED: '已完成', CANCELLED: '已取消' }
const measures = { MARKING_MAINTENANCE: '标线维护', SIGNAL_REVIEW: '信号配时检查', PEDESTRIAN_FACILITY_REVIEW: '行人设施检查', FIELD_SURVEY: '现场调查', OTHER: '其他' }
const priorities = { LOW: '低', MEDIUM: '中', HIGH: '高', URGENT: '紧急' }
const actionLabels: Record<TaskAction, string> = { edit: '保存草稿', publish: '发布任务', delete_draft: '删除草稿', assign: '重新分配', start: '开始执行', progress: '追加执行记录', submit: '提交复核', approve: '复核通过', reject: '退回执行', cancel: '取消任务' }
const eventLabels: Record<string, string> = { CREATE: '创建', EDIT: '修改', PUBLISH: '发布', DELETE_DRAFT: '删除草稿', ASSIGN: '分配', START: '开始执行', PROGRESS: '执行记录', SUBMIT: '提交复核', APPROVE: '复核通过', REJECT: '退回', CANCEL: '取消' }
const blank = (): DraftFields => ({ title: '', description: '', measure_type: 'FIELD_SURVEY', priority: 'MEDIUM', due_date: null, effective_on: null })
const draft = ref(blank()), edit = ref(blank()), radius = ref(50), rationale = ref('')
const items = ref<GovernanceTask[]>([]), total = ref(0), page = ref(1), status = ref(''), mine = ref(false)
const task = ref<GovernanceTask | null>(null), history = ref<TaskHistory[]>([]), selectedTaskId = ref('')
const assignees = ref<Assignee[]>([]), assigneeTotal = ref(0), search = ref(''), assignee = ref(''), note = ref('')
const busy = ref(false), error = ref(''), notice = ref(''), refreshRequired = ref(false)
const pending = ref<{ key: string; id: string } | null>(null)
const canEdit = computed(() => task.value?.allowed_actions.includes('edit'))
const needsAssignee = computed(() => task.value?.allowed_actions.some(value => ['publish', 'assign'].includes(value)))
const ready = computed(() => Boolean(draft.value.title.trim() && draft.value.description.trim() &&
  (props.profile?.risk_level === 'HIGH' || rationale.value.trim()) && radius.value >= 1 && radius.value <= 1000))

function requestId(key: string) {
  if (pending.value?.key !== key) pending.value = { key, id: crypto.randomUUID() }
  return pending.value.id
}
async function run(work: () => Promise<void>) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await work() }
  catch (e) { error.value = e instanceof Error ? e.message : '操作未完成。' }
  finally { busy.value = false }
}
async function loadList() {
  items.value = []; total.value = 0
  const result = await getTasks(page.value, status.value, mine.value)
  items.value = result.items; total.value = result.total
}
async function loadAssignees() {
  assignees.value = []; assigneeTotal.value = 0
  const result = await getAssignees(search.value.trim())
  assignees.value = result.items; assigneeTotal.value = result.total
}
function fields(value: GovernanceTask): DraftFields {
  return { title: value.title, description: value.description, measure_type: value.measure_type,
    priority: value.priority, due_date: value.due_date, effective_on: value.effective_on }
}
async function open(id: string) {
  selectedTaskId.value = id
  task.value = null; history.value = []; refreshRequired.value = true
  const result = await getTask(id)
  const records = await getHistory(id)
  task.value = result; history.value = records.items; edit.value = fields(result)
  assignee.value = result.assignee_id ?? ''; note.value = ''; refreshRequired.value = false
}
async function refresh() {
  const id = selectedTaskId.value
  await loadList()
  if (id) await open(id)
}
async function create() {
  if (!props.profile) return
  const body = { ...draft.value, due_date: draft.value.due_date || null, effective_on: draft.value.effective_on || null,
    profile_id: props.profile.profile_id, radius_m: radius.value, rationale: rationale.value.trim() || null }
  const result = await createTask({ ...body, request_id: requestId(JSON.stringify(body)) })
  pending.value = null; page.value = 1; status.value = ''; mine.value = false
  draft.value = blank(); rationale.value = ''
  task.value = result
  await open(result.task_id); await loadList()
  notice.value = `课程模拟草稿 ${result.task_code} 已建立。`
}
async function perform(action: TaskAction) {
  if (!task.value) return
  if (['delete_draft', 'cancel'].includes(action) && !window.confirm(`确认${actionLabels[action]}“${task.value.task_code}”？历史将保留。`)) return
  const body: Record<string, unknown> = { expected_version: task.value.version, note: note.value.trim() }
  if (action === 'edit') Object.assign(body, edit.value, { due_date: edit.value.due_date || null, effective_on: edit.value.effective_on || null })
  if (['publish', 'assign'].includes(action)) body.assignee_id = assignee.value
  if (['approve', 'reject'].includes(action)) body.decision = action.toUpperCase()
  const id = requestId(JSON.stringify({ task_id: task.value.task_id, action, body }))
  try {
    const result = await changeTask(task.value.task_id, action, { ...body, request_id: id })
    pending.value = null
    await open(result.task_id); await loadList()
    notice.value = `${actionLabels[action]}已完成。`
  } catch (e) {
    refreshRequired.value = true
    throw e
  }
}
watch(() => props.profile, value => {
  draft.value = blank(); rationale.value = ''; pending.value = null
  if (value) draft.value.title = `${value.street_a} / ${value.street_b} · 现场调查`
}, { immediate: true })
onMounted(() => run(async () => { await loadList(); await loadAssignees() }))
</script>

<template>
  <section id="governance" class="workflow-panel governance-page" aria-labelledby="governance-heading">
    <header class="page-heading">
      <div><p class="page-eyebrow">模拟治理 · 工作流</p><h2 id="governance-heading">任务工作区</h2><p class="page-lead">按状态跟进模拟工单，查看执行记录与复核历史。</p></div>
      <button class="button-secondary" :disabled="busy" @click="run(refresh)">{{ busy ? '刷新中…' : '刷新任务' }}</button>
    </header>
    <p class="simulated"><strong>课程模拟</strong><span>措施和生效日期由本系统登记，不表示纽约政府实际治理项目或工程授权。</span></p>
    <ol class="workflow-steps" aria-label="治理任务处理流程">
      <li>草稿</li><li>待执行</li><li>执行中</li><li>待复核</li><li>已完成</li>
    </ol>
    <p class="workflow-note">复核可退回执行。创建者或管理员发布、分配和取消，当前执行人记录和提交；执行人不能给自己通过复核。</p>
    <div v-if="notice" class="inline-message message-success" role="status">{{ notice }}</div>
    <div v-if="error" class="inline-message message-error" role="alert">{{ error }}</div>

    <form v-if="profile" class="surface-card draft-box" @submit.prevent="run(create)">
      <div class="card-heading"><div><p class="section-kicker">新建工单</p><h3>从风险画像建立草稿</h3></div><span class="risk-badge" :class="'risk-' + profile.risk_level.toLowerCase()">{{ profile.risk_level }}</span></div>
      <p class="profile-reference">依据画像 #{{ profile.profile_id }}，{{ profile.street_a }} / {{ profile.street_b }}，等级 {{ profile.risk_level }}。依据和评价范围在创建后冻结。</p>
      <p v-if="profile.risk_level === 'UNKNOWN'" class="inline-message message-warning">该画像数据不完整，只能创建现场调查草稿，不能发布；补齐数据后需从新画像另建任务。</p>
      <div class="task-controls">
        <label>任务标题<input v-model="draft.title" maxlength="160" required :disabled="busy" /></label>
        <label>措施类型<select v-model="draft.measure_type" :disabled="busy || profile.risk_level === 'UNKNOWN'"><option v-for="(label, value) in measures" :key="value" :value="value">{{ label }}</option></select></label>
        <label>优先级<select v-model="draft.priority" :disabled="busy"><option v-for="(label, value) in priorities" :key="value" :value="value">{{ label }}</option></select></label>
        <label>计划截止日期<input v-model="draft.due_date" type="date" :disabled="busy" /></label>
        <label>模拟生效日期<input v-model="draft.effective_on" type="date" :disabled="busy" /></label>
        <label>评价半径（米）<input v-model.number="radius" type="number" min="1" max="1000" :disabled="busy" required /></label>
      </div>
      <label>任务说明<textarea v-model="draft.description" rows="3" maxlength="10000" required :disabled="busy" /></label>
      <label>建立与评价范围理由（低、中、未知等级必填）<textarea v-model="rationale" rows="2" maxlength="2000" :required="profile.risk_level !== 'HIGH'" :disabled="busy" /></label>
      <div class="form-footer"><span class="quiet-note">建立后保存为课程模拟草稿。</span><button class="button-primary" :disabled="busy || !ready" type="submit">建立模拟草稿</button></div>
    </form>
    <p v-else class="empty-state">在风险画像中选择“建立治理草稿”，即可带入对应画像。</p>

    <section class="surface-card task-list-section" aria-label="治理任务列表">
      <div class="card-heading"><div><p class="section-kicker">任务队列</p><h3>工单列表</h3></div><span class="quiet-note">共 {{ total }} 条 · 第 {{ page }} 页</span></div>
      <div class="task-controls list-filters">
        <label>工单状态<select v-model="status" :disabled="busy" @change="page = 1; run(loadList)"><option value="">全部状态</option><option v-for="(label, value) in statuses" :key="value" :value="value">{{ label }}</option></select></label>
        <label class="check-label"><input v-model="mine" type="checkbox" :disabled="busy" @change="page = 1; run(loadList)" />我的执行待办</label>
      </div>
      <div class="table-wrap"><table class="task-table"><thead><tr><th>编号 / 标题</th><th>状态</th><th>优先级</th><th>执行人</th><th>版本</th><th>操作</th></tr></thead><tbody><tr v-for="row in items" :key="row.task_id"><td><strong>{{ row.task_code }}</strong><br />{{ row.title }}<br /><small>课程模拟 · 画像 #{{ row.profile_id }}</small></td><td><span class="state-badge" :class="'task-' + row.status.toLowerCase()">{{ statuses[row.status] }}</span></td><td><span class="priority-badge" :class="'priority-' + row.priority.toLowerCase()">{{ priorities[row.priority] }}</span></td><td>{{ row.assignee_name ?? (row.assignee_id ? '#' + row.assignee_id : '未分配') }}</td><td>{{ row.version }}</td><td><button class="button-secondary" :disabled="busy" @click="run(() => open(row.task_id))">工单详情</button></td></tr></tbody></table></div>
      <p v-if="!items.length && !busy" class="empty-state">当前筛选下没有治理任务。</p>
      <div class="task-pagination"><button class="button-secondary" :disabled="busy || page <= 1" @click="page--; run(loadList)">上一页工单</button><span>第 {{ page }} 页 / 共 {{ total }} 条</span><button class="button-secondary" :disabled="busy || page * 20 >= total" @click="page++; run(loadList)">下一页工单</button></div>
    </section>

    <section v-if="task" class="surface-card task-detail" aria-labelledby="task-detail-heading">
      <div class="card-heading task-detail-heading"><div><p class="section-kicker">工单详情 · 课程模拟</p><h3 id="task-detail-heading">{{ task.task_code }}</h3></div><div class="detail-heading-actions"><span class="state-badge" :class="'task-' + task.status.toLowerCase()">{{ statuses[task.status] }}</span><button class="button-secondary" :disabled="busy" @click="run(() => open(task!.task_id))">重新加载详情</button></div></div>
      <div class="task-meta"><span>版本 {{ task.version }}</span><span>创建人 {{ task.creator_name }} (#{{ task.created_by }})</span><span>执行人 {{ task.assignee_name ?? (task.assignee_id ? '#' + task.assignee_id : '未分配') }}</span><span class="priority-badge" :class="'priority-' + task.priority.toLowerCase()">{{ priorities[task.priority] }}优先级</span></div>
      <p v-if="task.deleted_at" class="inline-message message-warning">此草稿已逻辑删除，仅保留详情与历史。</p>
      <template v-if="canEdit">
        <div class="task-controls edit-grid"><label>草稿标题<input v-model="edit.title" maxlength="160" :disabled="busy" /></label><label>草稿措施<select v-model="edit.measure_type" :disabled="busy || task.risk_level === 'UNKNOWN'"><option v-for="(label, value) in measures" :key="value" :value="value">{{ label }}</option></select></label><label>草稿优先级<select v-model="edit.priority" :disabled="busy"><option v-for="(label, value) in priorities" :key="value" :value="value">{{ label }}</option></select></label><label>草稿截止日期<input v-model="edit.due_date" type="date" :disabled="busy" /></label><label>草稿模拟生效日期<input v-model="edit.effective_on" type="date" :disabled="busy" /></label></div>
        <label class="wide-field">草稿任务说明<textarea v-model="edit.description" rows="3" maxlength="10000" :disabled="busy" /></label>
      </template>
      <template v-else><h4>{{ task.title }}</h4><p class="preserve-text">{{ task.description }}</p><p>措施：{{ measures[task.measure_type] }}；截止 {{ task.due_date ?? '未设定' }}，模拟生效 {{ task.effective_on ?? '未设定' }}。</p></template>
      <details class="assessment-details"><summary>冻结的建立依据与评价范围（画像 #{{ task.profile_id }}）</summary><pre>{{ JSON.stringify(task.assessment_scope, null, 2) }}</pre></details>
      <section v-if="task.allowed_actions.length" class="task-action-group" aria-label="当前允许的处理动作">
        <div class="card-heading"><div><p class="section-kicker">按权限与工单状态生成</p><h4>处理动作</h4></div></div>
        <div v-if="needsAssignee" class="task-controls assignee-controls"><label>按显示名查找执行人<input v-model="search" maxlength="80" :disabled="busy" /></label><button class="button-secondary" :disabled="busy" @click="run(loadAssignees)">查找执行人</button><label>启用的管理人员<select v-model="assignee" :disabled="busy"><option value="">请选择执行人</option><option v-for="user in assignees" :key="user.user_id" :value="user.user_id">{{ user.display_name }} (#{{ user.user_id }})</option></select></label><p v-if="assigneeTotal > assignees.length" class="quiet-note">匹配 {{ assigneeTotal }} 人，当前显示前100人；请缩小查找范围。</p></div>
        <label class="wide-field">本次处理说明 / 复核意见<textarea v-model="note" rows="3" maxlength="10000" :disabled="busy" /></label>
        <p v-if="refreshRequired" class="inline-message message-warning" role="status">上次请求未完成或版本可能变化，请重新加载详情后再提交。系统不会自动覆盖其他人的修改。</p>
        <div class="task-controls action-buttons"><button v-for="action in task.allowed_actions" :key="action" :class="['button-primary', { 'button-danger': ['delete_draft', 'cancel'].includes(action) }]" :disabled="busy || refreshRequired || !note.trim() || (['publish', 'assign'].includes(action) && !assignee)" @click="run(() => perform(action))">{{ actionLabels[action] }}</button></div>
      </section>
      <p v-else class="empty-state">当前身份或状态没有可用操作，历史仍可查看。</p>
      <section class="history-section" aria-labelledby="task-history-heading">
        <div class="card-heading"><div><p class="section-kicker">只追加，不覆盖</p><h4 id="task-history-heading">处理时间线</h4></div><span class="quiet-note">{{ history.length }} 条记录</span></div>
        <ol class="task-history"><li v-for="record in history" :key="record.history_id"><div class="history-marker"></div><div class="history-content"><strong>版本 {{ record.sequence_no }} · {{ eventLabels[record.event_type] ?? record.event_type }}</strong><p>{{ record.from_status ? statuses[record.from_status] : '无' }} → {{ statuses[record.to_status] }} · 操作者 {{ record.actor_name }} (#{{ record.actor_id }}) · {{ record.created_at }}</p><p class="preserve-text">{{ record.note }}</p><details v-if="Object.keys(record.changed_fields).length"><summary>变更摘要</summary><pre>{{ JSON.stringify(record.changed_fields, null, 2) }}</pre></details></div></li></ol>
      </section>
    </section>
  </section>
</template>

<style scoped>
.workflow-panel { --panel-ink:#17324d; --panel-muted:#61758c; --panel-line:#dbe5f0; --panel-blue:#083da6; min-width:0; margin:0; padding:0; border:0; border-radius:0; background:transparent; box-shadow:none; color:var(--panel-ink); }
.page-heading,.card-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.page-heading { margin-bottom:20px; }
.page-heading h2 { color:var(--panel-ink); font-size:18px; letter-spacing:-.01em; }
.page-eyebrow,.section-kicker { margin:0 0 6px; color:var(--panel-blue); font-size:11px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.page-lead,.quiet-note { color:var(--panel-muted); font-size:13px; line-height:1.65; }
.page-lead { margin:7px 0 0; }
.surface-card { min-width:0; margin:16px 0 0; padding:20px; border:1px solid var(--panel-line); border-radius:12px; background:#fff; box-shadow:0 5px 18px rgb(29 55 89 / 5%); }
.surface-card h3,.surface-card h4 { margin:0; color:var(--panel-ink); }
.card-heading { margin-bottom:15px; }
.card-heading .section-kicker { margin-bottom:3px; }
.quiet-note { margin:0; }
.simulated { display:flex; align-items:flex-start; gap:12px; margin:0; padding:14px 16px; border:1px solid #f0dfb8; border-radius:10px; background:#fff9eb; color:#73551c; font-size:13px; line-height:1.65; }
.simulated strong { flex:none; color:#69470d; }
.workflow-steps { display:flex; align-items:center; gap:0; overflow-x:auto; margin:13px 0 0; padding:0; list-style:none; }
.workflow-steps li { position:relative; flex:1 0 100px; padding:9px 12px; border:1px solid #dbe5f0; background:#fff; color:var(--panel-muted); text-align:center; font-size:11px; font-weight:700; }
.workflow-steps li:first-child { border-radius:8px 0 0 8px; }.workflow-steps li:last-child { border-radius:0 8px 8px 0; }
.workflow-steps li + li { border-left:0; }.workflow-steps li:not(:last-child)::after { position:absolute; z-index:1; top:50%; right:-5px; width:8px; height:8px; border-top:1px solid #dbe5f0; border-right:1px solid #dbe5f0; background:#fff; content:""; transform:translateY(-50%) rotate(45deg); }
.workflow-note { margin:8px 0 16px; color:var(--panel-muted); font-size:12px; line-height:1.65; }
.inline-message { margin:12px 0; padding:12px 14px; border:1px solid transparent; border-radius:9px; font-size:13px; line-height:1.6; }
.message-success { border-color:#cae8db; background:#eff9f4; color:#176b51; }.message-error { border-color:#f1d0d0; background:#fff4f3; color:#9f3333; }.message-warning { border-color:#f1ddb9; background:#fff8eb; color:#805711; }
.draft-box { border-color:#cbd8f1; }
.profile-reference { margin:0 0 14px; padding:11px 13px; border-radius:8px; background:#f5f7fb; color:var(--panel-muted); font-size:13px; line-height:1.6; }
.risk-badge,.state-badge,.priority-badge { display:inline-flex; align-items:center; min-height:26px; padding:5px 9px; border-radius:999px; font-size:11px; font-weight:800; white-space:nowrap; }
.risk-high,.task-in_progress,.task-pending_review { background:#fff0ee; color:#a4302e; }.risk-medium,.priority-high,.priority-urgent { background:#fff5db; color:#825400; }.risk-low,.task-completed { background:#e8f5ee; color:#146c48; }.risk-unknown,.task-cancelled { background:#edf0f5; color:#58677b; }
.task-draft,.task-open { background:#eaf0ff; color:#17499c; }.priority-low { background:#edf2f7; color:#53657a; }.priority-medium { background:#eaf0ff; color:#17499c; }
label { display:flex; flex-direction:column; gap:7px; max-width:100%; color:var(--panel-muted); font-size:12px; font-weight:650; }
input,select,textarea { width:100%; min-width:0; max-width:100%; min-height:42px; padding:9px 11px; border:1px solid #cbd7e7; border-radius:8px; box-sizing:border-box; background:#fff; color:var(--panel-ink); font:inherit; }
textarea { resize:vertical; }
input:focus,select:focus,textarea:focus { border-color:var(--panel-blue); outline:3px solid rgb(8 61 166 / 12%); }
button { min-height:40px; padding:9px 14px; border:1px solid transparent; border-radius:8px; background:var(--panel-blue); color:#fff; font:inherit; font-size:13px; font-weight:700; cursor:pointer; transition:background .15s ease,transform .15s ease; }
button:hover:not(:disabled) { background:#062f83; transform:translateY(-1px); }.button-secondary { border-color:#d4deec; background:#f4f7fc; color:var(--panel-blue); }.button-secondary:hover:not(:disabled) { background:#eaf0ff; }.button-danger { border-color:#f0cccc; background:#fff2f1; color:#a12e2b; }.button-danger:hover:not(:disabled) { background:#fde5e3; }
button:disabled { opacity:.52; cursor:not-allowed; }
.task-controls { display:flex; flex-wrap:wrap; gap:12px; align-items:end; margin:16px 0; }
.task-controls label { max-width:100%; flex:1 1 170px; }
.draft-box > label,.task-detail > .wide-field { margin:14px 0; }
.form-footer { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:14px; }
.task-list-section { margin-top:0; }
.list-filters { margin:0 0 12px; padding:12px; border-radius:9px; background:#f6f8fc; }
.list-filters .check-label { display:flex; flex:0 1 auto; flex-direction:row; align-items:center; gap:8px; padding:8px 10px; }
.check-label input { width:18px; min-height:18px; height:18px; padding:0; accent-color:#083da6; }
.table-wrap { overflow-x:auto; border:1px solid #e4eaf2; border-radius:9px; }
table { width:100%; border-collapse:collapse; font-size:13px; }.task-table { min-width:700px; }
th { white-space:nowrap; color:var(--panel-muted); background:#f6f8fc; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
th,td { padding:11px 10px; border-bottom:1px solid #e9eef5; text-align:left; vertical-align:top; }.task-table tbody tr:last-child td { border-bottom:0; }.task-table td:first-child strong { color:var(--panel-blue); }.task-table small { color:var(--panel-muted); }
.task-pagination,.detail-heading-actions,.task-meta { display:flex; align-items:center; flex-wrap:wrap; gap:10px; color:var(--panel-muted); font-size:12px; }
.task-pagination { justify-content:center; margin-top:15px; }.task-pagination button { min-height:36px; }
.task-detail { border-color:#cbd8f1; }.detail-heading-actions { justify-content:flex-end; }.task-meta { padding:11px 12px; border-radius:8px; background:#f6f8fc; }
.edit-grid { align-items:end; }.wide-field { display:flex; flex-direction:column; gap:7px; max-width:100%; color:var(--panel-muted); font-size:12px; font-weight:650; }
.assessment-details { margin:14px 0; padding:12px 14px; border:1px solid #e4eaf2; border-radius:9px; background:#fafbfd; }.assessment-details summary { color:var(--panel-blue); cursor:pointer; font-size:12px; font-weight:700; }
.task-action-group,.history-section { margin-top:20px; padding-top:18px; border-top:1px solid var(--panel-line); }.task-action-group { padding:16px; border:1px solid #e1e8f2; border-radius:10px; background:#f9fbff; }
.assignee-controls .quiet-note { flex-basis:100%; }.action-buttons { align-items:center; }.action-buttons button { min-height:38px; }
.task-history { display:grid; gap:0; margin:0; padding:0; list-style:none; }.task-history li { position:relative; display:grid; grid-template-columns:16px minmax(0,1fr); gap:12px; padding:0 0 18px; }.task-history li:not(:last-child)::after { position:absolute; top:16px; bottom:-1px; left:6px; width:1px; background:#dbe5f0; content:""; }.history-marker { z-index:1; width:13px; height:13px; margin-top:3px; border:3px solid #dce7fb; border-radius:50%; background:#083da6; }.history-content { min-width:0; }.history-content strong { color:var(--panel-ink); font-size:13px; }.history-content p { margin:5px 0; color:var(--panel-muted); font-size:12px; line-height:1.6; }.preserve-text { white-space:pre-wrap; overflow-wrap:anywhere; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; }.empty-state { padding:15px; border-radius:9px; background:#f6f8fc; color:var(--panel-muted); }
@media(max-width:700px) {
  .workflow-panel { padding:0; border-radius:0; }
  .page-heading { align-items:flex-start; flex-direction:column; }.page-heading > button { width:100%; }
  .card-heading { align-items:flex-start; flex-direction:column; }
  .form-footer { align-items:stretch; flex-direction:column; }.form-footer button { width:100%; }
  .task-controls > button { width:100%; }.task-meta { align-items:flex-start; flex-direction:column; }
  .detail-heading-actions { width:100%; justify-content:space-between; }.detail-heading-actions button { flex:1; }
  .list-filters label { flex-basis:100%; }.workflow-steps li { flex-basis:88px; padding-inline:8px; }
}
</style>
