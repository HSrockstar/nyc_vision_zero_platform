'use strict';

// 面向合成隔离库的真实浏览器回归。此脚本不 mock 成功业务响应，也不修改业务数据（唯一例外为显式开启的一次治理草稿创建）。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(path.join(process.cwd(), 'frontend', 'node_modules', 'playwright'));

const [, , configArg, outputArg] = process.argv;
if (!configArg || !outputArg) {
  process.stderr.write('用法：node frontend/tests/refactor.acceptance.cjs <browser-private.json> <空输出目录>\n');
  process.exit(2);
}

const configPath = path.resolve(process.cwd(), configArg);
const outputDir = path.resolve(process.cwd(), outputArg);
const reportPath = path.join(outputDir, 'browser-acceptance-report.json');
const screenshotDir = path.join(outputDir, 'screenshots');
const report = {
  result: 'running',
  started_at: new Date().toISOString(),
  checks: [],
  screenshots: [],
  api_requests: [],
  api_failures: [],
  blocked_mutations: [],
  expected_tile_aborts: 0,
  expected_auth_console_errors: [],
  expected_invalid_login_responses: [],
  console_errors: [],
  page_errors: [],
  request_failures: [],
  script_errors: [],
  governance_create: null,
};

let browser;
let context;
let page;
let activeRole = 'unassigned';
let expectedInvalidLogin = false;
let draftCreateWindow = false;
let draftCreateCount = 0;
let detailEvidence = null;
let currentSecrets = [];
const collisionResponseSummaries = [];
let pendingExpectedLogin401Console = 0;

