<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, clearSession, sessionUser } from './api/auth'
import { navigation, roleLabels } from './navigation'
import { resetWorkspace } from './workspace'
import AppIcon from './components/AppIcon.vue'
import HealthStatus from './components/HealthStatus.vue'

const route = useRoute(), router = useRouter()
const collapsed = ref(false), mobileOpen = ref(false), signingOut = ref(false), sessionError = ref('')
const sidebar = ref<HTMLElement | null>(null), menuButton = ref<HTMLButtonElement | null>(null)
async function openNavigation() {
  mobileOpen.value = true
  await nextTick()
  sidebar.value?.querySelector<HTMLElement>('a,button')?.focus()
}
async function closeNavigation() {
  mobileOpen.value = false
  await nextTick()
  if (narrow.value) menuButton.value?.focus()
}
function navigationKeydown(event: KeyboardEvent) {
  if (!narrow.value || !mobileOpen.value || event.key !== 'Tab') return
  const items = Array.from(sidebar.value?.querySelectorAll<HTMLElement>('a,button') ?? []).filter(item => item.getClientRects().length > 0)
  const first = items[0], last = items[items.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
function focusContent() { document.getElementById('workspace-content')?.focus() }
const media = window.matchMedia('(max-width: 900px)')
const narrow = ref(media.matches)
function mediaChange() { narrow.value = media.matches; mobileOpen.value = false }
media.addEventListener('change', mediaChange)
onBeforeUnmount(() => media.removeEventListener('change', mediaChange))
const menu = computed(() => navigation.filter(item => !item.roles || (sessionUser.value && item.roles.includes(sessionUser.value.role))))
const groups = computed(() => [...new Set(menu.value.map(item => item.group))])
const identityKey = computed(() => `${sessionUser.value?.user_id ?? ''}:${sessionUser.value?.role ?? ''}`)
watch(identityKey, () => {
  resetWorkspace(); mobileOpen.value = false; sessionError.value = ''
  if (!sessionUser.value && !route.meta.public) void router.replace({ path: '/login', query: { redirect: route.fullPath } })
  else if (route.meta.roles && sessionUser.value && !route.meta.roles.includes(sessionUser.value.role)) void router.replace('/forbidden')
})
watch(() => route.path, () => { mobileOpen.value = false; sessionError.value = '' })
async function signOut() {
  signingOut.value = true; sessionError.value = ''
  try { await api('/auth/logout', 'POST'); clearSession() }
  catch (error) { sessionError.value = error instanceof Error ? error.message : '退出未完成，请重试。' }
  finally { signingOut.value = false }
}
</script>

<template>
  <RouterView v-if="route.meta.public" />
  <div v-else-if="sessionUser" :class="['app-shell', { 'nav-collapsed': collapsed, 'mobile-nav-open': mobileOpen, 'statistics-route': route.path === '/statistics' }]" @keydown.esc="closeNavigation">
    <a class="skip-link" href="#workspace-content" @click.prevent="focusContent">跳到主要内容</a>
    <button v-if="mobileOpen" class="nav-backdrop" aria-label="关闭导航" tabindex="-1" @click="closeNavigation" />
    <aside ref="sidebar" class="app-sidebar" :inert="narrow && !mobileOpen" :role="narrow && mobileOpen ? 'dialog' : undefined" :aria-modal="narrow && mobileOpen ? true : undefined" aria-label="主导航" @keydown="navigationKeydown">
      <RouterLink to="/" class="brand" aria-label="Vision Zero 工作总览">
        <span class="brand-symbol"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M8 7h7v8h6V7h7v22h-7v-8h-6v8H8z" fill="currentColor"/><path d="M16.5 4h3v28h-3z" fill="white" opacity=".65"/></svg></span>
        <span class="brand-copy"><strong>Vision Zero<span class="brand-period">.</span></strong><small>城市交通安全治理</small></span>
      </RouterLink>
      <nav class="nav-groups">
        <div v-for="group in groups" :key="group" class="nav-group">
          <p class="nav-label">{{ group }}</p>
          <RouterLink v-for="item in menu.filter(entry => entry.group === group)" :key="item.path" :to="item.path" :title="collapsed ? item.label : undefined" :class="['nav-item', { active: route.path === item.path }]" :aria-current="route.path === item.path ? 'page' : undefined"><AppIcon :name="item.icon" /><span>{{ item.label }}</span><span v-if="route.path === item.path" class="nav-active-dot" /></RouterLink>
        </div>
      </nav>
      <div class="sidebar-bottom"><div class="workspace-note"><AppIcon name="shield" /><span>公开数据 · 课程模拟治理</span></div><button class="collapse-button" :aria-label="collapsed ? '展开导航' : '收起导航'" :aria-expanded="!collapsed" @click="collapsed = !collapsed"><AppIcon name="chevron" /><span>收起导航</span></button><button class="mobile-close secondary-button" @click="closeNavigation">关闭导航</button></div>
    </aside>
    <div class="workspace" :inert="narrow && mobileOpen">
      <header class="app-topbar">
        <div class="breadcrumb"><button ref="menuButton" class="icon-button mobile-menu" aria-label="打开导航" :aria-expanded="mobileOpen" @click="openNavigation"><AppIcon name="menu" /></button><span class="breadcrumb-root">工作空间</span><span class="breadcrumb-divider">/</span><span>{{ route.meta.title }}</span></div>
        <div class="topbar-actions"><HealthStatus /><span class="topbar-divider" /><RouterLink class="profile-link" to="/account"><span class="avatar">{{ sessionUser.display_name.slice(0, 1) }}</span><span class="profile-copy"><strong>{{ sessionUser.display_name }}</strong><small>{{ roleLabels[sessionUser.role] }}</small></span></RouterLink><button class="icon-button logout-button" :disabled="signingOut" aria-label="退出全部会话" title="退出全部会话" @click="signOut"><AppIcon name="logout" /></button></div>
      </header>
      <main id="workspace-content" class="workspace-main" tabindex="-1">
        <div class="page-heading"><div><p class="eyebrow">VISION ZERO / {{ route.path === '/' ? 'OVERVIEW' : 'WORKSPACE' }}</p><h1>{{ route.meta.title }}</h1><p class="page-description">{{ route.meta.description }}</p></div><span v-if="route.path === '/governance'" class="simulation-badge">课程模拟业务</span><span v-else class="page-context">纽约 · 交通碰撞数据</span></div>
        <p v-if="sessionError" class="error" role="alert">{{ sessionError }}</p>
        <div class="page-content"><RouterView :key="identityKey + ':' + route.path" /></div>
        <footer class="workspace-footer"><span>Vision Zero · 让每一项治理有据可循</span><span>公开碰撞数据 / 课程设计</span></footer>
      </main>
    </div>
  </div>
</template>
