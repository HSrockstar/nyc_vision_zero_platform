<script setup lang="ts">
import { computed, onMounted, reactive, ref, shallowRef } from 'vue'
import { sessionUser } from '../api/auth'
import {
  getImport, listImportIssues, listImports, publishImport, retryImport, submitImport, updateDataIssue,
  type DataIssue, type ImportBatch, type ImportDetail,
} from '../api/m2'

const pageSize = 20
const uploadLimit = 256 * 1024 * 1024
const isAdmin = computed(() => sessionUser.value?.role === 'ADMIN')
const page = ref(1)
const total = ref<number | null>(null)
const batches = ref<ImportBatch[]>([])
const listBusy = ref(false)
const listError = ref('')
const detailBusy = ref(false)
const detailError = ref('')
const detail = ref<ImportDetail | null>(null)
const selectedBatchId = ref('')
const issues = ref<DataIssue[]>([])
const issuePage = ref(1)
const issueTotal = ref<number | null>(null)
const issueBusy = ref(false)
const issueError = ref('')
const issueNotes = reactive<Record<string, string>>({})
const issueActionBusy = ref('')
const actionBusy = ref('')
const actionError = ref('')
const notice = ref('')

const requestedStart = ref('')
const requestedEnd = ref('')
const headerMode = ref<'api' | 'display' | 'auto'>('auto')
const crashesFile = shallowRef<File | null>(null)
const personsFile = shallowRef<File | null>(null)
const vehiclesFile = shallowRef<File | null>(null)
const uploadBusy = ref(false)
const uploadError = ref('')
const uploadNotice = ref('')
const uploadRequestId = ref('')
const uploadForm = ref<HTMLFormElement | null>(null)
const uploadSize = computed(() => (crashesFile.value?.size ?? 0) + (personsFile.value?.size ?? 0) + (vehiclesFile.value?.size ?? 0))
const hasNextBatchPage = computed(() => total.value === null ? batches.value.length === pageSize : page.value * pageSize < total.value)
const hasNextIssuePage = computed(() => issueTotal.value === null ? issues.value.length === pageSize : issuePage.value * pageSize < issueTotal.value)

const publishOperation = ref<{ batchId: string; requestId: string } | null>(null)
const retryOperation = ref<{ batchId: string; requestId: string } | null>(null)

function display(value: string | number | null | undefined) {
  return value === null || value === undefined || value === '' ? '缺失' : String(value)
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    UPLOADED: '已上传，等待校验', VALIDATING: '校验中', READY: '可发布',
    PUBLISHING: '等待或正在发布', SUCCEEDED: '已发布', FAILED: '失败', CANCELLED: '已取消',
  }
  return labels[status] ?? status
}

const batchFlow = [
  { key: 'UPLOADED', label: '已接收' },
  { key: 'VALIDATING', label: '校验中' },
  { key: 'READY', label: '可发布' },
  { key: 'PUBLISHING', label: '发布中' },
  { key: 'SUCCEEDED', label: '已发布' },
] as const

function flowStageIndex(status: string) {
  return batchFlow.findIndex((stage) => stage.key === status)
}

function severityLabel(value: string) {
  const labels: Record<string, string> = { INFO: '提示', WARNING: '警告', ERROR: '错误' }
  return labels[value] ?? value
}

function byteLabel(value: number) {
  if (value >= 1024 * 1024) return (value / (1024 * 1024)).toFixed(1) + ' MiB'
  if (value >= 1024) return (value / 1024).toFixed(1) + ' KiB'
  return value + ' B'
}

function sourceCountSummary(sourceCounts: Record<string, Record<string, number>> | undefined) {
  if (!sourceCounts) return ''
  const names: Record<string, string> = { accepted: '有效', rejected: '隔离', skipped: '跳过' }
  return Object.entries(sourceCounts).map(([kind, counts]) => kind + '：' + Object.entries(counts).map(([status, count]) => (names[status] ?? status) + count).join('，')).join(' · ')
}

function coverageSummary(value: unknown) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return '包含 ' + value.length + ' 项覆盖信息'
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).slice(0, 6)
    return entries.map(([key, item]) => {
      const summary = item === null || item === undefined ? '缺失' :
        typeof item === 'object' ? '含细项' : String(item)
      return key + '：' + summary
    }).join(' · ')
  }
  return ''
}
function resetUploadOperation() {
  uploadRequestId.value = ''
}

