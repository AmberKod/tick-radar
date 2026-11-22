import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1', port: 15173, strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:18100', '/health': 'http://127.0.0.1:18100' },
  },
  test: { environment: 'jsdom', clearMocks: true, restoreMocks: true },
})
