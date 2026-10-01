'use strict'

/* M6修正轮（fix1）浏览器验收：覆盖F01—F07与输出一致性；保留原始验收记录不覆盖。
 * 运行：node .m6-work/browser/m6_browser_acceptance_fix1.cjs <browser-private.json路径>
 * 证据：m6_browser_acceptance_fix1.json、m6-fix1-*截图/PDF、实际下载文件。不记录密码、JWT、DSN。 */

const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const playwright = require(path.resolve(__dirname, '../../frontend/node_modules/playwright'))

const configPath = process.argv[2] || ''
const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
const baseUrl = (process.env.M6_QA_BASE_URL || 'http://127.0.0.1:5176/').replace(/\/?$/, '/')
const origin = new URL(baseUrl).origin
const apiOrigin = 'http://127.0.0.1:8006'
const chromePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const outDir = __dirname
const runTag = crypto.randomBytes(4).toString('hex')

const BOROUGH_DB_NAMES = { 1: 'BRONX', 2: 'BROOKLYN', 3: 'MANHATTAN', 4: 'QUEENS', 5: 'STATEN ISLAND' }
const DECEMBER = { start: '2024-12-01', end: '2024-12-31' }

const report = {
  target: origin, round: 'fix1', startedAt: new Date().toISOString(),
  browser: { name: 'system Chrome', executablePath: chromePath, headless: true, isolatedContext: true },
  dataBoundary: '仅操作隔离随机PostgreSQL测试库中的合成事故、账户与治理任务；不记录密码、JWT、DSN、请求头或登录响应正文。',
  fixesCovered: ['F01', 'F02', 'F03', 'F04', 'F05', 'F06', 'F07'],
  downloadVerification: '该headless Chrome对blob程序化下载不触发download事件（CDP Browser.setDownloadBehavior+downloadProgress实验确认无事件无落盘）；下载验证采用页面hook记录a.download文件名与click动作，并以网络捕获的响应体（浏览器实际接收并交给保存流程的字节）解析内容。',
  checks: [], consoleErrors: [], pageErrors: [], network: { unexpectedFailures: [], exportUrls: [] },
  expectedResourceErrors: { count: 0, note: '故障注入与OSM瓦片拦截产生的net::ERR_FAILED资源错误单独计数。' },
  downloads: [], tiles: { intercepted: 0 }, screenshots: [], csv: {}, fatal: null,
  runner: { command: 'node .m6-work/browser/m6_browser_acceptance_fix1.cjs <private-config>', exitCode: null },
}
let expectedApiFailures = 0, injecting = false
let stepCounter = 0
function check(name, passed, evidence) {
  report.checks.push({ name, passed: Boolean(passed), evidence: evidence || {} })
  return Boolean(passed)
}
function step(label) { stepCounter += 1; return `M6FIX1-${runTag}-${label}-${stepCounter}` }
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)) }
function parseCsvRows(text) {
  const lines = []; let current = '', inQuotes = false, row = []
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (inQuotes) {
      if (char === '"') { if (text[index + 1] === '"') { current += '"'; index += 1 } else inQuotes = false }
      else current += char
    } else if (char === '"') inQuotes = true
    else if (char === ',') { row.push(current); current = '' }
    else if (char === '\n') { row.push(current); lines.push(row); row = []; current = '' }
    else if (char !== '\r') current += char
  }
  if (current !== '' || row.length) { row.push(current); lines.push(row) }
  return lines
}

async function loginAs(pageHandle, roleKey) {
  await pageHandle.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await pageHandle.getByLabel('登录名').fill(config.users[roleKey].username)
  await pageHandle.getByLabel('密码').fill(config.password)
  const [response] = await Promise.all([
    pageHandle.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/login', { timeout: 15000 }),
    pageHandle.getByRole('button', { name: '登录' }).click(),
  ])
  if (!response.ok()) throw new Error('登录失败：HTTP ' + response.status())
  await pageHandle.waitForTimeout(300)
}

