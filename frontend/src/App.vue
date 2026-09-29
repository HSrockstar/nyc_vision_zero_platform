<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { loadHealth, type HealthState } from './api/health'
import AccountPanel from './components/AccountPanel.vue'

const state = ref<HealthState>({ live: false, ready: false, detail: '正在检查开发环境…' })
const checking = ref(false)

async function refresh() {
  checking.value = true
  try { state.value = await loadHealth() }
  finally { checking.value = false }
}

onMounted(refresh)
</script>

<template>
  <main>
    <p class="eyebrow">VISION ZERO · M1</p>
    <h1>纽约交通碰撞风险识别<br />与高危交叉口治理管理系统</h1>
    <p class="intro">当前提供环境检查、登录和账户管理。事故数据导入、查询及治理功能将在后续阶段加入。</p>
    <section aria-labelledby="health-heading">
      <div class="section-title">
        <h2 id="health-heading">环境状态</h2>
        <button :disabled="checking" @click="refresh">{{ checking ? '检查中…' : '重新检查' }}</button>
      </div>
      <dl>
        <div><dt>后端进程</dt><dd :class="{ good: state.live }">{{ checking ? '检查中' : state.live ? '已启动' : '不可访问' }}</dd></div>
        <div><dt>数据库与迁移</dt><dd :class="{ good: state.ready }">{{ checking ? '检查中' : state.ready ? '已就绪' : '未就绪' }}</dd></div>
      </dl>
      <p class="detail" aria-live="polite">{{ state.detail }}</p>
    </section>
    <AccountPanel />
    <p class="footnote">数据库运行在 Docker；Python 后端和前端在 Windows 开发。</p>
  </main>
</template>
