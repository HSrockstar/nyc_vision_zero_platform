const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..', '..', '..')
const OUTPUT = path.resolve(ROOT, '.m1-work', 'model', 'browser')
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PROFILE = path.resolve(OUTPUT, 'chrome-profile')
const TEMP = path.resolve(OUTPUT, 'browser-temp')

for (const candidate of [PROFILE, TEMP]) {
  if (!candidate.startsWith(OUTPUT + path.sep)) throw new Error('浏览器临时目录越界。')
}
if (!fs.existsSync(CHROME)) throw new Error('本机 Chrome 不可用；未尝试下载浏览器。')

process.env.TEMP = TEMP
process.env.TMP = TEMP
process.env.TMPDIR = TEMP
fs.mkdirSync(TEMP, { recursive: true })

const { chromium } = require(path.join(ROOT, 'frontend', 'node_modules', 'playwright'))
const adminFile = fs.readFileSync(path.join(ROOT, '.m1-work', 'model', 'initial-admin.txt'), 'utf8')
const username = adminFile.match(/^用户名：([^\r\n]+)$/m)?.[1]?.trim()
const password = adminFile.match(/^密码：([^\r\n]+)$/m)?.[1]?.trim()
if (!username || !password) throw new Error('首次管理员凭据文件格式不符合预期。')

const report = {
  task: 'M1 前端浏览器验收',
  result: 'running',
  viewports: { desktop: '1366x900', narrow: '390x844' },
  flows: {},
  layout: {},
  apiResponses: [],
  consoleErrors: 0,
  consoleErrorMessages: [],
  consoleErrorLocations: [],
  expectedUnauthorizedConsoleErrors: 0,
  pageErrors: [],
  otherHttpFailures: [],
  screenshots: [],
}

function saveScreenshot(name) {
  const file = path.join(OUTPUT, name)
  if (!file.startsWith(OUTPUT + path.sep)) throw new Error('截图目标越界。')
  return file
}

function safeFailure(error) {
  let message = error.message || '验收失败。'
  for (const secret of [password, username]) {
    if (secret) message = message.split(secret).join('[redacted]')
  }
  message = message.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
  return { name: error.name || 'Error', message }
}

function safeConsoleMessage(value) {
  let message = value
  for (const secret of [password, username]) {
    if (secret) message = message.split(secret).join('[redacted]')
  }
  return message.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').slice(0, 240)
}

async function checkNoPageOverflow(page, label) {
  const result = await page.evaluate(() => {
    const wrap = document.querySelector('.table-wrap')
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      tableWrapClientWidth: wrap?.clientWidth ?? null,
      tableWrapScrollWidth: wrap?.scrollWidth ?? null,
    }
  })
  assert.equal(result.documentWidth <= result.viewportWidth, true, `${label}: 页面存在横向溢出`)
  assert.equal(result.bodyWidth <= result.viewportWidth, true, `${label}: body 存在横向溢出`)
  report.layout[label] = result
}

async function ensurePasswordsBlank(page, label) {
  const hasValue = await page.locator('input[type="password"]').evaluateAll((items) =>
    items.some((item) => item.value.length > 0),
  )
  assert.equal(hasValue, false, `${label}: 页面中仍有密码输入值`)
}