function sanitize(value) {
  let text = String(value ?? '');
  for (const secret of currentSecrets) {
    if (secret) text = text.split(secret).join('[已脱敏]');
  }
  return text
    .replace(/Bearer\s+[^\s"'<>]+/gi, 'Bearer [已脱敏]')
    .replace(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}/g, '[JWT已脱敏]')
    .replace(/(password|token|authorization)\s*[:=]\s*[^\s,;]+/gi, '$1=[已脱敏]');
}
function addCheck(name, passed, detail = '') {
  report.checks.push({ name, passed, ...(detail ? { detail: sanitize(detail) } : {}) });
}
function ensure(condition, message) {
  assert.ok(condition, message);
}
async function scenario(name, work) {
  try {
    await work();
    addCheck(name, true);
    return true;
  } catch (error) {
    addCheck(name, false, error instanceof Error ? error.message : String(error));
    return false;
  }
}
function safeQuery(url) {
  const params = new URL(url).searchParams;
  const result = {};
  for (const key of ['start', 'end', 'page', 'page_size', 'include_total', 'risk_level', 'sort', 'status', 'my_todo', 'rule_id', 'west', 'south', 'east', 'north']) {
    if (params.has(key)) result[key] = params.get(key);
  }
  if (params.has('street')) {
    result.street_filter = detailEvidence && params.get('street') === detailEvidence.street ? 'synthetic_detail' : 'present';
  }
  result.has_cursor = params.has('cursor');
  return result;
}
function apiPath(url) {
  const parsed = new URL(url);
  return parsed.pathname.startsWith('/api/v1/') ? parsed.pathname : null;
}
function addApiListeners(targetPage) {
  const byRequest = new WeakMap();
  targetPage.on('request', request => {
    const pathname = apiPath(request.url());
    if (!pathname) return;
    const record = {
      role: activeRole,
      method: request.method(),
      path: pathname,
      query: safeQuery(request.url()),
      status: null,
    };
    byRequest.set(request, record);
    report.api_requests.push(record);
  });
  targetPage.on('response', response => {
    const record = byRequest.get(response.request());
    if (!record) return;
    record.status = response.status();
    if (record.method === 'POST' && record.path === '/api/v1/governance-tasks' && report.governance_create) {
      report.governance_create.status = response.status();
    }
    if (response.status() < 400) return;
    const expected = record.path === '/api/v1/auth/login' && record.status === 401 && expectedInvalidLogin;
    if (expected) {
      pendingExpectedLogin401Console += 1;
      report.expected_invalid_login_responses.push({ path: record.path, status: record.status });
    }
    if (!expected) report.api_failures.push({ role: record.role, method: record.method, path: record.path, status: record.status });
    return;
  });
  targetPage.on('requestfailed', request => {
    const url = request.url();
    if (/^https?:\/\/tile\.openstreetmap\.org\//i.test(url)) return;
    const pathname = apiPath(url);
    if (pathname) report.request_failures.push({ role: activeRole, method: request.method(), path: pathname });
  });
  targetPage.on('pageerror', error => report.page_errors.push({ role: activeRole, message: sanitize(error.message) }));
  targetPage.on('console', message => {
    if (message.type() !== 'error') return;
    const text = message.text();
    const sourceUrl = message.location().url || '';
    if (/ERR_(?:ABORTED|BLOCKED_BY_CLIENT)/.test(text) && /tile\.openstreetmap\.org/i.test(sourceUrl + text)) {
      return;
    }
    if (pendingExpectedLogin401Console > 0 && /status of 401|401 \(Unauthorized\)/i.test(text)) {
      pendingExpectedLogin401Console -= 1;
      report.expected_auth_console_errors.push({ path: '/api/v1/auth/login', status: 401 });
      return;
    }
    report.console_errors.push({ role: activeRole, message: sanitize(text) });
  });
  targetPage.on('response', response => {
    const record = byRequest.get(response.request());
    if (!record || record.path !== '/api/v1/collisions' || record.method !== 'GET') return;
    void response.json().then(payload => {
      const data = payload?.data ?? payload;
      const items = Array.isArray(data?.items) ? data.items : [];
      const targetIndex = detailEvidence ? items.findIndex(item => String(item.collision_id) === detailEvidence.id) : -1;
      const summary = {
        role: record.role,
        start: record.query.start ?? '',
        end: record.query.end ?? '',
        street_filter: record.query.street_filter ?? 'absent',
        count: items.length,
        target_index: targetIndex,
      };
      collisionResponseSummaries.push({ ...summary, ids: items.map(item => String(item.collision_id)) });
      report.collision_query_summaries ??= [];
      report.collision_query_summaries.push(summary);
    }).catch(() => {});
  });
}
async function login(pageToUse, user, password) {
  await pageToUse.getByLabel('登录名', { exact: true }).fill(user.username);
  await pageToUse.getByLabel('密码', { exact: true }).fill(password);
  await pageToUse.getByRole('button', { name: '登录', exact: true }).click();
}
async function routeTo(pageToUse, routePath, title, resolvedPath = routePath) {
  const expectedHash = '#' + routePath;
  const resolvedHash = '#' + resolvedPath;
  await pageToUse.evaluate(hash => {
    if (window.location.hash !== hash) window.location.hash = hash;
  }, expectedHash);
  await pageToUse.waitForFunction(hash => window.location.hash.split('?')[0] === hash, resolvedHash, { timeout: 10000 });
  await pageToUse.getByRole('heading', { name: title, exact: true, level: 1 }).waitFor({ state: 'visible', timeout: 10000 });
}
async function signInAs(role, routePath) {
  activeRole = role;
  const user = config.users[role];
  if (page.url().includes('#/login')) {
    await page.waitForSelector('input[autocomplete="username"]');
  } else {
    await page.goto(config.base_url + '/#' + routePath, { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: '登录工作空间', exact: true, level: 2 }).waitFor({ state: 'visible', timeout: 10000 });
  }
  await login(page, user, config.password);
  await routeTo(page, routePath, routeTitles[routePath]);
}
const routeTitles = {
  '/': '工作总览',
  '/collisions': '事故查询',
  '/map': '地图与交叉口',
  '/risks': '风险画像',
  '/governance': '治理任务',
  '/statistics': '统计报表',
  '/imports': '数据导入与质量',
  '/users': '账户管理',
  '/account': '个人账户',
  '/forbidden': '无访问权限',
};
function slug(routePath) {
  return routePath === '/' ? 'overview' : routePath.slice(1).replaceAll('/', '-');
}
function screenshotMasks(routePath) {
  const masks = [page.locator('.profile-link')];
  if (routePath === '/users') masks.push(page.locator('.account-panel .table-wrap tbody td:first-child'));
  if (routePath === '/account') masks.push(page.locator('.account-panel .section-title .detail'));
  return masks;
}
async function capture(routePath, viewport) {
  const file = path.join(screenshotDir, activeRole + '-' + slug(routePath) + '-' + viewport + '.png');
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled', mask: screenshotMasks(routePath), maskColor: '#66758a' });
  report.screenshots.push(path.relative(outputDir, file).replaceAll('\\', '/'));
}
async function verifyNoPageOverflow(routePath) {
  // 等待主工作区与响应式断点完成布局，再判定整页尺寸。
  await page.waitForTimeout(450);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  }));
  ensure(dimensions.document <= dimensions.viewport + 1, routePath + ' 整页横向溢出：' + dimensions.document + ' > ' + dimensions.viewport);
}
async function waitUntil(predicate, timeoutMs = 10000, message = '等待页面状态超时') {
  await page.waitForFunction(predicate, null, { timeout: timeoutMs }).catch(error => {
    throw new Error(message + '：' + (error instanceof Error ? error.message : String(error)));
  });
}
async function waitCollisionQueryIdle() {
  await page.waitForFunction(() => {
    const button = document.querySelector('.collision-panel .filter-footer button[type="submit"]');
    return Boolean(button && !button.disabled);
  }, null, { timeout: 10000 });
}
function apiRecords(pathname, method = 'GET') {
  return report.api_requests.filter(item => item.path === pathname && item.method === method);
}
async function waitApiSuccess(pathname, beforeCount, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = apiRecords(pathname).slice(beforeCount).find(item => item.status === 200);
    if (response) return response;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error('等待 API 成功响应超时：' + pathname);
}
async function waitCollisionSummary(role, start, end) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const summary = collisionResponseSummaries.slice().reverse().find(item => item.role === role
      && item.start === start && item.end === end && item.street_filter === 'synthetic_detail');
    if (summary) return summary;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error('等待目标日期与街道事故查询结果超时');
}
async function waitForMapBounds(beforeCount) {
  const request = await waitApiSuccess('/api/v1/map/collisions', beforeCount);
  return request.query;
}
async function openConfiguredCollision(role) {
  const summary = await waitCollisionSummary(role, detailEvidence.start, detailEvidence.end);
  const rowIndex = summary.ids.indexOf(detailEvidence.id);
  ensure(rowIndex >= 0, '目标合成事故编号没有出现在日期与街道筛选结果中');
  const row = page.locator('.collision-table tbody tr').nth(rowIndex);
  await row.waitFor({ state: 'visible', timeout: 10000 });
  await row.getByRole('button', { name: '查看详情', exact: true }).click();
  await page.getByRole('heading', { name: new RegExp('事故详情.*' + detailEvidence.id) }).waitFor({ state: 'visible', timeout: 10000 });
  await page.locator('section[aria-label="人员明细"] tbody tr').first().waitFor({ state: 'visible', timeout: 10000 });
}
function hashQueryValue(url, key) {
  const hash = new URL(url).hash.slice(1);
  const query = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : '';
  return new URLSearchParams(query).get(key);
}
async function waitForHashRoute(routePath, title) {
  const hash = '#' + routePath;
  await page.waitForFunction(expected => window.location.hash.split('?')[0] === expected, hash, { timeout: 10000 });
  await page.getByRole('heading', { name: title, exact: true, level: 1 }).waitFor({ state: 'visible', timeout: 10000 });
}
function safeCreateBodySummary(body) {
  let parsed;
  try { parsed = JSON.parse(body ?? '{}'); } catch { parsed = {}; }
  return {
    has_profile_id: typeof parsed.profile_id === 'string' && parsed.profile_id.length > 0,
    has_title: typeof parsed.title === 'string' && parsed.title.trim().length > 0,
    has_description: typeof parsed.description === 'string' && parsed.description.trim().length > 0,
    has_radius: Number.isFinite(parsed.radius_m) && parsed.radius_m >= 1,
    high_risk: parsed.rationale === null || parsed.rationale === '',
  };
}