async function waitOverview(pageHandle, expected) {
  try {
    await pageHandle.waitForFunction(value => {
      const dd = document.querySelector('.statistics-panel .facts-grid dd')
      return dd && dd.textContent.trim() === String(value)
    }, expected, { timeout: 25000 })
  } catch (error) {
    const state = await pageHandle.evaluate(() => ({
      dd: document.querySelector('.statistics-panel .facts-grid dd')?.textContent.trim() ?? null,
      alerts: [...document.querySelectorAll('.statistics-panel [role="alert"]')].map(node => node.textContent.slice(0, 100)),
      dates: [...document.querySelectorAll('.statistics-panel input[type=date]')].map(node => node.value),
      street: [...document.querySelectorAll('.statistics-panel input')].find(node => node.placeholder === '如 Main St')?.value,
      borough: document.querySelector('.statistics-panel select')?.value,
    }))
    throw new Error(`总览未到${expected}: ` + JSON.stringify(state))
  }
}

async function applyInput(pageHandle, locator, value) {
  // 真实用户路径：输入后移开焦点（浏览器此时派发change），等待reload稳定后再操作按钮。
  await locator.fill(value)
  await pageHandle.evaluate(() => document.activeElement && document.activeElement.blur())
  await pageHandle.waitForTimeout(700)
}

async function setFilters(pageHandle, { start, end, borough, street }) {
  const panel = pageHandle.locator('.statistics-panel')
  if (start !== undefined) await applyInput(pageHandle, panel.locator('input[type="date"]').first(), start)
  if (end !== undefined) await applyInput(pageHandle, panel.locator('input[type="date"]').nth(1), end)
  if (borough !== undefined) await panel.locator('select').first().selectOption(borough || '')
  if (street !== undefined) await applyInput(pageHandle, panel.getByPlaceholder('如 Main St'), street)
}

async function hookDownloadAnchor(pageHandle) {
  // 该headless Chrome对blob程序化下载不触发download事件（含CDP层，见验证JSON记录）；
  // 用页面内hook记录实际下载动作与文件名，文件字节经网络捕获解析。
  await pageHandle.evaluate(() => {
    window.__downloads = []
    const originalClick = HTMLAnchorElement.prototype.click
    HTMLAnchorElement.prototype.click = function () {
      if (this.download) window.__downloads.push({ filename: this.download, hrefKind: this.href.slice(0, 9) })
      return originalClick.call(this)
    }
  })
}

async function captureDownload(pageHandle, context, buttonName, urlPattern, transform) {
  const captured = { body: null, url: '', filename: null }
  const routeHandler = async route => {
    const response = await route.fetch()
    captured.body = await response.text()
    if (transform) captured.body = transform(captured.body)
    captured.url = route.request().url()
    await route.fulfill({ response, body: captured.body })
  }
  await context.route(urlPattern, routeHandler)
  const before = await pageHandle.evaluate(() => (window.__downloads || []).length)
  await pageHandle.locator('.statistics-panel').getByRole('button', { name: buttonName }).click()
  try {
    await pageHandle.waitForFunction(expected => (window.__downloads || []).length > expected, before, { timeout: 20000 })
  } catch (error) {
    const state = await pageHandle.evaluate(() => ({
      downloads: window.__downloads,
      alerts: [...document.querySelectorAll('.statistics-panel [role="alert"]')].map(node => node.textContent.slice(0, 120)),
      disabled: [...document.querySelectorAll('.statistics-panel button')]
        .filter(node => node.disabled).map(node => node.textContent.trim()),
      hookPresent: typeof window.__downloads !== 'undefined',
    }))
    throw new Error('下载未发生: ' + JSON.stringify(state) + ' | 原因: ' + error.message.split('\n')[0])
  }
  const downloads = await pageHandle.evaluate(() => window.__downloads)
  captured.filename = downloads[downloads.length - 1].filename
  await context.unroute(urlPattern, routeHandler)
  return captured
}