function setUploadFile(kind: 'crashes' | 'persons' | 'vehicles', event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0] ?? null
  if (kind === 'crashes') crashesFile.value = file
  if (kind === 'persons') personsFile.value = file
  if (kind === 'vehicles') vehiclesFile.value = file
  resetUploadOperation()
}

async function loadBatches() {
  listBusy.value = true
  listError.value = ''
  try {
    const result = await listImports(page.value, pageSize)
    batches.value = result.items
    total.value = result.total
  } catch (error) {
    listError.value = error instanceof Error ? error.message : '批次列表暂不可用。'
  } finally {
    listBusy.value = false
  }
}

async function loadIssues(id: string, requestedPage = issuePage.value) {
  if (!isAdmin.value) return
  issueBusy.value = true
  issueError.value = ''
  try {
    const result = await listImportIssues(id, requestedPage, pageSize)
    if (selectedBatchId.value === id) {
      issues.value = result.items
      issueTotal.value = result.total
      issuePage.value = requestedPage
    }
  } catch (error) {
    if (selectedBatchId.value === id) issueError.value = error instanceof Error ? error.message : '问题列表暂不可用。'
  } finally {
    if (selectedBatchId.value === id) issueBusy.value = false
  }
}

async function loadDetail(id: string) {
  detailBusy.value = true
  detailError.value = ''
  try {
    const result = await getImport(id)
    if (selectedBatchId.value === id) {
      detail.value = result
      if (result.status !== 'READY' && publishOperation.value?.batchId === id) publishOperation.value = null
      if (result.status !== 'FAILED' && retryOperation.value?.batchId === id) retryOperation.value = null
    }
  } catch (error) {
    if (selectedBatchId.value === id) detailError.value = error instanceof Error ? error.message : '批次详情暂不可用。'
  } finally {
    if (selectedBatchId.value === id) detailBusy.value = false
  }
}

async function selectBatch(id: string) {
  selectedBatchId.value = id
  detail.value = null
  issues.value = []
  issueTotal.value = null
  issuePage.value = 1
  issueError.value = ''
  actionError.value = ''
  notice.value = ''
  await Promise.all([loadDetail(id), loadIssues(id, 1)])
}

async function refresh() {
  await loadBatches()
  if (selectedBatchId.value) {
    await Promise.all([loadDetail(selectedBatchId.value), loadIssues(selectedBatchId.value)])
  }
}

function resetUploadFields() {
  requestedStart.value = ''
  requestedEnd.value = ''
  headerMode.value = 'auto'
  crashesFile.value = null
  personsFile.value = null
  vehiclesFile.value = null
  uploadForm.value?.reset()
}

async function uploadBatch() {
  uploadError.value = ''
  uploadNotice.value = ''
  if (!crashesFile.value || !personsFile.value || !vehiclesFile.value) {
    uploadError.value = '请分别选择事故、人员和车辆 CSV 文件。'
    return
  }
  if (!requestedStart.value || !requestedEnd.value || requestedEnd.value <= requestedStart.value) {
    uploadError.value = '请填写有效日期范围，并确保结束日期晚于开始日期。'
    return
  }
  const selectedFiles = [crashesFile.value, personsFile.value, vehiclesFile.value]
  if (selectedFiles.some((file) => !file.name.toLowerCase().endsWith('.csv'))) {
    uploadError.value = '仅接受 CSV 文件。'
    return
  }
  if (uploadSize.value > uploadLimit) {
    uploadError.value = '三个文件合计超过 256 MiB，请缩小文件后重新选择。'
    return
  }
  if (!uploadRequestId.value) uploadRequestId.value = crypto.randomUUID()
  const form = new FormData()
  form.set('request_id', uploadRequestId.value)
  form.set('requested_start', requestedStart.value)
  form.set('requested_end', requestedEnd.value)
  form.set('header_mode', headerMode.value)
  form.set('crashes', crashesFile.value)
  form.set('persons', personsFile.value)
  form.set('vehicles', vehiclesFile.value)
  uploadBusy.value = true
  try {
    const created = await submitImport(form)
    uploadRequestId.value = ''
    resetUploadFields()
    uploadNotice.value = '批次已接收，后台将继续校验；发布需要管理员另行确认。'
    page.value = 1
    await loadBatches()
    await selectBatch(created.batch_id)
  } catch (error) {
    uploadError.value = error instanceof Error ? error.message : '上传未完成。相同文件和范围重试时会复用操作编号。'
  } finally {
    uploadBusy.value = false
  }
}

