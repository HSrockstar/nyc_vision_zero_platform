'use strict'
// 截图仅使用显式指定的合成验收配置，不写入业务数据。
const fs = require('node:fs'), path = require('node:path')
const { chromium } = require(path.join(process.cwd(), 'frontend/node_modules/playwright'))
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const output = path.resolve(process.argv[3])
if (!config.synthetic_only) throw new Error('仅允许合成验收配置')
fs.mkdirSync(output, { recursive: true })
;(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
  const errors = [], results = []
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(config.base_url)
    await page.getByRole('button', { name: '登录', exact: true }).waitFor()
    await page.screenshot({ path: path.join(output, 'login-desktop.png'), fullPage: true })
    await page.getByLabel('登录名', { exact: true }).fill(config.users.admin.username)
    await page.getByLabel('密码', { exact: true }).fill(config.password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.locator('.metric-card .metric-value').first().waitFor({ timeout: 30000 })
    const titles = { '/': '工作总览', '/collisions': '事故查询', '/map': '地图与交叉口', '/risks': '风险画像', '/governance': '治理任务', '/statistics': '统计报表', '/imports': '数据导入与质量', '/users': '账户管理', '/account': '个人账户' }
    async function navigate(hash) {
      await page.evaluate(route => { location.hash = route }, hash)
      await page.waitForFunction(title => document.querySelector('.breadcrumb')?.textContent.includes(title), titles[hash], { timeout: 60000 })
      await page.waitForFunction(route => {
        const selectors = { '/': '.metric-card .metric-value', '/collisions': '.collision-panel', '/map': '.map-panel .coverage-card', '/risks': '.risk-page .coverage-grid', '/governance': '.governance-page', '/statistics': '.statistics-panel .facts-grid', '/imports': '.import-page', '/users': '.page-content tbody tr', '/account': '.account-form' }
        const content = document.querySelector('.page-content')
        const target = document.querySelector(selectors[route])
        return target && content && !/刷新中…|加载中…|查询中…|载入中…/.test(content.textContent)
      }, hash, { timeout: 30000 })
      await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {})
      await page.waitForTimeout(350)
    }
    for (const [name, hash] of [['overview', '/'], ['collisions', '/collisions'], ['map', '/map'], ['risks', '/risks'], ['governance', '/governance'], ['statistics', '/statistics'], ['imports', '/imports'], ['users', '/users'], ['account', '/account']]) {
      await navigate(hash)
      await page.screenshot({ path: path.join(output, name + '-desktop.png'), fullPage: true })
      results.push({ name, url: page.url(), overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1) })
    }
    await page.setViewportSize({ width: 390, height: 844 })
    for (const [name, hash] of [['overview', '/'], ['collisions', '/collisions'], ['map', '/map'], ['risks', '/risks'], ['governance', '/governance'], ['statistics', '/statistics'], ['imports', '/imports'], ['users', '/users']]) {
      await navigate(hash)
      await page.screenshot({ path: path.join(output, name + '-mobile.png'), fullPage: true })
      results.push({ name: name + '-mobile', overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1) })
    }
  } finally {
    await browser.close()
    fs.writeFileSync(path.join(output, 'render.json'), JSON.stringify({ synthetic_only: true, results, errors }, null, 2))
    console.log(JSON.stringify({ results, errors }))
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
