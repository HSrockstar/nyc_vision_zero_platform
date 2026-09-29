import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    lib: { entry: 'smoke.ts', formats: ['es'], fileName: 'dependency-smoke' },
  },
})
