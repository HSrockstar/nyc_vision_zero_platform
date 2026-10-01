<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { loadHealth, type HealthState } from './api/health'
import { sessionUser } from './api/auth'
import AccountPanel from './components/AccountPanel.vue'
import M2Panel from './components/M2Panel.vue'
import RiskPanel from './components/RiskPanel.vue'
import GovernancePanel from './components/GovernancePanel.vue'
import StatisticsPanel from './components/StatisticsPanel.vue'
import type { RiskProfile } from './api/m4'

const state = ref<HealthState>({ live: false, ready: false, detail: '正在检查开发环境…' })
const checking = ref(false)
const governanceProfile = ref<RiskProfile | null>(null)
watch(() => sessionUser.value?.user_id, () => { governanceProfile.value = null })
function selectGovernance(profile: RiskProfile) {
  governanceProfile.value = profile
  requestAnimationFrame(() => document.getElementById('governance')?.scrollIntoView({ behavior: 'smooth' }))
}

async function refresh() {
  checking.value = true
  try { state.value = await loadHealth() }
  finally { checking.value = false }
}

onMounted(refresh)
</script>

<template>
  <main>
    <p class="eyebrow">VISION ZERO · M5</p>
    <h1>纽约交通碰撞风险识别<br />与高危交叉口治理管理系统</h1>
    <p class="intro">登录后可查询事故、地图观察点、交叉口与风险画像；治理人员可复核地点归属、建立模拟治理任务并记录执行和复核过程，管理员可管理数据导入与账户。</p>
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
    <M2Panel v-if="sessionUser" />
    <RiskPanel v-if="sessionUser" :key="sessionUser.user_id" @governance="selectGovernance" />
    <GovernancePanel v-if="sessionUser && sessionUser.role !== 'VIEWER'" :key="sessionUser.user_id" :profile="governanceProfile" />
    <StatisticsPanel v-if="sessionUser" :key="sessionUser.user_id" />
    <p class="footnote">数据库运行在 Docker；Python 后端和前端在 Windows 开发。</p>
  </main>
</template>
