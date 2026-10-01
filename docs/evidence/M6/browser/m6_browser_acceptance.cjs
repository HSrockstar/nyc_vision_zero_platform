'use strict'

/* M6统计整合浏览器验收：仅操作隔离随机PostgreSQL测试库中的合成数据。
 * 运行：node .m6-work/browser/m6_browser_acceptance.cjs <browser-private.json路径>
 * 证据：m6_browser_acceptance.json、截图、打印PDF与下载CSV摘要；不记录密码、JWT、DSN。 */

const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const playwright = require(path.resolve(__dirname, '../../frontend/node_modules/playwright'))

const configPath = process.argv[2] || ''
const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
const baseUrl = (process.env.M6_QA_BASE_URL || 'http://127.0.0.1:5176/').replace(/\/?$/, '/')
const origin = new URL(baseUrl).origin
const chromePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const outDir = __dirname
const runTag = crypto.randomBytes(4).toString('hex')

const report = {
  target: origin, startedAt: new Date().toISOString(),
  browser: { name: 'system Chrome', executablePath: chromePath, headless: true, isolatedContext: true },
  dataBoundary: '仅操作隔离随机PostgreSQL测试库中的合成事故、账户与治理任务；不记录密码、JWT、DSN、请求头或登录响应正文。',
  synthetic: config.hand_computed_january ? 'hand-computed January fixture' : 'unknown',
  checks: [], consoleErrors: [], pageErrors: [], network: { api: [], unexpectedFailures: [], responses: [] },
  expectedResourceErrors: { count: 0, note: '故障注入与OSM瓦片拦截产生的net::ERR_FAILED资源错误单独计数，不计入JS错误。' },
  tiles: { intercepted: 0 }, csv: {}, screenshots: [], viewports: {}, fatal: null,
  runner: { command: 'node .m6-work/browser/m6_browser_acceptance.cjs <private-config>', exitCode: null },
}
let expectedApiFailures = 0
let injecting = false
let stepCounter = 0
function check(name, passed, evidence) {
  report.checks.push({ name, passed: Boolean(passed), evidence: evidence || {} })
  return Boolean(passed)
}
function step(label) { stepCounter += 1; return `M6QA-${runTag}-${label}-${stepCounter}` }
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)) }

const page = { handle: null }
let context = null

async function apiCapture(pageHandle, pattern) {
  const captured = { bodies: [] }
  await pageHandle.route(pattern, async route => {
    const response = await route.fetch()
    const body = await response.text()
    captured.bodies.push(body)
    await route.fulfill({ response, body })
  })
  return captured
}

