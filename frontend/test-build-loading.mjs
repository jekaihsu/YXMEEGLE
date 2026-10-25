// Run after npm run build. Walk static imports so shared chunks cannot hide eager code.
import assert from 'node:assert/strict';
import {readFile,stat} from 'node:fs/promises';
const manifest=JSON.parse(await readFile(new URL('./dist/.vite/manifest.json',import.meta.url),'utf8'));
const initial=new Set();
function visit(key){if(initial.has(key))return;initial.add(key);for(const dependency of manifest[key].imports||[])visit(dependency)}
visit('index.html');
for(const source of ['ProjectsList','Operations','DispatchWorkflowPage','IntegratedPages','PeopleDirectoryPanel','LarkPilotPanel','Quotes','ProjectDetail']){
 const key=Object.keys(manifest).find(key=>manifest[key].name===source&&manifest[key].file.endsWith('.js'));
 assert.ok(key,`${source} has its own chunk`);
 assert.ok(manifest[key]?.isDynamicEntry,`${source} remains a route import`);
 assert.ok(!initial.has(key),`${source} is not eagerly loaded`);
}
const integrated=Object.values(manifest).find(chunk=>chunk.name==='IntegratedPages');
assert.ok(!integrated.imports.some(key=>/Dispatch/.test(manifest[key].name)),'work and source-health routes do not pull dispatch code');
const css=[...initial].flatMap(key=>manifest[key].css||[]);
for(const source of ['Operations','DispatchPublish','ProjectsList'])assert.ok(!css.some(file=>file.includes(source)),`${source} CSS is deferred with its screen`);
const sizes=await Promise.all([...initial].map(async key=>(await stat(new URL(`./dist/${manifest[key].file}`,import.meta.url))).size));
assert.ok(sizes.reduce((a,b)=>a+b,0)<460000,'all initial JS stays within the existing budget');
console.log(`Build loading: ${initial.size} static JS chunks, ${sizes.reduce((a,b)=>a+b,0)} bytes; secondary routes and CSS deferred`);
