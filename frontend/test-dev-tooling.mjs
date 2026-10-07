// Issue #51: protect patched tooling, including Vite's nested esbuild, and local binding.
// Run after npm ci and npm run build: npm run test:dev-tooling
import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { isIP } from 'node:net';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer, preview } from 'vite';

const root = fileURLToPath(new URL('.', import.meta.url));
const json = async path => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));
const pkg = await json('package.json');
const lock = await json('package-lock.json');

function patched(name, version) {
  assert.match(version, /^\d+\.\d+\.\d+$/, `${name} must use a stable version`);
  const [major, minor, patch] = version.split('.').map(Number);
  if (name === 'vite') {
    // GHSA-fx2h-pf6j-xcff: patched releases on each published major line.
    const minimum = { 6: [4, 3], 7: [3, 5], 8: [0, 16] }[major];
    assert.ok(minimum && (minor > minimum[0] ||
      (minor === minimum[0] && patch >= minimum[1])), `unsafe Vite ${version}`);
  } else {
    // GHSA-67mh-4wv8-2f99: esbuild <=0.24.2 is affected.
    assert.ok(major > 0 || minor >= 25, `unsafe esbuild ${version}`);
  }
}

test('manifest and every locked tooling copy use patched, consistent versions', async () => {
  for (const name of ['vite', 'esbuild']) {
    patched(name, pkg.devDependencies[name]);
    assert.equal(lock.packages[''].devDependencies[name], pkg.devDependencies[name]);
    assert.equal(lock.packages[`node_modules/${name}`].version, pkg.devDependencies[name]);
    const copies = Object.entries(lock.packages).filter(([path]) => path.endsWith(`/node_modules/${name}`) || path === `node_modules/${name}`);
    assert.ok(copies.length > 0);
    for (const [path, entry] of copies) {
      patched(name, entry.version);
      assert.equal((await json(`${path}/package.json`)).version, entry.version, path);
    }
  }
});

test('local CI runs tooling after the build and checks API responses', async () => {
  assert.equal(pkg.scripts['test:dev-tooling'], 'node --test --test-timeout=30000 test-dev-tooling.mjs');
  const ci = await readFile(new URL('../scripts/local_ci.sh', import.meta.url), 'utf8');
  assert.match(ci, /npm run test:api-response/);
  assert.match(ci, /npm run build[\s\S]*npm run test:dev-tooling/);
});

test('production keeps the company route outside the initial JavaScript budget', async () => {
  const manifest = await json('dist/.vite/manifest.json');
  const entry = manifest['index.html'];
  const company = manifest['src/CompanyCockpit.tsx'];
  assert.ok(entry?.isEntry);
  assert.ok(company?.isDynamicEntry, 'company must remain a lazy route');
  assert.ok(entry.dynamicImports.includes('src/CompanyCockpit.tsx'));

  const initial = new Set();
  function visit(key) {
    if (initial.has(key)) return;
    initial.add(key);
    for (const dependency of manifest[key].imports || []) visit(dependency);
  }
  visit('index.html');
  assert.ok(!initial.has('src/CompanyCockpit.tsx'), 'company must not be eagerly imported');
  const entryBytes = (await stat(new URL(`dist/${entry.file}`, import.meta.url))).size;
  const initialBytes = (await Promise.all([...initial].map(async key =>
    (await stat(new URL(`dist/${manifest[key].file}`, import.meta.url))).size
  ))).reduce((total, bytes) => total + bytes, 0);
  // Baseline: one 449.84 KB chunk. Count all static imports to avoid hiding bytes in vendors.
  assert.ok(entryBytes < 300_000, `entry JavaScript is ${entryBytes} bytes (budget 300000)`);
  assert.ok(initialBytes < 445_000, `initial JavaScript is ${initialBytes} bytes (budget 445000)`);
  const html = await readFile(new URL('dist/index.html', import.meta.url), 'utf8');
  assert.ok(!html.includes(company.file), 'company must not be preloaded on first paint');
});

function loopback(server) {
  const { address } = server.address();
  assert.ok((isIP(address) === 4 && address.startsWith('127.')) || address === '::1',
    `server exposed at ${address}`);
  return `http://${address.includes(':') ? `[${address}]` : address}:${server.address().port}`;
}

test('default dev server binds locally and transforms the React entry without permissive CORS', async () => {
  assert.equal(pkg.scripts.dev, 'vite', 'network exposure must require an explicit CLI override');
  // HTTP probes do not crawl imports like a browser; let optimization finish independently.
  const server = await createServer({ root, server: { port: 0 }, optimizeDeps: { holdUntilCrawlEnd: false, force: true } });
  try {
    await server.listen();
    const origin = loopback(server.httpServer);
    for (const path of ['/', '/src/main.tsx', '/src/App.tsx', '/node_modules/.vite/deps/react.js']) {
      const response = await fetch(origin + path, {
        headers: { Origin: 'https://untrusted.invalid' }, signal: AbortSignal.timeout(10000),
      });
      assert.equal(response.status, 200, path);
      assert.equal(response.headers.get('access-control-allow-origin'), null);
      assert.ok((await response.text()).length > 0, path);
    }
  } finally {
    server.httpServer.closeAllConnections();
    await server.close();
  }
});

test('default production preview also binds locally', async () => {
  assert.equal(pkg.scripts.preview, 'vite preview');
  const server = await preview({ root, preview: { port: 0 } });
  try {
    const origin = loopback(server.httpServer);
    const response = await fetch(origin, { signal: AbortSignal.timeout(10000) });
    assert.equal(response.status, 200);
    assert.match(await response.text(), /src="\/assets\//, 'preview serves the production bundle');
    const company = (await json('dist/.vite/manifest.json'))['src/CompanyCockpit.tsx'];
    for (const file of [company.file, ...(company.css || [])]) {
      const asset = await fetch(`${origin}/${file}`, { signal: AbortSignal.timeout(10000) });
      assert.equal(asset.status, 200, `lazy route asset ${file}`);
      assert.match(asset.headers.get('content-type'), file.endsWith('.css') ? /text\/css/ : /javascript/);
      assert.ok((await asset.text()).length > 0);
    }
  } finally {
    server.httpServer.closeAllConnections();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
