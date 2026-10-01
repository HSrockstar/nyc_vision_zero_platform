'use strict'

const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const playwright = require(path.resolve(__dirname, '../../frontend/node_modules/playwright'))
const chromium = playwright.chromium
const apiRequest = playwright.request
const baseUrl = (process.env.M5_QA_BASE_URL || 'http://127.0.0.1:5175/').replace(/\/?$/, '/')
const origin = new URL(baseUrl).origin
const configPath = process.env.M5_QA_PRIVATE_CONFIG || process.argv[2] || ''
const chromePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const runTag = crypto.randomBytes(4).toString('hex')
const state = { browser: null, context: null, page: null, config: null, creatorApi: null, creatorToken: '',
  report: {
    target: origin, route: '/', browser: { name: 'system Chrome', executablePath: chromePath, headless: true, isolatedContext: true },
    dataBoundary: '仅操作隔离随机PostgreSQL测试库中的合成账号、画像和治理任务；不记录密码、JWT、DSN、请求头或登录响应正文。',
    startedAt: new Date().toISOString(), runtime: { node: process.version, playwright: 'workspace dependency' },
    roles: [], checks: [],
    network: { api: { requests: [], responses: [], unexpectedHttpErrors: [], requestFailures: [] },
      apiHelpers: [], otherResourceErrors: [] },
    expectedBlocked: { osmTiles: { interceptionInstalled: false, intercepted: 0, blockedFailures: 0, consoleErrors: 0 } },
    faultInjection: { list503: 0, detail503: 0, expectedConsoleErrors: 0, recoveredList: false, recoveredDetail: false },
    consoleErrors: [], pageErrors: [], screenshots: [], viewports: {}, iframeCount: null, fatal: null,
    runner: { command: 'node .m5-work/browser/m5_browser_acceptance.cjs <private-config-path>', exitCode: null },
  },
}
const report = state.report
const statusLabels = { DRAFT: '草稿', OPEN: '待执行', IN_PROGRESS: '执行中',
  PENDING_REVIEW: '待复核', COMPLETED: '已完成', CANCELLED: '已取消' }
const eventLabels = { CREATE: '创建', EDIT: '修改', PUBLISH: '发布', DELETE_DRAFT: '删除草稿',
  ASSIGN: '分配', START: '开始执行', PROGRESS: '执行记录', SUBMIT: '提交复核',
  APPROVE: '复核通过', REJECT: '退回', CANCEL: '取消' }
const faultPlan = { nextList: false, nextDetail: false }
let expectedStale409 = 0
let expectedStaleConsoleErrors = 0
let expectedInjected503 = 0
let expectedFaultConsoleErrors = 0
let stepCounter = 0

function check(name, passed, evidence) {
  report.checks.push({ name, passed: Boolean(passed), evidence: evidence || {} })
}
function uniqueName(label) {
  stepCounter += 1
  return 'M5QA-' + runTag + '-' + label + '-' + stepCounter
}
function safePath(pathname) {
  const taskPrefix = '/api/v1/governance-tasks/'
  if (pathname === '/api/v1/governance-tasks/assignees') return pathname
  if (pathname.startsWith(taskPrefix)) {
    const suffix = pathname.slice(taskPrefix.length)
    return taskPrefix + (suffix.endsWith('/history') ? ':task_id/history' : ':task_id')
  }
  if (/^\/api\/v1\/risk-profiles\/[^/]+$/.test(pathname)) return '/api/v1/risk-profiles/:profile_id'
  if (/^\/api\/v1\/risk-runs\/[^/]+$/.test(pathname)) return '/api/v1/risk-runs/:run_id'
  return pathname
}
function safeApiUrl(rawUrl) {
  const url = new URL(rawUrl)
  let suffix = ''
  if (url.pathname === '/api/v1/governance-tasks') {
    const pairs = []
    for (const key of ['status', 'my_todo', 'page', 'page_size']) {
      if (url.searchParams.has(key)) pairs.push(key + '=' + url.searchParams.get(key))
    }
    if (pairs.length) suffix = '?' + pairs.join('&')
  }
  return safePath(url.pathname) + suffix
}
function isApiUrl(rawUrl) {
  try { return new URL(rawUrl).pathname.startsWith('/api/v1/') } catch (_) { return false }
}
function attachBrowserEvidence(page) {
  page.on('request', request => {
    if (isApiUrl(request.url())) report.network.api.requests.push({
      method: request.method(), path: safeApiUrl(request.url()), source: 'browser',
    })
  })
  page.on('response', response => {
    const rawUrl = response.url()
    const url = new URL(rawUrl)
    if (url.pathname.startsWith('/api/v1/')) {
      const entry = { method: response.request().method(), path: safeApiUrl(rawUrl), status: response.status() }
      if (response.status() === 409 && expectedStale409 > 0 && entry.method === 'PATCH') {
        expectedStale409 -= 1
        entry.classification = 'expected_stale_version_conflict'
      } else if (response.status() === 503 && expectedInjected503 > 0) {
        expectedInjected503 -= 1
        entry.classification = 'expected_fault_injection'
      } else if (response.status() >= 400) report.network.api.unexpectedHttpErrors.push(entry)
      report.network.api.responses.push(entry)
    } else if (response.status() >= 400 && !/tile\.openstreetmap\.org/i.test(rawUrl)) {
      report.network.otherResourceErrors.push({ kind: 'http', host: url.hostname,
        path: safePath(url.pathname), status: response.status() })
    }
  })
  page.on('requestfailed', request => {
    const rawUrl = request.url()
    if (/tile\.openstreetmap\.org/i.test(rawUrl)) {
      report.expectedBlocked.osmTiles.blockedFailures += 1
      return
    }
    if (isApiUrl(rawUrl)) {
      const failure = request.failure()
      report.network.api.requestFailures.push({ method: request.method(), path: safeApiUrl(rawUrl),
        failure: (failure && failure.errorText || 'unknown').slice(0, 100) })
      return
    }
    const url = new URL(rawUrl)
    const failure = request.failure()
    report.network.otherResourceErrors.push({ kind: 'network', host: url.hostname,
      path: safePath(url.pathname), failure: (failure && failure.errorText || 'unknown').slice(0, 100) })
  })
  page.on('console', message => {
    if (message.type() !== 'error') return
    const value = message.text()
    const source = message.location().url || ''
    if (/tile\.openstreetmap\.org/i.test(value) || /tile\.openstreetmap\.org/i.test(source)) {
      report.expectedBlocked.osmTiles.consoleErrors += 1
      return
    }
    if (expectedStaleConsoleErrors > 0 && /(?:409|failed to load resource)/i.test(value) &&
        /\/api\/v1\/governance-tasks\/\d+(?:\?|$)/.test(source)) {
      expectedStaleConsoleErrors -= 1
      report.network.api.expectedConflictConsoleErrors =
        (report.network.api.expectedConflictConsoleErrors || 0) + 1
      return
    }
    if (expectedFaultConsoleErrors > 0 && /(?:503|failed to load resource)/i.test(value) &&
        /\/api\/v1\/governance-tasks(?:\/|(?:\?|$))/.test(source)) {
      expectedFaultConsoleErrors -= 1
      report.faultInjection.expectedConsoleErrors += 1
      return
    }
    const generic = /failed to load resource/i.test(value) ? 'Failed to load resource' :
      value.split(/[\r\n]/)[0].replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').slice(0, 140)
    report.consoleErrors.push({ message: generic, source: source ? safeApiUrl(source) : '' })
  })
  page.on('pageerror', error => report.pageErrors.push({
    name: String(error.name || 'Error').slice(0, 60),
    message: String(error.message || '').split(/[\r\n]/)[0]
      .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').slice(0, 140),
  }))
}


