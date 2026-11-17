import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Cấu hình Vite Dev Server tích hợp Proxy tự động chuyển tiếp tới Backend FastAPI
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/auth': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/me': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/users': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/barns': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/devices': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/registrations': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/alerts': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/audit-logs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/scheduled-events': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/camera': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/events': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
