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
 * Run with `--watch` to rebuild on change while developing.
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

const alias = { '@': path.join(root, 'src') };

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

async function copyManifest() {
  const source = path.join(root, 'manifest.json');
  const manifest = JSON.parse(await fs.readFile(source, 'utf8'));
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

  const version = await copyManifest();
  console.log(`\n  StockWatch v${version} → ${path.relative(process.cwd(), outDir)}`);
  console.log('  Load it with chrome://extensions → Developer mode → Load unpacked\n');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