async function apiHelper(context, method, pathname, body, purpose, expectedStatus) {
  const options = { method, timeout: 15000, headers: { 'X-Request-ID': crypto.randomUUID() } }
  if (body !== undefined) options.data = body
  const response = await context.fetch(origin + pathname, options)
  const status = response.status()
  const entry = { purpose, method, path: safePath(new URL(pathname, origin).pathname), status }
  if (expectedStatus !== undefined && status === expectedStatus) entry.classification = 'expected'
  report.network.apiHelpers.push(entry)
  let data = null
  if (status >= 200 && status < 300) {
    const envelope = await response.json()
    data = envelope && envelope.data
  }
  return { status, data }
}
function validateConfig(config) {
  const roles = ['admin', 'creator', 'executor', 'viewer']
  const levels = ['low', 'medium', 'unknown', 'high']
  return Boolean(config && config.users && config.profiles && config.password &&
    roles.every(key => config.users[key] && config.users[key].username && config.users[key].user_id) &&
    levels.every(key => config.profiles[key] && config.profiles[key].profile_id && config.profiles[key].run_id))
}
async function newAuthenticatedApiContext(token) {
  return apiRequest.newContext({ baseURL: origin, extraHTTPHeaders: {
    Authorization: 'Bearer ' + token, 'Content-Type': 'application/json',
  } })
}
async function loginAs(roleKey) {
  const account = state.config.users[roleKey]
  await state.page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 20000 })
  await state.page.getByRole('heading', { name: '账户与权限' }).waitFor({ state: 'visible', timeout: 15000 })
  await state.page.getByLabel('登录名').fill(account.username)
  await state.page.getByLabel('密码').fill(state.config.password)
  const responsePromise = state.page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/auth/login', { timeout: 15000 })
  await state.page.getByRole('button', { name: '登录', exact: true }).click()
  const response = await responsePromise
  let token = ''
  if (response.status() === 200) {
    const envelope = await response.json()
    token = envelope && envelope.data && envelope.data.access_token || ''
  }
  const role = roleKey === 'creator' || roleKey === 'executor' ? 'MANAGER' : roleKey.toUpperCase()
  await state.page.getByText(new RegExp('角色：' + role)).waitFor({ state: 'visible', timeout: 15000 })
  if (role !== 'VIEWER') {
    await state.page.locator('#governance .task-table').waitFor({ state: 'visible', timeout: 15000 })
  }
  check('UI真实登录：' + role, response.status() === 200 && Boolean(token), {
    httpStatus: response.status(), roleVisible: true,
  })
  if (!report.roles.includes(role)) report.roles.push(role)
  return token
}
async function logoutUi() {
  const button = state.page.getByRole('button', { name: '退出全部会话' })
  if (!(await button.count())) return
  const responsePromise = state.page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/auth/logout', { timeout: 15000 })
  await button.click()
  const response = await responsePromise
  check('UI退出当前测试身份', response.status() === 200, { httpStatus: response.status() })
  await state.page.getByLabel('登录名').waitFor({ state: 'visible', timeout: 10000 })
}
async function selectProfileFromRiskPanel(level) {
  const risk = state.page.locator('section[aria-labelledby="risk-heading"]')
  await risk.waitFor({ state: 'visible', timeout: 15000 })
  const profile = state.config.profiles[level.toLowerCase()]
  const batch = risk.getByLabel('同周期历史批次')
  const targetLevel = level.toUpperCase()
  if ((await batch.inputValue()) !== profile.run_id) {
    const runPromise = state.page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/v1/risk-profiles' && url.searchParams.get('run_id') === profile.run_id
    }, { timeout: 15000 })
    await batch.selectOption(profile.run_id)
    await runPromise
  }
  const levelControl = risk.getByLabel('等级')
  if ((await levelControl.inputValue()) !== targetLevel) {
    const profilePromise = state.page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/v1/risk-profiles' &&
        url.searchParams.get('run_id') === profile.run_id &&
        url.searchParams.get('risk_level') === targetLevel
    }, { timeout: 15000 })
    await levelControl.selectOption(targetLevel)
    await profilePromise
  }
  const rows = risk.locator('.risk-table tbody tr')
  await rows.first().waitFor({ state: 'visible', timeout: 15000 })
  const count = await rows.count()
  const rowText = await rows.first().innerText()
  const label = level.toUpperCase() === 'UNKNOWN' ? '未知' :
    level.toUpperCase() === 'HIGH' ? '高' : level.toUpperCase() === 'MEDIUM' ? '中' : '低'
  const match = count === 1 && rowText.includes(label)
  check('风险面板选中合成' + level.toUpperCase() + '批次', match, {
    expectedProfile: true, matchingRows: count,
  })
  if (!match) throw new Error('risk profile row did not match the requested synthetic run')
  await rows.first().getByRole('button', { name: '建立治理草稿' }).click()
  await state.page.locator('#governance .draft-box').waitFor({ state: 'visible', timeout: 10000 })
  await state.page.locator('#governance .draft-box')
    .getByText(new RegExp('依据画像\\s*#' + profile.profile_id)).waitFor({ state: 'visible', timeout: 10000 })
  check('UI草稿绑定选定画像', true, { level: level.toUpperCase(), profileMatched: true })
}
async function waitSnapshot(status, version, eventType) {
  const label = statusLabels[status]
  const event = eventLabels[eventType]
  await state.page.waitForFunction(args => {
    const detail = document.querySelector('#governance .task-detail')
    if (!detail) return false
    const heading = detail.querySelector('.section-title h3')
    const current = detail.querySelector(':scope > p')
    const records = [...detail.querySelectorAll('ol.task-history li')]
    if (!heading || !current || !records.length) return false
    const strong = records[records.length - 1].querySelector('strong')
    const transition = records[records.length - 1].querySelector('p')
    return heading.textContent.includes(args.label) &&
      current.textContent.includes('版本 ' + args.version) &&
      strong && strong.textContent.includes('版本 ' + args.version) &&
      strong.textContent.includes(args.event) &&
      transition && transition.textContent.includes('→ ' + args.label) &&
      records.length === args.version
  }, { label, version, event }, { timeout: 15000 })
  const detail = state.page.locator('#governance .task-detail')
  const rows = await detail.locator('ol.task-history li').count()
  const header = await detail.locator('.section-title h3').innerText()
  const current = await detail.locator(':scope > p').first().innerText()
  const last = await detail.locator('ol.task-history li').last().innerText()
  const versionOk = new RegExp('版本\\s+' + version + '\\b').test(current)
  const historyOk = last.includes('版本 ' + version + ' · ' + event) && last.includes('→ ' + label)
  check('当前任务快照与追加历史一致：' + label + ' v' + version,
    header.includes(label) && versionOk && historyOk && rows === version, {
      statusMatched: header.includes(label) && historyOk,
      snapshotVersion: versionOk ? version : null,
      historySequenceCount: rows,
      lastEventMatched: historyOk,
    })
}
async function createTaskViaUi(label, options) {
  const opts = options || {}
  const title = uniqueName(label)
  const responsePromise = state.page.waitForResponse(response =>
    response.request().method() === 'POST' &&
    new URL(response.url()).pathname === '/api/v1/governance-tasks', { timeout: 15000 })
  await state.page.getByLabel('任务标题').fill(title)
  await state.page.getByLabel('任务说明', { exact: true }).fill('随机合成浏览器验收记录；仅用于隔离QA库。')
  if (opts.rationale) {
    await state.page.getByLabel('建立与评价范围理由（低、中、未知等级必填）', { exact: true }).fill(opts.rationale)
  }
  await state.page.getByRole('button', { name: '建立课程模拟草稿', exact: true }).click()
  const response = await responsePromise
  if (response.status() !== 201) throw new Error('UI task creation failed with HTTP ' + response.status())
  const envelope = await response.json()
  const task = envelope && envelope.data
  if (!task || !task.task_id) throw new Error('UI create response omitted task projection')
  await state.page.locator('#governance .task-detail h3').waitFor({ state: 'visible', timeout: 15000 })
  await waitSnapshot(task.status, task.version, 'CREATE')
  check('UI创建课程模拟草稿', task.status === 'DRAFT' && task.version === 1 && task.is_simulated === true, {
    status: task.status, version: task.version, simulated: task.is_simulated === true,
  })
  return task
}


