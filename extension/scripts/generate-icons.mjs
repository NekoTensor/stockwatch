/**
 * Icon generation.
 *
 * The toolbar icons are drawn from the same geometry as the `Logo` component so
 * the mark in the popup and the mark in the toolbar are literally the same
 * shape. Generating them means no binary blobs in git and no drift when the
 * brand colours change — edit the constants below and rebuild.
 *
 * PNG is written by hand (deflate + CRC32) to keep the toolchain dependency
 * free; the files are tiny and fully spec-compliant.
 */

import zlib from 'node:zlib';
import fs from 'node:fs/promises';
import path from 'node:path';

const SIZES = [16, 32, 48, 128];

/** Gradient endpoints — indigo-500 to purple-500, matching the popup mark. */
const FROM = [0x63, 0x66, 0xf1];
const TO = [0xa8, 0x55, 0xf7];

/** Bars, in the 32x32 design grid: [x, y, width, height, radius]. */
const BARS = [
  [8, 17, 3.5, 7, 1.4],
  [14.25, 13, 3.5, 11, 1.4],
  [20.5, 8, 3.5, 16, 1.4],
];
const CANVAS = 32;
const CORNER = 9;
const SAMPLES = 3; // per axis; 3x3 supersampling smooths the rounded corners

function insideRoundedRect(x, y, left, top, width, height, radius) {
  if (x < left || y < top || x > left + width || y > top + height) return false;
  const r = Math.min(radius, width / 2, height / 2);

  const dx = x < left + r ? left + r - x : x > left + width - r ? x - (left + width - r) : 0;
  const dy = y < top + r ? top + r - y : y > top + height - r ? y - (top + height - r) : 0;
  return dx * dx + dy * dy <= r * r;
}

/** Colour of one sample point in the 32x32 design space, as [r,g,b,a]. */
function sample(x, y) {
  if (!insideRoundedRect(x, y, 0, 0, CANVAS, CANVAS, CORNER)) return [0, 0, 0, 0];

  for (const [bx, by, bw, bh, br] of BARS) {
    if (insideRoundedRect(x, y, bx, by, bw, bh, br)) return [255, 255, 255, 255];
  }

  // Diagonal gradient across the tile.
  const t = Math.min(1, Math.max(0, (x + y) / (CANVAS * 2)));
  return [
    Math.round(FROM[0] + (TO[0] - FROM[0]) * t),
    Math.round(FROM[1] + (TO[1] - FROM[1]) * t),
    Math.round(FROM[2] + (TO[2] - FROM[2]) * t),
    255,
  ];
}

function renderRgba(size) {
  const pixels = Buffer.alloc(size * size * 4);
  const scale = CANVAS / size;
  const step = 1 / SAMPLES;

  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;

      for (let sy = 0; sy < SAMPLES; sy += 1) {
        for (let sx = 0; sx < SAMPLES; sx += 1) {
          const [sr, sg, sb, sa] = sample((px + (sx + 0.5) * step) * scale, (py + (sy + 0.5) * step) * scale);
          const alpha = sa / 255;
          r += sr * alpha;
          g += sg * alpha;
          b += sb * alpha;
          a += sa;
        }
      }

      const count = SAMPLES * SAMPLES;
      const alphaSum = a / 255;
      const offset = (py * size + px) * 4;
      // Un-premultiply so edge pixels keep their colour instead of going dark.
      pixels[offset] = alphaSum ? Math.round(r / alphaSum) : 0;
      pixels[offset + 1] = alphaSum ? Math.round(g / alphaSum) : 0;
      pixels[offset + 2] = alphaSum ? Math.round(b / alphaSum) : 0;
      pixels[offset + 3] = Math.round(a / count);
    }
  }

  return pixels;
}

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buffer) {
  let crc = -1;
  for (const byte of buffer) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ -1) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function encodePng(size, rgba) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // colour type: RGBA
  // 10..12 stay zero: deflate, adaptive filtering, no interlace.

  // One filter byte (0 = None) per scanline.
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    const rowStart = y * (size * 4 + 1);
    raw[rowStart] = 0;
    rgba.copy(raw, rowStart + 1, y * size * 4, (y + 1) * size * 4);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

export async function generateIcons(targetDir) {
  await fs.mkdir(targetDir, { recursive: true });
  for (const size of SIZES) {
    await fs.writeFile(path.join(targetDir, `icon${size}.png`), encodePng(size, renderRgba(size)));
  }
  return SIZES;
}

// Allow `npm run icons` as well as being imported by the build.
if (process.argv[1] && import.meta.url.endsWith(path.basename(process.argv[1]))) {
  const target = path.resolve(process.cwd(), 'public', 'icons');
  const sizes = await generateIcons(target);
  console.log(`Wrote ${sizes.map((s) => `icon${s}.png`).join(', ')} to ${target}`);
}