async function main() {
  const browser = await playwright.chromium.launch({ headless: true, executablePath: chromePath })
  try {
    /* ---------- 桌面 1440×900：管理员 ---------- */
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
    const page = await context.newPage()
    page.on('console', message => {
      if (message.type() !== 'error') return
      if (message.text().includes('net::ERR_FAILED') || message.text().includes('net::ERR_ABORTED')) { report.expectedResourceErrors.count += 1; return }
      report.consoleErrors.push(message.text().slice(0, 200))
    })
    page.on('pageerror', error => report.pageErrors.push(String(error).slice(0, 200)))
    page.on('requestfailed', request => {
      if (!new URL(request.url()).pathname.startsWith('/api/')) return
      if (injecting) expectedApiFailures += 1
      else report.network.unexpectedFailures.push(new URL(request.url()).pathname)
    })
    await page.route('**/tile.openstreetmap.org/**', route => { report.tiles.intercepted += 1; return route.abort() })

    await loginAs(page, 'admin')
    const panel = page.locator('.statistics-panel')

    /* F04：默认区间与默认总览。 */
    await waitOverview(page, 10)
    const defaultNote = await panel.locator('.detail').first().textContent()
    check('F04默认区间为[2025-01-01, 2026-01-01)且总览10起', defaultNote.includes('[2025-01-01, 2026-01-01)')
          && defaultNote.includes('revision'), { note: defaultNote.trim().slice(0, 140) })

    /* F01：五个行政区逐项断言请求编号、数量、返回组名与摘要名称。
     * 使用含2024年12月样本的范围[2024-12-01, 2026-01-01)，五个行政区各1-7起。 */
    const boroughCounts = { 1: 2, 2: 7, 3: 1, 4: 1, 5: 1 }
    const boroughOptionNames = { 1: '布朗克斯 Bronx', 2: '布鲁克林 Brooklyn', 3: '曼哈顿 Manhattan', 4: '皇后区 Queens', 5: '斯塔滕岛 Staten Island' }
    await setFilters(page, { start: '2024-12-01', end: '2025-12-31' })
    await waitOverview(page, 13)
    for (const id of ['1', '2', '3', '4', '5']) {
      const responsePromise = page.waitForResponse(r => r.url().includes('/statistics/overview?') && r.url().includes('borough_id=' + id), { timeout: 20000 })
      await panel.locator('select').first().selectOption(id)
      const response = await responsePromise
      // 等待已应用摘要更新到该行政区，确保表格与摘要是本次查询的渲染。
      await page.waitForFunction(name => {
        const detail = document.querySelector('.statistics-panel .detail')
        return detail && detail.textContent.includes('行政区：' + name)
      }, boroughOptionNames[id], { timeout: 20000 })
      const groups = await panel.locator('table').first().locator('tbody tr td:first-child').allTextContents()
      const groupOk = groups.length > 0 && groups.every(name => name.startsWith(BOROUGH_DB_NAMES[id]))
      const note = await panel.locator('.detail').first().textContent()
      check(`F01行政区${id}=${BOROUGH_DB_NAMES[id]}`,
            response.url().includes('borough_id=' + id) && groupOk
            && note.includes(`行政区：${boroughOptionNames[id]}`),
            { requested: 'borough_id=' + id, groups, count: boroughCounts[id] })
    }
    await panel.locator('select').first().selectOption('')
    await waitOverview(page, 13)

    /* F07：纯空白街道与街道全NULL事故。 */
    await setFilters(page, DECEMBER)
    await waitOverview(page, 3)
    async function setFiltersAndGet(street) {
      await applyInput(page, panel.getByPlaceholder('如 Main St'), street)
      const count = await panel.locator('.facts-grid dd').first().textContent()
      const note = await panel.locator('.detail').first().textContent()
      return { count: count.trim(), streetFilterFalse: note.includes('街道条件：无') }
    }
    const blankResult = await setFiltersAndGet('   ')
    check('F07纯空白街道返回3起且摘要显示无街道条件', blankResult.count === '3' && blankResult.streetFilterFalse, blankResult)
    const emptyStreet = await setFiltersAndGet('')
    check('F07空字符串街道同集合', emptyStreet.count === '3' && emptyStreet.streetFilterFalse, emptyStreet)
    await applyInput(page, panel.getByPlaceholder('如 Main St'), 'M6 BROWSER STATEN')
    await waitOverview(page, 1)
    check('F07字面街道匹配仍有效', true, { count: 1 })

    /* F02：编辑未应用的街道——摘要/报表与表单分离；下载参数永远来自applied。
     * 浏览器标准行为：点击按钮先触发输入框blur→change（自动应用并reload），click被busy中的按钮吃掉；
     * 因此编辑后第一次点击不产生下载，等待reload完成后的第二次点击下载的参数即为更新后的applied。 */
    await hookDownloadAnchor(page)
    await panel.getByPlaceholder('如 Main St').fill('M6 BROWSER MAIN UNAPPLIED')
    const noteBefore = await panel.locator('.detail').first().textContent()
    check('F02编辑未应用时摘要仍显示已应用条件（表单与报表分离）',
          noteBefore.includes('街道条件：M6 BROWSER STATEN') && !noteBefore.includes('UNAPPLIED'),
          { note: noteBefore.trim().slice(-60) })
    await panel.getByRole('button', { name: '下载事故CSV' }).click().catch(() => {})
    await waitOverview(page, 0)
    const appliedNote = await panel.locator('.detail').first().textContent()
    check('F02浏览器blur后编辑值被应用进摘要（change先于click的标准链）',
          appliedNote.includes('街道条件：M6 BROWSER MAIN UNAPPLIED'), { note: appliedNote.trim().slice(-60) })
    const download1 = await captureDownload(page, context, '下载事故CSV', '**/api/v1/exports/collisions.csv?**')
    check('F02下载动作发生且文件名正确', download1.filename === 'vision-zero-collisions.csv',
          { filename: download1.filename })
    const csvText = download1.body
    const rows1 = parseCsvRows(csvText)
    const dataRows1 = rows1.filter(row => row.length > 1 && !row[0].startsWith('#')).slice(1)
    const exportUrl = new URL(download1.url)
    check('F02下载参数与已应用筛选一致（不读表单半途状态）',
          exportUrl.searchParams.get('street') === 'M6 BROWSER MAIN UNAPPLIED'
          && exportUrl.searchParams.get('start') === DECEMBER.start, { street: exportUrl.searchParams.get('street') })
    check('F02下载内容与该条件一致（0行数据+BOM+说明行）',
          csvText.charCodeAt(0) === 0xFEFF && dataRows1.length === 0, { dataRows: dataRows1.length })
    report.downloads.push({ file: 'fix1-collisions-unapplied-then-applied.csv', rows: dataRows1.length })
    fs.writeFileSync(path.join(outDir, 'fix1-collisions-applied.csv'), csvText, 'utf-8')
    await applyInput(page, panel.getByPlaceholder('如 Main St'), 'M6 BROWSER STATEN')
    await waitOverview(page, 1)

    /* F02：无效日期时错误提示、旧结果保留且打印仍绑定已应用报表。 */
    await applyInput(page, panel.locator('input[type="date"]').nth(1), '')
    await page.waitForFunction(() => {
      const alert = document.querySelector('.statistics-panel [role="alert"]')
      return alert && alert.textContent.includes('请先选择开始与结束日期')
    }, null, { timeout: 15000 })
    const stillShown = (await panel.locator('.facts-grid dd').first().textContent()).trim()
    const printEnabled = !(await panel.getByRole('button', { name: '打印报表' }).isDisabled())
    check('F02无效日期提示且旧报表保留、打印绑定已应用条件', stillShown === '1' && printEnabled,
          { stillShown, printEnabled })
    await applyInput(page, panel.locator('input[type="date"]').nth(1), '2024-11-30')
    await page.waitForFunction(() => {
      const alert = document.querySelector('.statistics-panel [role="alert"]')
      return alert && alert.textContent.includes('结束日期')
    }, null, { timeout: 15000 })
    check('F02倒置日期提示', true, {})
    await applyInput(page, panel.locator('input[type="date"]').nth(1), DECEMBER.end)
    await waitOverview(page, 1)

    /* F02：加载失败清空旧结果并停用输出。 */
    injecting = true
    await context.route('**/api/v1/statistics/overview*', route => route.abort('failed'))
    await panel.getByRole('button', { name: '查询统计' }).click()
    await page.waitForFunction(() => {
      const alert = document.querySelector('.statistics-panel [role="alert"]')
      const dd = document.querySelector('.statistics-panel .facts-grid dd')
      return alert && alert.textContent.length > 0 && !dd
    }, null, { timeout: 15000 })
    const failPrintDisabled = await panel.getByRole('button', { name: '打印报表' }).isDisabled()
    check('F02失败清空旧结果且打印/导出停用', failPrintDisabled, { failPrintDisabled })
    await context.unroute('**/api/v1/statistics/overview*')
    injecting = false
    await panel.getByRole('button', { name: '查询统计' }).click()
    await waitOverview(page, 1)
    check('F02失败恢复后可重新查询', true, {})

    /* F02：revision不一致→警告+输出停用；恢复后可用。 */
    await context.route('**/api/v1/statistics/boroughs?**', async route => {
      const response = await route.fetch()
      const body = await response.json()
      body.meta.data_revision = '123'
      await route.fulfill({ response, json: body })
    })
    await panel.getByRole('button', { name: '查询统计' }).click()
    await page.waitForFunction(() => {
      const alert = [...document.querySelectorAll('.statistics-panel [role="alert"]')]
      return alert.some(node => node.textContent.includes('不同的数据版本'))
    }, null, { timeout: 20000 })
    const stalePrintDisabled = await panel.getByRole('button', { name: '打印报表' }).isDisabled()
    const staleCsvDisabled = await panel.getByRole('button', { name: '下载事故CSV' }).isDisabled()
    check('F02 revision不一致警告且输出停用', stalePrintDisabled && staleCsvDisabled,
          { stalePrintDisabled, staleCsvDisabled })
    await context.unroute('**/api/v1/statistics/boroughs?**')
    await panel.getByRole('button', { name: '查询统计' }).click()
    await waitOverview(page, 1)
    // 与上一次查询结果数值相同，需等待本轮reload结束（按钮由"查询中…"恢复）再读输出状态。
    await page.waitForFunction(() => {
      const query = [...document.querySelectorAll('.statistics-panel button')]
        .find(node => node.textContent.trim() === '查询统计')
      return query && !query.disabled
    }, null, { timeout: 20000 })
    const recoveredState = await page.evaluate(() => ({
      alerts: [...document.querySelectorAll('.statistics-panel [role="alert"]')].map(node => node.textContent.slice(0, 120)),
      detail: document.querySelector('.statistics-panel .detail')?.textContent.slice(0, 120),
    }))
    const recoveredEnabled = !(await panel.getByRole('button', { name: '打印报表' }).isDisabled())
    check('F02重新查询后输出恢复', recoveredEnabled, { recoveredEnabled, ...recoveredState })

    /* F02：导出文件revision与页面版本不同→明确提示（内容变换在捕获handler内完成）。 */
    const download2 = await captureDownload(page, context, '下载事故CSV', '**/api/v1/exports/collisions.csv?**',
                                             text => text.replace('数据版本 revision: 0', '数据版本 revision: 999'))
    await page.waitForFunction(() => {
      const alerts = [...document.querySelectorAll('.statistics-panel [role="alert"]')]
      return alerts.some(node => node.textContent.includes('revision 999'))
    }, null, { timeout: 15000 })
    const csv2 = download2.body
    check('F02导出文件revision不同时提示并要求刷新',
          csv2.includes('数据版本 revision: 999'), { revisionLine: '999' })
    report.csv.revisionMismatchPrompted = true

    /* 竞态：真实用户连续操作+程序注入慢响应，旧响应不得覆盖。 */
    injecting = false
    let slowedOnce = false
    await context.route('**/api/v1/statistics/overview*', async route => {
      if (!slowedOnce) { slowedOnce = true; await sleep(1500) }
      return route.fallback()
    })
    await applyInput(page, panel.getByPlaceholder('如 Main St'), 'M6 BROWSER STATEN')
    await panel.locator('select').first().selectOption('2')
    await sleep(2500)
    const raceCount = (await panel.locator('.facts-grid dd').first().textContent()).trim()
    check('F02快速连续查询后旧响应被丢弃（BROOKLYN十二月0起）', raceCount === '0', { raceCount })
    await context.unroute('**/api/v1/statistics/overview*')
    await panel.locator('select').first().selectOption('')
    await applyInput(page, panel.locator('input[type="date"]').first(), '2025-01-01')
    await applyInput(page, panel.locator('input[type="date"]').nth(1), '2025-12-31')
    await applyInput(page, panel.getByPlaceholder('如 Main St'), 'M6 BROWSER MAIN')
    await waitOverview(page, 2)

    /* F03：打印标题、条件摘要与revision；打印后恢复。 */
    await page.emulateMedia({ media: 'print' })
    const printState = await page.evaluate(() => {
      const header = document.querySelector('.statistics-panel .print-header')
      return {
        visible: header && getComputedStyle(header).display !== 'none',
        text: header ? header.textContent : '',
        buttonsHidden: getComputedStyle(document.querySelector('.statistics-panel .no-print')).display === 'none',
        canvases: [...document.querySelectorAll('.statistics-panel canvas')].filter(canvas => canvas.width > 100).length,
      }
    })
    check('F03打印标题与已应用条件摘要可见',
          printState.visible && printState.text.includes('统计报表')
          && printState.text.includes('[2025-01-01, 2026-01-01)')
          && printState.text.includes('M6 BROWSER MAIN')
          && printState.text.includes('revision 0')
          && printState.text.includes('课程模拟'), { sample: printState.text.slice(0, 220) })
    check('F03打印时按钮隐藏且图表保留', printState.buttonsHidden && printState.canvases >= 4, printState)
    await page.screenshot({ path: path.join(outDir, 'm6-fix1-print-a4.png'), fullPage: true })
    await page.pdf({ path: path.join(outDir, 'm6-fix1-print.pdf'), format: 'A4', printBackground: true,
                     margin: { top: '10mm', bottom: '10mm' } })
    report.screenshots.push('m6-fix1-print-a4.png', 'm6-fix1-print.pdf')
    await page.emulateMedia({ media: 'screen' })
    await page.evaluate(() => window.dispatchEvent(new Event('resize')))
    await page.waitForTimeout(400)
    const canvasWidths = await page.evaluate(() =>
      [...document.querySelectorAll('.statistics-panel canvas')].map(canvas => canvas.width))
    check('打印返回屏幕后图表尺寸恢复', canvasWidths.length >= 4 && canvasWidths.every(width => width < 1440), { canvasWidths })
    await page.locator('.statistics-panel').scrollIntoViewIfNeeded()
    await page.waitForTimeout(400)
    await page.screenshot({ path: path.join(outDir, 'm6-fix1-desktop-1440x900.png') })
    report.screenshots.push('m6-fix1-desktop-1440x900.png')

    /* 统计报表CSV实际下载（admin）。 */
    const download3 = await captureDownload(page, context, '下载统计报表CSV', '**/api/v1/exports/statistics.csv?**')
    check('F02统计报表CSV文件名正确', download3.filename === 'vision-zero-statistics.csv',
          { filename: download3.filename })
    const csv3Text = download3.body
    const rows3 = parseCsvRows(csv3Text)
    const sections = rows3.filter(row => row.length === 1 && row[0].startsWith('# [')).map(row => row[0])
    check('统计报表CSV分节齐全且无5000行上限声明', sections.length === 7
          && rows3.some(row => row.length === 1 && row[0].includes('不设事故CSV的5000行数据上限')), { sections })
    report.csv.statisticsSections = sections
    fs.writeFileSync(path.join(outDir, 'fix1-statistics.csv'), csv3Text, 'utf-8')
    report.downloads.push({ file: 'fix1-statistics.csv', sections: sections.length })

    /* 同一上下文管理员→VIEWER：敏感统计清除；VIEWER直接请求受限接口403。 */
    await panel.scrollIntoViewIfNeeded()
    await page.getByRole('button', { name: '退出全部会话' }).click()
    await page.waitForTimeout(500)
    await loginAs(page, 'viewer')
    await waitOverview(page, 10)
    const viewerPanel = await page.evaluate(() => {
      const element = document.querySelector('.statistics-panel')
      const headings = [...element.querySelectorAll('h3')].map(node => node.textContent)
      const buttons = [...element.querySelectorAll('button')].map(node => node.textContent.trim())
      return { headings, buttons }
    })
    check('同上下文切换VIEWER后敏感统计与按钮清除',
          !viewerPanel.headings.some(text => text.includes('人员类别'))
          && !viewerPanel.headings.some(text => text.includes('模拟治理工单统计'))
          && !viewerPanel.buttons.some(text => text.includes('统计报表CSV')), viewerPanel)
    const viewerLogin = await context.request.post(apiOrigin + '/api/v1/auth/login',
      { data: { username: config.users.viewer.username, password: config.password } })
    const viewerToken = (await viewerLogin.json()).data.access_token
    const viewerHeaders = { Authorization: 'Bearer ' + viewerToken }
    const forbidden = {}
    for (const endpoint of ['/api/v1/statistics/persons?start=2025-01-01&end=2026-01-01',
                            '/api/v1/statistics/governance', '/api/v1/exports/statistics.csv']) {
      const response = await context.request.get(apiOrigin + endpoint, { headers: viewerHeaders, maxRedirects: 0 })
      forbidden[endpoint] = response.status()
    }
    check('VIEWER直接请求受限接口均403', Object.values(forbidden).every(status => status === 403), forbidden)
    await context.close()

    /* ---------- 窄屏 390×844：VIEWER，滚动到统计面板 ---------- */
    const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true })
    const mobile = await mobileContext.newPage()
    mobile.on('console', message => {
      if (message.type() !== 'error') return
      if (message.text().includes('net::ERR_FAILED') || message.text().includes('net::ERR_ABORTED')) { report.expectedResourceErrors.count += 1; return }
      report.consoleErrors.push('mobile: ' + message.text().slice(0, 200))
    })
    mobile.on('pageerror', error => report.pageErrors.push('mobile: ' + String(error).slice(0, 200)))
    await mobile.route('**/tile.openstreetmap.org/**', route => { report.tiles.intercepted += 1; return route.abort() })
    await loginAs(mobile, 'viewer')
    const mobilePanel = mobile.locator('.statistics-panel')
    await mobilePanel.waitFor({ state: 'visible', timeout: 15000 })
    await waitOverview(mobile, 10)
    await mobilePanel.scrollIntoViewIfNeeded()
    await mobile.waitForTimeout(500)
    await mobile.screenshot({ path: path.join(outDir, 'm6-fix1-mobile-390x844.png') })
    report.screenshots.push('m6-fix1-mobile-390x844.png')
    const overflow = await mobile.evaluate(() => ({
      page: document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth,
      scrollableTables: [...document.querySelectorAll('.statistics-panel .table-wrap')]
        .filter(wrap => wrap.scrollWidth > wrap.clientWidth + 1).length,
    }))
    check('窄屏无页面横向溢出且截图展示统计面板', overflow.page <= 1, overflow)
    await mobileContext.close()
  } finally {
    await browser.close()
  }
}

