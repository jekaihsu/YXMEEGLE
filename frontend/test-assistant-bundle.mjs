import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {gzipSync} from 'node:zlib';
const manifest=JSON.parse(await readFile(new URL('./dist/.vite/manifest.json',import.meta.url),'utf8'));
const initial=new Set();
function visit(key){if(initial.has(key))return;initial.add(key);for(const imported of manifest[key].imports||[])visit(imported)}
visit('index.html');
const key='src/Assistant.tsx',chunk=manifest[key];
assert.equal(chunk.isDynamicEntry,true);assert.equal(initial.has(key),false);
assert.equal([...initial].flatMap(key=>manifest[key].css||[]).some(file=>file.includes('Assistant')),false);
const bytes=await readFile(new URL(`./dist/${chunk.file}`,import.meta.url));
console.log(`Assistant lazy chunk ${chunk.file}: ${bytes.length} bytes raw, ${gzipSync(bytes).length} bytes gzip.`);
