// 仅编译第三方模块，用于验证依赖组合；不实现业务界面。
import { defineComponent, version } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'
import { ElButton } from 'element-plus'
import * as echarts from 'echarts'
import * as leaflet from 'leaflet'

export const dependencySmoke = {
  vueVersion: version,
  component: defineComponent({ name: 'M0DependencySmoke' }),
  router: createRouter({ history: createMemoryHistory(), routes: [] }),
  pinia: createPinia(),
  button: ElButton,
  chartVersion: echarts.version,
  mapVersion: leaflet.version,
}