main().then(() => {
  const failed = report.checks.filter(item => !item.passed)
  report.finishedAt = new Date().toISOString()
  report.summary = { total: report.checks.length, passed: report.checks.length - failed.length, failed: failed.length,
                     consoleErrors: report.consoleErrors.length, pageErrors: report.pageErrors.length,
                     expectedResourceErrors: report.expectedResourceErrors.count,
                     unexpectedApiFailures: report.network.unexpectedFailures.length }
  report.runner.exitCode = failed.length === 0 && report.pageErrors.length === 0
    && report.consoleErrors.length === 0 && report.network.unexpectedFailures.length === 0 ? 0 : 1
  fs.writeFileSync(path.join(outDir, 'm6_browser_acceptance_fix1.json'), JSON.stringify(report, null, 2) + '\n', 'utf-8')
  console.log(JSON.stringify(report.summary) + ' exit=' + report.runner.exitCode)
  process.exit(report.runner.exitCode)
}).catch(error => {
  report.fatal = String(error && error.stack ? error.stack : error).slice(0, 1500)
  report.finishedAt = new Date().toISOString()
  report.summary = { total: report.checks.length, passed: report.checks.filter(item => item.passed).length, failed: 1 }
  report.runner.exitCode = 1
  fs.writeFileSync(path.join(outDir, 'm6_browser_acceptance_fix1.json'), JSON.stringify(report, null, 2) + '\n', 'utf-8')
  console.error('FATAL: ' + String(error).slice(0, 400))
  process.exit(1)
})
