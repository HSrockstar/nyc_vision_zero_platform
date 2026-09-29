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
  <section aria-labelledby="imports-heading" class="m2-section">
    <div class="section-title">
      <h2 id="imports-heading">数据导入批次</h2>
      <button class="secondary-button" :disabled="listBusy || detailBusy" @click="refresh">{{ listBusy ? '刷新中…' : '手动刷新' }}</button>
    </div>
    <p class="detail">页面不会自动轮询；可手动刷新批次和所选详情。</p>

    <section v-if="isAdmin" class="detail-panel" aria-labelledby="upload-heading">
      <h3 id="upload-heading">导入新批次</h3>
      <p class="detail">上传文件仅用于后台校验。结束日期为排他边界；WARNING 可隔离后继续，ERROR 冲突会阻断发布。三个 CSV 合计不超过 256 MiB。</p>
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
          <button :disabled="uploadBusy">{{ uploadBusy ? '上传中…' : '提交后台校验' }}</button>
          <span class="detail">当前合计 {{ byteLabel(uploadSize) }}。</span>
        </div>
      </form>
      <p class="detail">网络中断时，保持文件和日期不变后重新提交会复用同一 request UUID；更换文件、范围或表头模式会开始新操作。</p>
      <p v-if="uploadError" class="error" role="alert">{{ uploadError }}</p>
      <p v-if="uploadNotice" class="notice" role="status">{{ uploadNotice }}</p>
    </section>

    <p v-if="listError" class="error" role="alert">{{ listError }}</p>
    <p v-if="listBusy && !batches.length" class="detail" role="status">正在加载导入批次…</p>
    <p v-else-if="!batches.length && !listBusy && !listError" class="empty-state">当前没有导入批次。</p>
    <div v-if="batches.length" class="batch-list">
      <article v-for="batch in batches" :key="batch.batch_id" class="batch-card">
        <div class="section-title">
          <div><h3>批次 {{ batch.batch_id }}</h3><p class="detail">{{ display(batch.requested_start) }} 至 {{ display(batch.requested_end) }}（结束日期不包含）</p></div>
          <div class="batch-actions">
            <span class="status-chip">{{ statusLabel(batch.status) }}</span>
            <button class="secondary-button" @click="selectBatch(batch.batch_id)">查看批次</button>
          </div>
        </div>
        <p class="detail">创建：{{ display(batch.created_at) }} · 清洗版本：{{ display(batch.cleaning_version) }} · 数据版本：{{ display(batch.published_revision) }}</p>
        <div class="batch-counts">
          <span>读取 {{ display(batch.rows_read) }}</span><span>接受 {{ display(batch.rows_accepted) }}</span>
          <span>拒绝 {{ display(batch.rows_rejected) }}</span><span>跳过 {{ display(batch.rows_skipped) }}</span>
        </div>
      </article>
    </div>
    <div v-if="batches.length || page > 1" class="pagination">
      <button class="secondary-button" :disabled="page <= 1 || listBusy" @click="changeBatchPage(page - 1)">上一页</button>
      <span class="detail">第 {{ page }} 页{{ total === null ? '' : '，共 ' + total + ' 批' }}</span>
      <button class="secondary-button" :disabled="!hasNextBatchPage || listBusy" @click="changeBatchPage(page + 1)">下一页</button>
    </div>

    <section v-if="selectedBatchId" class="detail-panel" aria-labelledby="batch-detail-heading">
      <div class="section-title">
        <h3 id="batch-detail-heading">批次详情 · {{ selectedBatchId }}</h3>
        <button class="secondary-button" @click="selectedBatchId = ''; detail = null; issues = []">收起</button>
      </div>
      <p v-if="detailBusy" class="detail" role="status">正在加载批次详情…</p>
      <p v-if="detailError" class="error" role="alert">{{ detailError }}</p>
      <template v-if="detail">
        <p class="detail">状态：{{ statusLabel(detail.status) }} · 请求日期：{{ display(detail.requested_start) }} 至 {{ display(detail.requested_end) }}（结束日期不包含）</p>
        <p v-if="detail.error_summary" class="error">{{ detail.error_summary }}</p>
        <div class="batch-counts">
          <span>读取 {{ display(detail.rows_read) }}</span><span>接受 {{ display(detail.rows_accepted) }}</span>
          <span>拒绝 {{ display(detail.rows_rejected) }}</span><span>跳过 {{ display(detail.rows_skipped) }}</span>
        </div>

        <template v-if="isAdmin && detail.input_manifest">
          <h4>来源文件摘要</h4>
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
        <p v-else-if="!isAdmin" class="detail">当前角色仅查看批次摘要。</p>
        <p v-else class="detail">该批次没有可显示的文件清单。</p>

        <p v-if="isAdmin && detail.status === 'READY'" class="detail publish-guidance">
          WARNING 问题可隔离后继续；ERROR 冲突会阻断发布。确认后，数据变更在单一事务中提交并生成新版本。
        </p>
        <div v-if="isAdmin && detail.status === 'READY'" class="action-row">
          <button :disabled="actionBusy !== ''" @click="publishSelected">{{ actionBusy === 'publish' ? '提交中…' : '确认发布此批次' }}</button>
        </div>
        <div v-if="isAdmin && detail.status === 'FAILED'" class="action-row">
          <button :disabled="actionBusy !== ''" @click="retrySelected">{{ actionBusy === 'retry' ? '提交中…' : '重新校验' }}</button>
          <span class="detail">重新校验不会自动发布。</span>
        </div>
        <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
        <p v-if="notice" class="notice" role="status">{{ notice }}</p>

        <template v-if="isAdmin">
          <div class="section-title issue-heading">
            <h4>质量问题</h4>
            <span class="detail">{{ issueTotal === null ? '' : '共 ' + issueTotal + ' 条' }}</span>
          </div>
          <p v-if="issueBusy" class="detail" role="status">正在加载问题…</p>
          <p v-if="issueError" class="error" role="alert">{{ issueError }}</p>
          <p v-else-if="!issues.length && !issueBusy" class="empty-state">该批次没有待显示的问题。</p>
          <div v-if="issues.length" class="issue-list">
            <article v-for="issue in issues" :key="issue.issue_id" class="issue-card">
              <div class="section-title">
                <strong>{{ issue.issue_code }}</strong>
                <span class="status-chip" :class="'severity-' + issue.severity.toLowerCase()">{{ severityLabel(issue.severity) }}</span>
              </div>
              <p>{{ issue.description }}</p>
              <p class="detail">字段：{{ display(issue.field_name) }} · 来源：{{ display(issue.source_kind) }} · 行号：{{ display(issue.row_no) }} · 状态：{{ issue.status }}</p>
              <template v-if="issue.status !== 'RESOLVED'">
                <label>处理说明<textarea v-model="issueNotes[issue.issue_id]" maxlength="1000" rows="2" required></textarea></label>
                <div class="action-row">
                  <button class="secondary-button" :disabled="issueActionBusy !== ''" @click="updateIssue(issue, 'ACKNOWLEDGED')">确认记录</button>
                  <button :disabled="issueActionBusy !== ''" @click="updateIssue(issue, 'RESOLVED')">{{ issueActionBusy === issue.issue_id ? '保存中…' : '标记已解决' }}</button>
                </div>
                <p class="detail">处理状态不会改写来源事实或隔离状态。</p>
              </template>
            </article>
          </div>
          <div v-if="issues.length || issuePage > 1" class="pagination">
            <button class="secondary-button" :disabled="issuePage <= 1 || issueBusy" @click="changeIssuePage(issuePage - 1)">上一页</button>
            <span class="detail">第 {{ issuePage }} 页{{ issueTotal === null ? '' : '，共 ' + issueTotal + ' 条' }}</span>
            <button class="secondary-button" :disabled="issueBusy || !hasNextIssuePage" @click="changeIssuePage(issuePage + 1)">下一页</button>
          </div>
        </template>
      </template>
    </section>
  </section>
</template>
