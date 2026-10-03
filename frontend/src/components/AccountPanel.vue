<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { roleLabels } from '../navigation'
import { api, clearSession, hasSession, sessionUser, type User } from '../api/auth'

const props = defineProps<{ mode: 'users' | 'profile' }>()

const current = sessionUser
const users = ref<User[]>([])
const error = ref('')
const notice = ref('')
const busy = ref(false)
const newName = ref('')
const newDisplay = ref('')
const newRole = ref<User['role']>('VIEWER')
const newPassword = ref('')
const oldPassword = ref('')
const nextPassword = ref('')

async function run(action: () => Promise<void>) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() }
  catch (exception) {
    error.value = exception instanceof Error ? exception.message : '操作未完成。'
    if (!hasSession()) {
      current.value = null
      users.value = []
      newPassword.value = ''; oldPassword.value = ''; nextPassword.value = ''
    }
  }
  finally { busy.value = false }
}

async function loadUsers() {
  const result = await api<{ items: User[]; total: number }>('/users?page_size=100')
  users.value = result.items
  if (result.total > 100) notice.value = '当前展示前100个账户；更多账户可通过分页API查询。'
}

async function createAccount() {
  await run(async () => {
    await api('/users', 'POST', { username: newName.value, display_name: newDisplay.value,
      role: newRole.value, password: newPassword.value })
    newName.value = ''
    newDisplay.value = ''
    newPassword.value = ''
    await loadUsers()
    notice.value = '账户已建立。'
  })
}

async function save(user: User, toggle = false) {
  if (toggle && !window.confirm(`确认${user.is_active ? '停用' : '启用'}账户“${user.username}”？停用会使现有会话失效。`)) return
  await run(async () => {
    await api(`/users/${user.user_id}`, 'PATCH', { expected_version: user.version,
      display_name: user.display_name, role: user.role, is_active: toggle ? !user.is_active : user.is_active })
    current.value = await api<User>('/auth/me')
    if (current.value.role === 'ADMIN') await loadUsers()
    else users.value = []
    notice.value = '修改已保存；角色或启停变更会使该账户已有会话失效。'
  })
}

async function changePassword() {
  await run(async () => {
    await api('/auth/change-password', 'POST', { old_password: oldPassword.value, new_password: nextPassword.value })
    clearSession()
    current.value = null
    users.value = []
    notice.value = '密码已修改，请重新登录。此账户其他设备的会话也已失效。'
  })
  oldPassword.value = ''
  nextPassword.value = ''
}
onMounted(() => { if (props.mode === 'users' && current.value?.role === 'ADMIN') void run(loadUsers) })
</script>

<template>
  <section v-if="current" class="account-panel">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <template v-if="mode === 'profile'">
      <div class="section-title"><div><h2>账户信息</h2><p class="detail">{{ current.display_name }} · {{ current.username }}</p></div><span class="status-chip">{{ roleLabels[current.role] }}</span></div>
      <div class="account-security"><h3>修改密码</h3><p class="detail">修改成功后，此账户的全部现有会话将失效，请使用新密码重新登录。</p><form class="account-form" @submit.prevent="changePassword"><label>原密码<input v-model="oldPassword" type="password" autocomplete="current-password" required maxlength="128" /></label><label>新密码<input v-model="nextPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="128" /><small>至少 12 个字符</small></label><button :disabled="busy">修改密码并重新登录</button></form></div>
    </template>
    <template v-if="mode === 'users' && current.role === 'ADMIN'">
      <div class="section-title"><div><h2>用户目录</h2><p class="detail">不同角色拥有不同的数据与操作权限。</p></div><button class="secondary-button" :disabled="busy" @click="run(loadUsers)">刷新账户</button></div>
      <details class="create-account"><summary>建立账户</summary><form class="account-form" @submit.prevent="createAccount"><label>登录名<input v-model="newName" required pattern="[A-Za-z][A-Za-z0-9_.-]{2,79}" autocomplete="off" /></label><label>显示名<input v-model="newDisplay" required maxlength="80" /></label><label>角色<select v-model="newRole"><option value="VIEWER">查询用户</option><option value="MANAGER">交通管理人员</option><option value="ADMIN">系统管理员</option></select></label><label>初始密码<input v-model="newPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="128" /></label><button :disabled="busy">建立账户</button></form></details>
      <p v-if="busy && !users.length" class="empty-state" role="status">正在加载账户…</p>
      <div class="table-wrap"><table><thead><tr><th>登录名</th><th>显示名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="user in users" :key="user.user_id"><td><strong>{{ user.username }}</strong></td><td><input v-model="user.display_name" :aria-label="`${user.username}显示名`" maxlength="80" /></td><td><select v-model="user.role" :aria-label="`${user.username}角色`"><option value="ADMIN">系统管理员</option><option value="MANAGER">交通管理人员</option><option value="VIEWER">查询用户</option></select></td><td><span :class="['status-chip', { 'severity-warning': !user.is_active }]">{{ user.is_active ? '启用' : '停用' }}</span></td><td class="row-actions"><button :disabled="busy" @click="save(user)">保存</button><button class="secondary-button" :disabled="busy" @click="save(user, true)">{{ user.is_active ? '停用' : '启用' }}</button></td></tr></tbody></table></div>
    </template>
  </section>
</template>