function operationId(operation: typeof publishOperation, batchId: string) {
  if (!operation.value || operation.value.batchId !== batchId) {
    operation.value = { batchId, requestId: crypto.randomUUID() }
  }
  return operation.value.requestId
}

async function publishSelected() {
  const batchId = selectedBatchId.value
  if (!batchId || !isAdmin.value) return
  if (!window.confirm('发布将在单一事务中完成，新增或更新数据时会增加版本。确认发布此批次？')) return
  actionError.value = ''
  notice.value = ''
  actionBusy.value = 'publish'
  const requestId = operationId(publishOperation, batchId)
  try {
    await publishImport(batchId, requestId)
    notice.value = '发布请求已接收；重复点击会复用同一操作编号。'
    await Promise.all([loadDetail(batchId), loadBatches()])
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '发布请求暂未完成；重试会复用同一操作编号。'
  } finally {
    actionBusy.value = ''
  }
}

async function retrySelected() {
  const batchId = selectedBatchId.value
  if (!batchId || !isAdmin.value) return
  actionError.value = ''
  notice.value = ''
  actionBusy.value = 'retry'
  const requestId = operationId(retryOperation, batchId)
  try {
    await retryImport(batchId, requestId)
    notice.value = '重新校验请求已接收；系统不会自动发布。'
    await Promise.all([loadDetail(batchId), loadBatches()])
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '重试请求暂未完成；再次提交会复用同一操作编号。'
  } finally {
    actionBusy.value = ''
  }
}

async function updateIssue(issue: DataIssue, status: 'ACKNOWLEDGED' | 'RESOLVED') {
  const note = (issueNotes[issue.issue_id] ?? '').trim()
  if (!note) {
    issueError.value = '请填写处理说明后再保存。'
    return
  }
  issueActionBusy.value = issue.issue_id
  issueError.value = ''
  try {
    await updateDataIssue(issue.issue_id, status, note)
    issueNotes[issue.issue_id] = ''
    await loadIssues(selectedBatchId.value, issuePage.value)
    notice.value = '问题处理状态已更新；不会改写来源事实或隔离状态。'
  } catch (error) {
    issueError.value = error instanceof Error ? error.message : '问题状态暂未更新。'
  } finally {
    issueActionBusy.value = ''
  }
}

function changeIssuePage(nextPage: number) {
  if (nextPage < 1 || !selectedBatchId.value) return
  if (issueTotal.value !== null && nextPage > Math.ceil(issueTotal.value / pageSize)) return
  void loadIssues(selectedBatchId.value, nextPage)
}

function changeBatchPage(nextPage: number) {
  if (nextPage < 1) return
  page.value = nextPage
  void loadBatches()
}

onMounted(() => { void loadBatches() })
</script>

