import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend runs on :8000; the dev server proxies /api to it so no CORS setup is needed.
const API = process.env.FINSIGHT_API ?? 'http://localhost:8000'

export default defineConfig({
  // The hosted demo lives under /FinSight/ on GitHub Pages; locally the app is served from the root.
  base: process.env.FINSIGHT_BASE ?? '/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: API, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
