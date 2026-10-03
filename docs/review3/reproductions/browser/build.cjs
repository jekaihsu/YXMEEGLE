// Compile actual repository components. Generated files remain outside docs/git.
const path = require('path');
const fs = require('fs');
const root = path.resolve(__dirname, '../../../..');
const esbuild = require(path.join(root, 'frontend/node_modules/esbuild'));
const output = path.join(root, '.runtime/review3-public-browser');
fs.mkdirSync(output, {recursive: true});
fs.mkdirSync(path.join(root, 'output/playwright'), {recursive: true});
esbuild.buildSync({
  absWorkingDir: root,
  entryPoints: [path.join(__dirname, 'fixture.tsx')],
  outfile: path.join(output, 'main.js'),
  bundle: true,
  jsx: 'automatic',
  nodePaths: [path.join(root, 'frontend/node_modules')],
  loader: {'.css': 'empty'},
});
fs.writeFileSync(path.join(output, 'index.html'),
  '<!doctype html><html lang="zh-Hant"><meta charset="UTF-8"><title>Review 3 — synthetic reproductions</title><div id="root"></div><script src="main.js"></script></html>',
  'utf8');
console.log('Built .runtime/review3-public-browser (synthetic data, no production API).');