<template>
  <section aria-labelledby="imports-heading" class="workflow-panel import-page">
    <header class="page-heading">
      <div><p class="page-eyebrow">数据质量 · 导入批次</p><h2 id="imports-heading">批次工作区</h2><p class="page-lead">查看批次处理状态、数据质量和版本发布记录。</p></div>
      <button class="button-secondary" :disabled="listBusy || detailBusy" @click="refresh">{{ listBusy ? '刷新中…' : '手动刷新' }}</button>
    </header>
    <p class="refresh-note">页面不会自动轮询；可手动刷新批次和所选详情。</p>

    <section v-if="isAdmin" class="surface-card upload-card" aria-labelledby="upload-heading">
      <div class="card-heading"><div><p class="section-kicker">管理员操作</p><h3 id="upload-heading">导入新批次</h3></div><span class="admin-badge">ADMIN</span></div>
      <p class="quiet-note">上传文件仅用于后台校验。结束日期为排他边界；WARNING 可隔离后继续，ERROR 冲突会阻断发布。三个 CSV 合计不超过 256 MiB。</p>
      <form ref="uploadForm" class="upload-form" @submit.prevent="uploadBatch">
        <label>开始日期（包含）<input v-model="requestedStart" type="date" required @input="resetUploadOperation" /></label>
        <label>结束日期（不包含）<input v-model="requestedEnd" type="date" required @input="resetUploadOperation" /></label>
        <label>表头模式<select v-model="headerMode" @change="resetUploadOperation">
          <option value="auto">自动识别</option><option value="api">API 字段名</option><option value="display">展示字段名</option>
        </select></label>
        <label>事故 CSV<input type="file" accept=".csv,text/csv" required @change="setUploadFile('crashes', $event)" /></label>
        <label>人员 CSV<input type="file" accept=".csv,text/csv" required @change="setUploadFile('persons', $event)" /></label>
        <label>车辆 CSV<input type="file" accept=".csv,text/csv" required @change="setUploadFile('vehicles', $event)" /></label>
        <div class="filter-actions">
          <button class="button-primary" :disabled="uploadBusy">{{ uploadBusy ? '上传中…' : '提交后台校验' }}</button>
          <span class="quiet-note">当前合计 {{ byteLabel(uploadSize) }}。</span>
        </div>
      </form>
      <p class="quiet-note">网络中断时，保持文件和日期不变后重新提交会复用同一 request UUID；更换文件、范围或表头模式会开始新操作。</p>
      <p v-if="uploadError" class="inline-message message-error" role="alert">{{ uploadError }}</p>
      <p v-if="uploadNotice" class="inline-message message-success" role="status">{{ uploadNotice }}</p>
    </section>

    <p v-if="listError" class="inline-message message-error" role="alert">{{ listError }}</p>
    <p v-if="listBusy && !batches.length" class="loading-state" role="status">正在加载导入批次…</p>
    <p v-else-if="!batches.length && !listBusy && !listError" class="empty-state">当前没有导入批次。</p>
    <div v-if="batches.length" class="batch-list">
      <article v-for="batch in batches" :key="batch.batch_id" class="batch-card">
        <div class="batch-card-heading">
          <div><p class="section-kicker">导入批次</p><h3>#{{ batch.batch_id }}</h3><p class="quiet-note">{{ display(batch.requested_start) }} 至 {{ display(batch.requested_end) }}（结束日期不包含）</p></div>
          <div class="batch-actions">
            <span class="state-badge" :class="'batch-state-' + batch.status.toLowerCase()">{{ statusLabel(batch.status) }}</span>
            <button class="button-secondary" @click="selectBatch(batch.batch_id)">查看批次</button>
          </div>
        </div>
        <ol v-if="flowStageIndex(batch.status) >= 0" class="batch-flow" :aria-label="'批次进度：' + statusLabel(batch.status)">
          <li v-for="(stage, index) in batchFlow" :key="stage.key" :class="{ 'is-complete': index < flowStageIndex(batch.status), 'is-current': index === flowStageIndex(batch.status) }" :aria-current="index === flowStageIndex(batch.status) ? 'step' : undefined"><span class="flow-dot"></span><span>{{ stage.label }}</span></li>
        </ol>
        <p v-else class="terminal-state">批次结果：<span class="state-badge" :class="'batch-state-' + batch.status.toLowerCase()">{{ statusLabel(batch.status) }}</span></p>
        <p class="batch-meta">创建：{{ display(batch.created_at) }} <span>清洗版本：{{ display(batch.cleaning_version) }}</span> <span>数据版本：{{ display(batch.published_revision) }}</span></p>
        <div class="batch-counts">
          <div><span>读取</span><strong>{{ display(batch.rows_read) }}</strong></div><div><span>接受</span><strong>{{ display(batch.rows_accepted) }}</strong></div>
          <div><span>拒绝</span><strong>{{ display(batch.rows_rejected) }}</strong></div><div><span>跳过</span><strong>{{ display(batch.rows_skipped) }}</strong></div>
        </div>
      </article>
    </div>
    <div v-if="batches.length || page > 1" class="pagination">
      <button class="button-secondary" :disabled="page <= 1 || listBusy" @click="changeBatchPage(page - 1)">上一页</button>
      <span>第 {{ page }} 页{{ total === null ? '' : '，共 ' + total + ' 批' }}</span>
      <button class="button-secondary" :disabled="!hasNextBatchPage || listBusy" @click="changeBatchPage(page + 1)">下一页</button>
    </div>

    <section v-if="selectedBatchId" class="surface-card batch-detail" aria-labelledby="batch-detail-heading">
      <div class="card-heading">
        <div><p class="section-kicker">完整记录与问题处理</p><h3 id="batch-detail-heading">批次详情 · {{ selectedBatchId }}</h3></div>
        <button class="button-secondary" @click="selectedBatchId = ''; detail = null; issues = []">收起详情</button>
      </div>
      <p v-if="detailBusy" class="loading-state" role="status">正在加载批次详情…</p>
      <p v-if="detailError" class="inline-message message-error" role="alert">{{ detailError }}</p>
      <template v-if="detail">
        <div class="detail-status-line"><span class="state-badge" :class="'batch-state-' + detail.status.toLowerCase()">{{ statusLabel(detail.status) }}</span><span class="quiet-note">请求日期：{{ display(detail.requested_start) }} 至 {{ display(detail.requested_end) }}（结束日期不包含）</span></div>
        <p v-if="detail.error_summary" class="inline-message message-error">{{ detail.error_summary }}</p>
        <div class="batch-counts">
          <div><span>读取</span><strong>{{ display(detail.rows_read) }}</strong></div><div><span>接受</span><strong>{{ display(detail.rows_accepted) }}</strong></div>
          <div><span>拒绝</span><strong>{{ display(detail.rows_rejected) }}</strong></div><div><span>跳过</span><strong>{{ display(detail.rows_skipped) }}</strong></div>
        </div>

        <template v-if="isAdmin && detail.input_manifest">
          <h4 class="subsection-title">来源文件摘要</h4>
          <div class="table-wrap"><table>
            <thead><tr><th>数据类型</th><th>数据集</th><th>表头模式</th><th>记录数</th><th>文件大小</th><th>字段摘要</th></tr></thead>
            <tbody><tr v-for="file in detail.input_manifest.files" :key="file.source_kind">
              <td>{{ file.source_kind }}</td><td>{{ display(file.dataset_id) }}</td><td>{{ display(file.header_mode) }}</td>
              <td>{{ display(file.row_count) }}</td><td>{{ byteLabel(file.bytes) }}</td><td><details v-if="file.headers.length"><summary>查看 {{ file.headers.length }} 个字段</summary><p>{{ file.headers.join('、') }}</p></details><span v-else>缺失</span></td>
            </tr></tbody>
          </table></div>
          <template v-if="detail.input_manifest.validation">
            <h4>校验计划</h4>
            <p v-if="detail.input_manifest.validation.planned" class="detail">
              新增 {{ detail.input_manifest.validation.planned.inserted }} · 更新 {{ detail.input_manifest.validation.planned.updated }} · 未变化 {{ detail.input_manifest.validation.planned.unchanged }}
            </p>
            <p v-if="detail.input_manifest.validation.blocking_issue_count !== undefined" class="detail">
              阻断问题：{{ detail.input_manifest.validation.blocking_issue_count }}
            </p>
            <p v-if="sourceCountSummary(detail.input_manifest.validation.source_counts)" class="detail">
              来源记录数：{{ sourceCountSummary(detail.input_manifest.validation.source_counts) }}
            </p>
            <p v-if="coverageSummary(detail.input_manifest.validation.coverage)" class="detail">
              覆盖概况：{{ coverageSummary(detail.input_manifest.validation.coverage) }}
            </p>
          </template>
          <template v-if="detail.input_manifest.publication">
            <h4>发布结果</h4>
            <p class="detail">
              新增 {{ detail.input_manifest.publication.inserted }} · 更新 {{ detail.input_manifest.publication.updated }} · 未变化 {{ detail.input_manifest.publication.unchanged }} · 版本 {{ display(detail.input_manifest.publication.revision) }}
            </p>
          </template>
        </template>
        <p v-else-if="!isAdmin" class="read-only-note">当前角色仅查看批次摘要；发布和质量问题处理由管理员执行。</p>
        <p v-else class="quiet-note">该批次没有可显示的文件清单。</p>

        <p v-if="isAdmin && detail.status === 'READY'" class="publish-guidance">
          WARNING 问题可隔离后继续；ERROR 冲突会阻断发布。确认后，数据变更在单一事务中提交并生成新版本。
        </p>
        <div v-if="isAdmin && detail.status === 'READY'" class="action-row">
          <button class="button-primary" :disabled="actionBusy !== ''" @click="publishSelected">{{ actionBusy === 'publish' ? '提交中…' : '确认发布此批次' }}</button>
        </div>
        <div v-if="isAdmin && detail.status === 'FAILED'" class="action-row">
          <button class="button-primary" :disabled="actionBusy !== ''" @click="retrySelected">{{ actionBusy === 'retry' ? '提交中…' : '重新校验' }}</button>
          <span class="quiet-note">重新校验不会自动发布。</span>
        </div>
        <p v-if="actionError" class="inline-message message-error" role="alert">{{ actionError }}</p>
        <p v-if="notice" class="inline-message message-success" role="status">{{ notice }}</p>

        <template v-if="isAdmin">
          <div class="card-heading issue-heading">
            <div><p class="section-kicker">管理员处理</p><h4>质量问题</h4></div>
            <span class="quiet-note">{{ issueTotal === null ? '' : '共 ' + issueTotal + ' 条' }}</span>
          </div>
          <p v-if="issueBusy" class="loading-state" role="status">正在加载问题…</p>
          <p v-if="issueError" class="inline-message message-error" role="alert">{{ issueError }}</p>
          <p v-else-if="!issues.length && !issueBusy" class="empty-state">该批次没有待显示的问题。</p>
          <div v-if="issues.length" class="issue-list">
            <article v-for="issue in issues" :key="issue.issue_id" class="issue-card">
                <div class="issue-heading-row">
                  <strong>{{ issue.issue_code }}</strong>
                <span class="status-chip" :class="'severity-' + issue.severity.toLowerCase()">{{ severityLabel(issue.severity) }}</span>
              </div>
              <p>{{ issue.description }}</p>
                <p class="issue-meta">字段：{{ display(issue.field_name) }} · 来源：{{ display(issue.source_kind) }} · 行号：{{ display(issue.row_no) }} · 状态：{{ issue.status }}</p>
              <template v-if="issue.status !== 'RESOLVED'">
                <label>处理说明<textarea v-model="issueNotes[issue.issue_id]" maxlength="1000" rows="2" required></textarea></label>
                <div class="action-row">
                  <button class="button-secondary" :disabled="issueActionBusy !== ''" @click="updateIssue(issue, 'ACKNOWLEDGED')">确认记录</button>
                  <button class="button-primary" :disabled="issueActionBusy !== ''" @click="updateIssue(issue, 'RESOLVED')">{{ issueActionBusy === issue.issue_id ? '保存中…' : '标记已解决' }}</button>
                </div>
                  <p class="quiet-note">处理状态不会改写来源事实或隔离状态。</p>
              </template>
            </article>
          </div>
          <div v-if="issues.length || issuePage > 1" class="pagination">
            <button class="button-secondary" :disabled="issuePage <= 1 || issueBusy" @click="changeIssuePage(issuePage - 1)">上一页</button>
            <span>第 {{ issuePage }} 页{{ issueTotal === null ? '' : '，共 ' + issueTotal + ' 条' }}</span>
            <button class="button-secondary" :disabled="issueBusy || !hasNextIssuePage" @click="changeIssuePage(issuePage + 1)">下一页</button>
          </div>
        </template>
      </template>
    </section>
  </section>
