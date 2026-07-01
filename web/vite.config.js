import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    // 本地开发时把 /api 代理到后端（uv run winnow web）
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