async function main() {
  ensure(fs.existsSync(configPath), '配置文件不存在');
  const stat = fs.statSync(configPath);
  ensure(stat.isFile(), '配置路径不是文件');
  config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  ensure(config.synthetic_only === true, 'synthetic_only 必须为 true');
  ensure(typeof config.database === 'string' && /^vision_zero_m1_test_[a-f0-9]+$/i.test(config.database), '数据库名不符合随机隔离合成库格式');
  ensure(typeof config.base_url === 'string', '缺少本地 base_url');
  const base = new URL(config.base_url);
  ensure(base.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(base.hostname) && base.port === '5176', '只允许访问本机 5176 前端');
  ensure(typeof config.password === 'string' && config.password.length >= 12, '缺少合成账户密码');
  for (const role of ['admin', 'manager', 'assignee', 'viewer']) {
    const user = config.users?.[role];
    ensure(user && typeof user.username === 'string' && user.username && typeof user.user_id === 'string' && user.user_id, '合成账户配置不完整：' + role);
  }
  ensure(config.detail_collision_id !== undefined && String(config.detail_collision_id) === '910013', '缺少本轮专用合成详情事故编号');
  currentSecrets = [config.password, ...Object.values(config.users).map(user => user.username)];
  detailEvidence = {
    id: String(config.detail_collision_id),
    street: 'FRONTEND SYNTHETIC BROADWAY',
    start: '2025-02-08',
    end: '2025-02-09',
  };

  ensure(!fs.existsSync(outputDir) || fs.readdirSync(outputDir).length === 0, '输出目录已存在且非空；拒绝覆盖已有证据');
  fs.mkdirSync(screenshotDir, { recursive: true });
  report.environment = { synthetic_only: true, host: base.hostname, port: base.port };

  browser = await chromium.launch({
    headless: true,
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
  await context.route('**/*', async route => {
    const request = route.request();
    const url = request.url();
    if (/^https?:\/\/tile\.openstreetmap\.org\//i.test(url)) {
      report.expected_tile_aborts += 1;
      await route.abort('blockedbyclient');
      return;
    }
    const pathname = apiPath(url);
    if (pathname && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      const loginAllowed = request.method() === 'POST' && pathname === '/api/v1/auth/login';
      const draftAllowed = request.method() === 'POST' && pathname === '/api/v1/governance-tasks'
        && draftCreateWindow && draftCreateCount === 0;
      if (draftAllowed) {
        draftCreateCount += 1;
        report.governance_create = {
          attempts: draftCreateCount,
          request: safeCreateBodySummary(request.postData()),
          status: null,
        };
      }
      if (!loginAllowed && !draftAllowed) {
        report.blocked_mutations.push({ role: activeRole, method: request.method(), path: pathname });
        await route.fulfill({ status: 405, contentType: 'application/json', body: '{"error":{"message":"Blocked by acceptance harness"}}' });
        return;
      }
    }
    await route.continue();
  });
  page = await context.newPage();
  addApiListeners(page);

  // 登录失败、原目标路由登录与刷新后重新登录。
  activeRole = 'admin';
  await page.goto(config.base_url + '/#/collisions', { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: '登录工作空间', exact: true, level: 2 }).waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForFunction(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('redirect') === '/collisions', null, { timeout: 10000 });
  ensure(hashQueryValue(page.url(), 'redirect') === '/collisions', '未登录直达事故页时没有保留目标路由');
  expectedInvalidLogin = true;
  await login(page, config.users.admin, config.password + '-incorrect');
  const loginError = page.getByRole('alert');
  await loginError.waitFor({ state: 'visible', timeout: 10000 });
  ensure((await loginError.innerText()).trim().length > 0, '错误登录没有反馈');
  ensure(apiRecords('/api/v1/auth/login', 'POST').some(item => item.status === 401), '错误登录未收到预期 401');
  expectedInvalidLogin = false;
  await login(page, config.users.admin, config.password);
  await waitForHashRoute('/collisions', routeTitles['/collisions']);
  addCheck('管理员：错误登录反馈与目标路由登录', true);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: '登录工作空间', exact: true, level: 2 }).waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForFunction(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('redirect') === '/collisions', null, { timeout: 10000 });
  ensure(hashQueryValue(page.url(), 'redirect') === '/collisions', '刷新后没有回到登录页并保留当前目标路由');
  await login(page, config.users.admin, config.password);
  await waitForHashRoute('/collisions', routeTitles['/collisions']);
  addCheck('管理员：刷新后需要重新登录并返回目标页', true);

  // 管理员的已授权路由和 desktop / mobile 页面截图。
  const adminRoutes = ['/', '/collisions', '/map', '/risks', '/governance', '/statistics', '/imports', '/users', '/account'];
  for (const routePath of adminRoutes) {
    await scenario('ADMIN 路由可访问：' + routePath, async () => {
      await routeTo(page, routePath, routeTitles[routePath]);
      if (routePath === '/users') {
        await page.locator('.account-panel table tbody tr').first().waitFor({ state: 'visible', timeout: 10000 });
        ensure(await page.locator('.account-panel table tbody tr').count() >= 4, '用户目录没有显示合成账户');
      }
      await capture(routePath, 'desktop');
    });
  }
  await scenario('ADMIN：账户页与用户目录复用时重新加载并清除密码状态', async () => {
    await routeTo(page, '/account', routeTitles['/account']);
    const nextPassword = page.locator('input[autocomplete="new-password"]').first();
    await nextPassword.fill('synthetic-unsent-password-state-123');
    const userListRequestsBefore = apiRecords('/api/v1/users').length;
    await routeTo(page, '/users', routeTitles['/users']);
    await page.locator('.account-panel table tbody tr').first().waitFor({ state: 'visible', timeout: 10000 });
    ensure(apiRecords('/api/v1/users').length > userListRequestsBefore, '从账户页切换后没有重新请求用户目录');
    await routeTo(page, '/account', routeTitles['/account']);
    ensure(await page.locator('input[autocomplete="new-password"]').first().inputValue() === '', '离开账户页再返回时新密码状态没有清除');
  });

  await scenario('ADMIN：事故查询游标绑定、筛选重置与合成详情分页', async () => {
    await routeTo(page, '/collisions', routeTitles['/collisions']);
    await waitCollisionQueryIdle();
    await page.locator('.results-heading').waitFor({ state: 'visible', timeout: 10000 });
    const collisionPath = '/api/v1/collisions';
    const firstBefore = apiRecords(collisionPath).length;
    // 当前无筛选查询默认有 73 起以上合成记录，每页 25 起。
    await page.getByRole('button', { name: '查询事故', exact: true }).click();
    await waitCollisionQueryIdle();
    await page.getByText(/25 条已加载/, { exact: false }).waitFor({ state: 'visible', timeout: 10000 });
    const firstPage = apiRecords(collisionPath).slice(firstBefore);
    ensure(firstPage.some(item => !item.query.has_cursor && item.query.page_size === '25'), '首屏查询缺少 page_size=25 或意外携带游标');
    const secondBefore = apiRecords(collisionPath).length;
    await page.getByRole('button', { name: '加载更多事故', exact: true }).click();
    await page.getByText(/50 条已加载/, { exact: false }).waitFor({ state: 'visible', timeout: 10000 });
    const secondPage = apiRecords(collisionPath).slice(secondBefore);
    ensure(secondPage.some(item => item.query.has_cursor && item.query.page_size === '25'), '第二页没有使用服务端游标和同一页大小');
    await page.getByLabel('街道关键词', { exact: true }).fill('FILTER SNAPSHOT CHECK');
    const more = page.getByRole('button', { name: /加载更多事故|重新查询后继续/ });
    ensure(await more.isDisabled(), '筛选条件变化后仍允许沿旧游标加载');
    const requestCountBeforeDisabledClick = apiRecords(collisionPath).length;
    if (await more.isEnabled()) await more.click();
    ensure(apiRecords(collisionPath).length === requestCountBeforeDisabledClick, '更改筛选条件后仍发出旧游标请求');
    await page.getByRole('button', { name: '查询事故', exact: true }).click();
    await waitCollisionQueryIdle();
    await page.getByText(/没有匹配的事故记录|0 条已加载/, { exact: false }).waitFor({ state: 'visible', timeout: 10000 });
    const resetPage = apiRecords(collisionPath).slice(requestCountBeforeDisabledClick);
    ensure(resetPage.some(item => !item.query.has_cursor && item.query.street_filter === 'present'), '更改筛选条件后没有从无游标的新查询开始');

    await page.getByLabel('开始日期（包含）', { exact: true }).fill(detailEvidence.start);
    await page.getByLabel('结束日期（不包含）', { exact: true }).fill(detailEvidence.end);
    await page.getByLabel('街道关键词', { exact: true }).fill(detailEvidence.street);
    const detailRequestBefore = apiRecords(collisionPath).length;
    await page.getByRole('button', { name: '查询事故', exact: true }).click();
    await waitCollisionQueryIdle();
    const targetQuery = apiRecords(collisionPath).slice(detailRequestBefore);
    ensure(targetQuery.some(item => item.query.start === detailEvidence.start && item.query.end === detailEvidence.end
      && item.query.street_filter === 'synthetic_detail' && !item.query.has_cursor), '合成详情检索没有使用目标日期与街道且从第一页开始');
    const targetSummary = await waitCollisionSummary('admin', detailEvidence.start, detailEvidence.end);
    ensure(targetSummary.count >= 1, '合成详情筛选没有返回记录');
    await openConfiguredCollision('admin');
    ensure(await page.locator('section[aria-label="人员明细"] tbody tr').count() === 20, '人员明细首页不是 20 条');
    const peoplePage2Before = apiRecords('/api/v1/collisions/' + detailEvidence.id + '/persons').length;
    await page.getByRole('button', { name: '加载更多人员', exact: true }).click();
    await waitUntil(() => document.querySelectorAll('section[aria-label="人员明细"] tbody tr').length === 21, 10000, '人员第二页未追加到详情');
    ensure(apiRecords('/api/v1/collisions/' + detailEvidence.id + '/persons').slice(peoplePage2Before)
      .some(item => item.query.page === '2'), '人员明细未请求第 2 页');
    await page.getByRole('tab', { name: '车辆明细', exact: true }).click();
    ensure(await page.locator('section[aria-label="车辆明细"] tbody tr').count() === 20, '车辆明细首页不是 20 条');
    const vehiclePage2Before = apiRecords('/api/v1/collisions/' + detailEvidence.id + '/vehicles').length;
    await page.getByRole('button', { name: '加载更多车辆', exact: true }).click();
    await waitUntil(() => document.querySelectorAll('section[aria-label="车辆明细"] tbody tr').length === 21, 10000, '车辆第二页未追加到详情');
    ensure(apiRecords('/api/v1/collisions/' + detailEvidence.id + '/vehicles').slice(vehiclePage2Before)
      .some(item => item.query.page === '2'), '车辆明细未请求第 2 页');
    ensure(await page.locator('.detail-drawer, .el-drawer').count() > 0, '事故详情抽屉没有渲染');
  });

  await scenario('ADMIN：HIGH画像携带依据并预填草稿（创建复用 browser-02 的真实201证据）', async () => {
    await routeTo(page, '/risks', routeTitles['/risks']);
    const highCard = page.locator('.profile-card').filter({ has: page.locator('.risk-high') }).first();
    await highCard.waitFor({ state: 'visible', timeout: 15000 });
    const streetPair = (await highCard.locator('h4').innerText()).trim();
    const createButton = highCard.getByRole('button', { name: '建立治理草稿', exact: true });
    await createButton.click();
    await routeTo(page, '/governance', routeTitles['/governance']);
    const draftForm = page.locator('form.draft-box');
    await draftForm.waitFor({ state: 'visible', timeout: 10000 });
    const title = await draftForm.getByLabel('任务标题', { exact: true }).inputValue();
    ensure(title.length > 0 && title.includes(streetPair), '初始风险画像没有预填治理草稿标题');
    const profileReference = (await draftForm.locator('.profile-reference').innerText()).trim();
    ensure(profileReference.includes('依据画像 #') && profileReference.includes(streetPair) && profileReference.includes('HIGH'), '治理草稿没有显示 HIGH 画像依据');
    const create = draftForm.getByRole('button', { name: '建立模拟草稿', exact: true });
    ensure(await create.isDisabled(), '空说明下的治理草稿不应可提交');
    report.reused_prior_governance_create_evidence = { report: 'browser-02/browser-acceptance-report.json', attempts: 1, status: 201 };
    ensure(draftCreateCount === 0, 'browser-03 不应再次创建治理草稿');
  });

  await scenario('ADMIN：地图真实渲染、缩放控件、侧栏与移动面板键盘切换', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await routeTo(page, '/map', routeTitles['/map']);
    const mapCanvas = page.locator('.map-canvas.leaflet-container');
    await mapCanvas.waitFor({ state: 'visible', timeout: 10000 });
    const mapSize = await mapCanvas.boundingBox();
    ensure(mapSize && mapSize.width > 300 && mapSize.height > 300, 'Leaflet 地图画布没有有效尺寸');
    ensure(await page.locator('.leaflet-control-zoom-in').isVisible(), '地图放大控件未渲染');
    ensure(await page.locator('.result-sidebar').isVisible(), '桌面端地图结果侧栏未显示');
    const sideSize = await page.locator('.result-sidebar').boundingBox();
    ensure(sideSize && sideSize.width > 150, '桌面端地图结果侧栏宽度无效');
    const mapRequestsBeforeZoom = apiRecords('/api/v1/map/collisions').length;
    await page.locator('.leaflet-control-zoom-in').click();
    await page.getByText('地图范围或中心已变化；点击“查询当前地图范围”刷新事故点。', { exact: true }).waitFor();
    await page.getByRole('button', { name: '查询当前地图范围', exact: true }).click();
    const zoomedBounds = await waitForMapBounds(mapRequestsBeforeZoom);
    const initialBounds = apiRecords('/api/v1/map/collisions').slice(0, mapRequestsBeforeZoom).at(-1)?.query;
    ensure(['west', 'south', 'east', 'north'].every(key => Number.isFinite(Number(zoomedBounds[key]))), '缩放后地图查询没有提交完整范围边界');
    ensure(['west', 'south', 'east', 'north'].some(key => zoomedBounds[key] !== initialBounds?.[key]), '缩放后查询边界与原范围完全相同');
    await page.getByRole('button', { name: '收起导航', exact: true }).click();
    ensure(await page.locator('.app-shell').evaluate(element => element.classList.contains('nav-collapsed')), '桌面导航侧栏没有收起');
    await page.getByRole('button', { name: '展开导航', exact: true }).click();
    ensure(await page.locator('.result-sidebar').isVisible(), '桌面导航侧栏恢复后地图结果侧栏丢失');

    await page.setViewportSize({ width: 390, height: 844 });
    const mapTab = page.locator('#map-view-tab');
    const resultsTab = page.locator('#map-results-tab');
    await mapTab.waitFor({ state: 'visible', timeout: 5000 });
    await resultsTab.click();
    ensure(await resultsTab.getAttribute('aria-selected') === 'true' && await page.locator('#map-results-panel').isVisible(), '移动端结果面板切换失败');
    await mapTab.focus();
    await page.keyboard.press('Home');
    ensure(await mapTab.getAttribute('aria-selected') === 'true', 'Home 没有先选中地图 tab');
    await page.keyboard.press('ArrowRight');
    ensure(await resultsTab.getAttribute('aria-selected') === 'true' && await resultsTab.evaluate(element => element === document.activeElement), '地图 tab 的方向键没有切换并移动焦点');
    await page.keyboard.press('Home');
    ensure(await mapTab.getAttribute('aria-selected') === 'true' && await mapTab.evaluate(element => element === document.activeElement), 'Home 没有回到地图 tab');
    await page.keyboard.press('End');
    ensure(await resultsTab.getAttribute('aria-selected') === 'true' && await resultsTab.evaluate(element => element === document.activeElement), 'End 没有切换到结果 tab');
  });

  // 管理端所有业务页在 390px 逐页检查；用户名相关区域在截图中遮罩。
  await page.setViewportSize({ width: 390, height: 844 });
  for (const routePath of adminRoutes) {
    await scenario('ADMIN 390px 无整页横溢并截图：' + routePath, async () => {
      await routeTo(page, routePath, routeTitles[routePath]);
      await verifyNoPageOverflow(routePath);
      await capture(routePath, 'mobile');
    });
  }

  await scenario('ADMIN：跳转链接聚焦主内容', async () => {
    await routeTo(page, '/', routeTitles['/']);
    const skipLink = page.getByRole('link', { name: '跳到主要内容', exact: true });
    await skipLink.focus();
    await page.keyboard.press('Enter');
    ensure(await page.evaluate(() => document.activeElement?.id === 'workspace-content'), '跳转主内容后焦点没有落到主内容区');
  });

  await scenario('ADMIN：移动导航焦点陷阱、Escape 关闭并恢复焦点', async () => {
    await routeTo(page, '/', routeTitles['/']);
    const openButton = page.getByRole('button', { name: '打开导航', exact: true });
    await openButton.click();
    const dialog = page.locator('aside[role="dialog"]');
    await dialog.waitFor({ state: 'visible', timeout: 5000 });
    const focusables = dialog.locator('a:visible,button:visible');
    const count = await focusables.count();
    ensure(count >= 2, '移动导航没有可测试的首尾焦点元素');
    const first = focusables.first();
    const last = focusables.last();
    await last.focus();
    await page.keyboard.press('Tab');
    ensure(await first.evaluate(element => element === document.activeElement), 'Tab 没有从移动导航末项循环到首项');
    await first.focus();
    await page.keyboard.press('Shift+Tab');
    ensure(await last.evaluate(element => element === document.activeElement), 'Shift+Tab 没有从移动导航首项循环到末项');
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden', timeout: 5000 });
    ensure(await openButton.evaluate(element => element === document.activeElement), '关闭移动导航后焦点没有恢复到打开按钮');
  });

  // 管理者和查询用户的权限矩阵、页面与详情隐私。
  await signInAs('manager', '/');
  await page.setViewportSize({ width: 1440, height: 1000 });
  const managerRoutes = ['/', '/collisions', '/map', '/risks', '/governance', '/statistics', '/imports', '/account'];
  for (const routePath of managerRoutes) {
    await scenario('MANAGER 路由可访问：' + routePath, async () => {
      const importsBefore = routePath === '/imports' ? apiRecords('/api/v1/imports').length : 0;
      await routeTo(page, routePath, routeTitles[routePath]);
      if (routePath === '/imports') {
        await page.locator('.import-page h2').waitFor({ state: 'visible', timeout: 10000 });
        await waitApiSuccess('/api/v1/imports', importsBefore);
        await waitUntil(() => Boolean(document.querySelector('.import-page .batch-card'))
          || document.querySelector('.import-page')?.innerText.includes('当前没有导入批次。'), 10000, 'MANAGER 导入摘要没有加载完成');
        ensure(await page.locator('input[type="file"]').count() === 0, 'MANAGER 页面暴露了文件上传输入框');
        ensure(await page.locator('.batch-card, .empty-state').count() > 0, 'MANAGER 页面没有批次摘要或空态');
      }
    });
  }
  await scenario('MANAGER：管理员专属用户目录直接访问被拒绝', async () => {
    await routeTo(page, '/users', routeTitles['/forbidden'], '/forbidden');
  });
  await scenario('MANAGER：按日期与街道查合成事故并加载明细第 2 页', async () => {
    await routeTo(page, '/collisions', routeTitles['/collisions']);
    await waitCollisionQueryIdle();
    await page.getByLabel('开始日期（包含）', { exact: true }).fill(detailEvidence.start);
    await page.getByLabel('结束日期（不包含）', { exact: true }).fill(detailEvidence.end);
    await page.getByLabel('街道关键词', { exact: true }).fill(detailEvidence.street);
    await page.getByRole('button', { name: '查询事故', exact: true }).click();
    await waitCollisionQueryIdle();
    await openConfiguredCollision('manager');
    const personHeaders = (await page.locator('section[aria-label="人员明细"] thead').innerText()).replace(/\s+/g, ' ');
    ensure(personHeaders.includes('年龄') && personHeaders.includes('性别'), '管理者没有看到人员年龄与性别列');
    ensure(await page.locator('section[aria-label="人员明细"] tbody tr').count() === 20, '管理者人员明细首页不是 20 条');
    const p2Before = apiRecords('/api/v1/collisions/' + detailEvidence.id + '/persons').length;
    await page.getByRole('button', { name: '加载更多人员', exact: true }).click();
    await waitUntil(() => document.querySelectorAll('section[aria-label="人员明细"] tbody tr').length === 21, 10000, '管理者人员第 2 页未追加');
    ensure(apiRecords('/api/v1/collisions/' + detailEvidence.id + '/persons').slice(p2Before).some(item => item.query.page === '2'),
      '管理者详情人员没有请求第 2 页');
    await page.getByRole('tab', { name: '车辆明细', exact: true }).click();
    ensure(await page.locator('section[aria-label="车辆明细"] tbody tr').count() === 20, '管理者车辆明细首页不是 20 条');
    const v2Before = apiRecords('/api/v1/collisions/' + detailEvidence.id + '/vehicles').length;
    await page.getByRole('button', { name: '加载更多车辆', exact: true }).click();
    await waitUntil(() => document.querySelectorAll('section[aria-label="车辆明细"] tbody tr').length === 21, 10000, '管理者车辆第 2 页未追加');
    ensure(apiRecords('/api/v1/collisions/' + detailEvidence.id + '/vehicles').slice(v2Before).some(item => item.query.page === '2'),
      '管理者详情车辆没有请求第 2 页');
  });

  await signInAs('viewer', '/');
  await page.setViewportSize({ width: 1440, height: 1000 });
  const viewerRoutes = ['/', '/collisions', '/map', '/risks', '/statistics', '/account'];
  for (const routePath of viewerRoutes) {
    await scenario('VIEWER 路由可访问：' + routePath, async () => {
      await routeTo(page, routePath, routeTitles[routePath]);
    });
  }
  for (const forbiddenPath of ['/governance', '/users', '/imports']) {
    await scenario('VIEWER 直接访问拒绝：' + forbiddenPath, async () => {
      await routeTo(page, forbiddenPath, routeTitles['/forbidden'], '/forbidden');
    });
  }
  await scenario('VIEWER：人员明细隐藏年龄与性别', async () => {
    await routeTo(page, '/collisions', routeTitles['/collisions']);
    await waitCollisionQueryIdle();
    await page.getByLabel('开始日期（包含）', { exact: true }).fill(detailEvidence.start);
    await page.getByLabel('结束日期（不包含）', { exact: true }).fill(detailEvidence.end);
    await page.getByLabel('街道关键词', { exact: true }).fill(detailEvidence.street);
    await page.getByRole('button', { name: '查询事故', exact: true }).click();
    await waitCollisionQueryIdle();
    await openConfiguredCollision('viewer');
    await waitUntil(() => document.querySelectorAll('section[aria-label="人员明细"] tbody tr').length > 0, 10000, 'VIEWER 人员明细没有加载');
    const headers = await page.locator('section[aria-label="人员明细"] thead').innerText();
    ensure(!headers.includes('年龄') && !headers.includes('性别'), 'VIEWER 人员表格显示了年龄或性别列');
    await page.getByText('当前角色不显示人员年龄与性别。', { exact: true }).waitFor({ state: 'visible', timeout: 5000 });
  });

  // 仅面向业务失败的错误计入验收；预期无效登录与被拦截的地图瓦片单独留证。
  ensure(report.blocked_mutations.length === 0, '发现不在允许范围内的业务写请求');
  ensure(report.api_failures.length === 0, '存在非预期 API 失败');
  ensure(report.request_failures.length === 0, '存在非地图瓦片的请求失败');
  ensure(report.page_errors.length === 0, '存在 JavaScript pageerror');
  ensure(report.console_errors.length === 0, '存在浏览器 console error');
  addCheck('网络与浏览器控制台：无非预期失败或错误', true);
}

