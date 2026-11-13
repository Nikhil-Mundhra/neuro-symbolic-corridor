import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

const gatewayTarget = process.env.GATEWAY_URL || 'http://127.0.0.1:8080';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
  },
  build: {
    target: 'esnext',
  },
  server: {
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: gatewayTarget,
        changeOrigin: true,
      },
      '/health': {
        target: gatewayTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: gatewayTarget,
        changeOrigin: true,
      },
      '/health': {
        target: gatewayTarget,
        changeOrigin: true,
      },
    },
  },
});