async function main() {
  let context
  let page
  try {
    context = await chromium.launchPersistentContext(PROFILE, {
      executablePath: CHROME,
      headless: true,
      viewport: { width: 1366, height: 900 },
      deviceScaleFactor: 1,
      args: ['--no-first-run', '--disable-extensions', '--disable-crash-reporter', '--disable-breakpad'],
    })
    page = context.pages()[0] ?? await context.newPage()

    page.on('console', (message) => {
      if (message.type() === 'error') {
        if (/\b401\b|unauthorized/i.test(message.text())) report.expectedUnauthorizedConsoleErrors += 1
        else {
          report.consoleErrors += 1
          report.consoleErrorMessages.push(safeConsoleMessage(message.text()))
          const location = message.location()
          let locationPath = ''
          try { locationPath = new URL(location.url).pathname } catch {}
          report.consoleErrorLocations.push({ path: locationPath, line: location.lineNumber })
        }
      }
    })
    page.on('pageerror', (error) => report.pageErrors.push(error.name || 'Error'))
    page.on('response', (response) => {
      const url = new URL(response.url())
      if (url.pathname.startsWith('/api/v1/') || url.pathname.startsWith('/health/')) {
        report.apiResponses.push({ method: response.request().method(), path: url.pathname, status: response.status() })
      } else if (response.status() >= 400) {
        report.otherHttpFailures.push({ method: response.request().method(), path: url.pathname, status: response.status() })
      }
    })

    await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle', timeout: 15000 })
    await page.getByRole('heading', { name: '账户与权限' }).waitFor()
    await page.getByText('已就绪', { exact: true }).waitFor()
    await page.getByLabel('登录名').waitFor()
    await checkNoPageOverflow(page, 'desktop_logged_out')
    await ensurePasswordsBlank(page, '初始登录页')
    await page.screenshot({ path: saveScreenshot('01-desktop-logged-out.png'), fullPage: true })
    report.screenshots.push('01-desktop-logged-out.png')
    report.flows.environment_ready = true

    await page.getByLabel('登录名').fill(`codex-ui-invalid-probe-${Date.now()}`)
    await page.getByLabel('密码').fill('not-a-valid-password')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByRole('alert').waitFor()
    assert.match(await page.getByRole('alert').innerText(), /用户名或密码不正确/)
    assert.equal(await page.getByLabel('密码').inputValue(), '')
    await ensurePasswordsBlank(page, '错误登录后')
    await page.screenshot({ path: saveScreenshot('02-invalid-login-cleared.png'), fullPage: true })
    report.screenshots.push('02-invalid-login-cleared.png')
    report.flows.invalid_login_shows_error_and_clears_password = true

    async function loginAsAdmin() {
      await page.getByLabel('登录名').fill(username)
      await page.getByLabel('密码').fill(password)
      await page.getByRole('button', { name: '登录', exact: true }).click()
      await page.getByText(/当前账户：/).waitFor()
    }

    await loginAsAdmin()
    await page.getByRole('heading', { name: '用户管理' }).waitFor()
    await page.locator('.table-wrap tbody tr').first().waitFor({ timeout: 10000 })
    const adminRows = await page.locator('.table-wrap tbody tr').evaluateAll((rows) =>
      rows.map((row) => Array.from(row.querySelectorAll('td')).map((cell, index) =>
        index === 2 ? cell.querySelector('select')?.value ?? cell.innerText.trim() : cell.innerText.trim(),
      )),
    )
    assert.equal(adminRows.length, 1, '管理员账户列表应仅有初始化管理员')
    assert.equal(adminRows[0][0], username, '账户列表中的用户名应为初始化管理员')
    assert.equal(adminRows[0][2], 'ADMIN', '账户列表角色应为 ADMIN')
    await ensurePasswordsBlank(page, '管理员页面')
    await checkNoPageOverflow(page, 'desktop_admin')
    await page.screenshot({ path: saveScreenshot('03-desktop-admin.png'), fullPage: true })
    report.screenshots.push('03-desktop-admin.png')
    report.flows.admin_login_and_single_admin_row = true
    report.adminAccountRows = adminRows.length

    await page.setViewportSize({ width: 390, height: 844 })
    await checkNoPageOverflow(page, 'narrow_admin')
    await ensurePasswordsBlank(page, '窄屏管理员页面')
    await page.screenshot({ path: saveScreenshot('04-narrow-admin.png'), fullPage: true })
    report.screenshots.push('04-narrow-admin.png')
    report.flows.narrow_viewport_without_page_overflow = true

    await page.setViewportSize({ width: 1366, height: 900 })
    await page.reload({ waitUntil: 'networkidle', timeout: 15000 })
    await page.getByLabel('登录名').waitFor()
    assert.equal(await page.getByRole('heading', { name: '用户管理' }).count(), 0)
    await ensurePasswordsBlank(page, '刷新后')
    await page.screenshot({ path: saveScreenshot('05-refresh-requires-login.png'), fullPage: true })
    report.screenshots.push('05-refresh-requires-login.png')
    report.flows.refresh_clears_session = true

    const forceUnauthorized = (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'AUTH_REQUIRED', message: '请重新登录。' },
        meta: { request_id: 'browser-acceptance' },
      }),
    })
    await page.route('**/api/v1/users**', forceUnauthorized)
    await loginAsAdmin()
    await page.getByLabel('登录名').waitFor()
    await page.getByRole('alert').waitFor()
    assert.equal(await page.getByLabel('密码').inputValue(), '')
    assert.equal(await page.getByRole('heading', { name: '用户管理' }).count(), 0)
    await ensurePasswordsBlank(page, '模拟 401 后')
    await page.screenshot({ path: saveScreenshot('06-unauthorized-clears-session.png'), fullPage: true })
    report.screenshots.push('06-unauthorized-clears-session.png')
    report.flows.simulated_401_clears_session = true
    await page.unroute('**/api/v1/users**', forceUnauthorized)

    report.progress = 'reauthenticated_after_mocked_401'
    await loginAsAdmin()
    await page.getByRole('heading', { name: '用户管理' }).waitFor()
    await page.locator('.table-wrap tbody tr').first().waitFor({ timeout: 10000 })
    report.progress = 'admin_authenticated_before_logout'
    const logoutResponseWaiter = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/v1/auth/logout', { timeout: 10000 },
    )
    await page.getByRole('button', { name: '退出全部会话' }).click()
    const logoutResponse = await logoutResponseWaiter
    assert.equal(logoutResponse.status(), 200, '退出接口未返回成功状态')
    report.progress = 'logout_response_received'
    await page.getByLabel('登录名').waitFor()
    assert.equal(await page.getByRole('heading', { name: '用户管理' }).count(), 0)
    await ensurePasswordsBlank(page, '退出后')
    await page.screenshot({ path: saveScreenshot('07-logout-returns-to-login.png'), fullPage: true })
    report.screenshots.push('07-logout-returns-to-login.png')
    report.flows.logout_returns_to_login = true

    const failures = report.apiResponses.filter((item) => item.status >= 400)
    assert.equal(failures.length, 2, '只应出现错误登录与模拟会话失效两次预期 401')
    assert.deepEqual(failures.map(({ method, path: apiPath, status }) => [method, apiPath, status]).sort(), [
      ['GET', '/api/v1/users', 401],
      ['POST', '/api/v1/auth/login', 401],
    ])
    assert.equal(report.consoleErrors, 0, '浏览器控制台有错误')
    assert.deepEqual(report.consoleErrorMessages, [])
    assert.deepEqual(report.otherHttpFailures, [], '出现了未预期的非 API HTTP 错误')
    assert.equal(report.expectedUnauthorizedConsoleErrors, 2, '预期登录错误与模拟 401 应各产生一个浏览器请求告警')
    assert.deepEqual(report.pageErrors, [], '页面发生未捕获异常')
    report.flows.only_expected_api_failures = true
    report.flows.no_unexpected_console_page_or_api_failures = true
    report.result = 'passed'
  } catch (error) {
    report.result = 'failed'
    report.failure = safeFailure(error)
  } finally {
    if (context) await context.close()
    fs.writeFileSync(path.join(OUTPUT, 'report.json'), JSON.stringify(report, null, 2) + '\n', 'utf8')
    fs.rmSync(PROFILE, { recursive: true, force: true })
    fs.rmSync(TEMP, { recursive: true, force: true })
  }

  process.stdout.write(JSON.stringify(report, null, 2) + '\n')
  if (report.result !== 'passed') process.exitCode = 1
}

main().catch((error) => {
  const safe = { result: 'failed', failure: safeFailure(error) }
  fs.writeFileSync(path.join(OUTPUT, 'report.json'), JSON.stringify(safe, null, 2) + '\n', 'utf8')
  process.stdout.write(JSON.stringify(safe, null, 2) + '\n')
  process.exitCode = 1
})