</template>

<style scoped>
.workflow-panel { --panel-ink:#17324d; --panel-muted:#61758c; --panel-line:#dbe5f0; --panel-blue:#083da6; min-width:0; margin:0; padding:0; border:0; border-radius:0; background:transparent; box-shadow:none; color:var(--panel-ink); }
.page-heading,.card-heading,.batch-card-heading,.issue-heading-row { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.page-heading { margin-bottom:12px; }.page-heading h2 { color:var(--panel-ink); font-size:18px; letter-spacing:-.01em; }
.page-eyebrow,.section-kicker { margin:0 0 6px; color:var(--panel-blue); font-size:11px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.page-lead,.quiet-note { color:var(--panel-muted); font-size:13px; line-height:1.65; }.page-lead { margin:7px 0 0; }.quiet-note { margin:0; }
.surface-card { min-width:0; margin:16px 0 0; padding:20px; border:1px solid var(--panel-line); border-radius:12px; background:#fff; box-shadow:0 5px 18px rgb(29 55 89 / 5%); }
.surface-card h3,.surface-card h4 { margin:0; color:var(--panel-ink); }.card-heading { margin-bottom:15px; }.card-heading .section-kicker { margin-bottom:3px; }
.refresh-note { margin:0 0 14px; color:var(--panel-muted); font-size:12px; }
.admin-badge { padding:6px 9px; border-radius:999px; background:#eaf0ff; color:#083da6; font-size:10px; font-weight:800; letter-spacing:.08em; }
.inline-message { margin:12px 0; padding:12px 14px; border:1px solid transparent; border-radius:9px; font-size:13px; line-height:1.6; }
.message-success { border-color:#cae8db; background:#eff9f4; color:#176b51; }.message-error { border-color:#f1d0d0; background:#fff4f3; color:#9f3333; }.loading-state,.empty-state { margin:14px 0; padding:16px; border-radius:9px; background:#f6f8fc; color:var(--panel-muted); font-size:13px; }
.upload-card { border-color:#cbd8f1; }.upload-form { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:13px; align-items:end; margin:16px 0; }.upload-form label { min-width:0; }
label { display:flex; flex-direction:column; gap:7px; max-width:100%; color:var(--panel-muted); font-size:12px; font-weight:650; }
input,select,textarea { width:100%; min-width:0; max-width:100%; min-height:42px; padding:9px 11px; border:1px solid #cbd7e7; border-radius:8px; box-sizing:border-box; background:#fff; color:var(--panel-ink); font:inherit; }
textarea { resize:vertical; } input:focus,select:focus,textarea:focus { border-color:var(--panel-blue); outline:3px solid rgb(8 61 166 / 12%); }
button { min-height:40px; padding:9px 14px; border:1px solid transparent; border-radius:8px; background:var(--panel-blue); color:#fff; font:inherit; font-size:13px; font-weight:700; cursor:pointer; transition:background .15s ease,transform .15s ease; }
button:hover:not(:disabled) { background:#062f83; transform:translateY(-1px); } button:disabled { opacity:.52; cursor:not-allowed; }
.button-secondary { border-color:#d4deec; background:#f4f7fc; color:var(--panel-blue); }.button-secondary:hover:not(:disabled) { background:#eaf0ff; }
.upload-form .filter-actions { grid-column:1/-1; display:flex; align-items:center; flex-wrap:wrap; gap:12px; }
.batch-list { display:grid; gap:13px; }.batch-card { min-width:0; padding:18px; border:1px solid var(--panel-line); border-radius:12px; background:#fff; box-shadow:0 4px 14px rgb(29 55 89 / 4%); }
.batch-card-heading { align-items:flex-start; }.batch-card-heading h3 { color:var(--panel-ink); font-size:17px; }.batch-card-heading .section-kicker { margin-bottom:3px; }
.batch-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }.state-badge { display:inline-flex; align-items:center; min-height:27px; padding:5px 10px; border-radius:999px; background:#edf2f8; color:#53657a; font-size:11px; font-weight:800; white-space:nowrap; }
.batch-state-succeeded { background:#e8f5ee; color:#146c48; }.batch-state-ready,.batch-state-validating,.batch-state-publishing { background:#eaf0ff; color:#17499c; }.batch-state-failed { background:#fff0ee; color:#a4302e; }.batch-state-cancelled { background:#edf0f5; color:#58677b; }
.batch-flow { display:flex; align-items:flex-start; margin:19px 0 16px; padding:0; list-style:none; }.batch-flow li { position:relative; display:flex; flex:1 1 0; flex-direction:column; align-items:center; gap:7px; color:#8997aa; font-size:10px; text-align:center; }.batch-flow li:not(:last-child)::after { position:absolute; top:6px; left:calc(50% + 10px); width:calc(100% - 20px); height:2px; background:#e2e8f1; content:""; }.batch-flow li.is-complete:not(:last-child)::after { background:#83b4a0; }.flow-dot { z-index:1; width:13px; height:13px; border:2px solid #dbe3ee; border-radius:50%; background:#fff; }.batch-flow .is-complete .flow-dot { border-color:#70a98e; background:#70a98e; }.batch-flow .is-current { color:var(--panel-blue); font-weight:800; }.batch-flow .is-current .flow-dot { border-color:var(--panel-blue); box-shadow:0 0 0 4px #eaf0ff; }
.terminal-state { display:flex; align-items:center; gap:8px; margin:13px 0; color:var(--panel-muted); font-size:12px; }
.batch-meta { display:flex; flex-wrap:wrap; gap:5px 14px; margin:0; color:var(--panel-muted); font-size:11px; line-height:1.6; }
.batch-counts { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:13px 0 0; }.batch-counts > div { min-width:0; padding:11px 12px; border-radius:9px; background:#f6f8fc; }.batch-counts span { display:block; color:var(--panel-muted); font-size:11px; }.batch-counts strong { display:block; margin-top:4px; color:var(--panel-ink); font-size:17px; overflow-wrap:anywhere; }
.pagination,.action-row { display:flex; align-items:center; justify-content:center; flex-wrap:wrap; gap:10px; margin:14px 0; }.pagination { color:var(--panel-muted); font-size:12px; }
.batch-detail { border-color:#cbd8f1; }.detail-status-line { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px; }.detail-panel h4,.subsection-title { margin:18px 0 10px; color:var(--panel-ink); }
.table-wrap { overflow-x:auto; border:1px solid #e4eaf2; border-radius:9px; } table { width:100%; border-collapse:collapse; font-size:12px; } th { background:#f6f8fc; color:var(--panel-muted); font-size:10px; letter-spacing:.04em; text-align:left; text-transform:uppercase; white-space:nowrap; } th,td { padding:10px; border-bottom:1px solid #e9eef5; vertical-align:top; text-align:left; }
.read-only-note { margin:15px 0; padding:11px 13px; border-radius:8px; background:#f6f8fc; color:var(--panel-muted); font-size:12px; }
.publish-guidance { margin:15px 0 0; padding:12px 14px; border:1px solid #f0dfb8; border-radius:9px; background:#fff9eb; color:#73551c; font-size:12px; line-height:1.6; }
.issue-heading { margin:25px 0 12px; padding-top:19px; border-top:1px solid var(--panel-line); }.issue-heading h4 { margin:0; color:var(--panel-ink); }.issue-list { display:grid; gap:11px; }.issue-card { min-width:0; padding:15px; border:1px solid #e4eaf2; border-radius:10px; background:#fbfcfe; }.issue-heading-row strong { overflow-wrap:anywhere; color:var(--panel-ink); font-size:13px; }.issue-card > p { margin:9px 0; line-height:1.6; }.issue-meta { color:var(--panel-muted); font-size:11px; overflow-wrap:anywhere; }
.status-chip { display:inline-flex; padding:5px 9px; border-radius:999px; font-size:10px; font-weight:800; white-space:nowrap; }.severity-warning { background:#fff3d8; color:#805500; }.severity-error { background:#fff0ee; color:#a4302e; }.severity-info { background:#eaf0ff; color:#17499c; }
.issue-card textarea { margin-top:6px; }.issue-card .action-row { justify-content:flex-start; }.issue-card .quiet-note { margin-top:7px; }
@media(max-width:760px) {
  .workflow-panel { padding:0; border-radius:0; }.page-heading,.card-heading { align-items:flex-start; flex-direction:column; }.page-heading > button { width:100%; }
  .upload-form { grid-template-columns:repeat(2,minmax(0,1fr)); }.batch-card-heading { flex-direction:column; }.batch-actions { width:100%; justify-content:space-between; }
}
@media(max-width:480px) {
  .upload-form { grid-template-columns:1fr; }.upload-form .filter-actions { grid-column:auto; align-items:flex-start; flex-direction:column; }
  .batch-counts { grid-template-columns:repeat(2,minmax(0,1fr)); }.batch-flow li { font-size:9px; }.batch-flow { margin-inline:-5px; }
  .batch-detail > .card-heading > button { width:100%; }.detail-status-line { align-items:flex-start; flex-direction:column; }
}
</style>
