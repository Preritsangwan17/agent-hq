/**
 * Vite config for the Agent HQ SPA.
 * - `/api` is proxied to the FastAPI server (VITE_API_TARGET, default http://127.0.0.1:8765) with the Host header
 *   kept as-is (changeOrigin: false) so the backend's host allowlist sees `localhost`.
 * - `VITE_MOCK=1` swaps the network for the in-browser simulator in `src/lib/mock` (no backend needed).
 */
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env };
  const target = env.VITE_API_TARGET || 'http://127.0.0.1:8765';
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      port: 5173,
      host: 'localhost',
      proxy: {
        '/api': { target, changeOrigin: false, ws: false },
      },
    },
    preview: { port: 4173, host: 'localhost' },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 900,
    },
  };
});
