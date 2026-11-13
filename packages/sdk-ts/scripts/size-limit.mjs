// Gzipped bundle-size budget for the published package. Dependency-free so CI
// needs nothing beyond Node. Fails (exit 1) if any entry exceeds its limit.
//
// tsup code-splits shared code into `chunk-*.js`, so an entry's real footprint
// is its own file plus the shared chunks it pulls in. We count the shared
// chunks under `core` (every consumer loads them) and the React entry's own
// file separately (a React consumer additionally reuses the shared chunks).
import { gzipSync } from 'node:zlib';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');

function gzipKb(...files) {
  let total = 0;
  for (const f of files) total += gzipSync(readFileSync(join(dist, f))).length;
  return total / 1024;
}

const sharedChunks = readdirSync(dist).filter((f) => /^chunk-.*\.js$/.test(f));

// Limits are gzipped KB — the number that matters to a consumer over the wire.
// Set with headroom above current size; tighten if a change blows past it.
const BUDGETS = [
  { name: 'core (@midsphere/sdk)', files: ['index.js', ...sharedChunks], limitKb: 16 },
  { name: 'react (@midsphere/sdk/react)', files: ['react/index.js'], limitKb: 3 },
];

let failed = false;
const rows = [];
for (const { name, files, limitKb } of BUDGETS) {
  let size;
  try {
    size = gzipKb(...files);
  } catch {
    console.error(`✗ ${name} — build output missing (run \`npm run build\` first)`);
    failed = true;
    continue;
  }
  const over = size > limitKb;
  failed ||= over;
  rows.push(
    `${over ? '✗' : '✓'} ${name.padEnd(30)} ${size.toFixed(2)} KB gz / ${limitKb} KB limit`,
  );
}

console.log(rows.join('\n'));
if (failed) {
  console.error('\nBundle-size budget exceeded.');
  process.exit(1);
}
console.log('\nAll bundles within budget.');
