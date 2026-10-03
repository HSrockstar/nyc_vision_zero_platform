<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../api/auth'
import { returnPath } from '../router'
import HealthStatus from '../components/HealthStatus.vue'
import AppIcon from '../components/AppIcon.vue'
const username = ref(''), password = ref(''), error = ref(''), busy = ref(false)
const router = useRouter(), route = useRoute()
async function signIn() {
  if (busy.value) return
  const target = returnPath(route.query.redirect)
  busy.value = true; error.value = ''
  try { await login(username.value.trim(), password.value); await router.replace(target) }
  catch (exception) { error.value = exception instanceof Error ? exception.message : '登录失败，请重试。' }
  finally { busy.value = false; password.value = '' }
}
</script>
<template>
  <div class="login-page">
    <section class="login-story">
      <div class="login-brand"><span class="brand-symbol"><AppIcon name="map" /></span><strong>Vision Zero<span>.</span></strong></div>
      <div class="login-story-copy"><p class="eyebrow">URBAN SAFETY, INFORMED BY DATA</p><h1>读懂城市风险，<br />让道路更安全。</h1><p>纽约交通碰撞风险识别<br />与高危交叉口治理管理系统</p><div class="story-tags"><span>事故洞察</span><span>风险识别</span><span>治理追踪</span></div></div>
      <svg class="city-illustration" viewBox="0 0 600 280" fill="none" aria-hidden="true"><defs><pattern id="city-grid" width="56" height="56" patternUnits="userSpaceOnUse" patternTransform="rotate(-22)"><path d="M0 0h56v56" stroke="#d9e5f5" stroke-width="1"/></pattern></defs><rect width="600" height="280" fill="url(#city-grid)"/><path d="M-20 230 120 162 228 175 344 86 460 100 620 10" stroke="#c6d9f4" stroke-width="30"/><path d="M-20 230 120 162 228 175 344 86 460 100 620 10" stroke="white" stroke-width="16"/><path d="m96-20 44 130 118 48 26 130 M430-20 20 102 62 210" stroke="white" stroke-width="12"/><path d="M120 162 228 175 344 86 460 100" stroke="#083da6" stroke-width="3" stroke-dasharray="6 6"/><circle cx="228" cy="175" r="23" fill="#083da6" opacity=".1"/><circle cx="228" cy="175" r="8" fill="#083da6" stroke="white" stroke-width="4"/><circle cx="344" cy="86" r="7" fill="#238b7c" stroke="white" stroke-width="3"/><circle cx="460" cy="100" r="7" fill="#c38933" stroke="white" stroke-width="3"/></svg>
      <p class="login-source">公开数据驱动 · 课程模拟治理</p>
    </section>
    <main class="login-main"><div class="login-status"><HealthStatus /></div><div class="login-card"><p class="eyebrow">WELCOME BACK</p><h2>登录工作空间</h2><p class="detail">使用你的账户，继续交通安全分析与治理工作。</p><form class="login-form" @submit.prevent="signIn"><label>登录名<input v-model="username" autocomplete="username" required maxlength="80" placeholder="请输入登录名" autofocus /></label><label>密码<input v-model="password" type="password" autocomplete="current-password" required maxlength="128" placeholder="请输入密码" /></label><p v-if="error" class="error" role="alert">{{ error }}</p><button :disabled="busy">{{ busy ? '正在登录…' : '登录' }}<AppIcon name="arrow" /></button></form><p class="login-session-note"><AppIcon name="shield" />登录状态仅在当前页面有效，刷新后需重新登录。</p></div><p class="login-footer">VISION ZERO · 纽约交通安全治理平台</p></main>
  </div>
</template>
