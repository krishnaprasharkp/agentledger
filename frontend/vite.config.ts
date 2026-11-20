import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: Object.fromEntries(
      ['/app-mode', '/demo', '/health', '/docs', '/openapi.json', '/portfolio', '/adapters', '/analytics', '/events', '/invoices'].map(path => [path, 'http://127.0.0.1:8000']),
    ),
  },
});
