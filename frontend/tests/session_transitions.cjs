'use strict'
// 两个真实会话验证退出全部会话和旧令牌 401；只允许独立合成库。
const fs = require('node:fs'), path = require('node:path')
const { chromium } = require(path.join(process.cwd(), 'frontend/node_modules/playwright'))
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const output = path.resolve(process.argv[3])
if (!config.synthetic_only || !config.database.startsWith('vision_zero_m1_test_')) throw new Error('仅允许隔离合成配置')
if (fs.existsSync(output)) throw new Error('请使用新的输出目录')
fs.mkdirSync(output, { recursive: true })
const checks = [], errors = []
function check(name, passed) { checks.push({ name, passed }); if (!passed) throw new Error(name) }
async function login(page, target) {
  await page.goto(config.base_url + '/#' + target)
  await page.getByLabel('登录名', { exact: true }).fill(config.users.admin.username)
  await page.getByLabel('密码', { exact: true }).fill(config.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.locator('.app-shell').waitFor()
}
;(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
  try {
    const first = await browser.newPage(), second = await browser.newPage()
    for (const page of [first, second]) page.on('pageerror', error => errors.push(error.message))
    await login(first, '/collisions')
    await first.locator('.collision-table tbody tr').first().waitFor()
    await login(second, '/account')
    await second.getByRole('button', { name: '退出全部会话', exact: true }).click()
    await second.getByRole('button', { name: '登录', exact: true }).waitFor()
    check('logout-clears-shell-and-returns-login', await second.locator('.app-shell').count() === 0)
    const expired = first.waitForResponse(response => response.url().includes('/api/v1/collisions?') && response.status() === 401)
    await first.getByRole('button', { name: '查询事故', exact: true }).click()
    await expired
    await first.getByRole('button', { name: '登录', exact: true }).waitFor()
    check('revoked-token-receives-real-401', true)
    check('401-clears-shell-and-preserves-target', await first.locator('.app-shell').count() === 0 && new URLSearchParams(new URL(first.url()).hash.split('?')[1]).get('redirect') === '/collisions')
    await login(first, '/collisions')
    await first.locator('.collision-table tbody tr').first().waitFor()
    check('fresh-login-restores-authorized-route', new URL(first.url()).hash === '#/collisions')
    check('no-page-errors', errors.length === 0)
  } finally {
    await browser.close()
    fs.writeFileSync(path.join(output, 'acceptance.json'), JSON.stringify({ synthetic_only: true, checks, errors }, null, 2) + '\n')
    console.log(JSON.stringify({ checks, errors }))
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
