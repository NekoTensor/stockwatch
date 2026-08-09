import path from 'node:path';
import { defineConfig } from 'vitest/config';

/**
 * Detection is pure DOM work, so it can be tested against jsdom with saved
 * page fixtures — no browser, no network, no store cooperation required.
 */
export default defineConfig({
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.ts'],
  },
});
