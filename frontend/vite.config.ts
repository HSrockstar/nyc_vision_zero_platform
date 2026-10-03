import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.VISION_ZERO_API_TARGET ?? 'http://127.0.0.1:8000'
const parsed = new URL(apiTarget)
if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(parsed.hostname)) {
  throw new Error('开发代理只允许本机 HTTP 后端')
}

export default defineConfig({
  plugins: [vue()],
  // 业务页按路由懒加载；预编译其依赖，避免首次导航触发开发服务整页刷新。
  optimizeDeps: { include: ['vue-router', 'element-plus', 'echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers', 'leaflet'] },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/health': apiTarget, '/api': apiTarget },
  },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
})