function taskActionPath(taskId, action) {
  if (action === 'edit' || action === 'delete_draft') return '/api/v1/governance-tasks/' + taskId
  if (action === 'approve' || action === 'reject') return '/api/v1/governance-tasks/' + taskId + '/review'
  return '/api/v1/governance-tasks/' + taskId + '/' + action
}
async function actViaUi(task, action, note, options) {
  const opts = options || {}
  const labels = { edit: '保存草稿', publish: '发布任务', delete_draft: '删除草稿',
    assign: '重新分配', start: '开始执行', progress: '追加执行记录', submit: '提交复核',
    approve: '复核通过', reject: '退回执行', cancel: '取消任务' }
  const method = action === 'edit' ? 'PATCH' : action === 'delete_draft' ? 'DELETE' : 'POST'
  const target = taskActionPath(task.task_id, action)
  const responsePromise = state.page.waitForResponse(response =>
    response.request().method() === method && new URL(response.url()).pathname === target, { timeout: 15000 })
  if (action === 'edit' && opts.title) await state.page.getByLabel('草稿标题', { exact: true }).fill(opts.title)
  if (action === 'publish' || action === 'assign') {
    await state.page.getByLabel('启用的管理人员').selectOption(state.config.users.executor.user_id)
  }
  await state.page.getByLabel('本次处理说明 / 复核意见', { exact: true }).fill(note)
  if (action === 'delete_draft' || action === 'cancel') state.page.once('dialog', dialog => dialog.accept())
  await state.page.locator('#governance .task-detail')
    .getByRole('button', { name: labels[action], exact: true }).click()
  const response = await responsePromise
  if (response.status() < 200 || response.status() >= 300) {
    throw new Error('UI action ' + action + ' failed with HTTP ' + response.status())
  }
  const envelope = await response.json()
  const updated = envelope && envelope.data
  if (!updated || !updated.task_id) throw new Error('UI action response omitted task projection')
  const event = action === 'delete_draft' ? 'DELETE_DRAFT' :
    action === 'approve' ? 'APPROVE' : action === 'reject' ? 'REJECT' : action.toUpperCase()
  await waitSnapshot(updated.status, updated.version, event)
  check('UI操作：' + labels[action], true, {
    httpStatus: response.status(), status: updated.status, version: updated.version,
  })
  return updated
}
async function openTaskByCode(taskCode) {
  const row = state.page.locator('#governance .task-table tbody tr').filter({ hasText: taskCode })
  await row.first().waitFor({ state: 'visible', timeout: 12000 })
  await row.first().getByRole('button', { name: '工单详情' }).click()
  await state.page.locator('#governance .task-detail h3').waitFor({ state: 'visible', timeout: 12000 })
}
async function createApiDrafts(count) {
  state.creatorApi = await newAuthenticatedApiContext(state.creatorToken)
  const statuses = []
  for (let i = 0; i < count; i += 1) {
    const result = await apiHelper(state.creatorApi, 'POST', '/api/v1/governance-tasks', {
      request_id: crypto.randomUUID(),
      profile_id: state.config.profiles.high.profile_id,
      title: uniqueName('page-helper'),
      description: '随机合成分页辅助草稿；不对应正式业务。',
      measure_type: 'FIELD_SURVEY', priority: 'LOW', radius_m: 50, rationale: null,
    }, 'pagination_seed', 201)
    statuses.push(result.status)
    if (result.status !== 201 || !result.data) throw new Error('pagination helper create failed with HTTP ' + result.status)
  }
  check('API辅助建立' + count + '条合成分页草稿',
    statuses.length === count && statuses.every(status => status === 201), {
      created: statuses.filter(status => status === 201).length,
      allHttp201: statuses.every(status => status === 201),
    })
}
async function checkDraftFiltersAndPagination() {
  const panel = state.page.locator('#governance')
  const statusControl = panel.getByLabel('工单状态')
  const responsePromise = state.page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/governance-tasks' && url.searchParams.get('status') === 'DRAFT'
  }, { timeout: 15000 })
  await statusControl.selectOption('DRAFT')
  await responsePromise
  const pageOne = panel.locator('.task-controls span').filter({ hasText: /^第 1 页 \/ 共 \d+ 条$/ })
  await pageOne.waitFor({ state: 'visible', timeout: 10000 })
  const pageOneLabel = await pageOne.innerText()
  const total = Number((pageOneLabel.match(/共\s+(\d+)\s+条/) || [])[1] || 0)
  const firstRows = await panel.locator('.task-table tbody tr').count()
  check('草稿状态筛选与首屏分页', total >= 21 && firstRows === 20, {
    filteredTotal: total, visibleRows: firstRows,
  })
  const nextPromise = state.page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/governance-tasks' &&
      url.searchParams.get('status') === 'DRAFT' && url.searchParams.get('page') === '2'
  }, { timeout: 15000 })
  await panel.getByRole('button', { name: '下一页工单' }).click()
  await nextPromise
  await panel.getByText(new RegExp('第 2 页 / 共 ' + total + ' 条'), { exact: true }).waitFor({ state: 'visible', timeout: 10000 })
  const secondRows = await panel.locator('.task-table tbody tr').count()
  check('草稿分页进入第二页', total >= 21 && secondRows === Math.min(20, total - 20), {
    page: 2, visibleRows: secondRows, filteredTotal: total,
  })
  const previousPromise = state.page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/governance-tasks' &&
      url.searchParams.get('status') === 'DRAFT' && url.searchParams.get('page') === '1'
  }, { timeout: 15000 })
  await panel.getByRole('button', { name: '上一页工单' }).click()
  await previousPromise
  const pageOneAgain = await panel.getByText(new RegExp('第 1 页 / 共 ' + total + ' 条'), { exact: true }).isVisible()
  check('上一页返回第一页', pageOneAgain, { page: 1, filteredTotal: total })
  const clearPromise = state.page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/governance-tasks' &&
    !new URL(response.url()).searchParams.has('status'), { timeout: 15000 })
  await statusControl.selectOption('')
  await clearPromise
}
async function startTodoUi(mainTask, status) {
  const panel = state.page.locator('#governance')
  const todoPromise = state.page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/governance-tasks' && url.searchParams.get('my_todo') === 'true'
  }, { timeout: 15000 })
  await panel.getByLabel('我的执行待办').check()
  await todoPromise
  const list = await panel.locator('.task-table').innerText()
  const rows = await panel.locator('.task-table tbody tr').count()
  check('执行人“我的执行待办”筛选', rows === 1 && list.includes(mainTask.task_code), {
    totalRows: rows, targetPresent: list.includes(mainTask.task_code),
  })
  const filterPromise = state.page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/governance-tasks' && url.searchParams.get('my_todo') === 'true' &&
      url.searchParams.get('status') === status
  }, { timeout: 15000 })
  await panel.getByLabel('工单状态').selectOption(status)
  await filterPromise
  const label = statusLabels[status]
  const totalOne = await panel.getByText('第 1 页 / 共 1 条', { exact: true }).isVisible()
  check('执行待办状态过滤：' + label, totalOne, { status, total: totalOne ? 1 : 0 })
  await openTaskByCode(mainTask.task_code)
}


