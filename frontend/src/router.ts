import { createRouter, createWebHashHistory } from 'vue-router'
import { sessionUser } from './api/auth'
import type { User } from './api/auth'

declare module 'vue-router' {
  interface RouteMeta { title?: string; description?: string; public?: boolean; roles?: User['role'][] }
}

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('./views/LoginPage.vue'), meta: { title: '登录', public: true } },
    { path: '/', component: () => import('./views/OverviewPage.vue'), meta: { title: '工作总览', description: '从数据出发，关注城市道路安全。' } },
    { path: '/collisions', component: () => import('./components/CollisionPanel.vue'), meta: { title: '事故查询', description: '检索碰撞记录，了解事故、人员与车辆详情。' } },
    { path: '/map', component: () => import('./components/MapPanel.vue'), meta: { title: '地图与交叉口', description: '在空间中观察事故分布，核对交叉口与地点归属。' } },
    { path: '/risks', component: () => import('./views/RiskPage.vue'), meta: { title: '风险画像', description: '按周期和规则查看交叉口风险，以及每一项判断依据。' } },
    { path: '/governance', component: () => import('./views/GovernancePage.vue'), meta: { title: '治理任务', description: '从风险发现到执行复核，记录每一次治理行动。', roles: ['ADMIN', 'MANAGER'] } },
    { path: '/statistics', component: () => import('./components/StatisticsPanel.vue'), meta: { title: '统计报表', description: '在一致的数据口径下分析趋势、查看分布与输出报表。' } },
    { path: '/imports', component: () => import('./components/ImportPanel.vue'), meta: { title: '数据导入与质量', description: '追踪来源、导入批次与数据问题。', roles: ['ADMIN', 'MANAGER'] } },
    { path: '/users', component: () => import('./components/AccountPanel.vue'), props: { mode: 'users' }, meta: { title: '账户管理', description: '管理账户、角色和启用状态。', roles: ['ADMIN'] } },
    { path: '/account', component: () => import('./components/AccountPanel.vue'), props: { mode: 'profile' }, meta: { title: '个人账户', description: '查看当前身份，管理账户密码。' } },
    { path: '/forbidden', component: () => import('./views/MessagePage.vue'), props: { forbidden: true }, meta: { title: '无访问权限' } },
    { path: '/:pathMatch(.*)*', component: () => import('./views/MessagePage.vue'), meta: { title: '页面不存在' } },
  ],
  scrollBehavior(to, from, saved) { return saved ?? (to.path === from.path ? {} : { top: 0 }) },
})

// 只接受站内目标；登录后可继续访问刷新前的页面。
export function returnPath(value: unknown) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/login') ? value : '/'
}
router.beforeEach(to => {
  const user = sessionUser.value
  if (!to.meta.public && !user) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.path === '/login' && user) return '/'
  if (to.meta.roles && user && !to.meta.roles.includes(user.role)) return '/forbidden'
})
router.afterEach(to => { document.title = `${to.meta.title ?? '工作空间'} · Vision Zero` })
