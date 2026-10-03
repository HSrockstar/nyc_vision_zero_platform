'use strict'
const fs = require('node:fs'), path = require('node:path')
const { chromium } = require(path.join(process.cwd(), 'frontend/node_modules/playwright'))
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const output = path.resolve(process.argv[3])
if (!config.synthetic_only) throw new Error('仅允许隔离合成库')
fs.mkdirSync(output, { recursive: true })
;(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
  const checks = []
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    await page.goto(config.base_url + '/#/account')
    await page.getByLabel('登录名', { exact: true }).fill(config.users.admin.username)
    await page.getByLabel('密码', { exact: true }).fill(config.password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByLabel('原密码', { exact: true }).waitFor()
    await page.getByLabel('原密码', { exact: true }).fill('SYNTHETIC-UNSUBMITTED')
    await page.getByRole('link', { name: '账户管理', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('.breadcrumb')?.textContent.includes('账户管理'))
    await page.waitForLoadState('networkidle')
    checks.push({ name: 'account-to-users-loads-directory', passed: await page.locator('.account-panel tbody tr').count() >= 4 })
    await page.locator('.profile-link').click()
    await page.getByLabel('原密码', { exact: true }).waitFor()
    checks.push({ name: 'password-cleared-on-route-leave', passed: await page.getByLabel('原密码', { exact: true }).inputValue() === '' })
    await page.getByRole('link', { name: '风险画像', exact: true }).click()
    await page.getByRole('button', { name: '建立治理草稿', exact: true }).first().waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: '建立治理草稿', exact: true }).first().click()
    await page.getByLabel('任务标题', { exact: true }).waitFor()
    checks.push({ name: 'initial-profile-prefills-title', passed: (await page.getByLabel('任务标题', { exact: true }).inputValue()).includes('现场调查') })
    await page.screenshot({ path: path.join(output, 'governance-prefill.png'), fullPage: true })
  } finally {
    await browser.close()
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ checks }, null, 2))
    console.log(JSON.stringify(checks))
    if (checks.some(check => !check.passed) || checks.length !== 3) process.exitCode = 1
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
