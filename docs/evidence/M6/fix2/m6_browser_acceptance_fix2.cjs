'use strict'
// R01—R03独立回归；运行目录必须为仓库根目录。每轮输出到新目录，禁止覆盖历史结果。
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto')
const root = process.cwd()
const { chromium } = require(path.join(root, 'frontend/node_modules/playwright'))
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const out = path.resolve(process.argv[3])
fs.mkdirSync(out, { recursive: true })
if (fs.existsSync(path.join(out, 'acceptance.json'))) throw new Error('输出目录已有验收结果，请使用新轮次目录')
const report = { round: 'fix2', startedAt: new Date().toISOString(), browser: { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true }, syntheticDatabase: config.database, checks: [], downloads: [], pageErrors: [], fatal: null }
function check(name, passed, evidence) { report.checks.push({ name, passed: Boolean(passed), evidence }); console.log(`${passed ? 'PASS' : 'FAIL'} ${name}`) }
function parseCsv(text) {
  const rows = []; let row = [], field = '', quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) { if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++ } else quoted = false } else field += c }
    else if (c === '"') quoted = true
    else if (c === ',') { row.push(field); field = '' }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = '' }
    else if (c !== '\r') field += c
  }
  if (field || row.length) { row.push(field); rows.push(row) }
  return rows
}
async function main() {
  const browser = await chromium.launch({ ...report.browser })
  try {
    const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    page.on('pageerror', e => report.pageErrors.push(e.message))
    await page.route('**/tile.openstreetmap.org/**', r => r.abort())
    const panel = page.locator('.statistics-panel')
    const outputButtons = () => panel.getByRole('button').filter({ hasText: /^(打印报表|下载事故CSV|下载统计报表CSV)$/ })
    const failed = r => r.abort('failed')
    await page.route('**/statistics/overview?**', failed)
    await page.goto('http://127.0.0.1:5176/')
    await page.getByLabel('登录名').fill(config.users.admin.username)
    await page.getByLabel('密码', { exact: true }).fill(config.password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await panel.locator('[role=alert]').first().waitFor()
    async function printBlocked(label) {
      const disabled = await outputButtons().evaluateAll(nodes => nodes.length === 3 && nodes.every(n => n.disabled))
      await page.emulateMedia({ media: 'print' })
      const state = await panel.evaluate(el => {
        const visible = n => !!n && n.getBoundingClientRect().width > 0 && n.getBoundingClientRect().height > 0
        return { header: visible(el.querySelector('.print-header')), body: visible(el.querySelector('.report-body')), tables: [...el.querySelectorAll('table')].filter(visible).length, charts: [...el.querySelectorAll('canvas')].filter(visible).length, explanation: visible(el.querySelector('.print-unavailable')), reason: el.querySelector('.print-unavailable')?.textContent.trim() }
      })
      await page.pdf({ path: path.join(out, label + '.pdf'), format: 'A4', printBackground: true })
      check(label, disabled && !state.header && !state.body && !state.tables && !state.charts && state.explanation && /不可打印|停用/.test(state.reason), { disabled, ...state })
      await page.emulateMedia({ media: 'screen' })
    }
    await printBlocked('R01-no-valid-report')
    await page.unroute('**/statistics/overview?**', failed)
    async function settled(expected) {
      await page.waitForFunction(value => {
        const el = document.querySelector('.statistics-panel'), query = [...el.querySelectorAll('button')].find(n => n.textContent.trim() === '查询统计')
        return query && !query.disabled && el.querySelector('.facts-grid dd')?.textContent.trim() === String(value)
      }, expected, { timeout: 30000 })
    }
    await panel.locator('input[type=date]').nth(1).fill('2025-01-31')
    await panel.locator('input[type=date]').nth(1).press('Tab')
    await settled(3)
    const previous = await panel.locator('.report-body').textContent()
    const mixed = async route => { const response = await route.fetch(); const json = await response.json(); json.meta.data_revision = '123'; json.data.items[0].collision_count = 987654; await route.fulfill({ response, json }) }
    await page.route('**/statistics/boroughs?**', mixed)
    await panel.getByRole('button', { name: '查询统计', exact: true }).click()
    await panel.locator('[role=alert]').filter({ hasText: '本次查询读取到不同的数据版本' }).waitFor()
    check('R01-mixed-not-applied', (await panel.locator('.report-body').textContent()) === previous && !(await panel.textContent()).includes('987654'), { previousReportUnchanged: (await panel.locator('.report-body').textContent()) === previous })
    await printBlocked('R01-mixed-revisions')
    await page.unroute('**/statistics/boroughs?**', mixed)
    await panel.getByRole('button', { name: '查询统计', exact: true }).click(); await settled(3)
    let release
    const gate = new Promise(resolve => { release = resolve })
    const delayed = async route => { await gate; await route.continue() }
    await page.route('**/statistics/overview?**', delayed)
    await panel.getByRole('button', { name: '查询统计', exact: true }).click()
    await panel.getByRole('button', { name: '查询中…', exact: true }).waitFor()
    await printBlocked('R01-loading')
    release(); await settled(3); await page.unroute('**/statistics/overview?**', delayed)
    await page.route('**/statistics/overview?**', failed)
    await panel.getByRole('button', { name: '查询统计', exact: true }).click()
    await panel.locator('[role=alert]').first().waitFor()
    await printBlocked('R01-failed')
    await page.unroute('**/statistics/overview?**', failed)
    await panel.getByRole('button', { name: '查询统计', exact: true }).click(); await settled(3)
    for (const [label, value] of [['R02-empty-date', ''], ['R02-reversed-date', '2024-12-31']]) {
      // 不移开焦点：验证Ctrl+P可在change事件之前发生的输入状态。
      await panel.locator('input[type=date]').nth(1).evaluate((el, date) => {
        el.focus(); el.value = date; el.dispatchEvent(new Event('input', { bubbles: true }))
      }, value)
      await printBlocked(label)
      check(label + '-previous-result-labelled', (await panel.locator('.facts-grid dd').first().textContent()).trim() === '3' && (await panel.locator('[role=status]').allTextContents()).some(t => t.includes('上次成功查询结果')), { retainedCount: await panel.locator('.facts-grid dd').first().textContent() })
      await panel.locator('input[type=date]').nth(1).evaluate(el => { el.value = '2025-01-31'; el.dispatchEvent(new Event('input', { bubbles: true })) })
      check(label + '-requires-successful-query', await outputButtons().evaluateAll(nodes => nodes.length === 3 && nodes.every(n => n.disabled)), {})
      await panel.getByRole('button', { name: '查询统计', exact: true }).click(); await settled(3)
      check(label + '-recovered', await outputButtons().evaluateAll(nodes => nodes.length === 3 && nodes.every(n => !n.disabled)), {})
    }
    // 无路由修改、无a.click hook：真实后端响应→浏览器download事件→saveAs→读文件解析。
    for (const kind of ['collisions', 'statistics']) {
      const filename = 'vision-zero-' + kind + '.csv'
      const event = page.waitForEvent('download', { timeout: 20000 })
      await panel.getByRole('button', { name: kind === 'collisions' ? '下载事故CSV' : '下载统计报表CSV', exact: true }).click()
      const download = await event
      const failure = await download.failure(), suggestedFilename = download.suggestedFilename()
      if (failure) throw new Error(`${filename}: download.failure=${failure}`)
      await download.saveAs(path.join(out, filename))
      const bytes = fs.readFileSync(path.join(out, filename)), text = bytes.toString('utf8').replace(/^\uFEFF/, ''), rows = parseCsv(text)
      const data = rows.filter(r => r[0] && !r[0].startsWith('#'))
      const bom = bytes.subarray(0, 3).equals(Buffer.from([239, 187, 191]))
      let content
      if (kind === 'collisions') {
        const records = data.slice(1).map(r => Object.fromEntries(data[0].map((h, i) => [h, r[i]])))
        content = records.length === 3 && records.map(r => r.crash_date).join(',') === '2025-01-05,2025-01-06,2025-01-07' && records.map(r => r.persons_injured).join(',') === '2,2,' && records.map(r => r.persons_killed).join(',') === '0,1,' && new Set(records.map(r => r.collision_id)).size === 3
      } else {
        const sections = rows.filter(r => /^# \[/.test(r[0])).map(r => r[0])
        content = sections.length === 7 && data.some(r => r[0] === '不同事故数' && r[1] === '3') && data.some(r => r[0] === '已知受伤合计' && r[1] === '4') && data.some(r => r[0] === '已知死亡合计' && r[1] === '1') && data.some(r => r[0] === '受伤缺失事故数' && r[1] === '1')
      }
      const evidence = { suggestedFilename, failure, bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), parsedRows: data.length, bom, content, singleRevisionAndRange: /数据版本 revision: 0/.test(text) && text.includes('[2025-01-01, 2025-02-01)') }
      report.downloads.push(evidence)
      check('R03-' + kind + '-actual-download', suggestedFilename === filename && failure === null && bom && content && evidence.singleRevisionAndRange, evidence)
    }
    await page.evaluate(() => { window.__printEvents = { before: 0, after: 0 }; window.addEventListener('beforeprint', () => window.__printEvents.before++); window.addEventListener('afterprint', () => window.__printEvents.after++) })
    const sizes = () => panel.locator('.chart-box canvas').evaluateAll(nodes => nodes.map(n => ({ width: n.getBoundingClientRect().width, height: n.getBoundingClientRect().height })))
    const before = await sizes()
    await panel.getByRole('button', { name: '打印报表', exact: true }).click()
    await page.emulateMedia({ media: 'print' })
    const valid = await panel.evaluate(el => ({ body: el.querySelector('.report-body').getBoundingClientRect().width > 0, title: getComputedStyle(el.querySelector('.print-header')).display !== 'none', explanation: getComputedStyle(el.querySelector('.print-unavailable')).display !== 'none', text: el.querySelector('.print-header').textContent }))
    await page.screenshot({ path: path.join(out, 'normal-print.png'), fullPage: true })
    await page.pdf({ path: path.join(out, 'normal-print.pdf'), format: 'A4', printBackground: true })
    check('R01-normal-print', valid.body && valid.title && !valid.explanation && valid.text.includes('revision 0'), valid)
    await page.emulateMedia({ media: 'screen' })
    // 等待浏览器完成打印后的布局恢复，不注入afterprint或resize替代实际事件。
    await page.waitForFunction(() => [...document.querySelectorAll('.chart-box canvas')].every(n => Math.abs(n.getBoundingClientRect().width - n.closest('.chart-box').getBoundingClientRect().width) < 2), null, { timeout: 5000 }).catch(() => {})
    const after = await sizes(), events = await page.evaluate(() => window.__printEvents)
    check('R01-chart-restored-after-print', before.length === 4 && JSON.stringify(before) === JSON.stringify(after) && events.before > 0 && events.after > 0, { before, after, events })
    await page.screenshot({ path: path.join(out, 'normal-screen-after-print.png') })
    check('no-page-errors', report.pageErrors.length === 0, report.pageErrors)
  } finally { await browser.close() }
}
main().catch(e => { report.fatal = { name: e.name, message: e.message }; console.error(e.message) }).finally(() => {
  report.finishedAt = new Date().toISOString()
  report.exitCode = report.fatal || report.checks.some(c => !c.passed) ? 1 : 0
  fs.writeFileSync(path.join(out, 'acceptance.json'), JSON.stringify(report, null, 2) + '\n')
  process.exitCode = report.exitCode
})
