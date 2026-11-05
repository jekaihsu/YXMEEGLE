// Frontend lifecycle gate: only verified canonical lifecycle may allow work.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
const out=await build({entryPoints:['src/sourceLifecycle.ts'],bundle:true,write:false,platform:'node',format:'esm'});
const path=new URL('./.lifecycle-test-bundle.mjs',import.meta.url);
await fs.writeFile(path,out.outputFiles[0].text);
let m;try{m=await import(path.href)}finally{await fs.unlink(path)}
const l=(o)=>({relationship:'已關聯確認單',state:'mapped',canonical:'執行中',reasons:[],...o});
const bad={blank:l({state:'needs_verification',canonical:null,reasons:['blank']}),
 unknown:l({state:'needs_verification',canonical:null,reasons:['unknown_option']}),
 conflict:l({state:'needs_verification',canonical:null,reasons:['conflict']}),
 forged:l({reasons:['conflict']}),noCanonical:l({canonical:null})};
for(const [k,v] of Object.entries(bad)){
 assert.equal(m.declaredLifecycle({source_lifecycle:v}),null,k);
 assert.equal(m.lifecycleLabel(v),'待核對',k);
 assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:v}),'來源案件狀態待核對',k);
}
assert.equal(m.lifecycleGate({source_kind:'lark'}),'來源案件狀態待核對','missing summary fails closed');
assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:null}),'來源案件狀態待核對');
assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:l()}),'');
assert.equal(m.lifecycleGate({source_kind:'lark',source_lifecycle:l({canonical:'中止'})}),'來源案件已中止');
assert.equal(m.lifecycleGate({source_kind:'demo'}),'','demo cases have no source lifecycle');
const rb=await build({entryPoints:['src/ProjectReadiness.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const rpath=new URL('./.readiness-test-bundle.mjs',import.meta.url);
await fs.writeFile(rpath,rb.outputFiles[0].text);
let ProjectReadiness,renderToStaticMarkup;try{({ProjectReadiness}=await import(rpath.href));({renderToStaticMarkup}=await import('react-dom/server'))}finally{await fs.unlink(rpath)}
const html=(lc)=>renderToStaticMarkup(ProjectReadiness({w:{projects:[],policy_summary:[]},p:{id:'p',nodes:[],source_lifecycle:lc}}));
const forged=html(l({reasons:['conflict']}));
assert.ok(forged.includes('待核對')&&forged.includes('不一致'),'reason-bearing mapped summary shows 待核對 with its reasons');
assert.ok(!forged.includes('來源案件狀態：執行中'),'forged canonical is not shown as lifecycle');
const clean=html(l());
assert.ok(clean.includes('來源案件狀態：執行中')&&!clean.includes('（'),'verified lifecycle has no reasons suffix');
console.log('Source lifecycle gate: all checks passed');
