import type { User } from './api/auth'

export type IconName = 'overview' | 'collisions' | 'map' | 'risks' | 'governance' | 'statistics' | 'imports' | 'users' | 'menu' | 'chevron' | 'logout' | 'arrow' | 'shield'
export const roleLabels = { ADMIN: '系统管理员', MANAGER: '交通管理人员', VIEWER: '查询用户' }
export const navigation: { path: string; label: string; group: string; icon: IconName; roles?: User['role'][] }[] = [
  { path: '/', label: '工作总览', group: '工作空间', icon: 'overview' },
  { path: '/collisions', label: '事故查询', group: '数据分析', icon: 'collisions' },
  { path: '/map', label: '地图与交叉口', group: '数据分析', icon: 'map' },
  { path: '/risks', label: '风险画像', group: '数据分析', icon: 'risks' },
  { path: '/statistics', label: '统计报表', group: '数据分析', icon: 'statistics' },
  { path: '/governance', label: '治理任务', group: '治理工作', icon: 'governance', roles: ['ADMIN', 'MANAGER'] },
  { path: '/imports', label: '数据导入与质量', group: '系统管理', icon: 'imports', roles: ['ADMIN', 'MANAGER'] },
  { path: '/users', label: '账户管理', group: '系统管理', icon: 'users', roles: ['ADMIN'] },
]
