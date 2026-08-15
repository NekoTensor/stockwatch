/**
 * The extension build.
 *
 * Three separate Vite passes, because the three artefacts have genuinely
 * different requirements:
 *
 *   1. popup      — a normal React app with an HTML entry and Tailwind CSS
 *   2. content.js — must be ONE self-contained IIFE: `chrome.scripting` injects
 *                   a file, and an injected file cannot `import` anything
 *   3. background.js — the MV3 service worker, likewise a single file
 *
 * Passes 2 and 3 write to fixed, unhashed filenames on purpose: the popup
 * injects `content.js` by name, so the name has to be stable across builds.
 *
 * Run with `--watch` to rebuild on change while developing, or with `--release`
 * to build the artefact that goes to the Chrome Web Store — which requires
 * STOCKWATCH_API_URL to name a real, https backend:
 *
 *   STOCKWATCH_API_URL=https://api.example.com/api npm run build:release
 */

import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import { build } from 'vite';
import react from '@vitejs/plugin-react';

import { generateIcons } from './generate-icons.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, 'dist');
const watch = process.argv.includes('--watch');
const release = process.argv.includes('--release');

const alias = { '@': path.join(root, 'src') };

/** Matches the fallback in src/lib/config.ts. */
const LOCAL_API = 'http://localhost:8000/api';
/** Requestable rather than granted, so a self-hoster can point elsewhere. */
const LOCAL_HOSTS = ['http://localhost/*', 'http://127.0.0.1/*'];

const apiBaseUrl = (process.env.STOCKWATCH_API_URL ?? '').trim().replace(/\/+$/, '') || LOCAL_API;

if (release && !apiBaseUrl.startsWith('https://')) {
  // The whole point of the flag. A store build that talks to localhost is dead
  // on arrival for everyone who is not the person who built it.
  throw new Error(
    `A release build needs an https API, got "${apiBaseUrl}".\n` +
      '  STOCKWATCH_API_URL=https://api.example.com/api npm run build:release',
  );
}

/**
 * Which hosts the built extension may reach.
 *
 * Only the API this build actually talks to is granted outright; everything
 * else is optional and requested at runtime when someone changes the server
 * address. Match patterns are host-scoped and carry no port, so dropping
 * `:8000` widens nothing that matters.
 */
function hostAccess(baseUrl) {
  const { protocol, hostname } = new URL(baseUrl);
  const primary = `${protocol}//${hostname}/*`;
  const granted = LOCAL_HOSTS.includes(primary) ? [...LOCAL_HOSTS] : [primary];
  // Chrome rejects a pattern that appears in both lists.
  const optional = ['https://*/*', ...LOCAL_HOSTS].filter((pattern) => !granted.includes(pattern));
  return { granted, optional };
}

/** Read back by src/lib/config.ts, which falls back when it is absent. */
const define = { __API_BASE_URL__: JSON.stringify(apiBaseUrl) };

/**
 * The two HTML surfaces: popup and dashboard.
 *
 * Built together so React, Tailwind and the whole detection library are shared
 * between them instead of being duplicated into two bundles. Hashed asset names
 * are fine here because the HTML references them.
 */
function pagesConfig() {
  return {
    root,
    plugins: [react()],
    resolve: { alias },
    define,
    build: {
      outDir,
      emptyOutDir: true,
      sourcemap: true,
      rollupOptions: {
        input: {
          popup: path.join(root, 'popup.html'),
          dashboard: path.join(root, 'dashboard.html'),
        },
      },
    },
  };
}

/** A single-file IIFE bundle, written to an exact filename. */
function scriptConfig(entry, fileName) {
  return {
    root,
    resolve: { alias },
    define,
    build: {
      outDir,
      emptyOutDir: false,
      sourcemap: true,
      // The service worker and content script both run in a plain browser
      // context — no module loader, no chunk graph.
      rollupOptions: {
        input: path.join(root, entry),
        output: {
          format: 'iife',
          entryFileNames: fileName,
          inlineDynamicImports: true,
        },
      },
    },
  };
}

/**
 * The manifest is written, not merely copied: the hosts it declares are derived
 * from the API this build was pointed at, so the permissions can never drift
 * from the address in the bundle.
 */
async function writeManifest() {
  const source = path.join(root, 'manifest.json');
  const manifest = JSON.parse(await fs.readFile(source, 'utf8'));
  const { granted, optional } = hostAccess(apiBaseUrl);

  manifest.host_permissions = granted;
  manifest.optional_host_permissions = optional;

  await fs.writeFile(path.join(outDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return manifest.version;
}

async function main() {
  await generateIcons(path.join(root, 'public', 'icons'));

  const configs = [
    pagesConfig(),
    scriptConfig('src/content/index.ts', 'content.js'),
    scriptConfig('src/background/index.ts', 'background.js'),
  ];

  for (const config of configs) {
    if (watch) config.build.watch = {};
    await build(config);
  }

  const version = await writeManifest();
  console.log(`\n  StockWatch v${version} → ${path.relative(process.cwd(), outDir)}`);
  console.log(`  API: ${apiBaseUrl}${release ? '' : '  (set STOCKWATCH_API_URL to change)'}`);
  console.log('  Load it with chrome://extensions → Developer mode → Load unpacked\n');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
