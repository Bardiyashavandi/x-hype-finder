import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Dev mode: `npm run dev` (:5173) proxies /api straight through to the
      // FastAPI backend (`python -m src.cli.web run`, :8000) — same-origin
      // as far as the browser is concerned, so the session cookie set by
      // POST /api/auth/login round-trips correctly without CORS gymnastics
      // (specs/003-web-dashboard/plan.md §2 "Dev mode").
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
