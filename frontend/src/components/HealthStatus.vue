<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { loadHealth, type HealthState } from '../api/health'
const state = ref<HealthState>({ live: false, ready: false, detail: '正在检查服务状态…' })
const checking = ref(false)
async function refresh() {
  checking.value = true
  try { state.value = await loadHealth() } finally { checking.value = false }
}
onMounted(refresh)
</script>
<template>
  <details class="health-status">
    <summary><span :class="['status-dot', { healthy: state.ready }]" />{{ checking ? '检查中' : state.ready ? '服务正常' : '服务未就绪' }}</summary>
    <div class="health-popover">
      <strong>服务状态</strong>
      <dl><div><dt>后端进程</dt><dd>{{ state.live ? '已启动' : '不可访问' }}</dd></div><div><dt>数据库与迁移</dt><dd>{{ state.ready ? '已就绪' : '未就绪' }}</dd></div></dl>
      <p class="detail" aria-live="polite">{{ state.detail }}</p>
      <button class="secondary-button" :disabled="checking" @click="refresh">重新检查</button>
    </div>
  </details>
</template>