let config;
(async () => {
  try {
    await main();
  } catch (error) {
    const message = sanitize(error instanceof Error ? error.stack || error.message : String(error));
    const assertionFailure = error?.name === 'AssertionError';
    const browserFailure = error?.name === 'TimeoutError'
      || /waiting for|timeout|ERR_CONNECTION|net::ERR_|not visible|not enabled/i.test(String(error?.message ?? ''));
    if (report.checks.some(check => !check.passed) || assertionFailure || browserFailure) {
      report.result = 'failed';
      if (assertionFailure) report.acceptance_assertion_failures = [{ message }];
      else report.product_or_browser_failures = [{ message }];
    } else {
      report.result = 'harness_error';
      report.script_errors.push({ message });
    }
  } finally {
    report.finished_at = new Date().toISOString();
    report.summary = {
      passed: report.checks.filter(check => check.passed).length,
      failed: report.checks.filter(check => !check.passed).length,
      screenshots: report.screenshots.length,
      api_failures: report.api_failures.length,
      blocked_mutations: report.blocked_mutations.length,
      page_errors: report.page_errors.length,
      console_errors: report.console_errors.length,
      script_errors: report.script_errors.length,
      acceptance_assertion_failures: report.acceptance_assertion_failures?.length ?? 0,
      governance_create_attempts: draftCreateCount,
    };
    if (report.result === 'running') report.result = report.summary.failed || report.script_errors.length ? 'failed' : 'passed';
    try {
      if (browser) await browser.close();
    } catch (error) {
      report.script_errors.push({ message: '浏览器清理失败：' + sanitize(error instanceof Error ? error.message : String(error)) });
      report.result = 'failed';
    }
    if (fs.existsSync(outputDir)) {
      fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf8');
    }
    process.stdout.write(JSON.stringify({ result: report.result, summary: report.summary, report: reportPath }) + '\n');
    if (report.result !== 'passed') process.exitCode = 1;
  }
})();
