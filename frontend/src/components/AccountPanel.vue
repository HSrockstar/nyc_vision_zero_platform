<script setup lang="ts">
import { ref } from 'vue'
import { api, clearSession, hasSession, login, sessionUser, type User } from '../api/auth'

const current = sessionUser
const users = ref<User[]>([])
const username = ref('')
const password = ref('')
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
      password.value = ''; newPassword.value = ''; oldPassword.value = ''; nextPassword.value = ''
    }
  }
  finally { busy.value = false }
}

async function loadUsers() {
  const result = await api<{ items: User[]; total: number }>('/users?page_size=100')
  users.value = result.items
  if (result.total > 100) notice.value = '当前展示前100个账户；更多账户可通过分页API查询。'
}

async function signIn() {
  await run(async () => {
    current.value = await login(username.value, password.value)
    if (current.value.role === 'ADMIN') await loadUsers()
  })
  password.value = ''
}

async function signOut() {
  await run(async () => {
    await api('/auth/logout', 'POST')
    clearSession()
    current.value = null
    users.value = []
    notice.value = '已退出，此账户在其他设备的现有会话也已失效。'
  })
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
</script>

<template>
  <section aria-labelledby="account-heading">
    <div class="section-title"><h2 id="account-heading">账户与权限</h2>
      <button v-if="current" :disabled="busy" @click="signOut">退出全部会话</button></div>
    <p class="detail">登录状态仅保留在当前页面，刷新后需重新登录。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="detail" role="status">{{ notice }}</p>
    <form v-if="!current" class="account-form" @submit.prevent="signIn">
      <label>登录名<input v-model="username" autocomplete="username" required maxlength="80" /></label>
      <label>密码<input v-model="password" type="password" autocomplete="current-password" required maxlength="128" /></label>
      <button :disabled="busy">{{ busy ? '登录中…' : '登录' }}</button>
    </form>
    <template v-else>
      <p>当前账户：{{ current.display_name }}（{{ current.username }}），角色：{{ current.role }}</p>
      <form class="account-form" @submit.prevent="changePassword">
        <label>原密码<input v-model="oldPassword" type="password" autocomplete="current-password" required maxlength="128" /></label>
        <label>新密码<input v-model="nextPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="128" /></label>
        <button :disabled="busy">修改密码并重新登录</button>
      </form>
      <template v-if="current.role === 'ADMIN'">
        <h3>建立账户</h3>
        <form class="account-form" @submit.prevent="createAccount">
          <label>登录名<input v-model="newName" required pattern="[A-Za-z][A-Za-z0-9_.-]{2,79}" autocomplete="off" /></label>
          <label>显示名<input v-model="newDisplay" required maxlength="80" /></label>
          <label>角色<select v-model="newRole"><option>VIEWER</option><option>MANAGER</option><option>ADMIN</option></select></label>
          <label>初始密码<input v-model="newPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="128" /></label>
          <button :disabled="busy">建立账户</button>
        </form>
        <h3>用户管理</h3>
        <div class="table-wrap"><table>
          <thead><tr><th>登录名</th><th>显示名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
          <tbody><tr v-for="user in users" :key="user.user_id">
            <td>{{ user.username }}</td>
            <td><input v-model="user.display_name" :aria-label="`${user.username}显示名`" maxlength="80" /></td>
            <td><select v-model="user.role" :aria-label="`${user.username}角色`"><option>ADMIN</option><option>MANAGER</option><option>VIEWER</option></select></td>
            <td>{{ user.is_active ? '启用' : '停用' }}</td>
            <td><button :disabled="busy" @click="save(user)">保存</button>
              <button :disabled="busy" @click="save(user, true)">{{ user.is_active ? '停用' : '启用' }}</button></td>
          </tr></tbody>
        </table></div>
      </template>
    </template>
  </section>
</template>
