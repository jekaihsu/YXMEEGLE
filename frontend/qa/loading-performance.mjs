// Local synthetic fixtures only; browser requests outside this server are blocked.
// Usage: node qa/loading-performance.mjs <built dist directory> <output.json>
import {createServer} from 'node:http';
import {readFileSync, existsSync, writeFileSync} from 'node:fs';
import {extname, resolve} from 'node:path';
import {gzipSync} from 'node:zlib';
import {workspace, a, b} from '../session-epoch-fixture.mjs';
import {homeReportFixture} from '../home-reports-fixture.mjs';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || '/private/tmp/yxr/pwi/node_modules/playwright-core/index.mjs');
const directory = resolve(process.argv[2] || 'dist');
const output = resolve(process.argv[3] || 'loading-performance.json');
const examples = JSON.parse(readFileSync(new URL('../../backend/sop_import/api-examples.json', import.meta.url)));
const quotes = Array.from({length: 2000}, (_, i) => ({
  ...examples.quotes.items[0], quote_no: String(115000 + (i * 1979) % 2000), name: `案件${i}`,
}));
const session = {
  user: a, users: [a, b], mode: 'demo', environment: 'development',
  workspace_id: workspace.workspace_id, features: {workspace_shell: false},
};
function fixture(path) {
  if (path.pathname === '/api/session') return session;
  if (path.pathname === '/api/workspace') return workspace;
  if (path.pathname === '/api/reports/home') return homeReportFixture();
  if (path.pathname === '/api/quotes') {
    const offset = Number(path.searchParams.get('offset'));
    return {total: quotes.length, items: quotes.slice(offset, offset + 100)};
  }
  if (path.pathname.startsWith('/api/quotes/')) {
    const key = decodeURIComponent(path.pathname.split('/').at(-1));
    return {...quotes.find(q => q.quote_no === key), facts: {}, records: []};
  }
  if (path.pathname === '/api/home-panels') return {
    panel: path.searchParams.get('panel'), scope: 'mine', readState: 'fresh',
    snapshot_version: 'synthetic-v1', as_of: null,
    freshness: {status: 'fresh', last_success_at: null, refreshing: false},
    counts: {node_assignments: 0, tasks: 0, local_workflow: 0, sop_tasks: 0, complete: true},
    items: [], next_cursor: null, has_more: false, complete: true,
    total_count: 0, manager_view_available: true,
  };
  return {};
}
const contentTypes = {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html'};
const server = createServer((request, response) => {
  const path = new URL(request.url, 'http://localhost');
  if (path.pathname.startsWith('/api/')) {
    const body = Buffer.from(JSON.stringify(fixture(path)));
    response.setHeader('Content-Type', 'application/json');
    response.setHeader('Cache-Control', 'no-store');
    if (body.length >= 1000) {
      response.setHeader('Content-Encoding', 'gzip');
      response.end(gzipSync(body));
    } else response.end(body);
    return;
  }
  const file = resolve(directory, '.' + path.pathname);
  const target = file.startsWith(directory + '/') && existsSync(file) && extname(file)
    ? file : resolve(directory, 'index.html');
  response.setHeader('Content-Type', contentTypes[extname(target)] || 'application/octet-stream');
  response.setHeader('Content-Encoding', 'gzip');
  response.end(gzipSync(readFileSync(target)));
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({channel: 'chrome', headless: true});
  const results = [];
  for (let run = 0; run < 7; run++) {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.route('**/*', route => route.request().url().startsWith(origin + '/') ? route.continue() : route.abort());
    const cdp = await context.newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false, latency: 40, downloadThroughput: 1250000, uploadThroughput: 1250000,
    });
    await cdp.send('Emulation.setCPUThrottlingRate', {rate: 4});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/?perf=1#view=dashboard');
    await page.waitForSelector('.app-shell');
    await page.waitForTimeout(250);
    const data = await page.evaluate(() => ({
      marks: window.__yxPerf,
      resources: performance.getEntriesByType('resource').map(resource => ({
        name: new URL(resource.name).pathname, bytes: resource.encodedBodySize, decoded: resource.decodedBodySize,
      })),
      navigation: performance.getEntriesByType('navigation').map(navigation => ({
        dcl: navigation.domContentLoadedEventEnd, load: navigation.loadEventEnd,
      })),
      paints: performance.getEntriesByType('paint').map(paint => ({name: paint.name, start: paint.startTime})),
    }));
    const quoteStarted = performance.now();
    await page.goto(origin + '/?perf=1#view=quotes');
    await page.waitForSelector('tbody tr', {timeout: 30000});
    const quoteReadyMs = performance.now() - quoteStarted;
    const pagination = [];
    for (let pageNumber = 0; pageNumber < 4; pageNumber++) {
      const started = performance.now();
      await page.getByRole('button', {name: '下一頁', exact: true}).click();
      await page.waitForTimeout(0);
      pagination.push(performance.now() - started);
    }
    results.push({run, ...data, quoteReadyMs, pagination, errors});
    await context.close();
  }
  writeFileSync(output, JSON.stringify(results, null, 2));
  const median = values => values.sort((a, b) => a - b)[Math.floor(values.length / 2)];
  const first = results[0].resources;
  console.log(output, JSON.stringify({
    dcl: median(results.map(result => result.navigation[0].dcl)),
    fcp: median(results.map(result => result.paints.find(paint => paint.name === 'first-contentful-paint').start)),
    js: first.filter(resource => resource.name.endsWith('.js')).reduce((total, resource) => total + resource.bytes, 0),
    css: first.filter(resource => resource.name.endsWith('.css')).reduce((total, resource) => total + resource.decoded, 0),
    quoteReady: median(results.map(result => result.quoteReadyMs)),
    pagination: median(results.flatMap(result => result.pagination)),
    errors: results.flatMap(result => result.errors),
  }));
} finally {
  await browser?.close();
  server.close();
}