function parseCsvRows(text) {
  const lines = []
  let current = '', inQuotes = false, row = []
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (inQuotes) {
      if (char === '"') {
        if (text[index + 1] === '"') { current += '"'; index += 1 } else inQuotes = false
      } else current += char
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

async function waitForOverview(pageHandle, expectedCount) {
  const panel = pageHandle.locator('.statistics-panel')
  await panel.waitFor({ state: 'visible', timeout: 15000 })
  const target = `当前范围总览`
  await panel.getByText(target).waitFor({ timeout: 20000 })
  await pageHandle.waitForFunction(expected => {
    const dds = [...document.querySelectorAll('.statistics-panel .facts-grid dd')]
    return dds.length > 0 && dds[0].textContent.trim() === String(expected)
  }, expectedCount, { timeout: 20000 })
}

async function setFilters(pageHandle, { start, end, borough, street }) {
  const panel = pageHandle.locator('.statistics-panel')
  const startInput = panel.locator('input[type="date"]').first()
  const endInput = panel.locator('input[type="date"]').nth(1)
  await startInput.fill(start)
  await endInput.fill(end)
  if (borough !== undefined) {
    await panel.locator('select').first().selectOption(borough || '')
  }
  if (street !== undefined) {
    await panel.getByPlaceholder('如 Main St').fill(street)
  }
  await panel.getByRole('button', { name: '查询统计' }).click()
}

async function main() {
  const browser = await playwright.chromium.launch({ headless: true, executablePath: chromePath })
  report.viewports.desktop = { width: 1440, height: 900 }
  report.viewports.mobile = { width: 390, height: 844 }
  try {
    /* ---------- 桌面端 1440×900，管理员 ---------- */
    context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
    const pageHandle = await context.newPage()
    page.handle = pageHandle
    pageHandle.on('console', message => {
      if (message.type() !== 'error') return
      if (message.text().includes('net::ERR_FAILED') || message.text().includes('net::ERR_ABORTED')) {
        report.expectedResourceErrors.count += 1
        return
      }
      report.consoleErrors.push(message.text().slice(0, 200))
    })
    pageHandle.on('pageerror', error => report.pageErrors.push(String(error).slice(0, 200)))
    pageHandle.on('requestfailed', request => {
      const url = new URL(request.url())
      if (!url.pathname.startsWith('/api/')) return
      if (injecting) expectedApiFailures += 1
      else report.network.unexpectedFailures.push(url.pathname)
    })
    pageHandle.on('response', response => {
      const url = new URL(response.url())
      if (url.pathname.startsWith('/api/')) {
        report.network.responses.push({ path: url.pathname, status: response.status() })
      }
    })
    await pageHandle.route('**/tile.openstreetmap.org/**', route => {
      report.tiles.intercepted += 1
      return route.abort()
    })

    await loginAs(pageHandle, 'admin')
    const panel = pageHandle.locator('.statistics-panel')
    await panel.waitFor({ state: 'visible', timeout: 15000 })
    check('统计面板已渲染', true)
    // 默认范围2025全年：合成库共10起事故（1月3起+2月7起）。
    await waitForOverview(pageHandle, 10)
    check('默认全年总览=10起事故', true, { expected: 10 })
    const revisionText = await panel.locator('.detail').first().textContent()
    check('显示统计区间与revision', /统计区间 \[2025-01-01, 2026-01-02\)/.test(revisionText) && /revision \d+/.test(revisionText),
          { note: revisionText.trim().slice(0, 160) })

    // 图表：4个canvas且宽度>0。
    await pageHandle.waitForFunction(() => document.querySelectorAll('.statistics-panel canvas').length >= 4,
                                     null, { timeout: 20000 })
    const canvasInfo = await pageHandle.evaluate(() =>
      [...document.querySelectorAll('.statistics-panel canvas')].map(c => ({ w: c.width, h: c.height })))
    check('四张ECharts图表已渲染', canvasInfo.length >= 4 && canvasInfo.every(c => c.w > 100), canvasInfo)

    // 行政区表：BRONX（合成库borough 1）+ 未知行政区。
    const boroughCells = await panel.locator('table').first().locator('tbody tr').allTextContents()
    check('行政区表含BRONX与未知行政区组', boroughCells.some(t => /bronx/i.test(t))
          && boroughCells.some(t => t.includes('未知行政区')), { rows: boroughCells.length })

    // 月度表：2025-01 → 3起。
    const monthTable = await pageHandle.evaluate(() => {
      const headings = [...document.querySelectorAll('.statistics-panel .print-block h3')]
      const block = headings.find(h => h.textContent.includes('月度趋势'))?.closest('.print-block')
      const rows = [...block.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))
      return rows
    })
    const january = monthTable.find(row => row[0] === '2025-01')
    const february = monthTable.find(row => row[0] === '2025-02')
    check('月度表2025-01=3、2025-02=7', january && january[1] === '3' && february && february[1] === '7',
          { january, february })
    check('月度覆盖说明展示且不补零（默认范围13个月）', monthTable.length === 13
          && monthTable.every(row => row[4].length > 0), { months: monthTable.length })

    // 手算夹具：筛选1月。
    await setFilters(pageHandle, { start: '2025-01-01', end: '2025-01-31' })
    await waitForOverview(pageHandle, 3)
    const overviewValues = await pageHandle.evaluate(() => {
      const dds = [...document.querySelectorAll('.statistics-panel .facts-grid dd')]
      const dts = [...document.querySelectorAll('.statistics-panel .facts-grid dt')]
      return { values: dds.map(dd => dd.textContent.trim()), labels: dts.map(dt => dt.textContent.trim()) }
    })
    check('手算总览：3起/受伤4/死亡1', overviewValues.values[0] === '3' && overviewValues.values[1] === '4'
          && overviewValues.values[2] === '1', overviewValues.values.slice(0, 3))
    check('受伤/死亡缺失事故数在标签中展示',
          /缺失 1 起事故/.test(overviewValues.labels[1]) && /缺失 1 起事故/.test(overviewValues.labels[2]),
          overviewValues.labels.slice(1, 3))
    check('手算明细：人员4/车辆5/有坐标2缺1', overviewValues.values[3] === '4' && overviewValues.values[4] === '5'
          && overviewValues.values[5] === '2 / 1', overviewValues.values.slice(3, 6))
    check('归属0起且覆盖率0.000000', overviewValues.values[6] === '0' && overviewValues.values[7] === '0.000000',
          overviewValues.values.slice(6, 8))

    // 原因表：A涉及2起、无原因1起；Top N 标识。
    const factorBlockText = await pageHandle.evaluate(() => {
      const block = [...document.querySelectorAll('.statistics-panel .print-block')]
        .find(candidate => candidate.querySelector('h3')?.textContent.includes('事故原因分析'))
      if (!block) return null
      return { title: block.querySelector('h3').textContent.trim(),
               rows: [...block.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim())) }
    })
    check('原因TopN标识', factorBlockText && factorBlockText.title.includes('前10'), { title: factorBlockText ? factorBlockText.title : null })
    const factorA = factorBlockText ? factorBlockText.rows.find(row => row[0] === 'M6 BROWSER FACTOR A') : null
    const noFactor = factorBlockText ? factorBlockText.rows.find(row => row[0] === '无原因记录的事故') : null
    check('原因A=2起且无原因事故=1', factorA && factorA[1] === '2' && noFactor && noFactor[1] === '1',
          { factorA, noFactor })

    // 车型表：A记录3/事故2；未知车型组存在。
    const vehicleRows = await pageHandle.evaluate(() => {
      const block = [...document.querySelectorAll('.statistics-panel .print-block')]
        .find(candidate => candidate.querySelector('h3')?.textContent.includes('车辆类型分析'))
      if (!block) return null
      return [...block.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))
    })
    const typeARow = vehicleRows ? vehicleRows.find(row => row[0] === 'M6 BROWSER TYPE A') : null
    const unknownRow = vehicleRows ? vehicleRows.find(row => row[0] === '未知车型') : null
    check('车型A记录3/事故2且未知组保留', typeARow && typeARow[1] === '3' && typeARow[2] === '2'
          && Boolean(unknownRow), { typeARow, unknownRow })

    // 人员表（管理员可见）。
    const personRows = await pageHandle.evaluate(() => {
      const block = [...document.querySelectorAll('.statistics-panel .print-block')]
        .find(candidate => candidate.querySelector('h3')?.textContent.includes('人员类别'))
      if (!block) return null
      return [...block.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))
    })
    check('人员明细口径表含4组', personRows && personRows.length === 4
          && personRows.some(row => row[0] === 'driver' && row[1] === 'Killed')
          && personRows.some(row => row[0] === '未知类别' && row[1] === '未知状态'), { rows: personRows })

    // 治理统计（管理员可见）。
    const governanceText = await pageHandle.evaluate(() => {
      const block = [...document.querySelectorAll('.statistics-panel .print-block')]
        .find(candidate => candidate.querySelector('h3')?.textContent.includes('模拟治理工单统计'))
      return block ? block.textContent : ''
    })
    check('治理统计显示总数3、未分配单列与处理情况', governanceText.includes('工单总数：3')
          && governanceText.includes('未分配') && governanceText.includes('处理情况'),
          { sample: governanceText.slice(0, 240) })

    /* ---------- CSV导出（路由捕获响应体） ---------- */
    const collisionsCapture = await apiCapture(pageHandle, '**/api/v1/exports/collisions.csv*')
    await panel.getByRole('button', { name: '下载事故CSV' }).click()
    await pageHandle.waitForTimeout(1200)
    const collisionsCsv = collisionsCapture.bodies[0]
    check('事故CSV已请求', Boolean(collisionsCsv), { bytes: collisionsCsv ? collisionsCsv.length : 0 })
    if (collisionsCsv) {
      const bomPresent = collisionsCsv.charCodeAt(0) === 0xFEFF
      const rows = parseCsvRows(collisionsCsv)
      const dataRows = rows.filter(row => row.length > 1 && !row[0].startsWith('#'))
      const comments = rows.filter(row => row.length === 1 && row[0].startsWith('#'))
      report.csv.collisions = { bom: bomPresent, commentLines: comments.map(line => line[0].slice(0, 90)),
                                dataRows: dataRows.length,
                                header: dataRows[0] ? dataRows[0].join(',').slice(0, 120) : '' }
      check('事故CSV: BOM+说明行+3数据行', bomPresent && dataRows.length === 4 && comments.length >= 5,
            { dataRows: dataRows.length - 1, comments: comments.length })
      check('事故CSV含排他区间与revision说明',
            comments.some(line => line[0].includes('[2025-01-01, 2025-02-01)'))
            && comments.some(line => line[0].includes('revision')), {})
      const januaryRows = dataRows.slice(1).filter(row => row[1] === '2025-01-05' || row[1] === '2025-01-06' || row[1] === '2025-01-07')
      check('事故CSV按日期升序且含3起1月事故', januaryRows.length === 3
            && dataRows.slice(1)[0][1] === '2025-01-05', {})
      const c3 = dataRows.slice(1).find(row => row[1] === '2025-01-07')
      const injuredIndex = dataRows[0].indexOf('persons_injured')
      const killedIndex = dataRows[0].indexOf('persons_killed')
      check('事故CSV中NULL导出为空字段', c3 && c3[injuredIndex] === '' && c3[killedIndex] === '', {})
    }
    const statisticsCapture = await apiCapture(pageHandle, '**/api/v1/exports/statistics.csv*')
    await panel.getByRole('button', { name: '下载统计报表CSV' }).click()
    await pageHandle.waitForTimeout(1200)
    const statisticsCsv = statisticsCapture.bodies[0]
    if (statisticsCsv) {
      const rows = parseCsvRows(statisticsCsv)
      const sections = rows.filter(row => row.length === 1 && row[0].startsWith('# [')).map(row => row[0])
      const overviewRow = rows.find(row => row[0] === '不同事故数')
      report.csv.statistics = { sections, overviewRow }
      check('统计报表CSV分节齐全且含人员节', sections.length === 7
            && sections.some(text => text.includes('人员类别')), { sections })
      check('统计报表CSV总览=3起', overviewRow && overviewRow[1] === '3', { overviewRow })
      fs.writeFileSync(path.join(outDir, 'download-statistics.csv'), statisticsCsv, 'utf-8')
    } else check('统计报表CSV已请求', false, {})
    if (collisionsCsv) fs.writeFileSync(path.join(outDir, 'download-collisions.csv'), collisionsCsv, 'utf-8')

    /* ---------- 竞态：旧响应不得覆盖新结果 ---------- */
    await context.route('**/api/v1/statistics/overview*', async route => {
      if (!globalThis.__slowOnce) {
        globalThis.__slowOnce = true
        await sleep(1500)
      }
      return route.fallback()
    })
    const panelHandle = panel
    await panelHandle.locator('input[type="date"]').first().fill('2025-01-01')
    await panelHandle.locator('input[type="date"]').nth(1).fill('2025-01-31')
    await panelHandle.getByPlaceholder('如 Main St').fill('M6 BROWSER UNKNOWN')
    await panelHandle.getByRole('button', { name: '查询统计' }).click()
    await panelHandle.locator('select').first().selectOption('2')
    await panelHandle.getByRole('button', { name: '查询统计' }).click()
    await sleep(2500)
    const raceCount = await pageHandle.evaluate(() =>
      document.querySelector('.statistics-panel .facts-grid dd').textContent.trim())
    check('快速切换筛选后旧响应被丢弃（显示布朗克斯0起）', raceCount === '0', { raceCount })
    await context.unroute('**/api/v1/statistics/overview*')

    /* ---------- 故障注入：请求失败清空旧数据并提示，恢复后可重查 ---------- */
    injecting = true
    await context.route('**/api/v1/statistics/overview*', route => route.abort('failed'))
    await panelHandle.getByRole('button', { name: '查询统计' }).click()
    await pageHandle.waitForFunction(() => {
      const alert = document.querySelector('.statistics-panel [role="alert"]')
      return alert && alert.textContent.length > 0
    }, null, { timeout: 15000 })
    const errorText = await pageHandle.locator('.statistics-panel [role="alert"]').first().textContent()
    const dataCleared = await pageHandle.evaluate(() =>
      document.querySelectorAll('.statistics-panel .facts-grid').length === 0)
    check('故障时显示错误且旧结果被清空', errorText.length > 0 && dataCleared, { errorText: errorText.slice(0, 80) })
    await context.unroute('**/api/v1/statistics/overview*')
    injecting = false
    await panelHandle.locator('select').first().selectOption('')
    await panelHandle.getByPlaceholder('如 Main St').fill('')
    await panelHandle.getByRole('button', { name: '查询统计' }).click()
    await waitForOverview(pageHandle, 3)
    check('故障解除后统计恢复', true)

    /* ---------- 打印媒体 ---------- */
    await pageHandle.emulateMedia({ media: 'print' })
    const printLayout = await pageHandle.evaluate(() => {
      const main = document.querySelector('main')
      const children = [...main.children].map(child => ({
        tag: child.tagName, cls: child.className && String(child.className).slice(0, 40),
        display: getComputedStyle(child).display }))
      const panelElement = main.querySelector('.statistics-panel')
      const panelVisible = getComputedStyle(panelElement).display !== 'none'
      const buttonsHidden = getComputedStyle(panelElement.querySelector('.no-print')).display === 'none'
      const canvases = [...panelElement.querySelectorAll('canvas')].filter(c => c.width > 100).length
      return { children, panelVisible, buttonsHidden, canvases }
    })
    const hiddenOthers = printLayout.children.every(child =>
      child.cls.includes('statistics-panel') || child.display === 'none')
    check('打印媒体下仅统计面板可见', hiddenOthers && printLayout.panelVisible && printLayout.buttonsHidden,
          { children: printLayout.children })
    check('打印媒体下图表仍渲染（canvas非空）', printLayout.canvases >= 4, { canvases: printLayout.canvases })
    await pageHandle.screenshot({ path: path.join(outDir, 'm6-statistics-print-a4.png'), fullPage: true })
    await pageHandle.pdf({ path: path.join(outDir, 'm6-statistics-print.pdf'), format: 'A4',
                           printBackground: true, margin: { top: '10mm', bottom: '10mm' } })
    report.screenshots.push('m6-statistics-print-a4.png', 'm6-statistics-print.pdf')
    await pageHandle.emulateMedia({ media: 'screen' })
    // page.pdf的headless流程不触发afterprint；模拟真实打印返回后的窗口重排，恢复图表尺寸。
    await pageHandle.evaluate(() => window.dispatchEvent(new Event('resize')))
    await pageHandle.waitForTimeout(400)
    const canvasWidths = await pageHandle.evaluate(() =>
      [...document.querySelectorAll('.statistics-panel canvas')].map(canvas => canvas.width))
    check('打印返回屏幕后图表恢复容器宽度', canvasWidths.length >= 4
          && canvasWidths.every(width => width < 1440), { canvasWidths })
    await pageHandle.locator('.statistics-panel').scrollIntoViewIfNeeded()
    await pageHandle.waitForTimeout(400)
    await pageHandle.screenshot({ path: path.join(outDir, 'm6-statistics-desktop-1440x900.png'), fullPage: false })
    report.screenshots.push('m6-statistics-desktop-1440x900.png')

    const overflowDesktop = await pageHandle.evaluate(() => {
      const vw = document.scrollingElement.clientWidth
      const wide = []
      for (const el of document.querySelectorAll('*')) {
        const rect = el.getBoundingClientRect()
        if (rect.right > vw + 1 && rect.width > 0) {
          wide.push({ tag: el.tagName, cls: String(el.className).slice(0, 40), right: Math.round(rect.right) })
          if (wide.length >= 6) break
        }
      }
      return { overflowPx: document.scrollingElement.scrollWidth - vw, wide }
    })
    check('桌面无页面横向溢出', overflowDesktop.overflowPx <= 1, overflowDesktop)
    await context.close()

    /* ---------- 窄屏 390×844，普通查询用户 ---------- */
    context = await browser.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true })
    const mobile = await context.newPage()
    mobile.on('console', message => {
      if (message.type() !== 'error') return
      if (message.text().includes('net::ERR_FAILED') || message.text().includes('net::ERR_ABORTED')) {
        report.expectedResourceErrors.count += 1
        return
      }
      report.consoleErrors.push('mobile: ' + message.text().slice(0, 200))
    })
    mobile.on('pageerror', error => report.pageErrors.push('mobile: ' + String(error).slice(0, 200)))
    await mobile.route('**/tile.openstreetmap.org/**', route => { report.tiles.intercepted += 1; return route.abort() })
    await loginAs(mobile, 'viewer')
    const mobilePanel = mobile.locator('.statistics-panel')
    await mobilePanel.waitFor({ state: 'visible', timeout: 15000 })
    await mobile.waitForFunction(() => {
      const dds = [...document.querySelectorAll('.statistics-panel .facts-grid dd')]
      return dds.length > 0 && dds[0].textContent.trim() !== ''
    }, null, { timeout: 20000 })
    check('窄屏VIEWER总览可读', true)
    const viewerButtons = await mobile.evaluate(() => {
      const panelElement = document.querySelector('.statistics-panel')
      const names = [...panelElement.querySelectorAll('button')].map(button => button.textContent.trim())
      const headings = [...panelElement.querySelectorAll('h3')].map(h => h.textContent)
      return { names, headings }
    })
    check('VIEWER不可见统计报表CSV/人员/治理',
          !viewerButtons.names.some(name => name.includes('统计报表CSV'))
          && !viewerButtons.headings.some(title => title.includes('人员类别'))
          && !viewerButtons.headings.some(title => title.includes('模拟治理工单')),
          { names: viewerButtons.names, headings: viewerButtons.headings })
    const overflowMobile = await mobile.evaluate(() =>
      ({ page: document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth,
         tables: [...document.querySelectorAll('.statistics-panel .table-wrap')]
           .filter(wrap => wrap.scrollWidth > wrap.clientWidth + 1).length }))
    check('窄屏无页面横向溢出（表格容器内滚动）', overflowMobile.page <= 1, overflowMobile)
    await mobile.screenshot({ path: path.join(outDir, 'm6-statistics-mobile-390x844.png'), fullPage: false })
    report.screenshots.push('m6-statistics-mobile-390x844.png')
    await context.close()
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
  fs.writeFileSync(path.join(outDir, 'm6_browser_acceptance.json'), JSON.stringify(report, null, 2) + '\n', 'utf-8')
  console.log(JSON.stringify(report.summary) + ' exit=' + report.runner.exitCode)
  process.exit(report.runner.exitCode)
}).catch(error => {
  report.fatal = String(error && error.stack ? error.stack : error).slice(0, 1500)
  report.finishedAt = new Date().toISOString()
  report.summary = { total: report.checks.length, passed: report.checks.filter(item => item.passed).length, failed: 1 }
  report.runner.exitCode = 1
  fs.writeFileSync(path.join(outDir, 'm6_browser_acceptance.json'), JSON.stringify(report, null, 2) + '\n', 'utf-8')
  console.error('FATAL: ' + String(error).slice(0, 400))
  process.exit(1)
})
