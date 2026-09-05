import { defineConfig } from 'vite';

/**
 * Dev runs on 5799 and proxies the API to the backend on 7799, so the frontend never needs
 * to know an absolute origin — the same relative `/api/...` fetches work in dev and in the
 * production build the backend serves itself.
 */
export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5799,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:7799', changeOrigin: false },
      '/art': { target: 'http://127.0.0.1:7799', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
