import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': { target: `http://127.0.0.1:${process.env.PY_STREMIO_API_PORT ?? '8765'}`, ws: true },
    },
  },
  build: {
    outDir: '../../py_stremio/api/static',
    emptyOutDir: true,
  },
})
