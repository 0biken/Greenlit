import react from '@vitejs/plugin-react'
import { msw } from 'msw/vite'
import { defineConfig } from 'vite'

const API = process.env.API_ORIGIN ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  // The mock worker is served in development only; builds never ship it.
  plugins: [react(), ...(command === 'serve' ? [msw({ mode: 'worker-only' })] : [])],
  server: {
    // Same origin as the API in development, so session and CSRF cookies just work.
    proxy: {
      '/api': { target: API, changeOrigin: false },
      '/_allauth': { target: API, changeOrigin: false },
      // Local stand-in for the storage bucket (uploads and downloads in development).
      '/files': { target: API, changeOrigin: false },
    },
  },
}))