async function installRoutes(page) {
  await page.route(/https?:\/\/[^/]*tile\.openstreetmap\.org\//i, async route => {
    report.expectedBlocked.osmTiles.intercepted += 1
    await route.abort('blockedbyclient')
  })
  report.expectedBlocked.osmTiles.interceptionInstalled = true
  await page.route('**/api/v1/governance-tasks**', async route => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    let inject = false
    if (method === 'GET' && url.pathname === '/api/v1/governance-tasks' && faultPlan.nextList) {
      faultPlan.nextList = false
      report.faultInjection.list503 += 1
      inject = true
    } else if (method === 'GET' && /^\/api\/v1\/governance-tasks\/\d+$/.test(url.pathname) && faultPlan.nextDetail) {
      faultPlan.nextDetail = false
      report.faultInjection.detail503 += 1
      inject = true
    }
    if (inject) {
      expectedInjected503 += 1
      expectedFaultConsoleErrors += 1
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: { code: 'QA_INJECTED_UNAVAILABLE', message: '验收注入的服务不可用' } }),
      })
      return
    }
    await route.continue()
  })
}
async function doDesktopMobileEvidence() {
  const page = state.page
  const panel = page.locator('#governance')
  await page.setViewportSize({ width: 1440, height: 900 })
  await panel.evaluate(element => window.scrollTo(0, element.getBoundingClientRect().top + window.scrollY))
  report.viewports.desktop = await page.evaluate(() => {
    const wrap = document.querySelector('#governance .table-wrap')
    const table = wrap && wrap.querySelector('table')
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth },
      body: { clientWidth: document.body.clientWidth, scrollWidth: document.body.scrollWidth },
      taskTable: wrap && table ? {
        containerClientWidth: wrap.clientWidth, containerScrollWidth: wrap.scrollWidth,
        tableScrollWidth: table.scrollWidth, horizontalScrollInContainer: wrap.scrollWidth > wrap.clientWidth,
      } : null,
    }
  })
  check('桌面1440×900页面无水平溢出',
    report.viewports.desktop.document.scrollWidth <= report.viewports.desktop.document.clientWidth &&
    report.viewports.desktop.body.scrollWidth <= report.viewports.desktop.body.clientWidth,
    report.viewports.desktop)
  const desktopShot = path.join(__dirname, 'm5-governance-desktop-1440x900.png')
  await page.screenshot({ path: desktopShot, fullPage: false })
  report.screenshots.push(path.basename(desktopShot))

  await page.setViewportSize({ width: 390, height: 844 })
  await panel.evaluate(element => window.scrollTo(0, element.getBoundingClientRect().top + window.scrollY))
  report.viewports.mobile = await page.evaluate(() => {
    const wrap = document.querySelector('#governance .table-wrap')
    const table = wrap && wrap.querySelector('table')
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: { clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth },
      body: { clientWidth: document.body.clientWidth, scrollWidth: document.body.scrollWidth },
      taskTable: wrap && table ? {
        containerClientWidth: wrap.clientWidth, containerScrollWidth: wrap.scrollWidth,
        tableScrollWidth: table.scrollWidth, horizontalScrollInContainer: wrap.scrollWidth > wrap.clientWidth,
      } : null,
    }
  })
  check('窄屏390×844页面无水平溢出',
    report.viewports.mobile.document.scrollWidth <= report.viewports.mobile.document.clientWidth &&
    report.viewports.mobile.body.scrollWidth <= report.viewports.mobile.body.clientWidth,
    report.viewports.mobile)
  check('窄屏治理任务表在容器内横向滚动',
    Boolean(report.viewports.mobile.taskTable && report.viewports.mobile.taskTable.horizontalScrollInContainer),
    report.viewports.mobile.taskTable || {})
  const mobileShot = path.join(__dirname, 'm5-governance-mobile-390x844.png')
  await page.screenshot({ path: mobileShot, fullPage: false })
  report.screenshots.push(path.basename(mobileShot))
}
async function runAcceptance() {
  if (!configPath || !fs.existsSync(configPath)) throw new Error('private QA configuration unavailable')
  let config
  try { config = JSON.parse(fs.readFileSync(configPath, 'utf8')) }
  catch (_) { throw new Error('private QA configuration unreadable') }
  if (!validateConfig(config)) throw new Error('private QA configuration fields are incomplete')
  state.config = config
  if (!fs.existsSync(chromePath)) throw new Error('system Chrome unavailable')
  state.browser = await chromium.launch({ headless: true, executablePath: chromePath,
    args: ['--no-first-run', '--no-default-browser-check'] })
  state.context = await state.browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: false })
  state.page = await state.context.newPage()
  attachBrowserEvidence(state.page)
  await installRoutes(state.page)
  await state.page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 20000 })
  await state.page.getByRole('heading', { name: /纽约交通碰撞风险识别/ }).waitFor({ state: 'visible', timeout: 15000 })
  await state.page.getByRole('heading', { name: '账户与权限' }).waitFor({ state: 'visible', timeout: 15000 })
  report.iframeCount = await state.page.locator('iframe').count()
  check('首页路由与单页表单可观察', true, { route: '/', iframeCount: report.iframeCount })

  state.creatorToken = await loginAs('creator')
  await createApiDrafts(21)


  await selectProfileFromRiskPanel('HIGH')
  const deleted = await createTaskViaUi('soft-delete')
  await actViaUi(deleted, 'delete_draft', '保留只追加历史的逻辑删除验收。')
  const deletedNotice = await state.page.getByText('此草稿已逻辑删除，仅保留详情与历史。', { exact: true }).isVisible()
  const deletedHistoryRows = await state.page.locator('#governance .task-detail ol.task-history li').count()
  check('UI软删除保留历史', deletedNotice && deletedHistoryRows === 2, {
    tombstoneVisible: deletedNotice, historyRows: deletedHistoryRows,
  })

  const cancelled = await createTaskViaUi('cancel')
  await actViaUi(cancelled, 'publish', '发布独立模拟任务以验证取消。')
  const cancelledFinal = await actViaUi(cancelled, 'cancel', '取消独立课程模拟任务。')
  check('UI取消任务并保留终态', cancelledFinal.status === 'CANCELLED', { status: cancelledFinal.status })

  const staleDraft = await createTaskViaUi('stale-version')
  const externalTitle = uniqueName('external-version')
  const external = await apiHelper(state.creatorApi, 'PATCH',
    '/api/v1/governance-tasks/' + staleDraft.task_id, {
      request_id: crypto.randomUUID(), expected_version: staleDraft.version,
      note: 'QA外部API并发更新版本。', title: externalTitle,
    }, 'external_version_update', 200)
  check('外部API真实更新任务版本', external.status === 200 && external.data &&
    external.data.version === staleDraft.version + 1, {
      httpStatus: external.status,
      versionAdvanced: Boolean(external.data && external.data.version === staleDraft.version + 1),
    })
  const staleTitle = uniqueName('stale-ui-write')
  expectedStale409 += 1
  expectedStaleConsoleErrors += 1
  const stalePromise = state.page.waitForResponse(response =>
    response.request().method() === 'PATCH' &&
    new URL(response.url()).pathname === '/api/v1/governance-tasks/' + staleDraft.task_id &&
    response.status() === 409, { timeout: 15000 })
  await state.page.getByLabel('草稿标题', { exact: true }).fill(staleTitle)
  await state.page.getByLabel('本次处理说明 / 复核意见', { exact: true }).fill('提交旧版本以验证冲突保护。')
  await state.page.locator('#governance .task-detail')
    .getByRole('button', { name: '保存草稿', exact: true }).click()
  const staleResponse = await stalePromise
  const conflictAlert = state.page.locator('#governance [role="alert"]')
  const alertVisible = await conflictAlert.waitFor({ state: 'visible', timeout: 10000 }).then(() => true).catch(() => false)
  const alertText = alertVisible ? await conflictAlert.innerText() : ''
  const conflictMessageVisible = /任务/.test(alertText) && /刷新/.test(alertText)
  const refreshText = state.page.getByText(/上次请求未完成或版本可能变化.*重新加载详情后再提交/)
  const refreshInstructionVisible = await refreshText.isVisible()
  const saveButton = state.page.locator('#governance .task-detail')
    .getByRole('button', { name: '保存草稿', exact: true })
  const blockedSave = await saveButton.isDisabled()
  check('网页旧版本写入返回409并要求明确重新加载',
    staleResponse.status() === 409 && conflictMessageVisible &&
      refreshInstructionVisible && blockedSave, {
      httpStatus: staleResponse.status(),
      errorVisible: alertVisible,
      errorCategory: /其他操作修改/.test(alertText) ? 'version-conflict' : alertText ? 'other-error' : 'missing',
      staleWriteDisabled: blockedSave,
      reloadInstructionVisible: refreshInstructionVisible,
    })

  await state.page.locator('#governance .task-detail')
    .getByRole('button', { name: '重新加载详情', exact: true }).click()
  const titleInput = state.page.getByLabel('草稿标题', { exact: true })
  await titleInput.waitFor({ state: 'visible', timeout: 10000 })
  const latestTitle = await titleInput.inputValue()
  const savedTitle = uniqueName('after-reload')
  await titleInput.fill(savedTitle)
  await state.page.getByLabel('本次处理说明 / 复核意见', { exact: true }).fill('明确重新加载最新版本后再保存。')
  const writeEnabled = await saveButton.isEnabled()
  const savePromise = state.page.waitForResponse(response =>
    response.request().method() === 'PATCH' &&
    new URL(response.url()).pathname === '/api/v1/governance-tasks/' + staleDraft.task_id &&
    response.status() === 200, { timeout: 15000 })
  await saveButton.click()
  const savedResponse = await savePromise
  const savedEnvelope = await savedResponse.json()
  const saved = savedEnvelope.data
  check('明确重新加载后页面可按新版本写入',
    latestTitle === externalTitle && writeEnabled && saved.version === external.data.version + 1, {
      latestExternalValueLoaded: latestTitle === externalTitle,
      writeEnabledAfterReload: writeEnabled,
      httpStatus: savedResponse.status(),
      versionAdvanced: saved.version === external.data.version + 1,
    })
  await waitSnapshot('DRAFT', saved.version, 'EDIT')

  await selectProfileFromRiskPanel('UNKNOWN')
  const unknown = await createTaskViaUi('unknown-survey', {
    rationale: 'UNKNOWN合成画像数据不完整，仅建立现场调查草稿。',
  })
  const apiNoPublish = !unknown.allowed_actions.includes('publish')
  const uiNoPublish = await state.page.locator('#governance .task-detail')
    .getByRole('button', { name: '发布任务', exact: true }).count() === 0
  check('UNKNOWN画像仅创建现场调查且页面无发布操作',
    unknown.risk_level === 'UNKNOWN' && unknown.measure_type === 'FIELD_SURVEY' && apiNoPublish && uiNoPublish, {
      riskLevel: unknown.risk_level,
      fieldSurvey: unknown.measure_type === 'FIELD_SURVEY',
      publishActionAbsent: apiNoPublish && uiNoPublish,
    })
  const unknownPublish = await apiHelper(state.creatorApi, 'POST',
    '/api/v1/governance-tasks/' + unknown.task_id + '/publish', {
      request_id: crypto.randomUUID(), expected_version: unknown.version,
      assignee_id: state.config.users.executor.user_id, note: '验证UNKNOWN任务不允许发布。',
    }, 'unknown_publish_guard', 409)
  check('UNKNOWN后端发布请求拒绝', unknownPublish.status === 409, { httpStatus: unknownPublish.status })

  await selectProfileFromRiskPanel('HIGH')
  const mainTask = await createTaskViaUi('main-workflow')
  const published = await actViaUi(mainTask, 'publish', '创建者发布并分配给另一位合成治理人员。')
  check('发布任务由创建者分配给另一名执行人',
    published.status === 'OPEN' && published.assignee_id === state.config.users.executor.user_id &&
    published.created_by === state.config.users.creator.user_id, {
      status: published.status,
      differentCreatorAndExecutor: published.assignee_id !== published.created_by,
    })

  await checkDraftFiltersAndPagination()

  await logoutUi()
  await loginAs('executor')
  await startTodoUi(published, 'OPEN')
  const started = await actViaUi(published, 'start', '开始现场执行。')
  check('执行人可开始本人待办', started.status === 'IN_PROGRESS', { status: started.status })
  const progressOne = await actViaUi(started, 'progress',
    '执行记录一：已核对路口标线和信号控制器。')
  const progressOneText = await state.page.locator('#governance .task-detail ol.task-history').innerText()
  check('执行记录以追加历史保留', progressOne.status === 'IN_PROGRESS' &&
    progressOneText.includes('已核对路口标线和信号控制器'), {
      status: progressOne.status, recordRetained: progressOneText.includes('已核对路口标线和信号控制器'),
    })
  const submitted = await actViaUi(progressOne, 'submit', '执行阶段完成，请创建者复核。')
  const noSelfReview = await state.page.locator('#governance .task-detail')
    .getByRole('button', { name: '复核通过', exact: true }).count() === 0
  check('执行人提交后不能自行复核', submitted.status === 'PENDING_REVIEW' && noSelfReview, {
    status: submitted.status, approveButtonAbsent: noSelfReview,
  })


  await logoutUi()
  await loginAs('creator')
  await openTaskByCode(mainTask.task_code)
  const rejected = await actViaUi(mainTask, 'reject', '退回执行：请补录夜间视认性核查。')
  check('创建者退回给执行人补录',
    rejected.status === 'IN_PROGRESS' && rejected.assignee_id === state.config.users.executor.user_id, {
      status: rejected.status,
      assigneeRetained: rejected.assignee_id === state.config.users.executor.user_id,
    })

  await logoutUi()
  await loginAs('executor')
  await startTodoUi(rejected, 'IN_PROGRESS')
  const progressTwo = await actViaUi(rejected, 'progress',
    '执行补录：已完成夜间视认性复查并留存记录。')
  const allHistory = await state.page.locator('#governance .task-detail ol.task-history').innerText()
  check('退回后执行人补录并追加记录',
    progressTwo.status === 'IN_PROGRESS' && allHistory.includes('已完成夜间视认性复查并留存记录'), {
      status: progressTwo.status,
      appendedRecordVisible: allHistory.includes('已完成夜间视认性复查并留存记录'),
    })
  const submittedAgain = await actViaUi(progressTwo, 'submit', '补录已完成，请再次复核。')
  check('执行人补录后再次提交', submittedAgain.status === 'PENDING_REVIEW', { status: submittedAgain.status })

  await logoutUi()
  await loginAs('creator')
  await openTaskByCode(mainTask.task_code)
  const approved = await actViaUi(mainTask, 'approve', '复核通过：补录内容完整。')
  check('创建者最终复核通过', approved.status === 'COMPLETED', { status: approved.status })

  await logoutUi()
  const viewerToken = await loginAs('viewer')
  const hidden = await state.page.locator('#governance').count() === 0 &&
    await state.page.getByRole('heading', { name: '治理任务', exact: true }).count() === 0
  check('VIEWER界面隐藏治理任务模块', hidden, { governancePanelAbsent: hidden })
  const viewerApi = await newAuthenticatedApiContext(viewerToken)
  const viewerList = await apiHelper(viewerApi, 'GET', '/api/v1/governance-tasks', undefined,
    'viewer_governance_forbidden', 403)
  check('VIEWER治理列表API返回403', viewerList.status === 403, { httpStatus: viewerList.status })
  await viewerApi.dispose()

  await logoutUi()
  state.creatorToken = await loginAs('creator')
  if (state.creatorApi) await state.creatorApi.dispose()
  state.creatorApi = await newAuthenticatedApiContext(state.creatorToken)
  const mainId = mainTask.task_id

  faultPlan.nextList = true
  const list503Promise = state.page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/governance-tasks' && response.status() === 503,
  { timeout: 15000 })
  await state.page.locator('#governance').getByRole('button', { name: '刷新任务', exact: true }).click()
  const list503 = await list503Promise
  await state.page.locator('#governance').getByRole('alert').waitFor({ state: 'visible', timeout: 10000 })
  const listRowsAfterFailure = await state.page.locator('#governance .task-table tbody tr').count()
  const emptyVisible = await state.page.getByText('当前筛选下没有治理任务。', { exact: true }).isVisible()
  check('列表读取503清除旧列表并显示错误',
    list503.status() === 503 && listRowsAfterFailure === 0 && emptyVisible, {
      status: list503.status(), rowsAfterFailure: listRowsAfterFailure, emptyStateVisible: emptyVisible,
    })
  await state.page.locator('#governance').getByRole('button', { name: '刷新任务', exact: true }).click()
  await state.page.locator('#governance .task-table tbody tr').first().waitFor({ state: 'visible', timeout: 15000 })
  report.faultInjection.recoveredList = true
  check('移除列表故障后刷新恢复', true, { rowsRestored: true })

  await openTaskByCode(mainTask.task_code)

  faultPlan.nextDetail = true
  const detail503Promise = state.page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/v1/governance-tasks/' + mainId && response.status() === 503,
  { timeout: 15000 })
  await state.page.locator('#governance .task-detail')
    .getByRole('button', { name: '重新加载详情', exact: true }).click()
  const detail503 = await detail503Promise
  await state.page.locator('#governance').getByRole('alert').waitFor({ state: 'visible', timeout: 10000 })
  const detailCount = await state.page.locator('#governance .task-detail').count()
  check('详情读取503清除旧详情并显示错误',
    detail503.status() === 503 && detailCount === 0, {
      status: detail503.status(), detailsAfterFailure: detailCount,
    })
  await state.page.locator('#governance').getByRole('button', { name: '刷新任务', exact: true }).click()
  await state.page.locator('#governance .task-detail h3').waitFor({ state: 'visible', timeout: 15000 })
  report.faultInjection.recoveredDetail = true
  check('移除详情故障后刷新恢复', true, { detailRestored: true })

  await doDesktopMobileEvidence()
  check('地图瓦片请求已拦截', report.expectedBlocked.osmTiles.interceptionInstalled, {
    interceptionInstalled: report.expectedBlocked.osmTiles.interceptionInstalled,
    intercepted: report.expectedBlocked.osmTiles.intercepted,
  })
  check('无未分类业务API HTTP错误', report.network.api.unexpectedHttpErrors.length === 0, {
    errors: report.network.api.unexpectedHttpErrors,
  })
  check('无业务API网络失败', report.network.api.requestFailures.length === 0, {
    failures: report.network.api.requestFailures,
  })
  check('无意外外部或静态资源错误', report.network.otherResourceErrors.length === 0, {
    errors: report.network.otherResourceErrors,
  })
  check('无意外浏览器console错误', report.consoleErrors.length === 0, { errors: report.consoleErrors })
  check('无前端运行时异常', report.pageErrors.length === 0, { errors: report.pageErrors })
  check('关键故障注入均恢复',
    report.faultInjection.list503 === 1 && report.faultInjection.detail503 === 1 &&
    report.faultInjection.recoveredList && report.faultInjection.recoveredDetail,
    report.faultInjection)
  await state.creatorApi.dispose()
  state.creatorApi = null
}

async function main() {
  try {
    await runAcceptance()
  } catch (error) {
    const message = String(error && error.message || 'unknown failure')
      .split(/[\r\n]/)[0].replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
      .replace(/password|credential|authorization|token|dsn/gi, '[redacted]').slice(0, 180)
    report.fatal = { name: String(error && error.name || 'Error').slice(0, 60), message }
  } finally {
    if (state.creatorApi) { try { await state.creatorApi.dispose() } catch (_) {} }
    if (state.context) { try { await state.context.close() } catch (_) {} }
    if (state.browser) { try { await state.browser.close() } catch (_) {} }
    report.finishedAt = new Date().toISOString()
    report.runner.exitCode = report.fatal || report.checks.some(item => !item.passed) ? 1 : 0
    try {
      const output = path.join(__dirname, 'm5_browser_acceptance.json')
      fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n', 'utf8')
      process.stdout.write(JSON.stringify(report, null, 2) + '\n')
    } catch (_) {
      process.stdout.write(JSON.stringify({
        fatal: { name: 'OutputError', message: 'QA report could not be written.' }, exitCode: 1,
      }) + '\n')
      report.runner.exitCode = 1
    }
    process.exitCode = report.runner.exitCode
  }
}
main()

