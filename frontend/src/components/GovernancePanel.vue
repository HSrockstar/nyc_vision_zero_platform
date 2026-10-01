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
})
onMounted(() => run(async () => { await loadList(); await loadAssignees() }))
</script>

<template>
  <section id="governance" aria-labelledby="governance-heading">
    <div class="section-title"><h2 id="governance-heading">治理任务</h2><button :disabled="busy" @click="run(refresh)">刷新任务</button></div>
    <p class="simulated">课程模拟治理任务：措施和生效日期由本系统登记，不表示纽约政府实际治理项目或工程授权。</p>
    <p class="detail">草稿 → 待执行 → 执行中 → 待复核 → 已完成；复核可退回执行。创建者或管理员发布、分配和取消，当前执行人记录和提交；执行人不能给自己通过复核。</p>
    <p v-if="notice" role="status">{{ notice }}</p><p v-if="error" role="alert" class="error">{{ error }}</p>
    <form v-if="profile" class="draft-box" @submit.prevent="run(create)">
      <h3>从风险画像建立草稿</h3>
      <p>依据画像 #{{ profile.profile_id }}，{{ profile.street_a }} / {{ profile.street_b }}，等级 {{ profile.risk_level }}。依据和评价范围在创建后冻结。</p>
      <p v-if="profile.risk_level === 'UNKNOWN'" class="detail">该画像数据不完整，只能创建现场调查草稿，不能发布；补齐数据后需从新画像另建任务。</p>
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
      <button :disabled="busy || !ready" type="submit">建立课程模拟草稿</button>
    </form>
    <p v-else class="detail">在上方风险画像中选择“建立治理草稿”，即可从该画像建立任务。</p>
    <div class="task-controls">
      <label>工单状态<select v-model="status" :disabled="busy" @change="page = 1; run(loadList)"><option value="">全部状态</option><option v-for="(label, value) in statuses" :key="value" :value="value">{{ label }}</option></select></label>
      <label class="check-label"><input v-model="mine" type="checkbox" :disabled="busy" @change="page = 1; run(loadList)" />我的执行待办</label>
    </div>
    <div class="table-wrap"><table class="task-table"><thead><tr><th>编号 / 标题</th><th>状态</th><th>优先级</th><th>执行人</th><th>版本</th><th>操作</th></tr></thead><tbody><tr v-for="row in items" :key="row.task_id"><td>{{ row.task_code }}<br />{{ row.title }}<br /><small>课程模拟 · 画像 #{{ row.profile_id }}</small></td><td>{{ statuses[row.status] }}</td><td>{{ priorities[row.priority] }}</td><td>{{ row.assignee_name ?? (row.assignee_id ? '#' + row.assignee_id : '未分配') }}</td><td>{{ row.version }}</td><td><button :disabled="busy" @click="run(() => open(row.task_id))">工单详情</button></td></tr></tbody></table></div>
    <p v-if="!items.length && !busy" class="empty-state">当前筛选下没有治理任务。</p>
    <div class="task-controls"><button :disabled="busy || page <= 1" @click="page--; run(loadList)">上一页工单</button><span>第 {{ page }} 页 / 共 {{ total }} 条</span><button :disabled="busy || page * 20 >= total" @click="page++; run(loadList)">下一页工单</button></div>
    <div v-if="task" class="task-detail">
      <div class="section-title"><h3>{{ task.task_code }} · {{ statuses[task.status] }}</h3><button :disabled="busy" @click="run(() => open(task!.task_id))">重新加载详情</button></div>
      <p>课程模拟 · 版本 {{ task.version }} · 创建人 {{ task.creator_name }} (#{{ task.created_by }}) · 执行人 {{ task.assignee_name ?? (task.assignee_id ? '#' + task.assignee_id : '未分配') }}</p>
      <p v-if="task.deleted_at">此草稿已逻辑删除，仅保留详情与历史。</p>
      <template v-if="canEdit">
        <div class="task-controls"><label>草稿标题<input v-model="edit.title" maxlength="160" :disabled="busy" /></label><label>草稿措施<select v-model="edit.measure_type" :disabled="busy || task.risk_level === 'UNKNOWN'"><option v-for="(label, value) in measures" :key="value" :value="value">{{ label }}</option></select></label><label>草稿优先级<select v-model="edit.priority" :disabled="busy"><option v-for="(label, value) in priorities" :key="value" :value="value">{{ label }}</option></select></label><label>草稿截止日期<input v-model="edit.due_date" type="date" :disabled="busy" /></label><label>草稿模拟生效日期<input v-model="edit.effective_on" type="date" :disabled="busy" /></label></div>
        <label>草稿任务说明<textarea v-model="edit.description" rows="3" maxlength="10000" :disabled="busy" /></label>
      </template>
      <template v-else><h4>{{ task.title }}</h4><p class="preserve-text">{{ task.description }}</p><p>措施：{{ measures[task.measure_type] }}；截止 {{ task.due_date ?? '未设定' }}，模拟生效 {{ task.effective_on ?? '未设定' }}。</p></template>
      <details><summary>冻结的建立依据与评价范围（画像 #{{ task.profile_id }}）</summary><pre>{{ JSON.stringify(task.assessment_scope, null, 2) }}</pre></details>
      <template v-if="task.allowed_actions.length">
        <div v-if="needsAssignee" class="task-controls"><label>按显示名查找执行人<input v-model="search" maxlength="80" :disabled="busy" /></label><button :disabled="busy" @click="run(loadAssignees)">查找执行人</button><label>启用的管理人员<select v-model="assignee" :disabled="busy"><option value="">请选择执行人</option><option v-for="user in assignees" :key="user.user_id" :value="user.user_id">{{ user.display_name }} (#{{ user.user_id }})</option></select></label><p v-if="assigneeTotal > assignees.length" class="detail">匹配 {{ assigneeTotal }} 人，当前显示前100人；请缩小查找范围。</p></div>
        <label>本次处理说明 / 复核意见<textarea v-model="note" rows="3" maxlength="10000" :disabled="busy" /></label>
        <p v-if="refreshRequired" role="status">上次请求未完成或版本可能变化，请重新加载详情后再提交。系统不会自动覆盖其他人的修改。</p>
        <div class="task-controls"><button v-for="action in task.allowed_actions" :key="action" :disabled="busy || refreshRequired || !note.trim() || (['publish', 'assign'].includes(action) && !assignee)" @click="run(() => perform(action))">{{ actionLabels[action] }}</button></div>
      </template>
      <p v-else class="detail">当前身份或状态没有可用操作，历史仍可查看。</p>
      <h4>只追加处理历史</h4>
      <ol class="task-history"><li v-for="record in history" :key="record.history_id"><strong>版本 {{ record.sequence_no }} · {{ eventLabels[record.event_type] ?? record.event_type }}</strong><p>{{ record.from_status ? statuses[record.from_status] : '无' }} → {{ statuses[record.to_status] }} · 操作者 {{ record.actor_name }} (#{{ record.actor_id }}) · {{ record.created_at }}</p><p class="preserve-text">{{ record.note }}</p><details v-if="Object.keys(record.changed_fields).length"><summary>变更摘要</summary><pre>{{ JSON.stringify(record.changed_fields, null, 2) }}</pre></details></li></ol>
    </div>
  </section>
</template>

<style scoped>
.simulated { padding:12px; background:#fff6df; color:#6b4a13; border-left:4px solid #d99e34; line-height:1.7; }
.draft-box,.task-detail { padding:18px; border:1px solid #d7e1e7; border-radius:8px; margin:20px 0; }
.draft-box > label,.task-detail > label { margin:14px 0; }
.task-controls { display:flex; flex-wrap:wrap; gap:12px; align-items:end; margin:16px 0; }
.task-controls label { max-width:100%; flex:1 1 170px; }
.task-controls .check-label { display:flex; align-items:center; flex:0 1 auto; padding:10px 0; }
.task-table { min-width:650px; } th { white-space:nowrap; }
.task-history { padding-left:24px; } .task-history li { border-bottom:1px solid #d7e1e7; padding:12px 0; }
.preserve-text { white-space:pre-wrap; overflow-wrap:anywhere; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; }
@media(max-width:600px) { .draft-box,.task-detail { padding:12px; } .section-title { flex-wrap:wrap; } }
</style>
