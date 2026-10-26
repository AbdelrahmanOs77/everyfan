import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.EVERYFAN_LOCAL_API || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': { target: process.env.EVERYFAN_LOCAL_API || 'ws://127.0.0.1:8000', ws: true },
    },
  },
  test: { include: ['src/**/*.test.ts'] },
});
