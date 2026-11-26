import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
export default defineConfig(() => {
  const target = 'http://127.0.0.1:8016'
  const proxy = {
    '^/api(?:/|$)': {
      target,
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api(?=\/|$)/, '') || '/',
    },
  }
  return {
    plugins: [react(), tailwindcss()],
    cacheDir: '.vite-laboratorio',
    server: { host: '127.0.0.1', port: 5190, strictPort: true, proxy, headers: { 'Permissions-Policy': 'camera=(), microphone=()' } },
    preview: { host: '127.0.0.1', port: 5190, strictPort: true, proxy, headers: { 'Permissions-Policy': 'camera=(), microphone=()' } },
    build: { rollupOptions: { output: { manualChunks: { charts: ['recharts'] } } } },
  }
})
